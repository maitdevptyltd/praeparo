"""Reusable mock dataset helpers for the metric dataset builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, MutableMapping, Sequence


@dataclass(frozen=True)
class MockSeriesConfig:
    """Profile describing how to generate mock values for a metric series."""

    factory: str = "count"
    mean: float | None = None
    trend: float | None = None
    trend_range: tuple[float, float] | None = None


def iterate_mock_values(
    *,
    count: int,
    columns: Sequence[str],
    column_values: Mapping[str, Sequence[object]] | None,
    measure_map: Mapping[str, str],
    series_mocks: Mapping[str, MockSeriesConfig],
) -> Iterable[dict[str, object]]:
    """Yield deterministic mock rows for the supplied series configuration."""

    rows = max(count, 1)
    column_overrides = column_values or {}

    for index in range(rows):
        record: dict[str, object] = {}
        for column in columns or ("__row__",):
            values = column_overrides.get(column)
            if values and index < len(values):
                record[column] = values[index]
            else:
                record[column] = f"{column}:{index + 1}"

        for series_id, measure_name in measure_map.items():
            mock_config = series_mocks.get(series_id, MockSeriesConfig())
            base = mock_config.mean or 400.0
            trend = _resolve_trend(mock_config, index, rows)
            record[measure_name] = round(base + trend, 4)
        yield record


def _resolve_trend(config: MockSeriesConfig, index: int, rows: int) -> float:
    if config.trend_range:
        start, end = config.trend_range
        if rows <= 1:
            return start
        step = (end - start) / (rows - 1)
        return start + step * index
    if config.trend is not None:
        midpoint = (rows - 1) / 2
        return config.trend * (index - midpoint)
    return 0.0


__all__ = ["MockSeriesConfig", "iterate_mock_values"]

