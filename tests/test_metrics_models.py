"""Tests for Praeparo metric definition models."""

from __future__ import annotations

import pytest

from praeparo.metrics import MetricDefinition


def _sample_metric_payload() -> dict[str, object]:
    return {
        "schema": "draft-1",
        "key": "documents_sent",
        "display_name": "Documents sent",
        "section": "Document Preparation",
        "description": "Count of matters where document packs were sent",
        "calculate": [
            'dim_wf_component.WFComponentName = "Send Processed Documents"',
            'dim_event_type.MatterEventTypeName = "Milestone Complete"',
        ],
        "variants": {
            "automated": {
                "display_name": "Documents sent (automatically)",
                "calculate": ["fact_events.IsAutomated = TRUE()"],
            },
            "within_5_minutes": {
                "display_name": "Documents sent within 5 minutes",
                "calculate": [
                    "fact_events.BusinessHoursFromDocumentPreparation * 60 <= 5"
                ],
            },
        },
        "ratios": {
            "auto_percent_of_base": True,
            "format": "percent",
        },
    }


def test_metric_definition_validates_expected_payload() -> None:
    payload = _sample_metric_payload()
    metric = MetricDefinition.model_validate(payload)

    assert metric.schema_version == "draft-1"
    assert metric.key == "documents_sent"
    assert metric.variants["automated"].calculate == ["fact_events.IsAutomated = TRUE()"]
    assert metric.ratios is not None
    assert metric.ratios.auto_percent_of_base is True
    assert metric.ratios.auto_percent_format == "percent"


def test_metric_definition_enforces_slug_variant_keys() -> None:
    payload = _sample_metric_payload()
    payload["variants"]["Invalid Key"] = {
        "display_name": "Bad variant",
        "calculate": [],
    }

    with pytest.raises(ValueError):
        MetricDefinition.model_validate(payload)
