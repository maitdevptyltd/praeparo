from __future__ import annotations

import pytest

from praeparo.visuals.metrics import VisualGroupConfig, VisualMetricConfig
from praeparo.visuals.dax import (
    generate_measure_names,
    iter_group_metrics,
    normalise_define_blocks,
    split_metric_identifier,
)


def test_normalise_define_blocks_splits_text() -> None:
    blocks = normalise_define_blocks("MEASURE A = 1\n\nMEASURE B = 2")
    assert blocks == ("MEASURE A = 1", "MEASURE B = 2")


def test_generate_measure_names_applies_prefix_and_uniqueness() -> None:
    names = generate_measure_names(
        ["documents_sent", "documents_sent"],
        visual_slug="monthly_dashboard",
        prefix="msa_",
    )
    assert names == (
        "msa_monthly_dashboard_documents_sent",
        "msa_monthly_dashboard_documents_sent_2",
    )


def test_split_metric_identifier_handles_variant_path() -> None:
    base, variant = split_metric_identifier("documents_sent.manual.within_4_hours")
    assert base == "documents_sent"
    assert variant == "manual.within_4_hours"


def test_iter_group_metrics_yields_sections_and_metrics() -> None:
    metric = VisualMetricConfig.model_validate({"key": "documents_sent"})
    section = VisualGroupConfig.model_validate(
        {
            "metrics": [metric],
            "calculate": ["'dim_region'[IsActive] = TRUE()"],
        }
    )

    pairs = list(iter_group_metrics(groups=[section], metrics=None))
    assert len(pairs) == 1
    group, returned_metric = pairs[0]
    assert group is section
    assert returned_metric.key == "documents_sent"


def test_iter_group_metrics_rejects_invalid_entry() -> None:
    section = VisualGroupConfig.model_validate({"metrics": []})
    section.metrics.append(123)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        list(iter_group_metrics(groups=[section], metrics=None))
