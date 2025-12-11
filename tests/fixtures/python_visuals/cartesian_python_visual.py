from __future__ import annotations

from praeparo.models.cartesian import PythonCartesianChartConfig
from praeparo.pipeline import OutputTarget, PythonVisualBase
from praeparo.pipeline.core import ExecutionContext, VisualPipeline
from praeparo.pipeline.registry import DatasetArtifact, RenderOutcome
from praeparo.visuals.context_models import VisualContextModel


class CartesianPythonContext(VisualContextModel):
    pass


class CartesianPythonVisual(PythonVisualBase[dict[str, list[str]], CartesianPythonContext]):
    config_model = PythonCartesianChartConfig
    context_model = CartesianPythonContext
    name = "Cartesian Python Visual"

    def build_dataset(
        self,
        pipeline: VisualPipeline[CartesianPythonContext],
        config: PythonCartesianChartConfig,
        schema_artifact,
        context: ExecutionContext[CartesianPythonContext],
    ) -> DatasetArtifact[dict[str, list[str]]]:
        series_ids = [series.id for series in config.series]
        return DatasetArtifact(value={"series_ids": series_ids}, filename="series.json")

    def render(
        self,
        pipeline: VisualPipeline[CartesianPythonContext],
        config: PythonCartesianChartConfig,
        schema_artifact,
        dataset_artifact: DatasetArtifact[dict[str, list[str]]],
        context: ExecutionContext[CartesianPythonContext],
        outputs: list[OutputTarget],
    ) -> RenderOutcome:
        return RenderOutcome(outputs=[])
