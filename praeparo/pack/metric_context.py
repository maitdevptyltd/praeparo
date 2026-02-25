"""Resolve `context.metrics` bindings for packs and slides.

This module turns declarative metric bindings into scalar values before any
templating or PPTX work begins. The pack runner calls into this layer to:

1) Discover the dataset/metrics environment for the pack.
2) Fetch catalogue metrics in one batch for the pack root and per slide.
3) Evaluate expression bindings in dependency order.

The resulting alias map is merged into each slide's Jinja context so text
placeholders, YAML-authored shapes, and tables can reference them directly.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from jinja2 import Environment

from praeparo.datasets import MetricDatasetBuilder, MetricDatasetBuilderContext
from praeparo.datasets.context import resolve_default_metrics_root_for_pack
from praeparo.datasets.expression_eval import evaluate_expression
from praeparo.metrics import MetricCatalog, load_metric_catalog
from praeparo.models import FiltersType, PackMetricBinding
from praeparo.models.scoped_calculate import ScopedCalculateFilters, ScopedCalculateMap
from praeparo.formatting import parse_format_token
from praeparo.pack.templating import render_value
from praeparo.visuals.dax.expressions import ParsedExpression, parse_metric_expression


@dataclass
class ResolvedMetricContext:
    """Resolved scalar metric values plus reuse metadata."""

    aliases: dict[str, float | None]
    by_key: dict[str, float | None]
    signatures_by_key: dict[str, tuple[Any, ...]]
    formats_by_alias: dict[str, str]


def dump_context_payload(context: Mapping[str, Any] | Any | None) -> dict[str, object]:
    """Convert a PackContext/PacksSlideContext to a plain dict without metrics."""

    if context is None:
        return {}

    if isinstance(context, Mapping):
        payload: dict[str, object] = dict(context)
    else:
        payload = context.model_dump(mode="python", exclude_none=True)

    payload.pop("metrics", None)
    return payload


def discover_builder_context_for_pack(
    *,
    pack_path: Path,
    project_root: Path,
    metadata: Mapping[str, object] | None,
    calculate: Sequence[str] | str | None,
    define: Sequence[str] | str | None,
) -> MetricDatasetBuilderContext:
    """Discover a MetricDatasetBuilderContext aligned to a pack run."""

    raw_metrics_root = metadata.get("metrics_root") if metadata else None
    if isinstance(raw_metrics_root, (str, Path)):
        metrics_root = Path(raw_metrics_root).expanduser().resolve(strict=False)
    else:
        metrics_root = resolve_default_metrics_root_for_pack(pack_path)

    raw_measure_table = metadata.get("measure_table") if metadata else None
    measure_table = str(raw_measure_table) if isinstance(raw_measure_table, str) else None

    ignore_placeholders = bool(metadata.get("ignore_placeholders", False)) if metadata else False
    data_mode = str(metadata.get("data_mode") or "").strip().lower() if metadata else ""
    use_mock = data_mode == "mock"

    return MetricDatasetBuilderContext.discover(
        project_root=project_root,
        metrics_root=metrics_root,
        measure_table=measure_table,
        calculate=calculate,
        define=define,
        metadata=metadata,
        ignore_placeholders=ignore_placeholders,
        use_mock=use_mock,
    )


def load_catalog_for_context(builder_context: MetricDatasetBuilderContext) -> MetricCatalog:
    """Load the metric catalog for the supplied builder context."""

    return load_metric_catalog([builder_context.metrics_root])


def resolve_metric_context(
    *,
    bindings: Sequence[PackMetricBinding] | None,
    inherited: ResolvedMetricContext | None,
    builder_context: MetricDatasetBuilderContext,
    catalog: MetricCatalog,
    env: Environment,
    base_payload: Mapping[str, object],
    scope: str,
    metrics_calculate: ScopedCalculateMap | FiltersType | None = None,
    allow_empty: bool = True,
    artefact_dir: Path | None = None,
) -> ResolvedMetricContext:
    """Resolve bindings into scalars, reusing inherited values where valid."""

    # Start with inherited values so slides can extend/override root bindings.
    aliases: dict[str, float | None] = dict(inherited.aliases) if inherited else {}
    by_key: dict[str, float | None] = dict(inherited.by_key) if inherited else {}
    signatures_by_key: dict[str, tuple[Any, ...]] = dict(inherited.signatures_by_key) if inherited else {}
    formats_by_alias: dict[str, str] = dict(inherited.formats_by_alias) if inherited else {}

    raw_scope_calculate: object | None
    if metrics_calculate is None:
        raw_scope_calculate = None
    elif isinstance(metrics_calculate, ScopedCalculateMap):
        raw_scope_calculate = metrics_calculate.model_dump(mode="python")
    else:
        raw_scope_calculate = metrics_calculate

    rendered_scope_calculate = (
        render_value(raw_scope_calculate, env=env, context=base_payload) if raw_scope_calculate else None
    )
    scope_calculate_map = ScopedCalculateMap.from_raw(rendered_scope_calculate) if rendered_scope_calculate else ScopedCalculateMap()
    scope_define_filters = scope_calculate_map.flatten_define()
    scope_evaluate_filters = scope_calculate_map.flatten_evaluate()
    scope_signature = scope_calculate_map.combined_signature()

    if not bindings:
        return ResolvedMetricContext(
            aliases=aliases,
            by_key=by_key,
            signatures_by_key=signatures_by_key,
            formats_by_alias=formats_by_alias,
        )

    # Render any templated calculate/expression payloads before we build query plans.
    rendered_bindings: list[PackMetricBinding] = []
    for binding in bindings:
        rendered_ratio_to = binding.ratio_to
        if binding.ratio_to is True and binding.full_key and "." in binding.full_key:
            # Phase 7: ratio_to=true ratios against the base metric (before the first dot).
            rendered_ratio_to = binding.full_key.split(".", 1)[0]

        rendered_define = render_value(binding.calculate.define or None, env=env, context=base_payload)
        rendered_evaluate = render_value(binding.calculate.evaluate or None, env=env, context=base_payload)
        rendered_expression = (
            render_value(binding.expression, env=env, context=base_payload) if binding.expression else None
        )
        rendered_format = render_value(binding.format, env=env, context=base_payload) if binding.format else None
        cleaned_format = str(rendered_format).strip().lower() if rendered_format else None
        if cleaned_format:
            try:
                parse_format_token(cleaned_format)
            except ValueError as exc:
                alias = binding.alias or "<unknown>"
                raise ValueError(
                    f"{scope} context.metrics binding '{alias}' declares an invalid format token "
                    f"'{cleaned_format}': {exc}"
                ) from exc

        scoped_calculate = ScopedCalculateFilters(
            define=_normalise_rendered_calculate(rendered_define),
            evaluate=_normalise_rendered_calculate(rendered_evaluate),
        )
        rendered_bindings.append(
            binding.model_copy(
                update={
                    "calculate": scoped_calculate,
                    "expression": str(rendered_expression).strip() if rendered_expression else None,
                    "format": cleaned_format,
                    "ratio_to": rendered_ratio_to,
                }
            )
        )

    key_bindings = [binding for binding in rendered_bindings if binding.full_key and not binding.expression]
    expression_bindings = [binding for binding in rendered_bindings if binding.expression]

    # Parse expressions and discover metric-key dependencies that must be fetched.
    expr_aliases = {binding.alias for binding in expression_bindings if binding.alias}
    parsed_expressions: dict[str, ParsedExpression] = {}
    referenced_identifiers: set[str] = set()
    for binding in expression_bindings:
        assert binding.alias is not None and binding.expression is not None
        try:
            parsed = parse_metric_expression(binding.expression)
        except Exception as exc:
            raise ValueError(
                f"{scope} context.metrics expression for alias '{binding.alias}' is invalid: {exc}"
            ) from exc
        parsed_expressions[binding.alias] = parsed
        referenced_identifiers.update(ref.identifier for ref in parsed.references)

    explicit_full_keys = {binding.full_key for binding in key_bindings if binding.full_key}
    explicit_aliases = {binding.alias for binding in rendered_bindings if binding.alias}

    implicit_metric_keys: set[str] = set()
    for identifier in referenced_identifiers:
        if identifier in expr_aliases:
            continue
        if identifier in aliases:
            continue
        if identifier in explicit_aliases:
            continue
        if identifier in by_key:
            continue
        if catalog.contains(identifier):
            implicit_metric_keys.add(identifier)

    # Decide which explicit key bindings can be reused from inherited values.
    bindings_to_fetch: list[PackMetricBinding] = []
    binding_signatures: dict[str, tuple[Any, ...]] = {}
    for binding in key_bindings:
        full_key = binding.full_key
        assert full_key is not None
        if not catalog.contains(full_key):
            raise ValueError(f"{scope} context.metrics references unknown metric key '{full_key}'")

        binding_sig = binding.signature() + (scope_signature,)
        binding_signatures[full_key] = binding_sig
        inherited_sig = signatures_by_key.get(full_key)
        if inherited_sig is not None and inherited_sig == binding_sig:
            # Reuse inherited key and expose it under this alias if needed.
            alias = binding.alias or full_key.replace(".", "_")
            aliases[alias] = by_key.get(full_key)
            if binding.format:
                formats_by_alias[alias] = binding.format
            else:
                formats_by_alias.pop(alias, None)
            continue

        bindings_to_fetch.append(binding)

    # Add implicit metric keys required by expressions.
    dependency_fetches: dict[str, str] = {}
    taken_series_ids = set(explicit_aliases) | {binding.alias for binding in bindings_to_fetch if binding.alias}
    for full_key in sorted(implicit_metric_keys):
        if full_key in by_key or full_key in explicit_full_keys:
            continue
        if not catalog.contains(full_key):
            raise ValueError(
                f"{scope} context.metrics expression references unknown metric key '{full_key}'"
            )
        dep_alias = _allocate_dependency_alias(full_key, taken_series_ids)
        dependency_fetches[dep_alias] = full_key

    if bindings_to_fetch or dependency_fetches:
        # Batch DAX fetch once per scope, using global pack context filters/define blocks.
        builder = MetricDatasetBuilder(context=builder_context, slug=f"{scope}_metric_context")

        if builder_context.use_mock:
            builder.mock_rows(1)

        if scope_define_filters:
            builder.calculate(scope_define_filters)

        for binding in bindings_to_fetch:
            full_key = binding.full_key
            assert full_key is not None
            ratio_denominator = _resolve_ratio_denominator(binding, catalog=catalog, scope=scope)
            effective_evaluate = [*scope_evaluate_filters, *binding.calculate.evaluate]
            builder.metric(
                full_key,
                alias=binding.alias,
                calculate=binding.calculate.define,
                evaluate=effective_evaluate,
                ratio_to=ratio_denominator,
            )

        for dep_alias, full_key in dependency_fetches.items():
            builder.metric(full_key, alias=dep_alias, evaluate=scope_evaluate_filters)

        # Emit the compiled DAX plan before execution so pack authors can inspect it.
        plan = builder.plan()
        if artefact_dir is not None:
            _emit_metric_context_dax(
                statement=plan.statement,
                artefact_dir=artefact_dir,
                scope=scope,
            )

        rows = _execute_builder_rows(builder, scope=scope)
        if artefact_dir is not None:
            _emit_metric_context_results(rows=rows, artefact_dir=artefact_dir, scope=scope)
        if not rows:
            if not allow_empty:
                raise ValueError(
                    f"{scope} context.metrics expected a single-row dataset but received {len(rows)} rows. "
                    "Add pack or slide filters to scope the grain."
                )
            row: Mapping[str, object] = {}
        elif len(rows) > 1:
            raise ValueError(
                f"{scope} context.metrics expected a single-row dataset but received {len(rows)} rows. "
                "Add pack or slide filters to scope the grain."
            )
        else:
            row = rows[0]

        for binding in bindings_to_fetch:
            full_key = binding.full_key
            assert full_key is not None and binding.alias is not None
            value = _coerce_float(row.get(binding.alias))
            by_key[full_key] = value
            signatures_by_key[full_key] = binding_signatures.get(full_key, binding.signature() + (scope_signature,))
            aliases[binding.alias] = value
            if binding.format:
                formats_by_alias[binding.alias] = binding.format
            else:
                formats_by_alias.pop(binding.alias, None)

        for dep_alias, full_key in dependency_fetches.items():
            value = _coerce_float(row.get(dep_alias))
            by_key[full_key] = value
            signatures_by_key[full_key] = (full_key, tuple(), None, None, scope_signature)

    if expression_bindings:
        _evaluate_expressions(
            expression_bindings=expression_bindings,
            parsed_expressions=parsed_expressions,
            aliases=aliases,
            by_key=by_key,
            scope=scope,
        )
        for binding in expression_bindings:
            alias = binding.alias
            assert alias is not None
            if binding.format:
                formats_by_alias[alias] = binding.format
            else:
                formats_by_alias.pop(alias, None)

    return ResolvedMetricContext(
        aliases=aliases,
        by_key=by_key,
        signatures_by_key=signatures_by_key,
        formats_by_alias=formats_by_alias,
    )


def _normalise_rendered_calculate(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item and item.strip()]
    if isinstance(value, Sequence):
        cleaned: list[str] = []
        for item in value:
            if not item:
                continue
            cleaned_item = str(item).strip()
            if cleaned_item:
                cleaned.append(cleaned_item)
        return cleaned
    if isinstance(value, Mapping):
        return [str(item).strip() for item in value.values() if item and str(item).strip()]
    raise TypeError("calculate must render to string or list")


def _allocate_dependency_alias(full_key: str, taken: MutableMapping[str, object] | set[str]) -> str:
    base = f"__dep_{full_key.replace('.', '_')}"
    candidate = base
    counter = 2
    taken_set = taken if isinstance(taken, set) else set(taken.keys())
    while candidate in taken_set:
        candidate = f"{base}_{counter}"
        counter += 1
    if isinstance(taken, set):
        taken.add(candidate)
    else:
        taken[candidate] = True
    return candidate


def _resolve_ratio_denominator(
    binding: PackMetricBinding,
    *,
    catalog: MetricCatalog,
    scope: str,
) -> str | None:
    """Resolve and validate ratio_to denominators for metric-context bindings.

    Phase 7 accepts metric keys only for string denominators to avoid alias ambiguity.
    """

    if binding.ratio_to is None:
        return None

    alias = binding.alias or "<unknown>"
    full_key = binding.full_key
    if not full_key:
        raise ValueError(
            f"{scope} context.metrics binding '{alias}' declares ratio_to but is missing a numerator metric key."
        )

    if binding.expression:
        raise ValueError(
            f"{scope} context.metrics binding '{alias}' cannot combine ratio_to with expression bindings yet "
            f"(numerator '{full_key}')."
        )

    raw_ratio_to = binding.ratio_to
    if raw_ratio_to is True:
        if "." not in full_key:
            raise ValueError(
                f"{scope} context.metrics binding '{alias}' declares ratio_to=true but numerator '{full_key}' "
                "is not dotted; cannot infer a denominator."
            )
        denominator_key = full_key.split(".", 1)[0]
    else:
        assert isinstance(raw_ratio_to, str)
        denominator_key = raw_ratio_to

    if not catalog.contains(denominator_key):
        raise ValueError(
            f"{scope} context.metrics binding '{alias}' ratios numerator '{full_key}' against unknown "
            f"denominator metric key '{denominator_key}'."
        )

    return denominator_key


def _evaluate_expressions(
    *,
    expression_bindings: Sequence[PackMetricBinding],
    parsed_expressions: Mapping[str, ParsedExpression],
    aliases: MutableMapping[str, float | None],
    by_key: Mapping[str, float | None],
    scope: str,
) -> None:
    # Build dependency edges between expression aliases.
    expr_aliases = {binding.alias for binding in expression_bindings if binding.alias}
    deps_by_alias: dict[str, set[str]] = {}

    for binding in expression_bindings:
        alias = binding.alias
        assert alias is not None
        parsed = parsed_expressions[alias]
        deps = {ref.identifier for ref in parsed.references if ref.identifier in expr_aliases}
        deps_by_alias[alias] = deps

    ordered = _toposort(deps_by_alias, scope=scope)

    for alias in ordered:
        binding = next(b for b in expression_bindings if b.alias == alias)
        parsed = parsed_expressions[alias]

        substitutions: dict[str, float] = {}
        for ref in parsed.references:
            identifier = ref.identifier
            if identifier in aliases:
                value = aliases.get(identifier)
            elif identifier in by_key:
                value = by_key.get(identifier)
            else:
                raise ValueError(
                    f"{scope} context.metrics expression for alias '{alias}' references "
                    f"unknown identifier '{identifier}'."
                )
            if value is not None:
                substitutions[identifier] = float(value)

        result = evaluate_expression(parsed, substitutions)
        aliases[alias] = float(result) if result is not None else None


def _toposort(edges: Mapping[str, set[str]], *, scope: str) -> list[str]:
    remaining: dict[str, set[str]] = {key: set(deps) for key, deps in edges.items()}
    ready = [key for key, deps in remaining.items() if not deps]
    ordered: list[str] = []

    while ready:
        node = ready.pop()
        ordered.append(node)
        for key, deps in remaining.items():
            if node in deps:
                deps.remove(node)
                if not deps and key not in ordered and key not in ready:
                    ready.append(key)

    if len(ordered) != len(remaining):
        cyclic = [key for key, deps in remaining.items() if deps]
        raise ValueError(f"{scope} context.metrics contains a cyclic expression dependency: {cyclic}")

    return ordered


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return None


def _execute_builder_rows(builder: MetricDatasetBuilder, *, scope: str) -> list[dict[str, object]]:
    """Execute the builder in sync or async-friendly mode.

    MetricDatasetBuilder.execute() uses asyncio.run() and will fail if the pack
    runner is invoked from within an existing event loop (for example, notebooks
    or async CLIs). When we detect a running loop, execute the async path on a
    dedicated thread with its own loop and block on the result.
    """
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return builder.execute()
        raise RuntimeError("active_loop")
    except RuntimeError as exc:
        message = str(exc)
        if message not in ("active_loop",) and "MetricDatasetBuilder.execute() cannot run inside an active event loop" not in message:
            raise

    future: concurrent.futures.Future[list[dict[str, object]]] = concurrent.futures.Future()

    def _run_async() -> None:
        try:
            result = asyncio.run(builder.aexecute())
            future.set_result(result.rows)
        except Exception as exc:  # noqa: BLE001
            future.set_exception(exc)

    thread = threading.Thread(target=_run_async, name=f"praeparo_metric_context_{scope}", daemon=True)
    thread.start()
    return future.result()


def _emit_metric_context_dax(*, statement: str, artefact_dir: Path, scope: str) -> None:
    """Write a metric-context DAX statement into the artefact directory.

    Metric context bindings execute outside the visual pipeline, so we emit the
    compiled query here to keep debugging parity with visual `.dax` artifacts.
    """

    cleaned = (statement or "").strip()
    if not cleaned:
        return

    safe_scope = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in scope)
    filename = f"metric_context.{safe_scope}.dax"

    artefact_dir.mkdir(parents=True, exist_ok=True)
    (artefact_dir / filename).write_text(cleaned + "\n", encoding="utf-8")


def _emit_metric_context_results(
    *,
    rows: Sequence[Mapping[str, object]],
    artefact_dir: Path,
    scope: str,
) -> None:
    """Write resolved metric-context rows into the artefact directory.

    We always emit the raw rows (even if multi-row) so pack authors can debug
    grain issues without rerunning Power BI.
    """

    safe_scope = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in scope)
    filename = f"metric_context.{safe_scope}.data.json"

    artefact_dir.mkdir(parents=True, exist_ok=True)
    payload = [dict(row) for row in rows]
    (artefact_dir / filename).write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


__all__ = [
    "ResolvedMetricContext",
    "discover_builder_context_for_pack",
    "dump_context_payload",
    "load_catalog_for_context",
    "resolve_metric_context",
]
