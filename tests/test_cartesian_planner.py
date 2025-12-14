from __future__ import annotations

from pathlib import Path

from praeparo.models import CartesianChartConfig
from praeparo.datasources import DataSourceConfigError, ResolvedDataSource
from praeparo.models.cartesian import (
    AxisConfig,
    CartesianSeriesConfig,
    CategoryConfig,
    ValueAxesConfig,
)
from praeparo.pipeline import ExecutionContext, PipelineDataOptions, PipelineOptions
from praeparo.pipeline.providers.cartesian.dax import DaxBackedChartPlanner
from praeparo.visuals.metrics import VisualMetricConfig
import pytest


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
                '    calculate: [\"\'fact_documents\'[IsManual] = TRUE()\"]',
            ]
        ),
        encoding="utf-8",
    )


def _build_config() -> CartesianChartConfig:
    return CartesianChartConfig(
        schema="draft-1",
        type="column",
        title="Documents Sent",
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
            CartesianSeriesConfig(
                id="share",
                label="Share",
                type="line",
                metric=VisualMetricConfig(
                    key="share",
                    expression="documents_sent.manual / documents_sent",
                ),
            ),
        ],
    )


def test_dax_backed_chart_planner_with_mock_provider(tmp_path: Path) -> None:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    _write_metric(metrics_root / "documents_sent.yaml")

    config = _build_config()
    planner = DaxBackedChartPlanner()
    options = PipelineOptions()
    options.metadata["metrics_root"] = metrics_root
    options.metadata["measure_table"] = "'adhoc'"
    options.data = PipelineDataOptions(provider_key="mock")

    context = ExecutionContext(
        config_path=tmp_path / "visual.yaml",
        project_root=tmp_path,
        case_key="cartesian_test",
        options=options,
    )

    result = planner.plan(config, context=context)

    assert result.plan.statement.strip().startswith("DEFINE")
    assert result.dataset.categories  # mock data populated
    assert {series.id for series in result.dataset.series} == {"manual", "total", "share"}
    assert result.measure_map["manual"].startswith("documents_sent")


def test_dax_backed_chart_planner_emits_dax_before_execution_failure(tmp_path: Path) -> None:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    _write_metric(metrics_root / "documents_sent.yaml")

    artefact_dir = tmp_path / "artefacts"

    def _broken_resolver(reference: str | None, visual_path: Path) -> ResolvedDataSource:
        return ResolvedDataSource(name="broken", type="powerbi", dataset_id=None)

    config = _build_config()
    planner = DaxBackedChartPlanner(datasource_resolver=_broken_resolver)

    options = PipelineOptions(artefact_dir=artefact_dir)
    options.metadata["metrics_root"] = metrics_root
    options.data = PipelineDataOptions(datasource_override="broken")

    context = ExecutionContext(
        config_path=tmp_path / "visual.yaml",
        project_root=tmp_path,
        case_key="cartesian_failure",
        options=options,
    )

    with pytest.raises(DataSourceConfigError):
        planner.plan(config, context=context)

    assert (artefact_dir / "column.dax").exists()
