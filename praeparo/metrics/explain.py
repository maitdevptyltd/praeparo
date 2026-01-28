"""Explain helpers for metric debugging workflows.

The explain feature emits a row-based evidence query for a metric key (optionally
including a dotted variant path) so analysts can export "show your working"
inputs such as EventKeys, timestamps, deltas, and pass/fail flags.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping, Sequence

from praeparo.metrics.catalog import MetricCatalog
from praeparo.metrics.components import MetricComponentLoader
from praeparo.metrics.dax import MetricDaxBuilder
from praeparo.metrics.models import MetricDefinition, MetricExplainSpec, MetricVariant
from praeparo.utils import normalize_dax_expression
from praeparo.visuals.dax.cache import MetricCompilationCache, resolve_metric_reference
from praeparo.visuals.dax.utils import normalise_define_blocks
from praeparo.visuals.dax.utils import split_metric_identifier


DEFAULT_EXPLAIN_FROM = "fact_events"
DEFAULT_EXPLAIN_GRAIN = "fact_events[EventKey]"
DEFAULT_MEASURE_TABLE = "'adhoc'"
_EXPLAIN_METRIC_MEASURE = "__praeparo_explain_metric"
_EXPLAIN_BASE_MEASURE = "__praeparo_explain_base_metric"
_EXPLAIN_DENOMINATOR_MEASURE = "__praeparo_explain_denominator_metric"


@dataclass(frozen=True)
class MetricExplainPlan:
    """Compiled explain query + metadata for exporting evidence."""

    metric_identifier: str
    """The fully qualified key being explained (metric or metric.variant...)."""

    statement: str
    """The DAX statement to execute."""

    column_order: tuple[str, ...]
    """Deterministic column ordering used by exporters."""

    warnings: tuple[str, ...] = ()
    """Human-readable warnings (e.g. when __passes_variant could not be emitted)."""


def resolve_metric_explain_spec(
    catalog: MetricCatalog,
    *,
    metric_key: str,
    variant_path: str | None,
) -> MetricExplainSpec | None:
    """Return the effective explain spec for a metric + optional variant path.

    Resolution follows the same inheritance semantics as other metric fields:
    the `extends` chain is applied first (root → leaf), then variant patches are
    applied along the dotted variant path (parent variant → leaf variant).
    """

    metric = catalog.get_metric(metric_key)
    if metric is None:
        raise KeyError(f"Metric '{metric_key}' not found in catalog.")

    effective: MetricExplainSpec | None = None
    component_loader = MetricComponentLoader()

    for ancestor in _resolve_metric_chain(catalog, metric):
        declaring_file = catalog.sources.get(ancestor.key)
        if declaring_file is None:
            raise KeyError(f"Metric '{ancestor.key}' is missing a source path; cannot resolve compose entries.")

        for ref in ancestor.compose or []:
            component = component_loader.load(ref, declaring_file=declaring_file)
            effective = merge_explain_specs(effective, component.explain)
        effective = merge_explain_specs(effective, ancestor.explain)

    if variant_path:
        for variant in _walk_variant_chain(metric, variant_path):
            effective = merge_explain_specs(effective, variant.explain)

    return effective


def merge_explain_specs(base: MetricExplainSpec | None, patch: MetricExplainSpec | None) -> MetricExplainSpec | None:
    """Merge explain specs using the "patching" semantics described in the epic.

    - `from`: last-writer-wins
    - `grain` (mapping form): merge by key, last-writer-wins
    - `select`: merge by key, last-writer-wins
    - `where`: append-only
    - `define`: context-like merge (named last-writer-wins, unlabelled de-duped)
    """

    if patch is None:
        return base
    if base is None:
        return patch.model_copy(deep=True)

    resolved_from = patch.from_ if patch.from_ is not None else base.from_
    resolved_where = _append_lists(base.where, patch.where)
    resolved_define = _merge_define(base.define, patch.define)
    resolved_select = _merge_dicts(base.select, patch.select)
    resolved_grain = _merge_grain(base.grain, patch.grain)

    payload: dict[str, object] = {}
    if resolved_from is not None:
        payload["from_"] = resolved_from
    if resolved_where is not None:
        payload["where"] = resolved_where
    if resolved_grain is not None:
        payload["grain"] = resolved_grain
    if resolved_define is not None:
        payload["define"] = resolved_define
    if resolved_select is not None:
        payload["select"] = resolved_select

    return MetricExplainSpec.model_validate(payload) if payload else None


def build_metric_explain_plan(
    catalog: MetricCatalog,
    *,
    metric_identifier: str,
    context_calculate_filters: Sequence[str] = (),
    context_define_blocks: Sequence[str] = (),
    limit: int = 50_000,
    variant_mode: str = "flag",
) -> MetricExplainPlan:
    """Compile a metric explain plan into a row-based DAX query.

    The query is structured to avoid evaluating the metric measure per row:
    the headline measure is evaluated once (in filter context) and repeated as
    a constant evidence column.
    """

    if limit <= 0:
        raise ValueError("limit must be a positive integer.")

    metric_key, variant_path = split_metric_identifier(metric_identifier)
    metric = catalog.get_metric(metric_key)
    if metric is None:
        raise KeyError(f"Metric '{metric_key}' not found in catalog.")

    if variant_mode not in {"flag", "filter"}:
        raise ValueError("variant_mode must be one of {'flag', 'filter'}.")

    builder = MetricDaxBuilder(catalog)
    cache = MetricCompilationCache()

    _, base_definition = resolve_metric_reference(
        builder=builder,
        cache=cache,
        metric_key=metric_key,
        variant_path=None,
    )
    if variant_path:
        _, metric_definition = resolve_metric_reference(
            builder=builder,
            cache=cache,
            metric_key=metric_key,
            variant_path=variant_path,
        )
    else:
        metric_definition = base_definition

    # Start by resolving the merged explain spec (extends + variants), then apply defaults.
    explain_spec = resolve_metric_explain_spec(
        catalog,
        metric_key=metric_key,
        variant_path=variant_path,
    )
    driving_table = _resolve_driving_table(explain_spec)
    grain_columns = _resolve_grain_columns(explain_spec)
    select_columns = _resolve_select_columns(explain_spec)

    _raise_on_colliding_column_names(grain_columns, select_columns)

    primary_grain_expr = str(grain_columns.get("__grain") or _order_expression(grain_columns)).strip()
    primary_grain_table = _infer_table_from_column(primary_grain_expr) or driving_table or DEFAULT_EXPLAIN_FROM

    # When defining population filters inside `define: CALCULATE(...)`, extraction is best-effort.
    extracted_define_filters = _extract_define_calculate_filters(metric.define)

    # Build the rowset filters (metric + optional variant + context + explain.where).
    rowset_filters: list[str] = []
    rowset_filters.extend(_normalise_fragments(context_calculate_filters))
    rowset_filters.extend(_normalise_fragments(base_definition.filters))
    rowset_filters.extend(_normalise_fragments(base_definition.evaluate_filters))
    rowset_filters.extend(_normalise_fragments(extracted_define_filters))

    warnings: list[str] = []
    if variant_path and variant_mode == "filter":
        rowset_filters.extend(_normalise_fragments(_collect_variant_calculate_filters(metric, variant_path)))
    elif variant_path and not base_definition.filters and not extracted_define_filters:
        warnings.append(
            "Base metric does not declare any calculate filters; evidence export may be broad. "
            "Prefer moving population filters into metric.calculate or provide explain.where/from overrides."
        )

    if explain_spec and explain_spec.where:
        rowset_filters.extend(_normalise_fragments(explain_spec.where))

    rowset_filters = _dedupe_preserve_order(rowset_filters)

    passes_variant_expr: str | None = None
    if variant_path and variant_mode == "flag":
        variant_filters = _collect_variant_calculate_filters(metric, variant_path)
        passes_variant_expr = _try_build_passes_variant(
            variant_filters,
            driving_table=driving_table,
        )
        if passes_variant_expr is None and variant_filters:
            warnings.append(
                "Could not emit __passes_variant because one or more variant filters could not be converted "
                "into a per-row boolean expression. Add an explicit boolean in explain.select if required."
            )

    # Compile constant headline values once per query.
    metric_value_expr = normalize_dax_expression(metric_definition.expression)
    base_value_expr = normalize_dax_expression(base_definition.expression)
    context_filters = _format_filter_block(_dedupe_preserve_order(_normalise_fragments(context_calculate_filters)))

    define_body: list[str] = [f"  TABLE {DEFAULT_MEASURE_TABLE} = {{ {{ BLANK() }} }}"]
    define_body.extend(_format_define_blocks(context_define_blocks))
    define_body.extend(_format_define_blocks(_resolve_explain_define_blocks(explain_spec)))
    define_body.extend(
        _format_define_blocks(
            [
                f"MEASURE {DEFAULT_MEASURE_TABLE}[{_EXPLAIN_METRIC_MEASURE}] =\n{metric_value_expr}",
                f"MEASURE {DEFAULT_MEASURE_TABLE}[{_EXPLAIN_BASE_MEASURE}] =\n{base_value_expr}",
            ]
        )
    )

    evaluate_filters = _format_filter_block(
        _dedupe_preserve_order(_normalise_fragments(metric_definition.evaluate_filters))
    )
    base_evaluate_filters = _format_filter_block(
        _dedupe_preserve_order(_normalise_fragments(base_definition.evaluate_filters))
    )

    metric_value_var = _compose_calculate(
        f"{DEFAULT_MEASURE_TABLE}[{_EXPLAIN_METRIC_MEASURE}]",
        [*context_filters, *evaluate_filters],
    )
    base_value_var = _compose_calculate(
        f"{DEFAULT_MEASURE_TABLE}[{_EXPLAIN_BASE_MEASURE}]",
        [*context_filters, *base_evaluate_filters],
    )

    safe_identifier = _escape_dax_string(metric_identifier)
    safe_base_identifier = _escape_dax_string(metric_key)
    safe_grain_key = _escape_dax_string(primary_grain_expr or DEFAULT_EXPLAIN_GRAIN)
    safe_grain_table = _escape_dax_string(primary_grain_table)

    order_expr = normalize_dax_expression(_order_expression(grain_columns))

    rows_expr = _compose_calculatetable(
        driving_table,
        rowset_filters,
    )
    limited_rows_expr = (
        "TOPN(\n"
        f"    {limit},\n"
        "    __rows_raw,\n"
        f"    {order_expr},\n"
        "    ASC\n"
        ")"
    )

    column_pairs: list[tuple[str, str]] = [
        ("__metric_key", f'"{safe_identifier}"'),
        ("__metric_value", "__metric_value"),
    ]
    if variant_path:
        column_pairs.append(("__base_metric_key", f'"{safe_base_identifier}"'))
        column_pairs.append(("__base_metric_value", "__base_metric_value"))
    column_pairs.append(("__grain_table", f'"{safe_grain_table}"'))
    column_pairs.append(("__grain_key", f'"{safe_grain_key}"'))
    for label, expr in grain_columns.items():
        column_pairs.append((label, normalize_dax_expression(expr)))
    for label, expr in select_columns.items():
        column_pairs.append((label, normalize_dax_expression(expr)))
    if passes_variant_expr is not None:
        column_pairs.append(("__passes_variant", passes_variant_expr))

    column_order = tuple(label for label, _ in column_pairs)
    selectcolumns_args = _format_selectcolumns_args(column_pairs)

    lines: list[str] = []

    lines.append("DEFINE")
    lines.extend(define_body)
    lines.append("")
    lines.append("EVALUATE")
    lines.append(f"VAR __metric_value = {metric_value_var}")
    if variant_path:
        lines.append(f"VAR __base_metric_value = {base_value_var}")
    lines.append(f"VAR __rows_raw = {rows_expr}")
    lines.append(f"VAR __rows = {limited_rows_expr}")
    lines.append("RETURN")
    lines.append("SELECTCOLUMNS(")
    lines.append("    __rows,")
    lines.extend(selectcolumns_args)
    lines.append(")")
    lines.append("")

    statement = "\n".join(lines)

    return MetricExplainPlan(
        metric_identifier=metric_identifier,
        statement=statement,
        column_order=column_order,
        warnings=tuple(warnings),
    )


def build_metric_binding_explain_plan(
    catalog: MetricCatalog,
    *,
    metric_reference: str,
    metric_identifier: str,
    context_calculate_filters: Sequence[str] = (),
    context_define_blocks: Sequence[str] = (),
    limit: int = 50_000,
    variant_mode: str = "flag",
    numerator_define_filters: Sequence[str] = (),
    ratio_to: str | bool | None = None,
    visual_path: str | None = None,
    binding_id: str | None = None,
    binding_label: str | None = None,
) -> MetricExplainPlan:
    """Compile an explain plan for a metric binding inside a visual or pack.

    The binding workflow is similar to the core metric explain plan, but:

    - `metric_identifier` can be a binding-qualified label (for example, a full selector token)
      so output artefacts remain unique per binding instance.
    - `metric_reference` is the catalogue metric key used to resolve the underlying measure
      definition (including dotted variants).
    - `numerator_define_filters` are applied to the numerator only (mirroring metric dataset
      builder semantics for ratio_to).
    - When `ratio_to` is set, the plan emits numerator/denominator metadata columns and
      a computed `__ratio_value` column.
    """

    if limit <= 0:
        raise ValueError("limit must be a positive integer.")

    metric_key, variant_path = split_metric_identifier(metric_reference)

    metric = catalog.get_metric(metric_key)
    if metric is None:
        raise KeyError(f"Metric '{metric_key}' not found in catalog.")

    if variant_mode not in {"flag", "filter"}:
        raise ValueError("variant_mode must be one of {'flag', 'filter'}.")

    builder = MetricDaxBuilder(catalog)
    cache = MetricCompilationCache()

    _, base_definition = resolve_metric_reference(
        builder=builder,
        cache=cache,
        metric_key=metric_key,
        variant_path=None,
    )
    if variant_path:
        _, metric_definition = resolve_metric_reference(
            builder=builder,
            cache=cache,
            metric_key=metric_key,
            variant_path=variant_path,
        )
    else:
        metric_definition = base_definition

    # Start by resolving the merged explain spec (extends + variants), then apply defaults.
    explain_spec = resolve_metric_explain_spec(
        catalog,
        metric_key=metric_key,
        variant_path=variant_path,
    )
    driving_table = _resolve_driving_table(explain_spec)
    grain_columns = _resolve_grain_columns(explain_spec)
    select_columns = _resolve_select_columns(explain_spec)

    _raise_on_colliding_column_names(grain_columns, select_columns)

    primary_grain_expr = str(grain_columns.get("__grain") or _order_expression(grain_columns)).strip()
    primary_grain_table = _infer_table_from_column(primary_grain_expr) or driving_table or DEFAULT_EXPLAIN_FROM

    # When defining population filters inside `define: CALCULATE(...)`, extraction is best-effort.
    extracted_define_filters = _extract_define_calculate_filters(metric.define)

    # Build the rowset filters (metric + optional variant + context + binding + explain.where).
    rowset_filters: list[str] = []
    rowset_filters.extend(_normalise_fragments(context_calculate_filters))
    rowset_filters.extend(_normalise_fragments(base_definition.filters))
    rowset_filters.extend(_normalise_fragments(base_definition.evaluate_filters))
    rowset_filters.extend(_normalise_fragments(extracted_define_filters))
    rowset_filters.extend(_normalise_fragments(numerator_define_filters))

    warnings: list[str] = []
    if variant_path and variant_mode == "filter":
        rowset_filters.extend(_normalise_fragments(_collect_variant_calculate_filters(metric, variant_path)))
    elif variant_path and not base_definition.filters and not extracted_define_filters:
        warnings.append(
            "Base metric does not declare any calculate filters; evidence export may be broad. "
            "Prefer moving population filters into metric.calculate or provide explain.where/from overrides."
        )

    if explain_spec and explain_spec.where:
        rowset_filters.extend(_normalise_fragments(explain_spec.where))

    rowset_filters = _dedupe_preserve_order(rowset_filters)

    passes_variant_expr: str | None = None
    if variant_path and variant_mode == "flag":
        variant_filters = _collect_variant_calculate_filters(metric, variant_path)
        passes_variant_expr = _try_build_passes_variant(
            variant_filters,
            driving_table=driving_table,
        )
        if passes_variant_expr is None and variant_filters:
            warnings.append(
                "Could not emit __passes_variant because one or more variant filters could not be converted "
                "into a per-row boolean expression. Add an explicit boolean in explain.select if required."
            )

    # Compile constant headline values once per query.
    context_filters = _format_filter_block(_dedupe_preserve_order(_normalise_fragments(context_calculate_filters)))

    metric_value_expr = normalize_dax_expression(metric_definition.expression)
    binding_define = _format_filter_block(_dedupe_preserve_order(_normalise_fragments(numerator_define_filters)))
    if binding_define:
        metric_value_expr = normalize_dax_expression(_compose_calculate(metric_value_expr, binding_define))

    base_value_expr = normalize_dax_expression(base_definition.expression)

    ratio_to_token: str | None = None
    denominator_reference: str | None = None
    denominator_value_var: str | None = None
    denom_expr: str | None = None
    if ratio_to is not None:
        if ratio_to is True:
            ratio_to_token = "true"
            if "." not in metric_reference:
                raise ValueError("ratio_to=true requires a dotted metric reference to infer the base denominator.")
            denominator_reference = metric_key
        elif isinstance(ratio_to, str):
            ratio_to_token = ratio_to
            denominator_reference = ratio_to
        else:
            raise TypeError("ratio_to must be bool, str, or None.")

        denom_key, denom_variant = split_metric_identifier(denominator_reference)
        _, denom_definition = resolve_metric_reference(
            builder=builder,
            cache=cache,
            metric_key=denom_key,
            variant_path=denom_variant,
        )
        denom_expr = normalize_dax_expression(denom_definition.expression)

    define_body: list[str] = [f"  TABLE {DEFAULT_MEASURE_TABLE} = {{ {{ BLANK() }} }}"]
    define_body.extend(_format_define_blocks(context_define_blocks))
    define_body.extend(_format_define_blocks(_resolve_explain_define_blocks(explain_spec)))
    define_body.extend(
        _format_define_blocks(
            [
                f"MEASURE {DEFAULT_MEASURE_TABLE}[{_EXPLAIN_METRIC_MEASURE}] =\n{metric_value_expr}",
                f"MEASURE {DEFAULT_MEASURE_TABLE}[{_EXPLAIN_BASE_MEASURE}] =\n{base_value_expr}",
                f"MEASURE {DEFAULT_MEASURE_TABLE}[{_EXPLAIN_DENOMINATOR_MEASURE}] =\n{denom_expr}"
                if denom_expr is not None
                else "",
            ]
        )
    )

    evaluate_filters = _format_filter_block(
        _dedupe_preserve_order(_normalise_fragments(metric_definition.evaluate_filters))
    )
    base_evaluate_filters = _format_filter_block(
        _dedupe_preserve_order(_normalise_fragments(base_definition.evaluate_filters))
    )

    metric_value_var = _compose_calculate(
        f"{DEFAULT_MEASURE_TABLE}[{_EXPLAIN_METRIC_MEASURE}]",
        [*context_filters, *evaluate_filters],
    )
    base_value_var = _compose_calculate(
        f"{DEFAULT_MEASURE_TABLE}[{_EXPLAIN_BASE_MEASURE}]",
        [*context_filters, *base_evaluate_filters],
    )
    if denominator_reference and denom_expr is not None:
        denom_evaluate_filters = _format_filter_block(
            _dedupe_preserve_order(_normalise_fragments(denom_definition.evaluate_filters))
        )
        denominator_value_var = _compose_calculate(
            f"{DEFAULT_MEASURE_TABLE}[{_EXPLAIN_DENOMINATOR_MEASURE}]",
            [*context_filters, *denom_evaluate_filters],
        )

    safe_identifier = _escape_dax_string(metric_identifier)
    safe_reference = _escape_dax_string(metric_reference)
    safe_base_identifier = _escape_dax_string(metric_key)
    safe_grain_key = _escape_dax_string(primary_grain_expr or DEFAULT_EXPLAIN_GRAIN)
    safe_grain_table = _escape_dax_string(primary_grain_table)

    order_expr = normalize_dax_expression(_order_expression(grain_columns))

    rows_expr = _compose_calculatetable(
        driving_table,
        rowset_filters,
    )
    limited_rows_expr = (
        "TOPN(\n"
        f"    {limit},\n"
        "    __rows_raw,\n"
        f"    {order_expr},\n"
        "    ASC\n"
        ")"
    )

    column_pairs: list[tuple[str, str]] = [
        ("__metric_key", f'"{safe_identifier}"'),
        ("__metric_value", "__metric_value"),
    ]

    if visual_path:
        column_pairs.append(("__visual_path", f'"{_escape_dax_string(visual_path)}"'))
    if binding_id:
        column_pairs.append(("__binding_id", f'"{_escape_dax_string(binding_id)}"'))

    column_pairs.append(("__binding_metric_key", f'"{safe_reference}"'))
    if binding_label:
        column_pairs.append(("__binding_label", f'"{_escape_dax_string(binding_label)}"'))
    if ratio_to_token:
        column_pairs.append(("__ratio_to", f'"{_escape_dax_string(ratio_to_token)}"'))

    if denominator_reference and denominator_value_var is not None:
        column_pairs.extend(
            [
                ("__numerator_key", f'"{safe_reference}"'),
                ("__numerator_value", "__metric_value"),
                ("__denominator_key", f'"{_escape_dax_string(denominator_reference)}"'),
                ("__denominator_value", "__denominator_value"),
                ("__ratio_value", "__ratio_value"),
            ]
        )

    if variant_path:
        column_pairs.append(("__base_metric_key", f'"{safe_base_identifier}"'))
        column_pairs.append(("__base_metric_value", "__base_metric_value"))

    column_pairs.append(("__grain_table", f'"{safe_grain_table}"'))
    column_pairs.append(("__grain_key", f'"{safe_grain_key}"'))
    for label, expr in grain_columns.items():
        column_pairs.append((label, normalize_dax_expression(expr)))
    for label, expr in select_columns.items():
        column_pairs.append((label, normalize_dax_expression(expr)))
    if passes_variant_expr is not None:
        column_pairs.append(("__passes_variant", passes_variant_expr))

    column_order = tuple(label for label, _ in column_pairs)
    selectcolumns_args = _format_selectcolumns_args(column_pairs)

    lines: list[str] = []
    lines.append("DEFINE")
    lines.extend(define_body)
    lines.append("")
    lines.append("EVALUATE")
    lines.append(f"VAR __metric_value = {metric_value_var}")
    if denominator_reference and denominator_value_var is not None:
        lines.append(f"VAR __denominator_value = {denominator_value_var}")
        lines.append("VAR __ratio_value = DIVIDE(__metric_value, __denominator_value)")
    if variant_path:
        lines.append(f"VAR __base_metric_value = {base_value_var}")
    lines.append(f"VAR __rows_raw = {rows_expr}")
    lines.append(f"VAR __rows = {limited_rows_expr}")
    lines.append("RETURN")
    lines.append("SELECTCOLUMNS(")
    lines.append("    __rows,")
    lines.extend(selectcolumns_args)
    lines.append(")")
    lines.append("")

    statement = "\n".join(lines)

    return MetricExplainPlan(
        metric_identifier=metric_identifier,
        statement=statement,
        column_order=column_order,
        warnings=tuple(warnings),
    )


def _resolve_metric_chain(catalog: MetricCatalog, metric: MetricDefinition) -> list[MetricDefinition]:
    chain: list[MetricDefinition] = []
    current: MetricDefinition | None = metric
    seen: set[str] = set()
    while current is not None:
        chain.append(current)
        parent_key = current.extends
        if parent_key is None:
            break
        if parent_key in seen:
            raise ValueError(f"Circular extends detected while resolving metric '{metric.key}'.")
        seen.add(parent_key)
        parent = catalog.get_metric(parent_key)
        if parent is None:
            raise KeyError(f"Metric '{metric.key}' extends unknown parent '{parent_key}'.")
        current = parent
    return list(reversed(chain))


def _walk_variant_chain(metric: MetricDefinition, variant_path: str) -> list[MetricVariant]:
    segments = variant_path.split(".") if variant_path else []
    node: dict[str, MetricVariant] = dict(metric.variants)
    chain: list[MetricVariant] = []
    for segment in segments:
        if segment not in node:
            raise KeyError(f"Variant path '{variant_path}' not found for metric '{metric.key}'.")
        variant = node[segment]
        chain.append(variant)
        node = dict(variant.variants)
    return chain


def _append_lists(base: list[str] | None, patch: list[str] | None) -> list[str] | None:
    if not base and not patch:
        return None
    merged: list[str] = []
    for source in (base or [], patch or []):
        merged.extend(source)
    return merged or None


def _merge_dicts(base: Mapping[str, str] | None, patch: Mapping[str, str] | None) -> dict[str, str] | None:
    if not base and not patch:
        return None
    merged: dict[str, str] = dict(base or {})
    if patch:
        merged.update(patch)
    return merged or None


def _merge_grain(
    base: str | Mapping[str, str] | None,
    patch: str | Mapping[str, str] | None,
) -> str | dict[str, str] | None:
    if patch is None:
        return dict(base) if isinstance(base, Mapping) else base
    if isinstance(patch, str):
        return patch
    if not isinstance(patch, Mapping):
        raise TypeError("grain must be a string or mapping when merging.")
    if not isinstance(base, Mapping):
        return dict(patch)
    merged: dict[str, str] = dict(base)
    merged.update(patch)
    return merged


def _split_named_and_unlabelled_fragments(
    value: object | None,
    *,
    label: str,
) -> tuple[dict[str, str], list[str]]:
    """Split a context-style payload into named and unlabelled fragments."""

    named: dict[str, str] = {}
    unlabelled: list[str] = []

    if value is None:
        return named, unlabelled

    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            unlabelled.append(candidate)
        return named, unlabelled

    if isinstance(value, Mapping):
        for key, raw in value.items():
            if raw is None:
                continue
            if not isinstance(raw, str):
                raise TypeError(f"{label} mapping values must be strings.")
            candidate = raw.strip()
            if candidate:
                named[str(key)] = candidate
        return named, unlabelled

    if isinstance(value, Sequence):
        for entry in value:
            if entry is None:
                continue
            if isinstance(entry, Mapping):
                entry_named, entry_unlabelled = _split_named_and_unlabelled_fragments(entry, label=label)
                named.update(entry_named)
                unlabelled.extend(entry_unlabelled)
                continue
            if not isinstance(entry, str):
                raise TypeError(f"{label} entries must be strings or mappings when supplied as a list.")
            candidate = entry.strip()
            if candidate:
                unlabelled.append(candidate)
        return named, unlabelled

    raise TypeError(f"{label} must be supplied as a string, mapping, or sequence thereof.")


def _merge_define(base: object | None, patch: object | None) -> list[object] | None:
    if base is None and patch is None:
        return None
    if patch is None:
        existing_named, existing_unlabelled = _split_named_and_unlabelled_fragments(base, label="define")
        merged: list[object] = [{key: value} for key, value in existing_named.items()]
        merged.extend(existing_unlabelled)
        return merged or None

    existing_named, existing_unlabelled = _split_named_and_unlabelled_fragments(base, label="define")
    incoming_named, incoming_unlabelled = _split_named_and_unlabelled_fragments(patch, label="define")

    merged_named = dict(existing_named)
    merged_named.update(incoming_named)

    merged_unlabelled = list(existing_unlabelled)
    for item in incoming_unlabelled:
        if item not in merged_unlabelled:
            merged_unlabelled.append(item)

    merged: list[object] = [{key: value} for key, value in merged_named.items()]
    merged.extend(merged_unlabelled)
    return merged or None


def _flatten_define_fragments(value: object | None) -> list[str]:
    """Flatten merged define payload into a list of strings in stable order."""

    named, unlabelled = _split_named_and_unlabelled_fragments(value, label="define")
    return [*named.values(), *unlabelled]


def _resolve_explain_define_blocks(explain: MetricExplainSpec | None) -> tuple[str, ...]:
    if explain is None or not explain.define:
        return ()
    return normalise_define_blocks(_flatten_define_fragments(explain.define))


def _resolve_driving_table(explain: MetricExplainSpec | None) -> str:
    if explain and explain.from_:
        return explain.from_
    if explain and isinstance(explain.grain, str) and explain.grain:
        inferred = _infer_table_from_column(explain.grain)
        if inferred:
            return inferred
    if explain and isinstance(explain.grain, Mapping) and explain.grain:
        for expr in explain.grain.values():
            inferred = _infer_table_from_column(expr)
            if inferred:
                return inferred
    return DEFAULT_EXPLAIN_FROM


def _infer_table_from_column(expr: str) -> str | None:
    cleaned = expr.strip()
    if not cleaned:
        return None
    if "[" in cleaned:
        return cleaned.split("[", 1)[0].strip() or None
    if "." in cleaned:
        return cleaned.split(".", 1)[0].strip() or None
    return None


def _resolve_grain_columns(explain: MetricExplainSpec | None) -> dict[str, str]:
    if explain is None or explain.grain is None:
        return {"__grain": DEFAULT_EXPLAIN_GRAIN}
    grain = explain.grain
    if isinstance(grain, str):
        candidate = grain.strip()
        return {"__grain": candidate} if candidate else {"__grain": DEFAULT_EXPLAIN_GRAIN}
    if isinstance(grain, Mapping):
        if not grain:
            return {"__grain": DEFAULT_EXPLAIN_GRAIN}
        return dict(grain)
    return {"__grain": DEFAULT_EXPLAIN_GRAIN}


def _resolve_select_columns(explain: MetricExplainSpec | None) -> dict[str, str]:
    if explain is None or not explain.select:
        return {}
    return dict(explain.select)


def _raise_on_colliding_column_names(grain: Mapping[str, str], select: Mapping[str, str]) -> None:
    overlap = set(grain).intersection(select)
    if overlap:
        formatted = ", ".join(sorted(overlap))
        raise ValueError(
            f"explain.grain and explain.select define the same column label(s): {formatted}. "
            "Rename one side to keep evidence exports unambiguous."
        )


def _extract_define_calculate_filters(define: str | None) -> list[str]:
    """Best-effort extract CALCULATE(...) filter arguments from a define expression."""

    if not define or not isinstance(define, str):
        return []

    stripped = define.strip()
    if not stripped:
        return []

    cleaned = _strip_dax_line_comments(stripped)
    match = re.match(r"(?is)^CALCULATE\s*\(", cleaned)
    if not match:
        return []

    inside = cleaned[match.end() - 1 :]
    args = _split_dax_call_args(inside)
    if len(args) < 2:
        return []

    filters = [arg.strip() for arg in args[1:] if arg and arg.strip()]
    return filters


def _strip_dax_line_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if "//" in line:
            line = line.split("//", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def _split_dax_call_args(call_with_parens: str) -> list[str]:
    """Split a DAX function call argument list, given text starting with '('."""

    text = call_with_parens.strip()
    if not text.startswith("("):
        return []

    depth = 0
    in_string = False
    current: list[str] = []
    args: list[str] = []
    index = 0

    while index < len(text):
        ch = text[index]

        if ch == '"':
            if in_string and index + 1 < len(text) and text[index + 1] == '"':
                current.append('""')
                index += 2
                continue
            in_string = not in_string
            current.append(ch)
            index += 1
            continue

        if not in_string:
            if ch == "(":
                depth += 1
                # Skip the outer "(" so consumers only see the argument text.
                if depth == 1:
                    index += 1
                    continue
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "," and depth == 1:
                args.append("".join(current).strip())
                current = []
                index += 1
                continue

        current.append(ch)
        index += 1

    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return [arg for arg in args if arg]


def _collect_variant_calculate_filters(metric: MetricDefinition, variant_path: str) -> list[str]:
    """Collect define+evaluate calculate filters for the variant path (excluding base metric filters)."""

    filters: list[str] = []
    for variant in _walk_variant_chain(metric, variant_path):
        filters.extend(list(variant.calculate.define or ()))
        filters.extend(list(variant.calculate.evaluate or ()))
    return filters


def _try_build_passes_variant(filters: Sequence[str], *, driving_table: str) -> str | None:
    """Return a per-row boolean predicate representing the variant filters when possible."""

    predicates: list[str] = []
    for raw in filters:
        candidate = _try_extract_row_predicate(raw, driving_table=driving_table)
        if candidate is None:
            return None
        predicates.append(candidate)

    if not predicates:
        return None

    joined = " && ".join(f"({normalize_dax_expression(item)})" for item in predicates)
    return joined


_KEEPFILTERS_PREFIX = re.compile(r"(?is)^KEEPFILTERS\s*\(")
_FILTER_PREFIX = re.compile(r"(?is)^FILTER\s*\(")


def _try_extract_row_predicate(filter_expr: str, *, driving_table: str) -> str | None:
    """Convert a CALCULATE-style filter argument into a row-context boolean when safe."""

    cleaned = str(filter_expr or "").strip()
    if not cleaned:
        return None

    # Unwrap top-level KEEPFILTERS(...) so common metric patterns can be reused.
    while _KEEPFILTERS_PREFIX.match(cleaned):
        args = _split_dax_call_args(cleaned[cleaned.upper().find("KEEPFILTERS") + len("KEEPFILTERS") :])
        if len(args) != 1:
            break
        cleaned = args[0].strip()

    if _FILTER_PREFIX.match(cleaned):
        args = _split_dax_call_args(cleaned[cleaned.upper().find("FILTER") + len("FILTER") :])
        if len(args) != 2:
            return None
        table_arg = normalize_dax_expression(args[0].strip())
        predicate_arg = args[1].strip()

        # Only rewrite FILTER(<driving_table>, predicate) patterns; other table filters
        # may change row context and are not safely reducible.
        normalized_driving = normalize_dax_expression(driving_table)
        if _canonical_table_ref(table_arg) != _canonical_table_ref(normalized_driving):
            return None

        return predicate_arg.strip() or None

    # Treat anything else as a scalar predicate. We do not attempt to support
    # arbitrary table-returning filter expressions here.
    upper = cleaned.lstrip().upper()
    for prefix in ("CALCULATETABLE", "SUMMARIZE", "SUMMARIZECOLUMNS", "TREATAS", "VALUES", "ALL", "ALLEXCEPT"):
        if upper.startswith(prefix + "(") or upper.startswith(prefix + " ("):
            return None
    return cleaned


def _normalise_fragments(values: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for item in values or ():
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue
        cleaned.append(normalize_dax_expression(text))
    return cleaned


def _dedupe_preserve_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _order_expression(grain_columns: Mapping[str, str]) -> str:
    for expr in grain_columns.values():
        candidate = str(expr).strip()
        if candidate:
            return candidate
    return DEFAULT_EXPLAIN_GRAIN


def _format_define_blocks(blocks: Sequence[str]) -> list[str]:
    formatted: list[str] = []
    for block in blocks or ():
        if not block:
            continue
        for line in str(block).splitlines():
            if line.strip():
                formatted.append("  " + line.rstrip())
    return formatted


def _format_filter_block(filters: Sequence[str]) -> list[str]:
    return [str(value).strip() for value in filters or () if value and str(value).strip()]


def _compose_calculate(expression: str, filters: Sequence[str]) -> str:
    if not filters:
        return expression.strip()
    args = ",\n    ".join([expression.strip(), *filters])
    return f"CALCULATE(\n    {args}\n)"


def _compose_calculatetable(table_expr: str, filters: Sequence[str]) -> str:
    if not filters:
        return normalize_dax_expression(table_expr.strip())

    args = ",\n    ".join([normalize_dax_expression(table_expr.strip()), *filters])
    return f"CALCULATETABLE(\n    {args}\n)"


def _format_selectcolumns_args(column_pairs: Sequence[tuple[str, str]]) -> list[str]:
    args: list[str] = []
    for index, (label, expr) in enumerate(column_pairs):
        comma = "," if index < len(column_pairs) - 1 else ""
        args.append(f'    "{_escape_dax_string(label)}", {expr}{comma}')
    return args


def _escape_dax_string(value: str) -> str:
    return str(value).replace('"', '""')


def _canonical_table_ref(value: str) -> str:
    cleaned = value.strip().replace(" ", "")
    if cleaned.startswith("'") and "'" in cleaned[1:]:
        # Collapse 'table' into table for comparison.
        if cleaned.endswith("'"):
            cleaned = cleaned[1:-1]
    return cleaned


__all__ = [
    "DEFAULT_EXPLAIN_FROM",
    "DEFAULT_EXPLAIN_GRAIN",
    "MetricExplainPlan",
    "build_metric_binding_explain_plan",
    "build_metric_explain_plan",
    "merge_explain_specs",
    "resolve_metric_explain_spec",
]
