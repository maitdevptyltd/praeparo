"""Data providers for Praeparo visuals."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .dax import DaxQueryPlan
from .models import (
    CartesianChartConfig,
    CategoryOrder,
    CategorySortMode,
    MatrixConfig,
    SeriesTransformMode,
)
from .powerbi import PowerBIClient, PowerBISettings
from .templating import FieldReference


@dataclass
class MatrixResultSet:
    """Tabular data representing the outcome of a matrix query."""

    rows: list[dict[str, object]]
    row_fields: tuple[FieldReference, ...]


@dataclass
class ChartCategory:
    """Resolved category axis value."""

    value: object
    label: str


@dataclass
class ChartSeriesResult:
    """Collection of values for a specific chart series."""

    id: str
    measure_name: str
    values: list[object]


@dataclass
class ChartResultSet:
    """Dataset powering a cartesian chart visual."""

    categories: list[ChartCategory]
    series: list[ChartSeriesResult]


def _seed_value(base: int, multiplier: int) -> float:
    return round(base * multiplier / 100.0, 4)


def mock_matrix_data(config: MatrixConfig, row_fields: Iterable[FieldReference]) -> MatrixResultSet:
    """Generate deterministic sample data for a matrix visual."""

    ordered_fields = tuple(row_fields)
    generated_rows: list[dict[str, object]] = []

    for index in range(1, 4):
        row: dict[str, object] = {}
        for field in ordered_fields:
            seed = f"{field.column.replace('_', ' ').title()} {index}"
            row[field.placeholder] = seed
        for value_position, value in enumerate(config.values, start=1):
            multiplier = index * value_position
            if value.format and value.format.startswith("percent"):
                row[value.label or value.id] = _seed_value(multiplier, 5)
            elif value.format and value.format.startswith("duration"):
                row[value.label or value.id] = multiplier * 900
            else:
                row[value.label or value.id] = multiplier * 100
        generated_rows.append(row)

    return MatrixResultSet(rows=generated_rows, row_fields=ordered_fields)


def _lookup_with_variants(raw: dict[str, object], key: str) -> object | None:
    variants = {key}
    if not key.startswith('[') and not key.endswith(']'):
        variants.add(f"[{key}]")
    for variant in variants:
        if variant in raw:
            return raw[variant]
    return None


async def powerbi_matrix_data(
    config: MatrixConfig,
    row_fields: Sequence[FieldReference],
    query_plan: DaxQueryPlan,
    dataset_id: str,
    *,
    group_id: str | None = None,
    settings: PowerBISettings | None = None,
) -> MatrixResultSet:
    """Execute the matrix DAX query against a live Power BI dataset."""

    ordered_fields = tuple(row_fields)
    settings = settings or PowerBISettings.from_env()

    async with PowerBIClient(settings) as client:
        rows = await client.execute_dax(dataset_id, query_plan.statement, group_id=group_id)

    materialized: list[dict[str, object]] = []
    for raw in rows:
        record: dict[str, object] = {}
        for field in ordered_fields:
            value = (
                raw.get(field.placeholder)
                or raw.get(field.dax_reference)
                or raw.get(field.column)
                or _lookup_with_variants(raw, field.placeholder)
            )
            record[field.placeholder] = value
        for value_config in config.values:
            alias = value_config.label or value_config.id
            value = raw.get(alias) or _lookup_with_variants(raw, alias)
            record[alias] = value
        materialized.append(record)

    return MatrixResultSet(rows=materialized, row_fields=ordered_fields)

def _coerce_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str, bytes, bytearray)):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if math.isnan(number):
        return None
    return number


def _category_candidates(field: str) -> list[str]:
    cleaned = field.strip()
    candidates = [cleaned]
    if "[" in cleaned and "]" in cleaned:
        column_part = cleaned.split("[", 1)[1].rstrip("]")
        column_candidate = column_part.strip("'\" ")
        if column_candidate:
            candidates.append(column_candidate)
    if "." in cleaned:
        dotted_column = cleaned.split(".", 1)[1]
        candidates.append(dotted_column.replace("[", "").replace("]", "").strip())
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def _resolve_category_value(row: Mapping[str, object], field: str) -> object | None:
    for candidate in _category_candidates(field):
        if candidate in row:
            return row[candidate]
    return None


def _resolve_category_label(raw: object, format_hint: str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (int, float)) and format_hint and format_hint.startswith("percent"):
        return f"{raw:.0%}"
    return str(raw)


def _sort_records(
    config: CartesianChartConfig,
    measure_map: Mapping[str, str],
    records: list[tuple[ChartCategory, Mapping[str, object]]],
) -> list[tuple[ChartCategory, Mapping[str, object]]]:
    sort_config = config.category.sort
    if sort_config and sort_config.by is not None:
        direction = sort_config.direction
    else:
        direction = config.category.order or CategoryOrder.ASCENDING

    reverse = direction == CategoryOrder.DESCENDING

    if sort_config and sort_config.by == CategorySortMode.SERIES:
        target_series_id = sort_config.series_id or (config.series[0].id if config.series else "")
        measure_name = measure_map.get(target_series_id, target_series_id)

        def _series_key(item: tuple[ChartCategory, Mapping[str, object]]) -> float:
            value = item[1].get(measure_name)
            number = _coerce_number(value)
            return number if number is not None else float("-inf")

        return sorted(records, key=_series_key, reverse=reverse)

    def _category_key(item: tuple[ChartCategory, Mapping[str, object]]) -> str:
        return str(item[0].label)

    return sorted(records, key=_category_key, reverse=reverse)


def _build_chart_dataset(
    config: CartesianChartConfig,
    measure_map: Mapping[str, str],
    records: list[tuple[ChartCategory, Mapping[str, object]]],
) -> ChartResultSet:
    if not records:
        return ChartResultSet(categories=[], series=[])

    ordered_records = _sort_records(config, measure_map, records)
    limit = config.category.limit
    if limit is not None and limit > 0:
        ordered_records = ordered_records[:limit]

    categories: list[ChartCategory] = []
    series_values: dict[str, list[object]] = {}

    for entry in ordered_records:
        category, payload = entry
        categories.append(category)
        for series in config.series:
            measure_name = measure_map.get(series.id, series.id)
            series_values.setdefault(series.id, []).append(payload.get(measure_name))

    series_results = [
        ChartSeriesResult(id=series.id, measure_name=measure_map.get(series.id, series.id), values=series_values.get(series.id, []))
        for series in config.series
    ]

    dataset = ChartResultSet(categories=categories, series=series_results)
    _apply_series_transforms(config, dataset, measure_map)
    return dataset


def _apply_series_transforms(
    config: CartesianChartConfig,
    dataset: ChartResultSet,
    measure_map: Mapping[str, str],
) -> None:
    if not dataset.series:
        return
    series_lookup = {entry.id: entry for entry in dataset.series}

    for series_config in config.series:
        transform = series_config.transform
        if transform is None and series_config.show_as:
            # Future hook: map show_as to transformations when planners surface DAX rewrites.
            continue
        if transform is None:
            continue

        target_series = series_lookup.get(series_config.id)
        if target_series is None:
            continue

        source_series_id = transform.source_series or series_config.id
        source_series = series_lookup.get(source_series_id)
        if source_series is None:
            continue

        if transform.mode is SeriesTransformMode.PERCENT_OF_TOTAL:
            transformed: list[object] = []
            if transform.scope == "visual":
                for index in range(len(dataset.categories)):
                    denominator = 0.0
                    for candidate in dataset.series:
                        candidate_value = _coerce_number(candidate.values[index]) if index < len(candidate.values) else None
                        if candidate_value is not None:
                            denominator += candidate_value
                    value = _coerce_number(source_series.values[index]) if index < len(source_series.values) else None
                    if denominator and value is not None:
                        transformed.append(round(value / denominator, 6))
                    else:
                        transformed.append(0.0)
            else:
                numbers = [_coerce_number(value) or 0.0 for value in source_series.values]
                denominator = sum(numbers)
                transformed = [round(value / denominator, 6) if denominator else 0.0 for value in numbers]

            target_series.values = transformed


def mock_chart_data(
    config: CartesianChartConfig,
    measure_map: Mapping[str, str],
    *,
    seed: int = 42,  # noqa: ARG001 - placeholder for future deterministic jitter hooks
) -> ChartResultSet:
    """Generate deterministic sample data for a cartesian chart."""

    categories = list(config.category.mock_values or ())
    if not categories:
        categories = [f"Category {index}" for index in range(1, 5)]

    category_objects = [
        ChartCategory(value=value, label=_resolve_category_label(value, config.category.format))
        for value in categories
    ]

    series_value_cache: dict[str, list[object]] = {}
    midpoint = (len(categories) - 1) / 2

    for index, series in enumerate(config.series, start=1):
        mock_config = getattr(series.metric, "mock", None)
        base = getattr(mock_config, "mean", None)
        if base is None:
            base = index * 600
        trend = getattr(mock_config, "trend", None)
        trend_range = getattr(mock_config, "trend_range", None)
        factory = getattr(mock_config, "factory", "count")

        values: list[object] = []
        for position in range(len(categories)):
            if trend_range:
                start, end = trend_range
                step = 0 if len(categories) <= 1 else (end - start) / (len(categories) - 1)
                offset = start + step * position
            elif trend is not None:
                offset = trend * (position - midpoint)
            else:
                offset = (position - midpoint) * index * 40

            raw_value = base + offset
            if factory == "ratio" or (series.format and series.format.startswith("percent")):
                raw_value = max(0.0, min(1.0, raw_value / 100.0 if raw_value > 1 else raw_value))
            elif factory == "currency":
                raw_value = max(raw_value, 0.0)

            values.append(round(raw_value, 4))
        measure_name = measure_map.get(series.id, series.id)
        series_value_cache[measure_name] = values

    records: list[tuple[ChartCategory, Mapping[str, object]]] = []
    for index, category in enumerate(category_objects):
        payload: dict[str, object] = {}
        for series in config.series:
            measure_name = measure_map.get(series.id, series.id)
            payload[measure_name] = series_value_cache.get(measure_name, [])[index]
        records.append((category, payload))

    return _build_chart_dataset(config, measure_map, records)


async def powerbi_chart_data(
    config: CartesianChartConfig,
    plan: DaxQueryPlan,
    *,
    measure_map: Mapping[str, str],
    dataset_id: str,
    group_id: str | None = None,
    settings: PowerBISettings | None = None,
) -> ChartResultSet:
    """Execute the cartesian DAX query against a live Power BI dataset."""

    effective_settings = settings or PowerBISettings.from_env()

    async with PowerBIClient(effective_settings) as client:
        rows = await client.execute_dax(dataset_id, plan.statement, group_id=group_id)

    records: list[tuple[ChartCategory, Mapping[str, object]]] = []
    for raw in rows:
        value = _resolve_category_value(raw, config.category.field)
        category = ChartCategory(
            value=value,
            label=_resolve_category_label(value, config.category.format),
        )
        payload = {measure_map.get(series.id, series.id): raw.get(measure_map.get(series.id, series.id)) for series in config.series}
        records.append((category, payload))

    return _build_chart_dataset(config, measure_map, records)


__all__ = [
    "MatrixResultSet",
    "mock_matrix_data",
    "powerbi_matrix_data",
    "ChartCategory",
    "ChartSeriesResult",
    "ChartResultSet",
    "mock_chart_data",
    "powerbi_chart_data",
]
