from __future__ import annotations

import pytest
from pydantic import ValidationError

from praeparo.models import CartesianChartConfig
from praeparo.models.cartesian import (
    AxisConfig,
    CartesianSeriesConfig,
    CategoryConfig,
    DataLabelConfig,
    SeriesStackingConfig,
    SeriesStackingMode,
    SeriesTransformConfig,
    SeriesTransformMode,
    ValueAxesConfig,
)
from praeparo.visuals.metrics import VisualMetricConfig


def _base_series(series_id: str, **overrides) -> CartesianSeriesConfig:
    defaults: dict[str, object] = {
        "id": series_id,
        "label": series_id.title(),
        "type": "column",
        "metric": VisualMetricConfig(key=f"{series_id}_metric"),
    }
    defaults.update(overrides)
    return CartesianSeriesConfig.model_validate(defaults)


def _base_config(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "draft-1",
        "type": "column",
        "category": {
            "field": "'dim_calendar'[Month]",
            "label": "Month",
        },
        "value_axes": {
            "primary": {"label": "Count"},
        },
        "series": [
            {
                "id": "primary",
                "label": "Primary",
                "type": "column",
                "metric": {"key": "metric.primary"},
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_cartesian_requires_unique_series_ids() -> None:
    payload = _base_config(
        series=[
            {"id": "duplicate", "label": "First", "type": "column", "metric": {"key": "metric.one"}},
            {"id": "duplicate", "label": "Second", "type": "column", "metric": {"key": "metric.two"}},
        ]
    )
    with pytest.raises(ValidationError):
        CartesianChartConfig.model_validate(payload)


def test_series_transform_rejects_expression_metrics() -> None:
    payload = _base_config(
        series=[
            {
                "id": "share",
                "label": "Share",
                "type": "line",
                "metric": {"key": "share", "expression": "metric.a / metric.b"},
                "transform": {"mode": "percent_of_total"},
            }
        ]
    )
    with pytest.raises(ValidationError):
        CartesianChartConfig.model_validate(payload)


def test_series_configuration_accepts_optional_fields() -> None:
    series = _base_series(
        "with_labels",
        stacking=SeriesStackingConfig(key="group", mode=SeriesStackingMode.PERCENT),
        data_labels=DataLabelConfig(position="outside_end", format="percent:0"),
    )
    assert series.stacking and series.stacking.key == "group"
    assert series.data_labels and series.data_labels.format == "percent:0"


def test_transform_scope_defaults_to_visual() -> None:
    series = _base_series(
        "share",
        type="line",
        transform=SeriesTransformConfig(mode=SeriesTransformMode.PERCENT_OF_TOTAL),
    )
    assert series.transform and series.transform.scope == "visual"


def test_calculate_filters_coerced_to_tuple() -> None:
    config = CartesianChartConfig.model_validate(
        _base_config(
            calculate=[
                "'dim_matter'[LoanTypeLegacy] = \"New Loan\"",
                "'dim_calendar'[Year] = 2024",
            ]
        )
    )
    assert config.calculate == (
        "'dim_matter'[LoanTypeLegacy] = \"New Loan\"",
        "'dim_calendar'[Year] = 2024",
    )
