"""Tests for metric → DAX compilation."""

from __future__ import annotations

from pathlib import Path

import pytest

from praeparo.metrics import (
    MetricCatalog,
    MetricDaxBuilder,
    MetricDefinition,
    MetricVariant,
)
from praeparo.utils import normalize_dax_expression


def _metric_catalog(*metrics: MetricDefinition) -> MetricCatalog:
    registry = {metric.key: metric for metric in metrics}
    sources = {metric.key: Path(f"{metric.key}.yaml") for metric in metrics}
    return MetricCatalog(metrics=registry, sources=sources, files=[])


def test_compile_metric_with_base_filters_and_variants() -> None:
    metric = MetricDefinition.model_validate(
        {
            "key": "documents_sent",
            "display_name": "Documents sent",
            "section": "Document Preparation",
            "define": normalize_dax_expression("SUM('fact_events'[DocumentsSent])"),
            "calculate": ["dim_status.IsComplete = TRUE()"],
            "variants": {
                "automated": {
                    "display_name": "Documents sent (automatic)",
                    "calculate": ["fact_events.IsAutomated = TRUE()"],
                },
            },
        }
    )

    catalog = _metric_catalog(metric)
    builder = MetricDaxBuilder(catalog)
    plan = builder.compile_metric("documents_sent")

    expected_base = (
        "CALCULATE(\n"
        "    SUM('fact_events'[DocumentsSent]),\n"
        "    'dim_status'[IsComplete] = TRUE()\n"
        ")"
    )
    assert plan.base.expression == expected_base
    assert plan.variants
    automated = plan.variants["automated"]
    expected_variant = (
        "CALCULATE(\n"
        "    SUM('fact_events'[DocumentsSent]),\n"
        "    'dim_status'[IsComplete] = TRUE(),\n"
        "    'fact_events'[IsAutomated] = TRUE()\n"
        ")"
    )
    assert automated.expression == expected_variant
    assert automated.key == "documents_sent.automated"


def test_compile_metric_inherits_define_and_filters_from_parent() -> None:
    parent = MetricDefinition.model_validate(
            {
                "key": "documents_sent",
                "display_name": "Documents sent",
                "section": "Document Preparation",
                "define": normalize_dax_expression("SUM('fact_events'[DocumentsSent])"),
                "calculate": ["dim_status.IsComplete = TRUE()"],
            }
        )
    child = MetricDefinition.model_validate(
        {
            "key": "documents_sent_business",
            "display_name": "Business docs sent",
            "section": "Document Preparation",
            "extends": "documents_sent",
            "calculate": ["dim_matter.Segment = \"Business\""],
        }
    )

    catalog = _metric_catalog(parent, child)
    plan = MetricDaxBuilder(catalog).compile_metric("documents_sent_business")

    expected = (
        "CALCULATE(\n"
        "    SUM('fact_events'[DocumentsSent]),\n"
        "    'dim_status'[IsComplete] = TRUE(),\n"
        "    'dim_matter'[Segment] = \"Business\"\n"
        ")"
    )
    assert plan.base.expression == expected
    assert not plan.variants


def test_compile_metric_handles_nested_variants() -> None:
    variant = MetricVariant.model_validate(
        {
            "display_name": "Manual",
            "calculate": ["fact_events.IsAutomated = FALSE()"],
            "variants": {
                "within_4_hours": {
                    "display_name": "Manual within 4 hours",
                    "calculate": ["fact_events.BusinessHours <= 4"],
                }
            },
        }
    )
    metric = MetricDefinition(
        key="documents_sent",
        display_name="Documents sent",
        section="Document Preparation",
        define=normalize_dax_expression("SUM('fact_events'[DocumentsSent])"),
        variants={"manual": variant},
    )

    plan = MetricDaxBuilder(_metric_catalog(metric)).compile_metric("documents_sent")

    manual = plan.variants["manual"]
    assert (
        manual.expression
        == "CALCULATE(\n"
        "    SUM('fact_events'[DocumentsSent]),\n"
        "    'fact_events'[IsAutomated] = FALSE()\n"
        ")"
    )

    manual_nested = plan.variants["manual.within_4_hours"]
    assert (
        manual_nested.expression
        == "CALCULATE(\n"
        "    SUM('fact_events'[DocumentsSent]),\n"
        "    'fact_events'[IsAutomated] = FALSE(),\n"
        "    'fact_events'[BusinessHours] <= 4\n"
        ")"
    )


def test_compile_metric_raises_when_define_missing() -> None:
    metric = MetricDefinition.model_validate(
        {
            "key": "documents_sent",
            "display_name": "Documents sent",
            "section": "Document Preparation",
        }
    )
    catalog = _metric_catalog(metric)
    builder = MetricDaxBuilder(catalog)

    with pytest.raises(ValueError):
        builder.compile_metric("documents_sent")
