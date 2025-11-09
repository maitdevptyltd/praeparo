from __future__ import annotations

from pathlib import Path

from praeparo.datasets import MetricDatasetBuilder, MetricDatasetBuilderContext
from tests.snapshot_extensions import DaxSnapshotExtension


def _write_metric(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "schema: draft-1",
                "key: documents_sent",
                "display_name: Documents sent",
                "section: Document Preparation",
                'define: "COUNTROWS ( \'fact_documents\' )"',
                "variants:",
                "  manual:",
                "    display_name: Documents sent (manual)",
                "    calculate:",
                "      - \"'fact_documents'[IsManual] = TRUE()\"",
                "  automated:",
                "    display_name: Documents sent (automated)",
                "    calculate:",
                "      - \"'fact_documents'[IsManual] = FALSE()\"",
            ]
        ),
        encoding="utf-8",
    )


def _builder(tmp_path: Path) -> MetricDatasetBuilder:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    _write_metric(metrics_root / "documents_sent.yaml")

    context = MetricDatasetBuilderContext.discover(project_root=tmp_path, metrics_root=metrics_root)
    builder = MetricDatasetBuilder(context)
    return builder


def test_builder_plan_snapshot(snapshot, tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.slug("builder_snapshot_primary")
    builder.grain("'dim_calendar'[Month]")
    builder.metric("documents_sent", label="Documents Sent")
    builder.metric("documents_sent.manual", alias="manual")
    builder.metric("documents_sent.automated", alias="automated")
    builder.calculate(["'dim_calendar'[IsCurrent] = TRUE()"])

    plan = builder.plan()

    snapshot.use_extension(DaxSnapshotExtension).assert_match(plan.statement)


def test_builder_expression_snapshot(snapshot, tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.slug("builder_snapshot_expression")
    builder.grain("'dim_calendar'[Month]", "'dim_calendar'[Year]")
    builder.metric("documents_sent.manual", alias="manual")
    builder.metric("documents_sent.automated", alias="automated")
    builder.expression(
        "automation_share",
        "documents_sent.automated / documents_sent.manual",
        label="Automation Share",
    )
    builder.define("DEFINE MEASURE 'dim_calendar'[Dummy] = 1")

    plan = builder.plan()

    snapshot.use_extension(DaxSnapshotExtension).assert_match(plan.statement)

