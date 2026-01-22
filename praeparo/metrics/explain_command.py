"""CLI orchestration for `praeparo-metrics explain`."""

from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import cast

from praeparo.io.yaml_loader import load_visual_from_payload
from praeparo.models import PackConfig, PackPlaceholder, PackSlide, PackVisualRef
from praeparo.models.visual_base import BaseVisualConfig
from praeparo.models.scoped_calculate import ScopedCalculateFilters, ScopedCalculateMap
from praeparo.pack.loader import load_pack_config
from praeparo.pack.templating import create_pack_jinja_env, render_value
from praeparo.visuals import cartesian as _visuals_cartesian  # noqa: F401  # register built-ins
from praeparo.visuals import powerbi as _visuals_powerbi  # noqa: F401
from praeparo.visuals.bindings import require_visual_bindings_adapter
from praeparo.visuals.context import resolve_dax_context
from praeparo.visuals.context_layers import resolve_layered_context_payload
from praeparo.visuals.dax.filters import normalise_filter_group
from praeparo.visuals.metrics import CalculateInput
from praeparo.visuals.registry import load_visual_definition

from .catalog import MetricDiscoveryError, load_metric_catalog
from .explain import build_metric_binding_explain_plan, build_metric_explain_plan
from .explain_runner import (
    derive_explain_outputs,
    resolve_explain_datasource,
    run_explain_plan,
    write_explain_dax,
    write_summary_json,
)
from .selectors import (
    FileSelector,
    MetricSelector,
    PlaceholderSelector,
    SlideSelector,
    detect_selector_file_kind,
    parse_selector,
    resolve_pack_placeholder,
    resolve_pack_slide,
)

from pydantic import BaseModel


ContextFragment = str | Mapping[str, str]


def run_explain_command(args) -> int:  # noqa: ANN001 - argparse namespace
    selector = parse_selector(str(args.selector), cwd=Path.cwd())

    if isinstance(selector, MetricSelector):
        if args.list_slides or args.list_bindings:
            raise ValueError("Listing flags are only supported for visual/pack selectors.")
        return _run_metric_explain(args, metric_identifier=selector.metric_identifier)

    kind = detect_selector_file_kind(selector.path)
    if kind == "visual":
        return _run_visual_selector(args, selector)
    if kind == "pack":
        return _run_pack_selector(args, selector)
    raise ValueError(f"Unsupported selector kind: {kind}")


def _run_metric_explain(args, *, metric_identifier: str) -> int:  # noqa: ANN001
    metrics_root = _resolve_metrics_root(args)
    env = create_pack_jinja_env()

    context_payload, calculate_filters, define_blocks = _resolve_explain_context(
        metrics_root=metrics_root,
        env=env,
        context_paths=tuple(Path(path) for path in (args.context or ())),
        context_layers=(),
        cli_calculate=tuple(args.calculate or ()),
        extra_calculate=(),
        extra_define=(),
    )

    dest = _render_path_template(getattr(args, "dest", None), env=env, context=context_payload)
    artefact_dir = _render_path_template(getattr(args, "artefact_dir", None), env=env, context=context_payload)
    outputs = derive_explain_outputs(metric_identifier=metric_identifier, dest=dest, artefact_dir=artefact_dir)

    catalog = _load_catalog(metrics_root)
    if catalog is None:
        return 1

    if args.plan_only:
        plan = build_metric_explain_plan(
            catalog,
            metric_identifier=metric_identifier,
            context_calculate_filters=calculate_filters,
            context_define_blocks=define_blocks,
            limit=int(args.limit),
            variant_mode=args.variant_mode,
        )
        _write_plan_only(outputs, plan=plan)
        return 0

    datasource = _resolve_datasource_for_explain(args)
    plan = build_metric_explain_plan(
        catalog,
        metric_identifier=metric_identifier,
        context_calculate_filters=calculate_filters,
        context_define_blocks=define_blocks,
        limit=int(args.limit),
        variant_mode=args.variant_mode,
    )
    return _execute_plan(args, outputs=outputs, plan=plan, datasource=datasource)


def _run_visual_selector(args, selector: FileSelector) -> int:  # noqa: ANN001
    metrics_root = _resolve_metrics_root(args)
    env = create_pack_jinja_env()

    visual_path = selector.path
    visual: BaseVisualConfig = load_visual_definition(visual_path, base_path=visual_path.parent)

    if args.list_slides:
        raise ValueError("--list-slides is only supported for pack selectors.")

    base_token = _format_selector_path(visual_path)

    if args.list_bindings:
        if selector.segments:
            raise ValueError("--list-bindings expects a visual path (no binding segments).")
        return _print_visual_bindings(base_token=base_token, visual=visual, source_path=visual_path)

    if not selector.segments:
        raise ValueError("Visual selectors require a binding selector (use --list-bindings to discover bindings).")

    adapter = require_visual_bindings_adapter(visual.type)
    binding = adapter.resolve_binding(visual, selector.segments, source_path=visual_path)
    if not binding.metric_key:
        raise ValueError("Selected binding does not reference a catalogue metric key yet.")

    selector_identifier = f"{base_token}#{'#'.join(selector.segments)}"

    context_payload, calculate_filters, define_blocks = _resolve_explain_context(
        metrics_root=metrics_root,
        env=env,
        context_paths=tuple(Path(path) for path in (args.context or ())),
        context_layers=(),
        cli_calculate=tuple(args.calculate or ()),
        extra_calculate=(
            *_visual_global_calculate_fragments(visual),
            binding.calculate.evaluate,
        ),
        extra_define=(
            cast(CalculateInput | None, getattr(visual, "define", None)),
        ),
    )

    rendered_binding_define = normalise_filter_group(
        render_value(binding.calculate.define or None, env=env, context=context_payload)
        if binding.calculate.define
        else None
    )

    dest = _render_path_template(getattr(args, "dest", None), env=env, context=context_payload)
    artefact_dir = _render_path_template(getattr(args, "artefact_dir", None), env=env, context=context_payload)
    outputs = derive_explain_outputs(metric_identifier=selector_identifier, dest=dest, artefact_dir=artefact_dir)

    catalog = _load_catalog(metrics_root)
    if catalog is None:
        return 1

    plan = build_metric_binding_explain_plan(
        catalog,
        metric_reference=binding.metric_key,
        metric_identifier=selector_identifier,
        context_calculate_filters=calculate_filters,
        context_define_blocks=define_blocks,
        limit=int(args.limit),
        variant_mode=args.variant_mode,
        numerator_define_filters=rendered_binding_define,
        ratio_to=binding.ratio_to,
        visual_path=base_token,
        binding_id=binding.binding_id,
        binding_label=binding.label,
    )

    if args.plan_only:
        _write_plan_only(outputs, plan=plan)
        return 0

    datasource = _resolve_datasource_for_explain(args)
    return _execute_plan(args, outputs=outputs, plan=plan, datasource=datasource)


def _run_pack_selector(args, selector: FileSelector) -> int:  # noqa: ANN001
    metrics_root = _resolve_metrics_root(args)
    env = create_pack_jinja_env()

    pack_path = selector.path
    pack = load_pack_config(pack_path)

    base_token = _format_selector_path(pack_path)

    if args.list_slides:
        if selector.segments:
            raise ValueError("--list-slides expects a pack path (no slide/binding segments).")
        return _print_pack_slides(base_token, pack)

    if not selector.segments:
        raise ValueError("Pack selectors require a slide selector (use --list-slides to discover slides).")

    slide_selector = SlideSelector.parse(selector.segments[0])
    slide_index, slide = resolve_pack_slide(pack, slide_selector)

    if args.list_bindings:
        return _print_pack_bindings(
            base_token=base_token,
            pack_path=pack_path,
            slide_index=slide_index,
            slide=slide,
        )

    resolved_visual_path, visual_ref, placeholder_id, binding_segments = _resolve_pack_binding_target(
        pack_path,
        pack,
        slide_index=slide_index,
        slide=slide,
        selector_segments=selector.segments,
    )

    visual_token = _format_selector_path(resolved_visual_path) if resolved_visual_path else _pack_inline_visual_token(
        base_token,
        slide_index=slide_index,
        slide=slide,
        placeholder_id=placeholder_id,
    )
    visual: BaseVisualConfig = _load_pack_visual(pack_path, visual_ref)

    adapter = require_visual_bindings_adapter(visual.type)
    binding = adapter.resolve_binding(visual, binding_segments, source_path=resolved_visual_path)
    if not binding.metric_key:
        raise ValueError("Selected binding does not reference a catalogue metric key yet.")

    selector_identifier = _pack_binding_identifier(
        base_token=base_token,
        slide_index=slide_index,
        slide=slide,
        placeholder_id=placeholder_id,
        binding_segments=binding_segments,
    )

    # Resolve layered context using pack + slide context so dest templates can reference pack variables.
    slide_context_layer = _dump_pack_context_for_layer(slide.context)
    context_payload, calculate_filters, define_blocks = _resolve_explain_context(
        metrics_root=metrics_root,
        env=env,
        context_paths=(pack_path, *tuple(Path(path) for path in (args.context or ()))),
        context_layers=(slide_context_layer,) if slide_context_layer else (),
        cli_calculate=tuple(args.calculate or ()),
        extra_calculate=(
            slide.calculate,
            visual_ref.calculate,
            *_visual_global_calculate_fragments(visual),
            binding.calculate.evaluate,
        ),
        extra_define=(cast(CalculateInput | None, getattr(visual, "define", None)),),
    )

    rendered_binding_define = normalise_filter_group(
        render_value(binding.calculate.define or None, env=env, context=context_payload)
        if binding.calculate.define
        else None
    )

    dest = _render_path_template(getattr(args, "dest", None), env=env, context=context_payload)
    artefact_dir = _render_path_template(getattr(args, "artefact_dir", None), env=env, context=context_payload)
    outputs = derive_explain_outputs(metric_identifier=selector_identifier, dest=dest, artefact_dir=artefact_dir)

    catalog = _load_catalog(metrics_root)
    if catalog is None:
        return 1

    plan = build_metric_binding_explain_plan(
        catalog,
        metric_reference=binding.metric_key,
        metric_identifier=selector_identifier,
        context_calculate_filters=calculate_filters,
        context_define_blocks=define_blocks,
        limit=int(args.limit),
        variant_mode=args.variant_mode,
        numerator_define_filters=rendered_binding_define,
        ratio_to=binding.ratio_to,
        visual_path=visual_token,
        binding_id=binding.binding_id,
        binding_label=binding.label,
    )

    if args.plan_only:
        _write_plan_only(outputs, plan=plan)
        return 0

    datasource = _resolve_datasource_for_explain(args)
    return _execute_plan(args, outputs=outputs, plan=plan, datasource=datasource)


def _resolve_explain_context(
    *,
    metrics_root: Path,
    env,
    context_paths: Sequence[Path],
    context_layers: Sequence[Mapping[str, object]],
    cli_calculate: Sequence[str],
    extra_calculate: Sequence[CalculateInput | None],
    extra_define: Sequence[CalculateInput | None],
) -> tuple[dict[str, object], tuple[str, ...], tuple[str, ...]]:
    context_payload = resolve_layered_context_payload(
        metrics_root=metrics_root,
        context_paths=context_paths,
        context_layers=context_layers,
        calculate=cli_calculate,
        env=env,
    )

    # Packs store default scoping under `context.metrics.calculate`. For explain runs we treat those
    # defaults as additional calculate predicates so evidence exports are constrained automatically.
    metrics_calculate: object | None = None
    raw_metrics = context_payload.get("metrics")
    if isinstance(raw_metrics, dict):
        metrics_calculate = raw_metrics.get("calculate")
    rendered_metrics_calculate = (
        render_value(metrics_calculate, env=env, context=context_payload) if metrics_calculate else None
    )
    scoped_defaults = (
        ScopedCalculateMap.from_raw(rendered_metrics_calculate) if rendered_metrics_calculate else ScopedCalculateMap()
    )
    scoped_filters = [*scoped_defaults.flatten_define(), *scoped_defaults.flatten_evaluate()]

    rendered_extra_calculate: list[ContextFragment] = []
    for value in extra_calculate:
        if value is None:
            continue
        rendered = render_value(value, env=env, context=context_payload)
        rendered_extra_calculate.extend(
            _flatten_context_fragments(cast(CalculateInput | None, rendered), label="calculate")
        )

    rendered_extra_define: list[ContextFragment] = []
    for value in extra_define:
        if value is None:
            continue
        rendered = render_value(value, env=env, context=context_payload)
        rendered_extra_define.extend(
            _flatten_context_fragments(cast(CalculateInput | None, rendered), label="define")
        )

    calculate_filters, define_blocks = resolve_dax_context(
        base=context_payload,
        calculate=[*scoped_filters, *rendered_extra_calculate],
        define=rendered_extra_define,
    )
    return context_payload, calculate_filters, define_blocks


def _flatten_context_fragments(value: CalculateInput | None, *, label: str) -> list[ContextFragment]:
    """Flatten rendered calculate/define payloads into mergeable context fragments."""

    if value is None:
        return []
    if isinstance(value, str):
        candidate = value.strip()
        return [candidate] if candidate else []
    if isinstance(value, Mapping):
        flattened_mapping: dict[str, str] = {}
        for key, raw in value.items():
            if raw is None:
                continue
            if not isinstance(raw, str):
                raise TypeError(f"{label} context mapping values must be strings.")
            candidate = raw.strip()
            if candidate:
                flattened_mapping[str(key)] = candidate
        return [flattened_mapping] if flattened_mapping else []
    if isinstance(value, Sequence) and not isinstance(value, str):
        flattened: list[ContextFragment] = []
        for entry in value:
            if entry is None:
                continue
            if isinstance(entry, str):
                candidate = entry.strip()
                if candidate:
                    flattened.append(candidate)
                continue
            if isinstance(entry, Mapping):
                flattened.extend(_flatten_context_fragments(cast(Mapping[str, str], entry), label=label))
                continue
            raise TypeError(f"{label} context entries must be strings or mappings.")
        return flattened
    raise TypeError(f"{label} context entries must be strings, mappings, or sequences thereof.")


def _load_catalog(metrics_root: Path):
    try:
        return load_metric_catalog([metrics_root])
    except MetricDiscoveryError as exc:
        print("Failed to load metric catalog:")
        for message in exc.errors:
            print(f"  - {message}")
        return None


def _execute_plan(args, *, outputs, plan, datasource) -> int:  # noqa: ANN001
    dax_path, evidence_path, summary_path, row_count, warnings = run_explain_plan(
        plan=plan,
        limit=int(args.limit),
        data_mode=args.data_mode,
        datasource=datasource,
        outputs=outputs,
    )
    for warning in warnings:
        print(f"[WARN] {warning}")
    print(f"Rows: {row_count}")
    print(f"DAX: {dax_path}")
    print(f"Evidence: {evidence_path}")
    print(f"Summary: {summary_path}")
    return 0


def _write_plan_only(outputs, *, plan) -> None:  # noqa: ANN001
    write_explain_dax(outputs.dax_path, plan.statement)
    write_summary_json(
        outputs.summary_path,
        metric_identifier=plan.metric_identifier,
        row_count=0,
        null_counts={},
        distinct_counts={},
        warnings=plan.warnings,
        evidence_path=None,
        dax_path=outputs.dax_path,
    )
    for warning in plan.warnings:
        print(f"[WARN] {warning}")
    print(f"DAX: {outputs.dax_path}")
    print(f"Summary: {outputs.summary_path}")


def _resolve_datasource_for_explain(args):  # noqa: ANN001
    data_mode = args.data_mode or "live"
    if data_mode not in {"mock", "live"}:
        raise ValueError("data-mode must be one of {'mock', 'live'}.")
    if data_mode == "mock":
        return None

    datasource_ref = args.datasource
    dataset_id = args.dataset_id or os.getenv("PRAEPARO_PBI_DATASET_ID")
    workspace_id = args.workspace_id or os.getenv("PRAEPARO_PBI_WORKSPACE_ID")
    datasource = resolve_explain_datasource(
        datasource=datasource_ref,
        dataset_id=dataset_id,
        workspace_id=workspace_id,
        cwd=Path.cwd(),
    )
    if args.workspace_id:
        datasource = datasource.__class__(
            name=datasource.name,
            type=datasource.type,
            dataset_id=datasource.dataset_id,
            workspace_id=args.workspace_id,
            settings=datasource.settings,
            source_path=datasource.source_path,
        )
    return datasource


def _resolve_metrics_root(args) -> Path:  # noqa: ANN001
    metrics_root = getattr(args, "metrics_root", None)
    if metrics_root:
        return Path(metrics_root).expanduser().resolve(strict=False)
    return _discover_default_metrics_root(Path.cwd())


def _discover_default_metrics_root(start: Path) -> Path:
    current = start.resolve()
    for _ in range(6):
        candidate = current / "registry" / "metrics"
        if candidate.is_dir():
            return candidate
        candidate = current / "metrics"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return start


def _render_path_template(value: Path | None, *, env, context: Mapping[str, object]) -> Path | None:
    if value is None:
        return None
    rendered = render_value(str(value), env=env, context=context)
    if not isinstance(rendered, str):
        raise ValueError("Path templates must render to a string value.")
    return Path(rendered).expanduser()


def _format_selector_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _print_pack_slides(base_token: str, pack: PackConfig) -> int:
    for index, slide in enumerate(pack.slides):
        slide_id = slide.id
        if slide_id:
            print(f"{base_token}#{index} ({base_token}#{slide_id})  {slide.title}")
        else:
            print(f"{base_token}#{index}  {slide.title}")
    return 0


def _print_pack_bindings(
    *,
    base_token: str,
    pack_path: Path,
    slide_index: int,
    slide: PackSlide,
) -> int:
    slide_token = slide.id or str(slide_index)

    if slide.visual is not None and not slide.placeholders:
        visual = _load_pack_visual(pack_path, slide.visual)
        return _print_visual_bindings(
            base_token=f"{base_token}#{slide_token}",
            visual=visual,
            source_path=None,
        )

    if slide.placeholders:
        # List across all placeholders (stable YAML order) and emit explicit placeholder ids.
        for placeholder_id, placeholder in slide.placeholders.items():
            if not placeholder.visual:
                continue
            visual = _load_pack_visual(pack_path, placeholder.visual)
            _print_visual_bindings(
                base_token=f"{base_token}#{slide_token}#{placeholder_id}",
                visual=visual,
                source_path=None,
            )
        return 0

    print("Slide has no visual bindings.")
    return 0


def _print_visual_bindings(*, base_token: str, visual: BaseVisualConfig, source_path: Path | None) -> int:
    adapter = require_visual_bindings_adapter(visual.type)
    bindings = adapter.list_bindings(visual, source_path=source_path)
    if not bindings:
        print("No metric bindings found.")
        return 0

    for binding in bindings:
        selector = "#".join(binding.selector_segments)
        details: list[str] = []
        if binding.label:
            details.append(f"label={binding.label}")
        if binding.metric_key:
            details.append(f"metric={binding.metric_key}")
        elif binding.expression:
            details.append(f"expr={binding.expression}")
        suffix = f"  {'  '.join(details)}" if details else ""
        print(f"{base_token}#{selector}{suffix}")
    return 0


def _visual_global_calculate_fragments(visual: BaseVisualConfig) -> tuple[CalculateInput, ...]:
    calculate = getattr(visual, "calculate", None)
    if calculate is None:
        return ()

    # Some visuals use scoped calculate models (DEFINE/EVALUATE). Others use the legacy
    # "flat" calculate list. For explain we treat both scopes as context filters so
    # binding evidence aligns with runtime query semantics.
    if isinstance(calculate, ScopedCalculateFilters):
        return (calculate.define, calculate.evaluate)
    if isinstance(calculate, str):
        return (calculate,)
    if isinstance(calculate, Mapping):
        return (cast(Mapping[str, str], calculate),)
    if isinstance(calculate, Sequence):
        return (cast(Sequence[str | Mapping[str, str]], calculate),)
    raise TypeError("visual.calculate must be a string, mapping, sequence of fragments, or ScopedCalculateFilters.")


def _resolve_pack_binding_target(
    pack_path: Path,
    pack: PackConfig,
    *,
    slide_index: int,
    slide: PackSlide,
    selector_segments: Sequence[str],
) -> tuple[Path | None, PackVisualRef, str | None, tuple[str, ...]]:
    if len(selector_segments) < 2:
        raise ValueError("Pack binding selectors require at least #<slide>#<binding...>.")

    # First token is slide selector; remaining tokens are either binding segments (simple slide)
    # or placeholder selector + binding segments (placeholder slide).
    remaining = tuple(selector_segments[1:])

    if slide.visual is not None and not slide.placeholders:
        if not remaining:
            raise ValueError("Pack binding selectors require a binding segment after the slide selector.")
        visual_ref = slide.visual
        return _resolve_pack_visual_path(pack_path, visual_ref), visual_ref, None, remaining

    placeholders = slide.placeholders
    if placeholders:
        if len(remaining) < 2:
            available = ", ".join(placeholders.keys())
            raise ValueError(
                "Pack selectors for placeholder slides must include #<placeholder_id>#<binding...>. "
                f"Available placeholders: {available}"
            )
        placeholder_token = remaining[0]
        placeholder_id, placeholder = _resolve_pack_placeholder(slide, token=placeholder_token)
        if not placeholder.visual:
            raise ValueError(f"Placeholder '{placeholder_id}' does not contain a visual binding.")
        visual_ref = placeholder.visual
        binding_segments = remaining[1:]
        return _resolve_pack_visual_path(pack_path, visual_ref), visual_ref, placeholder_id, binding_segments

    raise ValueError("Selected slide does not contain a visual.")


def _resolve_pack_placeholder(slide: PackSlide, *, token: str) -> tuple[str, PackPlaceholder]:
    placeholders = slide.placeholders
    if not placeholders:
        raise ValueError("Slide does not define placeholders.")

    if token.isdigit():
        return resolve_pack_placeholder(slide, PlaceholderSelector.parse(token))
    if token in placeholders:
        return token, placeholders[token]
    raise ValueError(f"Unknown placeholder selector '{token}'.")


def _resolve_pack_visual_path(pack_path: Path, visual_ref: PackVisualRef) -> Path | None:
    if not visual_ref.ref:
        return None
    return (pack_path.parent / str(visual_ref.ref)).resolve()


def _load_pack_visual(pack_path: Path, visual_ref: PackVisualRef) -> BaseVisualConfig:
    if visual_ref.ref:
        resolved = (pack_path.parent / str(visual_ref.ref)).resolve()
        return load_visual_definition(resolved, base_path=resolved.parent)

    payload = visual_ref.model_dump(mode="python")
    payload.pop("ref", None)
    payload.pop("filters", None)
    payload.pop("calculate", None)
    return load_visual_from_payload(pack_path, payload, preprocess=True)


def _pack_inline_visual_token(
    base_token: str,
    *,
    slide_index: int,
    slide: PackSlide,
    placeholder_id: str | None,
) -> str:
    slide_token = slide.id or str(slide_index)
    if placeholder_id:
        return f"{base_token}#{slide_token}#{placeholder_id}"
    return f"{base_token}#{slide_token}"


def _pack_binding_identifier(
    *,
    base_token: str,
    slide_index: int,
    slide: PackSlide,
    placeholder_id: str | None,
    binding_segments: Sequence[str],
) -> str:
    slide_token = slide.id or str(slide_index)
    parts = [base_token, slide_token]
    if placeholder_id:
        parts.append(placeholder_id)
    parts.extend(binding_segments)
    return "#".join(parts)


def _dump_pack_context_for_layer(context: Mapping[str, object] | BaseModel | None) -> dict[str, object] | None:
    if context is None:
        return None
    if isinstance(context, Mapping):
        payload: dict[str, object] = dict(context)
    elif isinstance(context, BaseModel):
        payload = context.model_dump(mode="python", exclude_none=True)
    else:
        raise TypeError("Pack context must be a mapping or a Pydantic model.")
    payload.pop("metrics", None)
    return payload


__all__ = ["run_explain_command"]
