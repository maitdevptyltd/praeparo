from __future__ import annotations

from pathlib import Path

import pytest

from praeparo.data import ChartResultSet
from praeparo.io.yaml_loader import load_visual_config
from praeparo.pipeline import ExecutionContext, PipelineDataOptions, PipelineOptions, VisualPipeline
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
        result.figure.to_image(format="png", scale=2.0),
    )
