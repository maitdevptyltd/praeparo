from __future__ import annotations

from pathlib import Path

import pytest

from praeparo.datasources import ResolvedDataSource
from praeparo.io.yaml_loader import load_visual_config
from praeparo.pipeline import ExecutionContext, PipelineOptions
from praeparo.pipeline.providers.matrix.planners.dax import DaxBackedMatrixPlanner
from praeparo.powerbi import PowerBIQueryError


class _FailingDaxClient:
    def execute_matrix(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise PowerBIQueryError("400 Bad Request: DAX execution failed")


def test_matrix_planner_emits_dax_before_execution_failure(tmp_path: Path) -> None:
    config_path = tmp_path / "visual.yaml"
    fixture = Path(__file__).parent / "visuals" / "matrix" / "base.yaml"
    config_path.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    config = load_visual_config(config_path)
    assert getattr(config, "type", None) == "matrix"

    artefact_dir = tmp_path / "artefacts"
    options = PipelineOptions(artefact_dir=artefact_dir)
    context = ExecutionContext(
        config_path=config_path,
        project_root=tmp_path,
        case_key="matrix_failure",
        options=options,
    )

    def _resolver(reference: str | None, visual_path: Path) -> ResolvedDataSource:
        return ResolvedDataSource(name="broken", type="powerbi", dataset_id="dataset")

    planner = DaxBackedMatrixPlanner(
        dax_client=_FailingDaxClient(),
        datasource_resolver=_resolver,
    )

    with pytest.raises(PowerBIQueryError):
        planner.plan(config, context=context)  # type: ignore[arg-type]

    dax_path = artefact_dir / "matrix.dax"
    assert dax_path.exists()
    assert "EVALUATE" in dax_path.read_text(encoding="utf-8")

