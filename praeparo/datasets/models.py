"""Shared data structures for the metric dataset builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, MutableMapping, Sequence, Tuple

from praeparo import data as chart_data
from praeparo.data import ChartResultSet
from praeparo.datasources import ResolvedDataSource
from praeparo.models import CartesianChartConfig
from praeparo.visuals.dax.planner_core import MeasurePlan


@dataclass(frozen=True)
class MetricDatasetPlan:
    """Immutable representation of a compiled metric dataset."""

    slug: str
    measures: Tuple[MeasurePlan, ...]
    measure_map: dict[str, str]
    series_order: Tuple[str, ...]
    grain_columns: Tuple[str, ...]
    define_blocks: Tuple[str, ...]
    global_filters: Tuple[str, ...]
    placeholders: Tuple[str, ...]
    statement: str
    measure_table: str
    mock_rows: int | None = None
    mock_values: Mapping[str, Sequence[object]] | None = None

    def series_column(self, series_id: str) -> str:
        """Expose the storage column used by *series_id* (alias for now)."""

        return series_id


@dataclass(frozen=True)
class MetricDatasetResult:
    """Materialised metric dataset along with execution metadata."""

    rows: list[dict[str, object]]
    raw_rows: Tuple[Mapping[str, object], ...]
    measure_map: dict[str, str]
    placeholders: Tuple[str, ...]
    datasource: ResolvedDataSource
    execution_time: float
    plan: MetricDatasetPlan

    def to_dataframe(self):  # type: ignore[override]
        """Return the result as a pandas DataFrame (importing lazily)."""

        try:
            import pandas as pd  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            msg = "pandas is required for MetricDatasetResult.to_dataframe(); install pandas to continue."
            raise RuntimeError(msg) from exc
        return pd.DataFrame(self.rows)

    def to_chart_result(self, config: CartesianChartConfig) -> ChartResultSet:
        """Convert the tabular rows into a `ChartResultSet` for cartesian visuals."""

        records: list[tuple[chart_data.ChartCategory, Mapping[str, object]]] = []
        for raw in self.raw_rows:
            value = chart_data._resolve_category_value(raw, config.category.field)  # type: ignore[attr-defined]
            category = chart_data.ChartCategory(  # type: ignore[attr-defined]
                value=value,
                label=chart_data._resolve_category_label(value, config.category.format),  # type: ignore[attr-defined]
            )

            payload: MutableMapping[str, object] = {}
            for _, measure_name in self.measure_map.items():
                payload[measure_name] = raw.get(measure_name)
            records.append((category, payload))

        dataset = chart_data._build_chart_dataset(config, self.measure_map, records)  # type: ignore[attr-defined]
        return dataset


def lookup_column(raw: Mapping[str, object], column: str) -> object | None:
    """Resolve *column* in *raw* using the same variants cartsian planners expect."""

    candidates: list[str] = [column]
    stripped = column.strip("'\"")
    if stripped not in candidates:
        candidates.append(stripped)

    if "[" in column and "]" in column:
        inner = column[column.find("[") + 1 : column.rfind("]")]
        candidates.append(inner)

    if "." in column and "[" not in column:
        table, col = column.split(".", 1)
        candidates.append(col)
        candidates.append(f"'{table}'[{col}]")

    for candidate in dict.fromkeys(candidates):
        if candidate in raw:
            return raw[candidate]
    return raw.get(column)


__all__ = ["MetricDatasetPlan", "MetricDatasetResult", "lookup_column"]
