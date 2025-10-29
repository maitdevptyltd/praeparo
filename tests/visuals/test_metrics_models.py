from __future__ import annotations

import pytest

from praeparo.metrics import MetricGroupConfig
from praeparo.visuals.metrics import (
    VisualMetricConfig,
    VisualMetricMock,
    VisualMetricMockScenario,
    VisualMetricMockScenarioOverride,
    VisualMockConfig,
    normalise_str_sequence,
)


def test_normalise_str_sequence_accepts_string_and_list() -> None:
    assert normalise_str_sequence("a = 1") == ["a = 1"]
    assert normalise_str_sequence(["a", " b ", ""]) == ["a", "b"]


def test_visual_metric_mock_validates_factory() -> None:
    mock = VisualMetricMock(factory="COUNT")
    assert mock.factory == "count"
    with pytest.raises(ValueError):
        VisualMetricMock(factory="unknown")


def test_visual_metric_config_supports_calculate_and_mock_overrides() -> None:
    metric = VisualMetricConfig(
        key="documents_sent",
        calculate="'dim_lender'[LenderId] = 201",
        mock=VisualMetricMock(
            factory="count",
            scenario_overrides={
                "stress": VisualMetricMockScenarioOverride(multiplier=1.2)
            },
        ),
    )
    assert metric.calculate == ["'dim_lender'[LenderId] = 201"]
    assert metric.mock is not None
    assert metric.mock.scenario_overrides["stress"].multiplier == 1.2


def test_visual_mock_config_accepts_named_scenarios() -> None:
    config = VisualMockConfig(
        scenarios={
            "baseline": VisualMetricMockScenario(label="Baseline"),
        }
    )
    assert "baseline" in config.scenarios


def test_metric_group_config_accepts_nested_groups() -> None:
    child = MetricGroupConfig(metrics=["documents_sent"])
    parent = MetricGroupConfig(
        key="document_group",
        calculate=["'dim_region'[IsActive] = TRUE()"],
        metrics=[child, "documents_sent.manual"],
    )
    assert parent.key == "document_group"
    assert parent.calculate == ["'dim_region'[IsActive] = TRUE()"]
    assert len(parent.metrics) == 2
