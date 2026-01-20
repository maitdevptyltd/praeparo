"""Tests for Praeparo metric definition models."""

from __future__ import annotations

import pytest

from typing import Any

from praeparo.metrics import MetricDefinition


def _sample_metric_payload() -> dict[str, Any]:
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
    assert metric.calculate.define == [
        'dim_wf_component.WFComponentName = "Send Processed Documents"',
        'dim_event_type.MatterEventTypeName = "Milestone Complete"',
    ]
    assert metric.calculate.evaluate == []
    assert metric.variants["automated"].calculate.define == ["fact_events.IsAutomated = TRUE()"]
    assert metric.variants["automated"].calculate.evaluate == []
    assert metric.ratios is not None
    assert metric.ratios.auto_percent_of_base is True
    assert metric.ratios.auto_percent_format == "percent"


def test_metric_definition_supports_scoped_calculate_filters() -> None:
    payload = _sample_metric_payload()
    payload["calculate"] = {
        "define": ["dim_status.IsComplete = TRUE()"],
        "evaluate": ["'dim_calendar'[Month] = DATE(2025, 11, 1)"],
    }
    payload["variants"]["automated"]["calculate"] = {
        "evaluate": ["fact_events.IsAutomated = TRUE()"],
    }

    metric = MetricDefinition.model_validate(payload)

    assert metric.calculate.define == ["dim_status.IsComplete = TRUE()"]
    assert metric.calculate.evaluate == ["'dim_calendar'[Month] = DATE(2025, 11, 1)"]
    assert metric.variants["automated"].calculate.define == []
    assert metric.variants["automated"].calculate.evaluate == ["fact_events.IsAutomated = TRUE()"]


def test_metric_definition_enforces_slug_variant_keys() -> None:
    payload = _sample_metric_payload()
    payload["variants"]["Invalid Key"] = {
        "display_name": "Bad variant",
        "calculate": [],
    }

    with pytest.raises(ValueError):
        MetricDefinition.model_validate(payload)


def test_metric_definition_supports_nested_variants() -> None:
    payload = _sample_metric_payload()
    payload["variants"]["full"] = {
        "display_name": "Full discharges",
        "calculate": ['dim_discharge_type.DischargeTypeName = "Full"'],
        "variants": {
            "refinance": {
                "display_name": "Full discharges – refinance",
                "calculate": ['dim_discharge_reason_type.DischargeReasonTypeName = "Refinance"'],
            }
        },
    }

    metric = MetricDefinition.model_validate(payload)

    assert "full" in metric.variants
    assert "refinance" in metric.variants["full"].variants
    flat = metric.flattened_variants()
    assert "full" in flat
    assert "full.refinance" in flat


def test_metric_definition_accepts_explain_spec() -> None:
    payload = _sample_metric_payload()
    payload["explain"] = {
        "grain": {"event_key": "fact_events[EventKey]"},
        "select": {
            "event_timestamp_utc": "fact_events[EventTimestampUTC]",
            "within_sla": "fact_events[DeltaDays] <= 1",
        },
    }
    payload["variants"]["automated"]["explain"] = {
        "select": {"is_automated": "fact_events[IsAutomated] = TRUE()"},
        "where": ["fact_events[IsTest] = FALSE()"],
    }

    metric = MetricDefinition.model_validate(payload)

    assert metric.explain is not None
    assert metric.explain.grain == {"event_key": "fact_events[EventKey]"}
    assert metric.explain.select is not None
    assert "within_sla" in metric.explain.select
    assert metric.variants["automated"].explain is not None
    assert metric.variants["automated"].explain.where == ["fact_events[IsTest] = FALSE()"]


def test_metric_explain_spec_rejects_reserved_labels() -> None:
    payload = _sample_metric_payload()
    payload["explain"] = {"select": {"__bad": "1"}}

    with pytest.raises(ValueError):
        MetricDefinition.model_validate(payload)
