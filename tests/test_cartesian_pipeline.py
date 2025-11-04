from __future__ import annotations

from pathlib import Path

import pytest
import plotly.graph_objects as go

from praeparo.data import ChartResultSet
from praeparo.io.yaml_loader import load_visual_config
from praeparo.pipeline import ExecutionContext, PipelineDataOptions, PipelineOptions, VisualPipeline
from praeparo.pipeline.outputs import OutputTarget
from tests.snapshot_extensions import (
    DaxSnapshotExtension,
    PlotlyHtmlSnapshotExtension,
    PlotlyPngSnapshotExtension,
)

VISUAL_PATH = Path("tests/cartesian/visual.yaml")
METRICS_ROOT = VISUAL_PATH.parent / "metrics"


@pytest.mark.parametrize("visual_path", [VISUAL_PATH])
def test_cartesian_pipeline_snapshot(snapshot, tmp_path: Path, visual_path: Path) -> None:
    pytest.importorskip("kaleido")

    visual = load_visual_config(visual_path)
    pipeline = VisualPipeline()

    options = PipelineOptions()
    options.metadata["metrics_root"] = METRICS_ROOT
    options.metadata["measure_table"] = "'adhoc'"
    options.data = PipelineDataOptions(provider_key="mock")
    options.artefact_dir = tmp_path / "artefacts"

    context = ExecutionContext(
        config_path=visual_path,
        project_root=visual_path.parent.parent,
        case_key="cartesian_sample",
        options=options,
    )

    result = pipeline.execute(visual, context)

    assert isinstance(result.dataset, ChartResultSet)
    assert result.dataset.categories
    assert result.figure is not None

    snapshot.use_extension(PlotlyHtmlSnapshotExtension).assert_match(
        result.figure.to_html(full_html=True, include_plotlyjs="cdn", div_id="cartesian_sample"),
    )

    if result.plans:
        snapshot.use_extension(DaxSnapshotExtension).assert_match(result.plans[0].statement)

    snapshot.use_extension(PlotlyPngSnapshotExtension).assert_match(
        result.figure.to_image(format="png", scale=1.5, width=800, height=600,),
    )


def test_secondary_percent_axis_uses_percent_tickformat(tmp_path: Path) -> None:
    visual = load_visual_config(VISUAL_PATH)
    pipeline = VisualPipeline()

    options = PipelineOptions()
    options.metadata["metrics_root"] = METRICS_ROOT
    options.metadata["measure_table"] = "'adhoc'"
    options.data = PipelineDataOptions(provider_key="mock")
    options.artefact_dir = tmp_path / "artefacts"

    context = ExecutionContext(
        config_path=VISUAL_PATH,
        project_root=VISUAL_PATH.parent.parent,
        case_key="cartesian_percent_tickformat",
        options=options,
    )

    result = pipeline.execute(visual, context)
    assert result.figure is not None
    assert result.figure.layout.yaxis2.tickformat == ".0%"


def test_pipeline_applies_png_dimensions(monkeypatch, tmp_path: Path) -> None:
    visual = load_visual_config(VISUAL_PATH)
    pipeline = VisualPipeline()

    options = PipelineOptions()
    options.metadata["metrics_root"] = METRICS_ROOT
    options.metadata["measure_table"] = "'adhoc'"
    options.metadata["width"] = 300
    options.metadata["height"] = 200
    options.data = PipelineDataOptions(provider_key="mock")
    options.outputs = [OutputTarget.png(tmp_path / "dimensioned.png")]

    context = ExecutionContext(
        config_path=VISUAL_PATH,
        project_root=VISUAL_PATH.parent.parent,
        case_key="cartesian_dimensions",
        options=options,
    )

    monkeypatch.setattr("praeparo.rendering.cartesian.importlib_util.find_spec", lambda _: object())
    captured: dict[str, object] = {}

    def fake_write_image(self, output_path, **kwargs):
        captured["path"] = output_path
        captured["kwargs"] = kwargs

    monkeypatch.setattr(go.Figure, "write_image", fake_write_image, raising=False)

    result = pipeline.execute(visual, context)

    assert result.figure is not None
    assert result.figure.layout.width == 300
    assert result.figure.layout.height == 200
    assert captured["path"] == str(tmp_path / "dimensioned.png")
    assert captured["kwargs"]["width"] == 300
    assert captured["kwargs"]["height"] == 200
