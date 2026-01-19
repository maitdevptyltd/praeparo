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


def test_compile_metric_tracks_evaluate_filters_separately() -> None:
    metric = MetricDefinition.model_validate(
        {
            "key": "documents_sent",
            "display_name": "Documents sent",
            "section": "Document Preparation",
            "define": normalize_dax_expression("SUM('fact_events'[DocumentsSent])"),
            "calculate": {
                "define": ["dim_status.IsComplete = TRUE()"],
                "evaluate": ["dim_lender.LenderId = 201"],
            },
            "variants": {
                "automated": {
                    "display_name": "Documents sent (automatic)",
                    "calculate": {"evaluate": ["fact_events.IsAutomated = TRUE()"]},
                }
            },
        }
    )

    plan = MetricDaxBuilder(_metric_catalog(metric)).compile_metric("documents_sent")

    assert plan.base.evaluate_filters == ("dim_lender.LenderId = 201",)
    assert "dim_lender" not in plan.base.expression
    assert "'dim_lender'[LenderId] = 201" in plan.base.expression_with_evaluate_filters()

    automated = plan.variants["automated"]
    assert automated.evaluate_filters == (
        "dim_lender.LenderId = 201",
        "fact_events.IsAutomated = TRUE()",
    )

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


def test_compile_metric_carries_format_and_variant_override() -> None:
    metric = MetricDefinition.model_validate(
        {
            "key": "documents_sent",
            "display_name": "Documents sent",
            "section": "Document Preparation",
            "define": normalize_dax_expression("SUM('fact_events'[DocumentsSent])"),
            "format": "percent",
            "variants": {
                "automated": {
                    "display_name": "Documents sent (automatic)",
                    "calculate": ["fact_events.IsAutomated = TRUE()"],
                    "format": "currency",
                },
                "manual": {
                    "display_name": "Documents sent (manual)",
                    "calculate": ["fact_events.IsAutomated = FALSE()"],
                },
            },
        }
    )

    plan = MetricDaxBuilder(_metric_catalog(metric)).compile_metric("documents_sent")

    assert plan.base.format == "percent"
    assert plan.variants["automated"].format == "currency"
    assert plan.variants["manual"].format == "percent"


def test_compile_metric_inherits_format_from_parent_when_unset() -> None:
    parent = MetricDefinition.model_validate(
        {
            "key": "documents_sent",
            "display_name": "Documents sent",
            "section": "Document Preparation",
            "define": normalize_dax_expression("SUM('fact_events'[DocumentsSent])"),
            "format": "percent",
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

    plan = MetricDaxBuilder(_metric_catalog(parent, child)).compile_metric("documents_sent_business")

    assert plan.base.format == "percent"


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


def test_compile_metric_with_expression_base() -> None:
    metric_a = MetricDefinition.model_validate(
        {
            "key": "metric_a",
            "display_name": "Metric A",
            "section": "Expression",
            "define": "SUM('fact_events'[A])",
        }
    )
    metric_b = MetricDefinition.model_validate(
        {
            "key": "metric_b",
            "display_name": "Metric B",
            "section": "Expression",
            "define": "SUM('fact_events'[B])",
        }
    )
    expression_metric = MetricDefinition.model_validate(
        {
            "key": "metric_a_plus_b",
            "display_name": "A plus B",
            "section": "Expression",
            "expression": "metric_a + metric_b",
        }
    )

    catalog = _metric_catalog(metric_a, metric_b, expression_metric)
    plan = MetricDaxBuilder(catalog).compile_metric("metric_a_plus_b")

    assert (
        plan.base.expression
        == "((SUM('fact_events'[A])) + (SUM('fact_events'[B])))"
    )


def test_compile_metric_expression_with_variants_wraps_filters() -> None:
    metric_a = MetricDefinition.model_validate(
        {
            "key": "metric_a",
            "display_name": "Metric A",
            "section": "Expression",
            "define": "SUM('fact_events'[A])",
        }
    )
    metric_b = MetricDefinition.model_validate(
        {
            "key": "metric_b",
            "display_name": "Metric B",
            "section": "Expression",
            "define": "SUM('fact_events'[B])",
        }
    )
    expression_metric = MetricDefinition.model_validate(
        {
            "key": "metric_a_plus_b",
            "display_name": "A plus B",
            "section": "Expression",
            "expression": "metric_a + metric_b",
            "calculate": ["dim_status.IsComplete = TRUE()"],
            "variants": {
                "automated": {
                    "display_name": "A plus B (automatic)",
                    "calculate": ["fact_events.IsAutomated = TRUE()"],
                },
            },
        }
    )

    catalog = _metric_catalog(metric_a, metric_b, expression_metric)
    plan = MetricDaxBuilder(catalog).compile_metric("metric_a_plus_b")

    expected_base = (
        "CALCULATE(\n"
        "    ((SUM('fact_events'[A])) + (SUM('fact_events'[B]))),\n"
        "    'dim_status'[IsComplete] = TRUE()\n"
        ")"
    )
    assert plan.base.expression == expected_base

    expected_variant = (
        "CALCULATE(\n"
        "    ((SUM('fact_events'[A])) + (SUM('fact_events'[B]))),\n"
        "    'dim_status'[IsComplete] = TRUE(),\n"
        "    'fact_events'[IsAutomated] = TRUE()\n"
        ")"
    )
    assert plan.variants["automated"].expression == expected_variant


def test_compile_metric_leaf_expression_overrides_parent_define() -> None:
    parent = MetricDefinition.model_validate(
        {
            "key": "metric_a",
            "display_name": "Metric A",
            "section": "Expression",
            "define": "SUM('fact_events'[A])",
        }
    )
    metric_b = MetricDefinition.model_validate(
        {
            "key": "metric_b",
            "display_name": "Metric B",
            "section": "Expression",
            "define": "SUM('fact_events'[B])",
        }
    )
    child = MetricDefinition.model_validate(
        {
            "key": "metric_a_ratio",
            "display_name": "A / B",
            "section": "Expression",
            "extends": "metric_a",
            "expression": "metric_a / metric_b",
        }
    )

    catalog = _metric_catalog(parent, metric_b, child)
    plan = MetricDaxBuilder(catalog).compile_metric("metric_a_ratio")

    assert (
        plan.base.expression
        == "((SUM('fact_events'[A])) / (SUM('fact_events'[B])))"
    )


def test_compile_metric_leaf_define_overrides_parent_expression() -> None:
    metric_a = MetricDefinition.model_validate(
        {
            "key": "metric_a",
            "display_name": "Metric A",
            "section": "Expression",
            "define": "SUM('fact_events'[A])",
        }
    )
    metric_b = MetricDefinition.model_validate(
        {
            "key": "metric_b",
            "display_name": "Metric B",
            "section": "Expression",
            "define": "SUM('fact_events'[B])",
        }
    )
    parent = MetricDefinition.model_validate(
        {
            "key": "metric_total",
            "display_name": "Total",
            "section": "Expression",
            "expression": "metric_a + metric_b",
        }
    )
    child = MetricDefinition.model_validate(
        {
            "key": "metric_total_override",
            "display_name": "Override",
            "section": "Expression",
            "extends": "metric_total",
            "define": "SUM('fact_events'[Override])",
        }
    )

    catalog = _metric_catalog(metric_a, metric_b, parent, child)
    plan = MetricDaxBuilder(catalog).compile_metric("metric_total_override")

    assert plan.base.expression == "SUM('fact_events'[Override])"


def test_compile_metric_expression_circular_dependency_raises() -> None:
    metric_a = MetricDefinition.model_validate(
        {
            "key": "metric_a",
            "display_name": "Metric A",
            "section": "Expression",
            "expression": "metric_b",
        }
    )
    metric_b = MetricDefinition.model_validate(
        {
            "key": "metric_b",
            "display_name": "Metric B",
            "section": "Expression",
            "expression": "metric_a",
        }
    )

    catalog = _metric_catalog(metric_a, metric_b)
    builder = MetricDaxBuilder(catalog)

    with pytest.raises(ValueError, match="Circular metric dependency detected"):
        builder.compile_metric("metric_a")
