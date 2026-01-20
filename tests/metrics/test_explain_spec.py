from __future__ import annotations

from pathlib import Path

from praeparo.metrics.catalog import MetricCatalog
from praeparo.metrics.explain import resolve_metric_explain_spec
from praeparo.metrics.models import MetricDefinition


def _metric_payload(key: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "draft-1",
        "key": key,
        "display_name": key.replace("_", " ").title(),
        "section": "Test",
        "define": "1",
        "calculate": [],
    }
    payload.update(overrides)
    return payload


def test_resolve_metric_explain_spec_merges_extends_and_variants() -> None:
    base = MetricDefinition.model_validate(
        _metric_payload(
            "base",
            explain={
                "from": "fact_events",
                "where": ["dim_customer[CustomerId] = 1"],
                "grain": {"event_key": "fact_events[EventKey]"},
                "select": {"event_timestamp_utc": "fact_events[EventTimestampUTC]"},
            },
        )
    )
    child = MetricDefinition.model_validate(
        _metric_payload(
            "child",
            extends="base",
            explain={
                "from": "fact_events_overridden",
                "where": ["dim_channel[ChannelName] = \"Direct\""],
                "grain": {"matter_id": "fact_events[MatterId]"},
                "select": {
                    "event_timestamp_utc": "fact_events[EventTimestampLocal]",
                    "business_days": "GetCustomerBusinessDays(fact_events[Start], fact_events[End])",
                },
            },
            variants={
                "within_1_day": {
                    "display_name": "Within 1 day",
                    "calculate": ["FILTER(fact_events, fact_events[DeltaDays] <= 1)"],
                    "explain": {
                        "where": ["fact_events[IsTest] = FALSE()"],
                        "select": {"within_1_day": "fact_events[DeltaDays] <= 1"},
                    },
                }
            },
        )
    )

    catalog = MetricCatalog(
        metrics={"base": base, "child": child},
        sources={"base": Path("base.yaml"), "child": Path("child.yaml")},
        files=[Path("base.yaml"), Path("child.yaml")],
    )

    spec = resolve_metric_explain_spec(catalog, metric_key="child", variant_path="within_1_day")
    assert spec is not None
    assert spec.from_ == "fact_events_overridden"
    assert spec.where == [
        "dim_customer[CustomerId] = 1",
        'dim_channel[ChannelName] = "Direct"',
        "fact_events[IsTest] = FALSE()",
    ]
    assert spec.grain == {
        "event_key": "fact_events[EventKey]",
        "matter_id": "fact_events[MatterId]",
    }
    assert spec.select == {
        "event_timestamp_utc": "fact_events[EventTimestampLocal]",
        "business_days": "GetCustomerBusinessDays(fact_events[Start], fact_events[End])",
        "within_1_day": "fact_events[DeltaDays] <= 1",
    }

