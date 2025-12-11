from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types

import pytest

from praeparo.datasets import MetricDatasetBuilder, MetricDatasetBuilderContext
from praeparo.models import CartesianChartConfig
from praeparo.models.cartesian import AxisConfig, CartesianSeriesConfig, CategoryConfig, ValueAxesConfig
from praeparo.visuals.context_models import VisualContextModel
from praeparo.visuals.dax_context import DAXContextModel
from praeparo.visuals.metrics import VisualMetricConfig
from praeparo.pipeline.registry import DatasetArtifact
from praeparo.dax import DaxQueryPlan


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


def test_discover_merges_visual_context_dax(tmp_path: Path) -> None:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    visual_ctx = VisualContextModel(
        dax=DAXContextModel(
            calculate=("CTX_FILTER",),
            define=("DEFINE MEASURE Ctx[Value] = 1",),
        )
    )

    context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        calculate=["CLI_FILTER"],
        define=["DEFINE VAR Extra = 1"],
        visual_context=visual_ctx,
    )

    assert context.global_filters == ("CTX_FILTER", "CLI_FILTER")
    assert context.define_blocks == ("DEFINE MEASURE Ctx[Value] = 1", "DEFINE VAR Extra = 1")


def test_discover_falls_back_to_explicit_calculate_when_context_empty(tmp_path: Path) -> None:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    visual_ctx = VisualContextModel()

    context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        calculate="'dim_calendar'[IsCurrent] = TRUE()",
        define=None,
        visual_context=visual_ctx,
    )

    assert context.global_filters == ("'dim_calendar'[IsCurrent] = TRUE()",)
    assert context.define_blocks == ()


def test_plan_generates_expected_measure_map(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.grain("'dim_calendar'[Month]")
    builder.metric("documents_sent", label="Documents Sent")
    builder.metric("documents_sent.manual", alias="manual", label="Manual")

    plan = builder.plan()

    assert "documents_sent" in plan.measure_map
    assert plan.measure_map["manual"].startswith(plan.slug)
    assert "'dim_calendar'[Month]" in plan.statement


def test_plan_supports_expressions_and_global_filters(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.metric("documents_sent.manual", alias="manual")
    builder.metric("documents_sent", alias="total")
    builder.expression(
        "share",
        "documents_sent.manual / documents_sent",
        label="Share",
    ).calculate("'dim_calendar'[IsCurrent] = TRUE()")

    plan = builder.plan()

    assert "'dim_calendar'[IsCurrent] = TRUE()" in plan.global_filters
    assert any("CALCULATE" in measure.expression for measure in plan.measures)


def test_placeholder_series_when_allowed(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.metric("documents_sent", alias="total")
    builder.metric("missing.series", alias="placeholder", allow_placeholder=True)

    plan = builder.plan()

    assert "placeholder" in plan.placeholders


def test_ignore_placeholders_from_context_defaults_series(tmp_path: Path) -> None:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    _write_metric(metrics_root / "documents_sent.yaml")

    context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        ignore_placeholders=True,
    )
    builder = MetricDatasetBuilder(context)
    builder.metric("documents_sent", alias="total")
    builder.metric("missing.series", alias="missing_default")

    plan = builder.plan()

    assert "missing_default" in plan.placeholders


def test_global_ignore_overrides_explicit_allow_placeholder_false(tmp_path: Path) -> None:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    _write_metric(metrics_root / "documents_sent.yaml")

    context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        ignore_placeholders=True,
    )
    builder = MetricDatasetBuilder(context)
    builder.metric("documents_sent", alias="total")
    builder.metric("missing.series", alias="missing_explicit", allow_placeholder=False)

    plan = builder.plan()

    assert "missing_explicit" in plan.placeholders


def test_per_series_allow_placeholder_without_global_flag(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.metric("documents_sent", alias="total")
    builder.metric("missing.series", alias="missing", allow_placeholder=True)

    plan = builder.plan()

    assert "missing" in plan.placeholders


def test_missing_metric_raises_without_allowance(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.metric("documents_sent", alias="total")
    builder.metric("missing.series", alias="missing")

    with pytest.raises(KeyError):
        builder.plan()


def test_expression_inherits_global_ignore_placeholders(tmp_path: Path) -> None:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    _write_metric(metrics_root / "documents_sent.yaml")

    context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        ignore_placeholders=True,
    )
    builder = MetricDatasetBuilder(context)
    builder.metric("documents_sent", alias="total")
    builder.expression("share", "missing.metric")

    plan = builder.plan()

    assert "share" in plan.placeholders


def test_ignore_placeholder_override_without_context(tmp_path: Path) -> None:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    _write_metric(metrics_root / "documents_sent.yaml")

    builder = MetricDatasetBuilder(
        project_root=tmp_path,
        metrics_root=metrics_root,
        ignore_placeholders=True,
    )
    builder.metric("documents_sent", alias="total")
    builder.metric("missing.series", alias="missing")

    plan = builder.plan()

    assert "missing" in plan.placeholders


def test_execute_mock_returns_alias_columns(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.use_mock(True)
    builder.metric("documents_sent", alias="total")
    builder.metric("documents_sent.manual", alias="manual")

    rows = builder.execute()

    assert rows
    assert "total" in rows[0]
    assert "manual" in rows[0]


def test_result_to_dataframe_uses_pandas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.use_mock(True)
    builder.metric("documents_sent", alias="total")

    result = asyncio.run(builder.aexecute())

    captured: dict[str, object] = {}

    def _dataframe(payload):
        captured["value"] = payload
        return payload

    fake_module = types.ModuleType("pandas")
    fake_module.DataFrame = _dataframe  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pandas", fake_module)

    frame = result.to_dataframe()

    assert frame == result.rows
    assert captured["value"] == result.rows


def test_result_to_chart_result(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.use_mock(True)
    builder.metric("documents_sent", alias="total")
    builder.metric("documents_sent.manual", alias="manual")

    result = asyncio.run(builder.aexecute())

    config = CartesianChartConfig(
        schema="draft-1",
        type="column",
        title="Documents",
        category=CategoryConfig(field="'dim_calendar'[Month]", label="Month"),
        value_axes=ValueAxesConfig(primary=AxisConfig(label="Count")),
        series=[
            CartesianSeriesConfig(
                id="manual",
                label="Manual",
                type="column",
                metric=VisualMetricConfig(key="documents_sent.manual"),
            ),
            CartesianSeriesConfig(
                id="total",
                label="Total",
                type="column",
                metric=VisualMetricConfig(key="documents_sent"),
            ),
        ],
    )

    dataset = result.to_chart_result(config)

    assert dataset.categories
    assert {series.id for series in dataset.series} == {"manual", "total"}


def test_mock_controls_shape_rows(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.use_mock(True)
    builder.mock_rows(3)
    builder.mock_column("'dim_calendar'[Month]", ["Jan-25", "Feb-25", "Mar-25"])
    builder.metric("documents_sent", alias="total")

    rows = builder.execute()

    assert len(rows) == 3
    assert rows[0]["'dim_calendar'[Month]"] == "Jan-25"
    assert rows[-1]["'dim_calendar'[Month]"] == "Mar-25"


def test_mock_series_profiles_affect_values(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.use_mock(True)
    builder.mock_series("total", mean=520, trend=-20)
    builder.metric("documents_sent", alias="total")

    rows = builder.execute()

    values = []
    for row in rows:
        raw = row.get("total")
        if isinstance(raw, (int, float)):
            values.append(float(raw))
    assert values
    assert values[0] > values[-1]


def test_builder_to_dataset_artifact_wraps_plan_and_rows(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    builder.use_mock(True)
    builder.metric("documents_sent", alias="total")

    artifact = builder.to_dataset_artifact()

    assert isinstance(artifact, DatasetArtifact)
    assert isinstance(artifact.value, list)
    assert artifact.value
    assert artifact.plans
    assert isinstance(artifact.plans[0], DaxQueryPlan)
    assert isinstance(artifact.plans[0].statement, str)
