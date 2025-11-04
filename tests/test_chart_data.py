from __future__ import annotations

from typing import Literal, cast

import pytest

from praeparo.data import ChartResultSet, mock_chart_data
from praeparo.models import CartesianChartConfig
from praeparo.models.cartesian import (
    AxisConfig,
    CartesianSeriesConfig,
    CategoryConfig,
    SeriesTransformConfig,
    SeriesTransformMode,
    ValueAxesConfig,
)
from praeparo.visuals.metrics import VisualMetricConfig


def _build_chart_config(transform_scope: Literal["category", "visual"] | None = None) -> tuple[CartesianChartConfig, dict[str, str]]:
    if transform_scope is None:
        share_metric = VisualMetricConfig(
            key="metrics.share",
            expression="metrics.manual / metrics.total",
        )
        transform = None
    else:
        share_metric = VisualMetricConfig(key="metrics.manual")
        transform = SeriesTransformConfig(
            mode=SeriesTransformMode.PERCENT_OF_TOTAL,
            scope=transform_scope,
            source_series="manual",
        )

    config = CartesianChartConfig(
        schema="draft-1",
        type="column",
        title="Test Chart",
        category=CategoryConfig(
            field="'dim_calendar'[Month]",
            label="Month",
            mock_values=("Jan-25", "Feb-25", "Mar-25"),
        ),
        value_axes=ValueAxesConfig(
            primary=AxisConfig(label="Count"),
            secondary=AxisConfig(label="Percent", format="percent:0"),
        ),
        series=[
            CartesianSeriesConfig(
                id="total",
                label="Total",
                type="column",
                metric=VisualMetricConfig(key="metrics.total"),
            ),
            CartesianSeriesConfig(
                id="manual",
                label="Manual",
                type="column",
                metric=VisualMetricConfig(key="metrics.manual"),
            ),
            CartesianSeriesConfig(
                id="share",
                label="Share",
                type="line",
                axis="secondary",
                metric=share_metric,
                transform=transform,
            ),
        ],
    )

    measure_map = {
        "total": "measure_total",
        "manual": "measure_manual",
        "share": "measure_share",
    }
    return config, measure_map


def test_mock_chart_data_uses_mock_values() -> None:
    config, measure_map = _build_chart_config(transform_scope=None)
    dataset = mock_chart_data(config, measure_map)

    assert isinstance(dataset, ChartResultSet)
    assert {category.label for category in dataset.categories} == {"Jan-25", "Feb-25", "Mar-25"}
    assert {series.id for series in dataset.series} == {"total", "manual", "share"}


def test_percent_of_total_transform_visual_scope() -> None:
    config, measure_map = _build_chart_config(transform_scope="visual")
    dataset = mock_chart_data(config, measure_map)

    share_series = next(series for series in dataset.series if series.id == "share")
    manual_series = next(series for series in dataset.series if series.id == "manual")
    total_series = next(series for series in dataset.series if series.id == "total")

    for index, value in enumerate(share_series.values):
        value_float = cast(float, value)
        assert 0.0 <= value_float <= 1.0
        manual_value = cast(float, manual_series.values[index])
        total_value = cast(float, total_series.values[index])
        denominator = manual_value + total_value
        if denominator:
            upper_bound = manual_value / denominator
            assert value_float <= upper_bound + 1e-6


def test_percent_of_total_transform_category_scope() -> None:
    config, measure_map = _build_chart_config(transform_scope="category")
    dataset = mock_chart_data(config, measure_map)

    share_series = next(series for series in dataset.series if series.id == "share")
    numeric_values = [cast(float, value) for value in share_series.values]
    assert all(0.0 <= value <= 1.0 for value in numeric_values)
    assert pytest.approx(sum(numeric_values), rel=1e-9) == 1.0
