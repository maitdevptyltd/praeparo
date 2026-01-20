from __future__ import annotations

from pathlib import Path

from praeparo.metrics import load_metric_catalog
from praeparo.metrics.explain import build_metric_explain_plan
from tests.snapshot_extensions import DaxSnapshotExtension


def _write_metric(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "schema: draft-1",
                "key: documents_verified",
                "display_name: Documents verified",
                "section: Document Verification",
                "define: |",
                "  CALCULATE (",
                "      DISTINCTCOUNT ( 'fact_events'[MatterId] ),",
                "      // WFComponentId = 78",
                "      'dim_wf_component'[WFComponentName] = \"Check Returned Documents\",",
                "      'dim_event_type'[MatterEventTypeName] = \"Milestone Complete\"",
                "  )",
                "explain:",
                "  grain: fact_events[EventKey]",
                "  select:",
                "    event_timestamp_utc: fact_events[EventTimestampUTC]",
                "    milestone_started_timestamp_utc: fact_events[LastRelatedMilestoneStartedTimestampUTC]",
                "    business_days_to_verify: |",
                "      GetCustomerBusinessDays(",
                "        fact_events[LastRelatedMilestoneStartedTimestampUTC],",
                "        fact_events[EventTimestampUTC]",
                "      )",
                "variants:",
                "  within_1_day:",
                "    display_name: Documents verified within 1 day",
                "    calculate:",
                "      - FILTER(fact_events, GetCustomerBusinessDays(fact_events.LastRelatedMilestoneStartedTimestampUTC, fact_events.EventTimestampUTC) <= 1)",
            ]
        ),
        encoding="utf-8",
    )


def test_metric_explain_plan_snapshot(snapshot, tmp_path: Path) -> None:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    _write_metric(metrics_root / "documents_verified.yaml")

    catalog = load_metric_catalog([metrics_root])
    plan = build_metric_explain_plan(
        catalog,
        metric_identifier="documents_verified.within_1_day",
        context_calculate_filters=["'dim_calendar'[Month] = DATE(2025, 12, 1)"],
        context_define_blocks=["FUNCTION GetCustomerBusinessDays = () => 1"],
        limit=1000,
        variant_mode="flag",
    )

    snapshot.use_extension(DaxSnapshotExtension).assert_match(plan.statement)
