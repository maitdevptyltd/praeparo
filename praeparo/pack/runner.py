"""Pack execution orchestrator."""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence, cast

from jinja2 import Environment
from pydantic import ValidationError

from praeparo.models import BaseVisualConfig, FiltersType, PackConfig, PackPlaceholder, PackSlide, PackVisualRef
from praeparo.pack.filters import merge_calculate_filters, merge_odata_filters
from praeparo.pack.errors import PackEvidenceFailure, PackExecutionError
from praeparo.pack.evidence import (
    PackEvidenceTarget,
    build_pack_evidence_target,
    flatten_context_fragments,
    resolve_evidence_datasource,
    run_pack_evidence_exports,
    select_evidence_bindings,
)
from praeparo.pack.metric_context import (
    ResolvedMetricContext,
    discover_builder_context_for_pack,
    dump_context_payload,
    load_catalog_for_context,
    resolve_metric_context,
)
from praeparo.pack.formatted_values import FormattedMetricValue
from praeparo.pack.pbi_queue import PowerBIExportJob, PowerBIExportQueue, PowerBIExportResult
from praeparo.pack.templating import create_pack_jinja_env, render_value
from praeparo.pack.pptx import PlaceholderSize, assemble_pack_pptx, resolve_template_geometry
from praeparo.pipeline import (
    ExecutionContext,
    OutputKind,
    OutputTarget,
    PipelineOptions,
    PythonVisualBase,
    VisualExecutionResult,
    VisualPipeline,
    PYTHON_VISUAL_TYPE,
    build_default_query_planner_provider,
    register_visual_pipeline,
)
from praeparo.pipeline.python_visual_loader import load_python_visual
from praeparo.paths.registry_root import is_registry_anchored_path, resolve_registry_anchored_path
from praeparo.visuals.dax.planner_core import slugify
from praeparo.io.yaml_loader import load_visual_config, load_visual_from_payload
from praeparo.visuals.context import merge_context_payload, resolve_dax_context
from praeparo.visuals.context_layers import merge_context_layer_payload, resolve_layered_context_payload
from praeparo.visuals.registry import VisualTypeRegistration, get_visual_registration, _is_python_visual_type
from praeparo.visuals.context_models import VisualContextModel
from praeparo.models.scoped_calculate import ScopedCalculateFilters, ScopedCalculateMap
from praeparo.visuals.bindings import get_visual_bindings_adapter


VisualLoader = Callable[[Path], BaseVisualConfig]

logger = logging.getLogger(__name__)

_PACK_VISUAL_REF_RESERVED_KEYS = frozenset({"ref", "type", "filters", "calculate"})


def _resolve_registry_metrics_calculate_defaults(pack_payload: Mapping[str, object]) -> ScopedCalculateMap | None:
    """Return default context.metrics.calculate entries loaded from registry context layers.

    Downstream repos often store shared metric-context scoping predicates under
    `registry/context/**` so packs can omit boilerplate like month pinning.

    Registry context layers are merged into the pack payload (for templating),
    but metric-context execution relies on typed `context.metrics.calculate`
    models. This helper bridges the gap by extracting any discovered
    `metrics.calculate` mapping and normalising it into a ScopedCalculateMap.
    """

    raw_metrics = pack_payload.get("metrics")
    if not isinstance(raw_metrics, Mapping):
        return None

    raw_calculate = raw_metrics.get("calculate")
    if raw_calculate is None:
        return None

    try:
        return ScopedCalculateMap.from_raw(raw_calculate)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            "Registry context defines an invalid metrics.calculate payload; "
            "expected a string/list/mapping compatible with context.metrics.calculate."
        ) from exc


def _extract_pack_visual_ref_overrides(visual_ref: PackVisualRef) -> dict[str, object]:
    """Collect inline visual config overrides from a PackVisualRef.

    Packs allow referencing file-backed visuals via `visual.ref`. Any additional keys
    in that same `visual:` mapping should be treated as top-level config overrides
    for the referenced visual (except execution-scoped fields like `filters` and
    `calculate`).
    """

    payload = visual_ref.model_dump(mode="python", exclude_none=True)
    return {key: value for key, value in payload.items() if key not in _PACK_VISUAL_REF_RESERVED_KEYS}


@dataclass
class PackSlideResult:
    """Outcome for a single slide execution."""

    slide: PackSlide
    visual_path: Path
    result: VisualExecutionResult
    png_path: Path | None


DEFAULT_POWERBI_CONCURRENCY = 5


class PackPowerBIFailure(RuntimeError):
    """Raised when one or more Power BI slides fail during a pack run."""

    def __init__(
        self,
        message: str,
        *,
        successful_results: list[PackSlideResult],
        failed_exports: Sequence[PowerBIExportResult],
    ) -> None:
        super().__init__(message)
        self.successful_results = successful_results
        self.failed_exports = failed_exports


def _format_powerbi_failure_summary(failed_exports: Sequence[PowerBIExportResult]) -> str:
    """Build a human-readable summary of failed Power BI slide exports."""

    lines = [f"{len(failed_exports)} Power BI slide(s) failed:"]

    for item in failed_exports:
        exc = item.exception
        exc_type = exc.__class__.__name__ if exc else "Error"
        message = ""
        if exc:
            raw = str(exc)
            message = raw.splitlines()[0] if raw else repr(exc)
        title = f" ({item.job.slide_title})" if item.job.slide_title else ""
        lines.append(f"  - {item.job.slide_slug}{title}: {exc_type}: {message}".rstrip())

    focus_target = failed_exports[0].job.slide_title or failed_exports[0].job.slide_slug
    lines.append(
        f"Hint: re-run with --slides \"{focus_target}\" --max-pbi-concurrency 1 for focused debugging."
    )

    return "\n".join(lines)


def _resolve_pack_base_context_payload(
    *,
    pack_path: Path,
    metadata: Mapping[str, object] | None,
    pack_context_layer: Mapping[str, object] | None = None,
    env: Environment,
) -> dict[str, object]:
    """Resolve registry context layers, then merge any caller-supplied metadata context.

    Pack execution needs the same "global" DAX helpers as ad-hoc visual runs, so
    we start by loading `registry/context/**` (relative to the discovered
    metrics_root). Any context supplied via PipelineOptions metadata is then
    merged on top so explicit overrides win.
    """

    from praeparo.datasets.context import resolve_default_metrics_root_for_pack

    raw_metrics_root = metadata.get("metrics_root") if metadata else None
    if isinstance(raw_metrics_root, (str, Path)):
        metrics_root = Path(raw_metrics_root).expanduser().resolve(strict=False)
    else:
        metrics_root = resolve_default_metrics_root_for_pack(pack_path)

    # Start with registry-owned layers so downstream repos can ship default
    # helper definitions without repeating them in every pack.
    context_layers: list[Mapping[str, object]] = []

    raw_context = metadata.get("context") if metadata else None
    if isinstance(raw_context, Mapping):
        context_layers.append(dict(raw_context))

    if pack_context_layer:
        context_layers.append(dict(pack_context_layer))

    registry_payload = resolve_layered_context_payload(metrics_root=metrics_root, context_layers=context_layers, env=env)

    return registry_payload


def _render_slide_context_after_metric_injection(
    *,
    env: Environment,
    slide_payload: dict[str, object],
    display_payload: Mapping[str, object],
    raw_slide_context: Mapping[str, object],
) -> None:
    """Render slide-context values once after metric bindings are injected.

    Packs often store "display-ish" slide context strings (for example,
    governance highlight narratives) that are later referenced by another
    template layer via `{{ governance_highlights }}`. If those strings contain
    nested Jinja templates that reference metric-binding aliases, we need a
    second render pass once the alias values exist in the payload.

    This helper only updates the ephemeral `slide_payload` dict used by the pack
    runner and metadata. It never mutates the PackSlide models.
    """

    if not raw_slide_context:
        return

    rendered = render_value(raw_slide_context, env=env, context=slide_payload)
    if not isinstance(rendered, Mapping):
        return

    slide_payload.update(dict(rendered))

    # Phase 8: apply metric-binding formats automatically for display-only slide
    # context strings without leaking formatted values into execution surfaces.
    #
    # We only re-render fields that live outside known execution blocks (e.g.
    # DAX filters, DEFINE blocks, or expression payloads). This keeps formatting
    # predictable for narrative strings while preserving raw numeric values for
    # anything that influences queries or pipeline execution.
    excluded_display_blocks = {"calculate", "filters", "define", "expression"}

    for key, raw_value in raw_slide_context.items():
        if key in excluded_display_blocks:
            continue
        if raw_value is None:
            continue

        rendered_value = render_value(raw_value, env=env, context=display_payload)
        if rendered_value is None:
            slide_payload[key] = ""
        elif isinstance(rendered_value, list):
            slide_payload[key] = "\n".join(str(item) for item in rendered_value if item is not None)
        else:
            slide_payload[key] = str(rendered_value) if isinstance(rendered_value, (str, int, float)) else rendered_value


def _build_display_payload(
    *,
    raw_payload: Mapping[str, object],
    formats_by_alias: Mapping[str, str],
) -> dict[str, object]:
    """Clone *raw_payload* and wrap formatted metric aliases for display rendering."""

    payload: dict[str, object] = dict(raw_payload)
    for alias, token in formats_by_alias.items():
        raw_value = payload.get(alias)
        if raw_value is None or isinstance(raw_value, (int, float)):
            payload[alias] = FormattedMetricValue(value=raw_value, format=token)
    return payload


def _slug_for_slide(slide: PackSlide, index: int) -> str:
    if slide.id:
        return slugify(slide.id)
    if slide.title:
        return slugify(slide.title)
    return f"slide_{index}"


def _select_png_output(result: VisualExecutionResult, requested_outputs: Sequence[OutputTarget]) -> Path | None:
    png_targets = [target.path for target in requested_outputs if target.kind is OutputKind.PNG]
    if not png_targets:
        return None
    requested_paths = {path.resolve() for path in png_targets}
    for artifact in result.outputs:
        if artifact.kind is OutputKind.PNG and artifact.path.resolve() in requested_paths:
            return artifact.path
    return png_targets[0]

def _discover_dax_artifacts(directory: Path | None) -> tuple[Path, ...]:
    if directory is None or not directory.exists():
        return ()
    return tuple(sorted(directory.glob("*.dax")))

def _format_selector_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


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


def _render_visual_calculate_fragments(
    visual: BaseVisualConfig,
    *,
    env: Environment,
    context: Mapping[str, object],
) -> tuple[FiltersType, ...]:
    calculate = getattr(visual, "calculate", None)
    if calculate is None:
        return ()

    # Some visuals use a scoped calculate model (DEFINE/EVALUATE). For pack evidence we
    # treat both scopes as context filters so the explain plan matches runtime semantics.
    if isinstance(calculate, ScopedCalculateFilters):
        rendered_define = render_value(calculate.define or None, env=env, context=context)
        rendered_evaluate = render_value(calculate.evaluate or None, env=env, context=context)
        return cast(tuple[FiltersType, ...], (rendered_define, rendered_evaluate))

    if hasattr(calculate, "define") and hasattr(calculate, "evaluate"):
        raw_define = getattr(calculate, "define")
        raw_evaluate = getattr(calculate, "evaluate")
        rendered_define = render_value(raw_define or None, env=env, context=context)
        rendered_evaluate = render_value(raw_evaluate or None, env=env, context=context)
        return cast(tuple[FiltersType, ...], (rendered_define, rendered_evaluate))

    rendered = render_value(calculate, env=env, context=context)
    return (cast(FiltersType, rendered),)


def _render_metrics_calculate_filters_for_evidence(
    *,
    metrics_calculate: ScopedCalculateMap,
    env: Environment,
    context: Mapping[str, object],
) -> tuple[str, ...]:
    """Render context.metrics.calculate templates and flatten them into DAX predicates.

    Packs commonly define month scoping under `context.metrics.calculate` (for
    example in `registry/context/metrics.yaml`). Visual binding explain plans
    should reuse those same defaults so evidence exports match rendered numbers.
    """

    raw_payload = metrics_calculate.model_dump(mode="python")
    rendered = render_value(raw_payload, env=env, context=context)
    rendered_map = ScopedCalculateMap.from_raw(rendered)
    flattened = [*rendered_map.flatten_define(), *rendered_map.flatten_evaluate()]
    return tuple(item.strip() for item in flattened if item and item.strip())


def _prepare_slide_options(
    base_options: PipelineOptions,
    *,
    slide_slug: str,
    artefact_root: Path,
    metadata_update: Mapping[str, object] | None = None,
    png_scale: float | None = None,
) -> tuple[PipelineOptions, Path]:
    """Clone base options and attach per-slide outputs/artefact directory."""

    slide_dir = artefact_root / slide_slug
    slide_dir.mkdir(parents=True, exist_ok=True)

    options = copy.deepcopy(base_options)
    options.outputs = [OutputTarget.png(artefact_root / f"{slide_slug}.png")]
    options.artefact_dir = slide_dir
    if png_scale is not None:
        options.png_scale = png_scale

    merged_metadata: dict[str, object] = {}
    merged_metadata.update(base_options.metadata or {})
    if metadata_update:
        merged_metadata.update(metadata_update)
    options.metadata = merged_metadata
    return options, slide_dir


def _instantiate_slide_context(
    *,
    registration: VisualTypeRegistration | None,
    metadata: Mapping[str, object],
    project_root: Path,
) -> VisualContextModel | None:
    if registration is None or registration.context_model is None:
        return None

    context_model = registration.context_model
    raw_context: dict[str, object] = dict(metadata)

    metrics_root = raw_context.get("metrics_root")
    if isinstance(metrics_root, (str, Path)):
        resolved_root = Path(metrics_root)
        raw_context["metrics_root"] = resolved_root.expanduser().resolve(strict=False)

    context_payload = raw_context.get("context")
    if isinstance(context_payload, Mapping):
        raw_context["context"] = dict(context_payload)

    calculate_filters: tuple[str, ...]
    define_blocks: tuple[str, ...]
    calculate_filters, define_blocks = resolve_dax_context(
        base=context_payload if isinstance(context_payload, Mapping) else None,
        calculate=None,
        define=None,
    )
    raw_context["dax"] = {"calculate": calculate_filters, "define": define_blocks}

    return context_model.model_validate(raw_context)


def _instantiate_python_visual_context(
    *,
    visual: PythonVisualBase,
    metadata: Mapping[str, object],
) -> VisualContextModel:
    """Instantiate the declared Python visual context model from pack metadata."""

    raw_context: dict[str, object] = dict(metadata or {})

    metrics_root = raw_context.get("metrics_root")
    if isinstance(metrics_root, (str, Path)):
        resolved_root = Path(metrics_root)
        raw_context["metrics_root"] = resolved_root.expanduser().resolve(strict=False)

    context_payload = raw_context.get("context")
    if isinstance(context_payload, Mapping):
        raw_context["context"] = dict(context_payload)

    calculate_filters, define_blocks = resolve_dax_context(
        base=context_payload if isinstance(context_payload, Mapping) else None,
        calculate=None,
        define=None,
    )
    raw_context["dax"] = {"calculate": calculate_filters, "define": define_blocks}

    return visual.context_model.model_validate(raw_context)


def _should_run_slide(slide: PackSlide, *, only: set[str] | None) -> bool:
    if not only:
        return True
    candidates = {slide.title, slugify(slide.title)}
    if slide.id:
        candidates.add(slide.id)
        candidates.add(slugify(slide.id))
    return any(candidate in only for candidate in candidates)


def _resolve_default_template(pack_path: Path) -> Path | None:
    """
    Try common locations for the shared pack PPTX template.

    Preference order:
    - Sibling to the pack file
    - Parent folder
    - registry/packs/pack_template.pptx (rooted from pack path)
    """

    candidates: list[Path] = []
    # Local to pack
    candidates.append(pack_path.parent / "pack_template.pptx")
    # One level up
    candidates.append(pack_path.parent.parent / "pack_template.pptx")
    # Shared registry/packs template relative to pack location
    try:
        candidates.append(pack_path.parent.parent / "packs" / "pack_template.pptx")
        candidates.append(pack_path.parent.parent.parent / "packs" / "pack_template.pptx")
        candidates.append(pack_path.parent.parent.parent / "registry" / "packs" / "pack_template.pptx")
    except IndexError:
        pass

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _reuse_existing_assets(
    *,
    slide: PackSlide,
    slide_slug: str,
    ordinal: str,
    pack_root: Path,
    output_root: Path,
    slide_png_map: dict[str, Path],
    placeholder_png_map: dict[str, dict[str, Path]],
) -> None:
    """Populate PNG maps from prior artefacts and static image definitions.

    This helper is used when slides are skipped (partial runs) and by the
    PPTX-only restitch path to reuse existing outputs without executing
    visuals. Static images remain mandatory: if a path is configured but not
    found on disk, surface an error so callers can fix the pack definition.
    """

    if slide.image:
        image_path = (pack_root / slide.image).expanduser().resolve(strict=False)
        if not image_path.exists():
            raise ValueError(f"Static slide image not found for '{slide_slug}': {image_path}")
        slide_png_map.setdefault(slide_slug, image_path)

    png_path = output_root / f"[{ordinal}]_{slide_slug}.png"
    if png_path.exists():
        slide_png_map.setdefault(slide_slug, png_path)

    if not slide.placeholders:
        return

    placeholder_map = placeholder_png_map.setdefault(slide_slug, {})
    for placeholder_id, placeholder in slide.placeholders.items():
        placeholder_slug = f"{slide_slug}__{slugify(placeholder_id)}"

        if placeholder.image:
            image_path = (pack_root / placeholder.image).expanduser().resolve(strict=False)
            if not image_path.exists():
                raise ValueError(
                    f"Static placeholder image not found for '{placeholder_id}' on slide '{slide_slug}': {image_path}"
                )
            placeholder_map.setdefault(placeholder_slug, image_path)

        placeholder_png = output_root / f"[{ordinal}]_{placeholder_slug}.png"
        if placeholder_png.exists():
            placeholder_map.setdefault(placeholder_slug, placeholder_png)


def _render_slide_metadata(*, pack: PackConfig, env: Environment, context: Mapping[str, object]) -> None:
    """Apply Jinja templating to slide-level metadata so downstream consumers see rendered text."""

    for slide in pack.slides:
        if slide.title:
            slide.title = render_value(slide.title, env=env, context=context)
        if slide.notes:
            slide.notes = render_value(slide.notes, env=env, context=context)


def run_pack(
    pack_path: Path,
    pack: PackConfig,
    *,
    project_root: Path,
    output_root: Path,
    max_powerbi_concurrency: int | None = None,
    base_options: PipelineOptions | None = None,
    visual_loader: VisualLoader = load_visual_config,
    pipeline: VisualPipeline | None = None,
    env: Environment | None = None,
    only_slides: Iterable[str] | None = None,
    evidence_only: bool = False,
) -> list[PackSlideResult]:
    """Execute a pack and export PNGs for each visual slide."""

    started = time.perf_counter()

    output_root.mkdir(parents=True, exist_ok=True)
    resolved_project_root = project_root.expanduser().resolve(strict=False)

    jinja_env = env or create_pack_jinja_env()

    base = base_options or PipelineOptions()
    base_metadata = base.metadata if isinstance(base.metadata, Mapping) else None

    # Start by loading registry context layers, then apply any explicit context
    # payload provided via PipelineOptions metadata.
    base_context_payload = _resolve_pack_base_context_payload(
        pack_path=pack_path,
        metadata=base_metadata,
        pack_context_layer=dump_context_payload(pack.context),
        env=jinja_env,
    )

    # With base layers resolved, inherit pack context values so packs and slides
    # can override defaults while still benefiting from shared helpers.
    pack_payload = merge_context_layer_payload(base=base_context_payload, incoming=dump_context_payload(pack.context))
    rendered_global_filters = render_value(pack.filters, env=jinja_env, context=pack_payload)
    rendered_global_calculate = render_value(pack.calculate, env=jinja_env, context=pack_payload)
    rendered_define = render_value(pack.define, env=jinja_env, context=pack_payload)

    registry_metrics_calculate = _resolve_registry_metrics_calculate_defaults(pack_payload)

    root_metrics_context = pack.context.metrics
    root_bindings = root_metrics_context.bindings if root_metrics_context else []
    root_metrics_calculate = root_metrics_context.calculate if root_metrics_context else None
    root_metrics_calculate = ScopedCalculateMap.merge(registry_metrics_calculate, root_metrics_calculate)
    slide_bindings_present = any(
        slide.context is not None
        and slide.context.metrics is not None
        and slide.context.metrics.bindings
        for slide in pack.slides
    )
    has_metric_bindings = bool(root_bindings) or slide_bindings_present
    evidence_config = pack.evidence
    evidence_enabled = bool(evidence_config and evidence_config.enabled)
    if evidence_only and not evidence_enabled:
        raise ValueError("Evidence-only pack runs require pack.evidence.enabled=true.")

    builder_context = None
    catalog = None
    if has_metric_bindings or evidence_enabled:
        metrics_calculate, metrics_define = resolve_dax_context(
            base=pack_payload,
            calculate=rendered_global_calculate,
            define=rendered_define,
        )
        builder_context = discover_builder_context_for_pack(
            pack_path=pack_path,
            project_root=resolved_project_root,
            metadata=base_metadata,
            calculate=metrics_calculate,
            define=metrics_define,
        )
        catalog = load_catalog_for_context(builder_context)

    if has_metric_bindings:
        assert builder_context is not None
        assert catalog is not None
        # Resolve root-level metric bindings once and expose them as pack-wide Jinja variables.
        global_metrics_context = resolve_metric_context(
            bindings=root_bindings or None,
            inherited=None,
            builder_context=builder_context,
            catalog=catalog,
            env=jinja_env,
            base_payload=pack_payload,
            scope="root",
            metrics_calculate=root_metrics_calculate,
            artefact_dir=output_root,
        )
    else:
        global_metrics_context = ResolvedMetricContext(
            aliases={},
            by_key={},
            signatures_by_key={},
            formats_by_alias={},
        )
    global_payload: dict[str, object] = dict(pack_payload)
    global_payload.update(global_metrics_context.aliases)
    global_display_payload = _build_display_payload(
        raw_payload=global_payload,
        formats_by_alias=global_metrics_context.formats_by_alias,
    )

    effective_concurrency = max_powerbi_concurrency or DEFAULT_POWERBI_CONCURRENCY
    resolved_pipeline: VisualPipeline | None = None
    powerbi_queue: PowerBIExportQueue | None = None
    if not evidence_only:
        resolved_pipeline = pipeline or VisualPipeline(
            planner_provider=build_default_query_planner_provider(),
        )
        # VisualPipeline is currently stateless per execute() call and relies on per-call
        # ExecutionContext plus per-visual planners/clients. If future changes add shared
        # mutable state, re-evaluate thread safety for PowerBIExportQueue.
        powerbi_queue = PowerBIExportQueue(
            resolved_pipeline,
            max_concurrent_exports=effective_concurrency,
        )

    slide_filter = {slugify(item) for item in only_slides} if only_slides else None
    logger.info(
        "Running pack",
        extra={
            "pack_path": str(pack_path),
            "artefact_dir": str(output_root),
            "slide_count": len(pack.slides),
            "only_slides": sorted(slide_filter) if slide_filter else None,
            "powerbi_concurrency": effective_concurrency,
        },
    )

    if global_payload:
        logger.debug("Rendered pack context", extra={"keys": sorted(global_payload.keys())})
    if global_metrics_context.aliases:
        logger.debug(
            "Resolved root context.metrics",
            extra={"aliases": sorted(global_metrics_context.aliases.keys())},
        )
    if rendered_global_filters:
        if isinstance(rendered_global_filters, Mapping):
            logger.debug("Rendered global filters", extra={"keys": sorted(rendered_global_filters.keys())})
        else:
            logger.debug("Rendered global filters", extra={"count": len(rendered_global_filters)})
    if rendered_global_calculate:
        if isinstance(rendered_global_calculate, Mapping):
            logger.debug("Rendered global calculate", extra={"keys": sorted(rendered_global_calculate.keys())})
        else:
            try:
                logger.debug("Rendered global calculate", extra={"count": len(rendered_global_calculate)})  # type: ignore[arg-type]
            except TypeError:
                logger.debug("Rendered global calculate", extra={"count": 1})

    ordered_results: list[tuple[int, PackSlideResult]] = []
    slide_png_map: dict[str, Path] = {}
    placeholder_png_map: dict[str, dict[str, Path]] = {}
    slide_contexts_by_slug: dict[str, dict[str, object]] = {}
    pack_root = pack_path.parent
    pack_token = _format_selector_path(pack_path)
    evidence_targets: list[PackEvidenceTarget] = []

    # Resolve PPTX template geometry once per pack so visuals can size their canvases.
    template_geometry_by_template: dict[str, PlaceholderSize] = {}
    template_geometry_by_placeholder: dict[tuple[str, str], PlaceholderSize] = {}
    template_for_geometry = _resolve_default_template(pack_path)
    if template_for_geometry is not None:
        try:
            slide_geom, placeholder_geom = resolve_template_geometry(template_for_geometry)
            template_geometry_by_template = slide_geom
            template_geometry_by_placeholder = placeholder_geom
        except Exception:
            logger.exception(
                "Failed to resolve PPTX template geometry; continuing without width/height hints",
                extra={"template_path": str(template_for_geometry)},
            )

    for index, slide in enumerate(pack.slides, start=1):
        # Build the slide context by inheriting pack values, then applying slide overrides.
        slide_payload: dict[str, object] = dict(global_payload)
        raw_slide_context: dict[str, object] = {}
        if slide.context is not None:
            raw_slide_context = dump_context_payload(slide.context)
            slide_payload.update(raw_slide_context)

        effective_metrics_context = global_metrics_context
        if has_metric_bindings and builder_context is not None and catalog is not None:
            slide_metrics_config = slide.context.metrics if slide.context else None
            slide_metrics_calculate = ScopedCalculateMap.merge(
                root_metrics_calculate,
                slide_metrics_config.calculate if slide_metrics_config else None,
            )
            slide_metrics_context = resolve_metric_context(
                bindings=slide_metrics_config.bindings if slide_metrics_config else None,
                inherited=global_metrics_context,
                builder_context=builder_context,
                catalog=catalog,
                env=jinja_env,
                base_payload=slide_payload,
                scope=f"slide_{index}",
                metrics_calculate=slide_metrics_calculate,
                artefact_dir=output_root,
            )
            effective_metrics_context = slide_metrics_context
            slide_payload.update(slide_metrics_context.aliases)

        if has_metric_bindings:
            display_payload = _build_display_payload(
                raw_payload=slide_payload,
                formats_by_alias=effective_metrics_context.formats_by_alias,
            )
            _render_slide_context_after_metric_injection(
                env=jinja_env,
                slide_payload=slide_payload,
                display_payload=display_payload,
                raw_slide_context=raw_slide_context,
            )

        # Render title/notes using the full slide context so slugging aligns with outputs.
        slide.title = render_value(slide.title, env=jinja_env, context=slide_payload)
        if slide.notes:
            slide.notes = render_value(slide.notes, env=jinja_env, context=slide_payload)

        slide_slug = _slug_for_slide(slide, index)
        ordinal = f"{index:02d}"

        slide_payload.update(
            {
                "title": slide.title,
                "slide_index": index,
                "slide_id": slide.id,
                "slide_slug": slide_slug,
            }
        )
        slide_contexts_by_slug[slide_slug] = _build_display_payload(
            raw_payload=slide_payload,
            formats_by_alias=effective_metrics_context.formats_by_alias,
        )

        def _render_filters(value: object | None) -> FiltersType:
            return render_value(value, env=jinja_env, context=slide_payload)

        rendered_slide_calculate = _render_filters(slide.calculate)

        if slide_filter and not _should_run_slide(slide, only=slide_filter):
            _reuse_existing_assets(
                slide=slide,
                slide_slug=slide_slug,
                ordinal=ordinal,
                pack_root=pack_root,
                output_root=output_root,
                slide_png_map=slide_png_map,
                placeholder_png_map=placeholder_png_map,
            )
            continue

        def _execute_visual(
            *,
            visual_ref: PackVisualRef,
            slide_label: str,
            filters: FiltersType,
            calculate: FiltersType,
            slide_calculate: FiltersType,
            placeholder_id: str | None = None,
            target_map: dict[str, Path],
        ) -> None:
            python_visual: PythonVisualBase | None = None
            visual_path: Path

            visual_ref_label = visual_ref.ref or visual_ref.type
            slide_slug_for_error = slide_label

            try:
                if visual_ref.ref:
                    raw_ref = str(visual_ref.ref).strip()
                    if is_registry_anchored_path(raw_ref):
                        visual_path = resolve_registry_anchored_path(raw_ref, context_path=pack_path)
                    else:
                        visual_path = (pack_path.parent / raw_ref).resolve()
                    is_python_visual = visual_path.suffix.lower() == ".py"

                    if is_python_visual:
                        python_visual = load_python_visual(visual_path, class_name=None)
                        definition = python_visual.to_definition()
                        register_visual_pipeline(PYTHON_VISUAL_TYPE, definition, overwrite=True)
                        visual = python_visual.to_config()
                    else:
                        visual = visual_loader(visual_path)

                    # Apply inline config overrides (e.g. title) after loading the file-backed visual
                    # so pack authors can tweak presentation without duplicating the underlying YAML.
                    inline_overrides = _extract_pack_visual_ref_overrides(visual_ref)
                    if inline_overrides:
                        base_payload = visual.model_dump(mode="python")
                        # Some config models (notably Python visual configs that reuse shared base
                        # models) intentionally exclude the discriminator from serialisation so the
                        # YAML `type:` meta field does not conflict with their schema. Preserve the
                        # resolved discriminator explicitly so we don't accidentally drop it during
                        # override re-validation.
                        merged = {**base_payload, "type": visual.type, **inline_overrides}
                        try:
                            visual = visual.__class__.model_validate(merged)
                        except ValidationError as exc:
                            keys = ", ".join(sorted(inline_overrides))
                            wrapped = ValueError(f"Inline visual override validation failed for key(s): {keys}")
                            wrapped.__cause__ = exc
                            raise PackExecutionError(
                                pack_path=pack_path,
                                slide_index=index,
                                slide_slug=slide_slug_for_error,
                                slide_id=slide.id,
                                slide_title=slide.title,
                                visual_ref=visual_ref_label,
                                visual_path=visual_path,
                                phase="visual_override",
                                dax_artifact_paths=(),
                                cause=wrapped,
                            )
                else:
                    visual_path = pack_path
                    payload = visual_ref.model_dump()
                    payload.pop("ref", None)
                    payload.pop("filters", None)
                    payload.pop("calculate", None)

                    visual = load_visual_from_payload(visual_path, payload, preprocess=True)

                    raw_type = payload.get("type")
                    is_python_visual = isinstance(raw_type, str) and _is_python_visual_type(raw_type)

                    if is_python_visual:
                        module_path = (pack_path.parent / str(raw_type)).resolve()
                        python_visual = load_python_visual(module_path, class_name=None)
                        register_visual_pipeline(PYTHON_VISUAL_TYPE, python_visual.to_definition(), overwrite=True)
            except PackExecutionError:
                raise
            except Exception as exc:
                raise PackExecutionError(
                    pack_path=pack_path,
                    slide_index=index,
                    slide_slug=slide_slug_for_error,
                    slide_id=slide.id,
                    slide_title=slide.title,
                    visual_ref=visual_ref_label,
                    visual_path=visual_path if "visual_path" in locals() else None,
                    phase="visual_load",
                    dax_artifact_paths=(),
                    cause=exc,
                ) from exc

            merged_filters = merge_odata_filters(rendered_global_filters, _render_filters(filters))
            calculate_filters = merge_calculate_filters(
                rendered_global_calculate,
                slide_calculate,
                _render_filters(calculate),
            )

            if evidence_enabled and evidence_config is not None:
                adapter = get_visual_bindings_adapter(visual.type)
                if adapter is not None:
                    source_path = visual_path if visual_ref.ref else None
                    bindings = adapter.list_bindings(visual, source_path=source_path)
                    selected = select_evidence_bindings(bindings, selector=evidence_config)

                    if selected:
                        visual_token = (
                            _format_selector_path(visual_path)
                            if visual_ref.ref
                            else _pack_inline_visual_token(
                                pack_token,
                                slide_index=index,
                                slide=slide,
                                placeholder_id=placeholder_id,
                            )
                        )
                        slide_metrics_config = slide.context.metrics if slide.context else None
                        scoped_metrics_calculate = ScopedCalculateMap.merge(
                            root_metrics_calculate,
                            slide_metrics_config.calculate if slide_metrics_config else None,
                        )
                        metrics_scoped_filters = _render_metrics_calculate_filters_for_evidence(
                            metrics_calculate=scoped_metrics_calculate,
                            env=jinja_env,
                            context=slide_payload,
                        )
                        base_calculate = merge_calculate_filters(
                            list(metrics_scoped_filters),
                            calculate_filters,
                            *_render_visual_calculate_fragments(visual, env=jinja_env, context=slide_payload),
                        )

                        raw_visual_define = getattr(visual, "define", None)
                        rendered_visual_define = (
                            render_value(raw_visual_define, env=jinja_env, context=slide_payload)
                            if raw_visual_define is not None
                            else None
                        )
                        define_fragments = [
                            *flatten_context_fragments(rendered_define, label="define"),
                            *flatten_context_fragments(rendered_visual_define, label="define"),
                        ]
                        context_define = define_fragments or None

                        for binding in selected:
                            rendered_binding_evaluate = render_value(
                                binding.calculate.evaluate or None,
                                env=jinja_env,
                                context=slide_payload,
                            )
                            binding_calculate = merge_calculate_filters(base_calculate, rendered_binding_evaluate)

                            evidence_targets.append(
                                build_pack_evidence_target(
                                    pack_token=pack_token,
                                    visual_token=visual_token,
                                    slide_slug=slide_slug,
                                    slide_id=slide.id,
                                    slide_index=index,
                                    placeholder_id=placeholder_id,
                                    binding=binding,
                                    env=jinja_env,
                                    context_payload=slide_payload,
                                    context_calculate=binding_calculate or None,
                                    context_define=context_define,
                                )
                            )

            if evidence_only:
                return

            artifact_label = f"[{ordinal}]_{slide_label}"
            logger.info(
                "Processing slide",
                extra={
                    "slide": slide_label,
                    "index": index,
                    "title": slide.title,
                    "visual_ref": visual_ref,
                    "placeholder": placeholder_id,
                },
            )
            logger.debug(
                "Resolved visual",
                extra={"visual_path": str(visual_path), "visual_type": getattr(visual, "type", None)},
            )

            metadata_update: dict[str, object] = {}
            if slide_payload:
                metadata_update["context"] = slide_payload

            width_px: int | None = None
            height_px: int | None = None

            template_name = slide.template
            if placeholder_id is not None and template_name:
                geom = template_geometry_by_placeholder.get((template_name, placeholder_id))
                if geom:
                    width_px, height_px = geom.width_px, geom.height_px
            elif template_name:
                geom = template_geometry_by_template.get(template_name)
                if geom:
                    width_px, height_px = geom.width_px, geom.height_px

            base_meta = base.metadata or {}
            if width_px is not None and "width" not in base_meta:
                metadata_update.setdefault("width", width_px)
            if height_px is not None and "height" not in base_meta:
                metadata_update.setdefault("height", height_px)
            options, slide_dir = _prepare_slide_options(
                base,
                slide_slug=artifact_label,
                artefact_root=output_root,
                metadata_update=metadata_update,
                png_scale=base.png_scale,
            )

            if visual.type == "powerbi":
                if merged_filters:
                    options.metadata["powerbi_filters"] = merged_filters
                options.metadata.setdefault("build_artifacts_dir", slide_dir / "pbi_exports")

            if calculate_filters or rendered_define:
                existing_context = options.metadata.get("context") if isinstance(options.metadata, dict) else {}
                merged_context = merge_context_payload(
                    base=existing_context if isinstance(existing_context, Mapping) else {},
                    calculate=calculate_filters,
                    define=rendered_define,
                )
                options.metadata["context"] = merged_context
                logger.debug(
                    "Applied context to slide",
                    extra={
                        "slide": slide_label,
                        "calculate_count": len(calculate_filters) if calculate_filters else 0,
                        "has_define": bool(rendered_define),
                    },
                )

            if is_python_visual and python_visual is not None:
                try:
                    visual_context = _instantiate_python_visual_context(
                        visual=python_visual,
                        metadata=options.metadata,
                    )
                except Exception as exc:
                    raise PackExecutionError(
                        pack_path=pack_path,
                        slide_index=index,
                        slide_slug=slide_slug_for_error,
                        slide_id=slide.id,
                        slide_title=slide.title,
                        visual_ref=visual_ref_label,
                        visual_path=visual_path,
                        phase="visual_context",
                        dax_artifact_paths=_discover_dax_artifacts(options.artefact_dir),
                        cause=exc,
                    ) from exc
            else:
                registration = get_visual_registration(visual.type)
                try:
                    visual_context = _instantiate_slide_context(
                        registration=registration,
                        metadata=options.metadata,
                        project_root=resolved_project_root,
                    )
                except Exception as exc:
                    raise PackExecutionError(
                        pack_path=pack_path,
                        slide_index=index,
                        slide_slug=slide_slug_for_error,
                        slide_id=slide.id,
                        slide_title=slide.title,
                        visual_ref=visual_ref_label,
                        visual_path=visual_path,
                        phase="visual_context",
                        dax_artifact_paths=_discover_dax_artifacts(options.artefact_dir),
                        cause=exc,
                    ) from exc

            execution_context = ExecutionContext(
                config_path=visual_path,
                project_root=resolved_project_root,
                case_key=slide_label,
                options=options,
                visual_context=visual_context,
            )

            if visual.type == "powerbi":
                assert powerbi_queue is not None
                powerbi_queue.enqueue(
                    PowerBIExportJob(
                        slide_index=index,
                        slide_slug=slide_label,
                        slide_title=slide.title,
                        slide=slide,
                        visual=visual,
                        visual_path=visual_path,
                        execution_context=execution_context,
                    )
                )
                return

            try:
                assert resolved_pipeline is not None
                logger.debug(
                    "Executing pipeline",
                    extra={
                        "slide": slide_label,
                        "visual_type": getattr(visual, "type", None),
                        "odata_filter_keys": sorted(merged_filters.keys()) if isinstance(merged_filters, Mapping) else None,
                        "calculate_count": len(calculate_filters) if calculate_filters else 0,
                        "png_target": str(options.outputs[0].path) if options.outputs else None,
                        "artefact_dir": str(options.artefact_dir) if options.artefact_dir else None,
                    },
                )
                result = resolved_pipeline.execute(visual, execution_context)
            except PackExecutionError:
                raise
            except Exception as exc:
                logger.exception(
                    "Slide failed",
                    extra={
                        "slide": slide_label,
                        "visual_ref": visual_ref,
                        "visual_path": str(visual_path),
                    },
                )
                raise PackExecutionError(
                    pack_path=pack_path,
                    slide_index=index,
                    slide_slug=slide_slug_for_error,
                    slide_id=slide.id,
                    slide_title=slide.title,
                    visual_ref=visual_ref_label,
                    visual_path=visual_path,
                    phase="visual_execute",
                    dax_artifact_paths=_discover_dax_artifacts(options.artefact_dir),
                    cause=exc,
                ) from exc
            png_path = _select_png_output(result, options.outputs)
            logger.info(
                "Slide completed",
                extra={
                    "slide": slide_label,
                    "visual_type": getattr(visual, "type", None),
                    "png_path": str(png_path) if png_path else None,
                    "artefact_dir": str(slide_dir),
                },
            )

            if png_path:
                target_map[slide_label] = png_path

            ordered_results.append(
                (
                    index,
                    PackSlideResult(
                        slide=slide,
                        visual_path=visual_path,
                        result=result,
                        png_path=png_path,
                    ),
                )
            )

        if slide.visual is not None:
            _execute_visual(
                visual_ref=slide.visual,
                slide_label=slide_slug,
                filters=slide.visual.filters,
                calculate=slide.visual.calculate,
                slide_calculate=rendered_slide_calculate,
                target_map=slide_png_map,
            )

        if slide.placeholders:
            placeholder_map = placeholder_png_map.setdefault(slide_slug, {})
            for placeholder_id, placeholder in slide.placeholders.items():
                placeholder_slug = f"{slide_slug}__{slugify(placeholder_id)}"
                if placeholder.image:
                    image_path = (pack_root / placeholder.image).expanduser().resolve(strict=False)
                    if not image_path.exists():
                        raise ValueError(
                            f"Static placeholder image not found for '{placeholder_id}' on slide '{slide_slug}': {image_path}"
                        )
                    placeholder_map[placeholder_slug] = image_path
                    continue

                if placeholder.text:
                    continue

                if placeholder.visual is None:
                    raise ValueError(f"Placeholder '{placeholder_id}' on slide '{slide_slug}' is missing both visual and image")

                _execute_visual(
                    visual_ref=placeholder.visual,
                    slide_label=placeholder_slug,
                    filters=placeholder.visual.filters,
                    calculate=placeholder.visual.calculate,
                    slide_calculate=rendered_slide_calculate,
                    placeholder_id=placeholder_id,
                    target_map=placeholder_map,
                )

    if evidence_only:
        logger.info(
            "Evidence-only pack run: skipping slide execution and PPTX assembly",
            extra={"pack_path": str(pack_path), "slide_count": len(pack.slides), "target_count": len(evidence_targets)},
        )

        evidence_failure: tuple[Path, int] | None = None
        if evidence_enabled and evidence_config is not None:
            if catalog is None:
                raise ValueError("Pack evidence exports require a metric catalog; metrics_root could not be resolved.")

            data_mode = base.data.provider_key if base.data and base.data.provider_key else "live"
            if data_mode not in {"mock", "live"}:
                raise ValueError("Pack evidence exports only support data_mode in {'mock', 'live'}.")

            datasource = None
            if data_mode == "live":
                datasource = resolve_evidence_datasource(
                    pack_path,
                    dataset_id=base.data.dataset_id if base.data else None,
                    workspace_id=base.data.workspace_id if base.data else None,
                    datasource_name=base.data.datasource_override if base.data else None,
                )

            manifest_path, manifest_bindings, has_failures = run_pack_evidence_exports(
                config=evidence_config,
                catalog=catalog,
                pack_path=pack_path,
                artefact_dir=output_root,
                env=jinja_env,
                output_dir_context=global_payload,
                datasource=datasource,
                data_mode=data_mode,
                targets=evidence_targets,
            )

            failure_count = sum(1 for entry in manifest_bindings if entry.get("status") == "failed")
            logger.info(
                "Evidence-only pack run: evidence exports finished",
                extra={
                    "pack_path": str(pack_path),
                    "manifest_path": str(manifest_path),
                    "target_count": len(manifest_bindings),
                    "failure_count": failure_count,
                    "has_failures": has_failures,
                },
            )
            if has_failures and evidence_config.on_error == "fail":
                evidence_failure = (manifest_path, failure_count)

        elapsed = time.perf_counter() - started
        logger.info(
            "Evidence-only pack run completed in %.3fs",
            elapsed,
            extra={"pack": str(pack_path), "slide_count": len(pack.slides)},
        )

        if evidence_failure is not None:
            manifest_path, failure_count = evidence_failure
            raise PackEvidenceFailure(
                pack_path=pack_path,
                manifest_path=manifest_path,
                failure_count=failure_count,
                successful_results=[],
            )

        return []

    for index, slide in enumerate(pack.slides, start=1):
        slide_slug = _slug_for_slide(slide, index)
        if slide_slug in slide_png_map:
            continue
        if not slide.image:
            continue
        image_path = (pack_root / slide.image).expanduser().resolve(strict=False)
        if not image_path.exists():
            raise ValueError(f"Static slide image not found for '{slide_slug}': {image_path}")
        slide_png_map[slide_slug] = image_path

    assert powerbi_queue is not None
    powerbi_results = powerbi_queue.drain()
    for item in powerbi_results:
        if item.exception is None:
            continue
        if isinstance(item.exception, PackExecutionError):
            continue
        item.exception = PackExecutionError(
            pack_path=pack_path,
            slide_index=item.job.slide_index,
            slide_slug=item.job.slide_slug,
            slide_id=item.job.slide.id,
            slide_title=item.job.slide_title,
            visual_ref=str(item.job.visual_path) if item.job.visual_path else None,
            visual_path=item.job.visual_path,
            phase="powerbi_export",
            dax_artifact_paths=_discover_dax_artifacts(item.job.execution_context.options.artefact_dir),
            cause=item.exception,
        )
    failed_powerbi = [item for item in powerbi_results if item.exception]
    for item in powerbi_results:
        if item.result is None:
            continue
        png_path = _select_png_output(item.result, item.job.execution_context.options.outputs)
        if png_path:
            slide_slug = item.job.slide_slug
            if "__" in slide_slug:
                parent = slide_slug.split("__", 1)[0]
                placeholder_map = placeholder_png_map.setdefault(parent, {})
                placeholder_map[slide_slug] = png_path
            else:
                slide_png_map[slide_slug] = png_path
        ordered_results.append(
            (
                item.job.slide_index,
                PackSlideResult(
                    slide=item.job.slide,
                    visual_path=item.job.visual_path,
                    result=item.result,
                    png_path=png_path,
                ),
            )
        )

    ordered_results.sort(key=lambda pair: pair[0])
    sorted_results = [item[1] for item in ordered_results]

    pack_failed = bool(failed_powerbi)
    evidence_failure: tuple[Path, int] | None = None
    if evidence_enabled and evidence_config is not None:
        should_run_evidence = evidence_config.when == "always" or not pack_failed
        if should_run_evidence:
            if catalog is None:
                raise ValueError("Pack evidence exports require a metric catalog; metrics_root could not be resolved.")

            data_mode = base.data.provider_key if base.data and base.data.provider_key else "live"
            if data_mode not in {"mock", "live"}:
                raise ValueError("Pack evidence exports only support data_mode in {'mock', 'live'}.")

            datasource = None
            if data_mode == "live":
                datasource = resolve_evidence_datasource(
                    pack_path,
                    dataset_id=base.data.dataset_id if base.data else None,
                    workspace_id=base.data.workspace_id if base.data else None,
                    datasource_name=base.data.datasource_override if base.data else None,
                )

            logger.info(
                "Running pack evidence exports",
                extra={
                    "pack_path": str(pack_path),
                    "target_count": len(evidence_targets),
                    "when": evidence_config.when,
                    "on_error": evidence_config.on_error,
                    "output_dir": evidence_config.output_dir,
                },
            )
            manifest_path, manifest_bindings, has_failures = run_pack_evidence_exports(
                config=evidence_config,
                catalog=catalog,
                pack_path=pack_path,
                artefact_dir=output_root,
                env=jinja_env,
                output_dir_context=global_payload,
                datasource=datasource,
                data_mode=data_mode,
                targets=evidence_targets,
            )

            failure_count = sum(1 for entry in manifest_bindings if entry.get("status") == "failed")
            logger.info(
                "Pack evidence exports finished",
                extra={
                    "pack_path": str(pack_path),
                    "manifest_path": str(manifest_path),
                    "target_count": len(manifest_bindings),
                    "failure_count": failure_count,
                    "has_failures": has_failures,
                },
            )
            if has_failures:
                logger.warning(
                    "Pack evidence exports reported failures",
                    extra={
                        "pack": str(pack_path),
                        "manifest_path": str(manifest_path),
                        "failure_count": failure_count,
                    },
                )

            if has_failures and evidence_config.on_error == "fail" and not pack_failed:
                evidence_failure = (manifest_path, failure_count)
        else:
            logger.info(
                "Skipping pack evidence exports (pack failures and when=pack_complete)",
                extra={
                    "pack_path": str(pack_path),
                    "when": evidence_config.when,
                    "failed_powerbi_count": len(failed_powerbi),
                },
            )

    if failed_powerbi:
        failed_slides = [item.job.slide_slug for item in failed_powerbi]
        logger.error(
            "Power BI slides failed",
            extra={"failed_slide_count": len(failed_slides), "failed_slides": failed_slides},
        )
        summary = _format_powerbi_failure_summary(failed_powerbi)
        raise PackPowerBIFailure(
            summary,
            successful_results=sorted_results,
            failed_exports=failed_powerbi,
        )

    raw_result_file = base.metadata.get("result_file") if base.metadata else None
    result_file: Path | None = None
    if isinstance(raw_result_file, (str, Path)):
        result_file = Path(raw_result_file)
    elif raw_result_file is not None:
        logger.warning(
            "Skipping PPTX assembly because result_file metadata is not path-like",
            extra={"pack": str(pack_path), "result_file_type": type(raw_result_file).__name__},
        )

    if result_file:
        raw_template = base.metadata.get("pptx_template") if base.metadata else None
        if isinstance(raw_template, (str, Path)):
            template_path: Path | None = Path(raw_template)
        else:
            if raw_template is not None:
                logger.warning(
                    "Ignoring pptx_template metadata because it is not path-like",
                    extra={"pack": str(pack_path), "template_type": type(raw_template).__name__},
                )
            template_path = _resolve_default_template(pack_path)

        if template_path is None:
            logger.warning(
                "Skipping PPTX assembly because no template was found",
                extra={"pack": str(pack_path), "result_file": str(result_file)},
            )
        else:
            try:
                assemble_pack_pptx(
                    pack=pack,
                    results=sorted_results,
                    context_payload=global_display_payload,
                    slide_contexts=slide_contexts_by_slug,
                    slide_pngs=slide_png_map,
                    placeholder_pngs=placeholder_png_map,
                    result_path=result_file,
                    template_path=template_path,
                    allow_missing_pngs=bool(slide_filter),
                )
            except Exception:
                logger.exception("PPTX assembly failed", extra={"result_file": str(result_file)})
                raise

    elapsed = time.perf_counter() - started
    logger.info(
        "Pack run completed in %.3fs",
        elapsed,
        extra={
            "pack": str(pack_path),
            "slide_count": len(pack.slides),
            "slide_results": len(sorted_results),
            "result_file": str(result_file) if result_file else None,
        },
    )

    if evidence_failure is not None:
        manifest_path, failure_count = evidence_failure
        raise PackEvidenceFailure(
            pack_path=pack_path,
            manifest_path=manifest_path,
            failure_count=failure_count,
            successful_results=sorted_results,
        )

    return sorted_results


def restitch_pack_pptx(
    pack_path: Path,
    pack: PackConfig,
    *,
    output_root: Path,
    result_file: Path,
    base_options: PipelineOptions,
) -> None:
    """Rebuild a pack PPTX using existing artefacts and static images."""

    output_root.mkdir(parents=True, exist_ok=True)
    result_file.parent.mkdir(parents=True, exist_ok=True)

    # Resolve the same metric context as full runs so PPTX-only restitches can
    # render text placeholders consistently.
    jinja_env = create_pack_jinja_env()
    base_metadata = base_options.metadata if isinstance(base_options.metadata, Mapping) else None
    base_context_payload = _resolve_pack_base_context_payload(
        pack_path=pack_path,
        metadata=base_metadata,
        pack_context_layer=dump_context_payload(pack.context),
        env=jinja_env,
    )
    pack_payload = merge_context_layer_payload(base=base_context_payload, incoming=dump_context_payload(pack.context))

    rendered_global_calculate = render_value(pack.calculate, env=jinja_env, context=pack_payload)
    rendered_define = render_value(pack.define, env=jinja_env, context=pack_payload)

    root_metrics_context = pack.context.metrics
    root_bindings = root_metrics_context.bindings if root_metrics_context else []
    root_metrics_calculate = root_metrics_context.calculate if root_metrics_context else None
    slide_bindings_present = any(
        slide.context is not None
        and slide.context.metrics is not None
        and slide.context.metrics.bindings
        for slide in pack.slides
    )
    has_metric_bindings = bool(root_bindings) or slide_bindings_present

    builder_context = None
    catalog = None
    if has_metric_bindings:
        metrics_calculate, metrics_define = resolve_dax_context(
            base=pack_payload,
            calculate=rendered_global_calculate,
            define=rendered_define,
        )
        builder_context = discover_builder_context_for_pack(
            pack_path=pack_path,
            project_root=pack_path.parent.expanduser().resolve(strict=False),
            metadata=base_metadata,
            calculate=metrics_calculate,
            define=metrics_define,
        )
        catalog = load_catalog_for_context(builder_context)

        global_metrics_context = resolve_metric_context(
            bindings=root_bindings or None,
            inherited=None,
            builder_context=builder_context,
            catalog=catalog,
            env=jinja_env,
            base_payload=pack_payload,
            scope="root",
            metrics_calculate=root_metrics_calculate,
            artefact_dir=output_root,
        )
    else:
        global_metrics_context = ResolvedMetricContext(
            aliases={},
            by_key={},
            signatures_by_key={},
            formats_by_alias={},
        )
    global_payload: dict[str, object] = dict(pack_payload)
    global_payload.update(global_metrics_context.aliases)
    global_display_payload = _build_display_payload(
        raw_payload=global_payload,
        formats_by_alias=global_metrics_context.formats_by_alias,
    )

    slide_png_map: dict[str, Path] = {}
    placeholder_png_map: dict[str, dict[str, Path]] = {}
    slide_contexts_by_slug: dict[str, dict[str, object]] = {}
    pack_root = pack_path.parent

    for index, slide in enumerate(pack.slides, start=1):
        slide_payload: dict[str, object] = dict(global_payload)
        raw_slide_context: dict[str, object] = {}
        if slide.context is not None:
            raw_slide_context = dump_context_payload(slide.context)
            slide_payload.update(raw_slide_context)

        effective_metrics_context = global_metrics_context
        if has_metric_bindings and builder_context is not None and catalog is not None:
            slide_metrics_config = slide.context.metrics if slide.context else None
            slide_metrics_calculate = ScopedCalculateMap.merge(
                root_metrics_calculate,
                slide_metrics_config.calculate if slide_metrics_config else None,
            )
            slide_metrics_context = resolve_metric_context(
                bindings=slide_metrics_config.bindings if slide_metrics_config else None,
                inherited=global_metrics_context,
                builder_context=builder_context,
                catalog=catalog,
                env=jinja_env,
                base_payload=slide_payload,
                scope=f"slide_{index}",
                metrics_calculate=slide_metrics_calculate,
                artefact_dir=output_root,
            )
            effective_metrics_context = slide_metrics_context
            slide_payload.update(slide_metrics_context.aliases)

        if has_metric_bindings:
            display_payload = _build_display_payload(
                raw_payload=slide_payload,
                formats_by_alias=effective_metrics_context.formats_by_alias,
            )
            _render_slide_context_after_metric_injection(
                env=jinja_env,
                slide_payload=slide_payload,
                display_payload=display_payload,
                raw_slide_context=raw_slide_context,
            )

        slide.title = render_value(slide.title, env=jinja_env, context=slide_payload)
        if slide.notes:
            slide.notes = render_value(slide.notes, env=jinja_env, context=slide_payload)

        slide_slug = _slug_for_slide(slide, index)
        ordinal = f"{index:02d}"

        slide_payload.update(
            {
                "title": slide.title,
                "slide_index": index,
                "slide_id": slide.id,
                "slide_slug": slide_slug,
            }
        )
        slide_contexts_by_slug[slide_slug] = _build_display_payload(
            raw_payload=slide_payload,
            formats_by_alias=effective_metrics_context.formats_by_alias,
        )

        _reuse_existing_assets(
            slide=slide,
            slide_slug=slide_slug,
            ordinal=ordinal,
            pack_root=pack_root,
            output_root=output_root,
            slide_png_map=slide_png_map,
            placeholder_png_map=placeholder_png_map,
        )

    template_override = base_options.metadata.get("pptx_template") if base_options.metadata else None
    if isinstance(template_override, (str, Path)):
        template_path: Path | None = Path(template_override)
    else:
        if template_override is not None:
            logger.warning(
                "Ignoring pptx_template metadata because it is not path-like",
                extra={"pack": str(pack_path), "template_type": type(template_override).__name__},
            )
        template_path = _resolve_default_template(pack_path)
    if template_path is None:
        logger.warning(
            "Skipping PPTX assembly because no template was found",
            extra={"pack": str(pack_path), "result_file": str(result_file)},
        )
        return

    assemble_pack_pptx(
        pack=pack,
        results=[],
        context_payload=global_display_payload,
        slide_contexts=slide_contexts_by_slug,
        slide_pngs=slide_png_map,
        placeholder_pngs=placeholder_png_map,
        result_path=result_file,
        template_path=template_path,
    )


__all__ = ["PackPowerBIFailure", "PackSlideResult", "run_pack"]
