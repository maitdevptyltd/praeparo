from __future__ import annotations

from praeparo.pipeline import OutputTarget, PythonVisualBase
from praeparo.pipeline.core import ExecutionContext, VisualPipeline
from praeparo.pipeline.registry import DatasetArtifact, RenderOutcome
from praeparo.visuals.context_models import VisualContextModel
from praeparo.models import BaseVisualConfig
from pydantic import ConfigDict


class SimpleYamlConfig(BaseVisualConfig):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    message: str
    type: str | None = None


class SimpleYamlContext(VisualContextModel):
    pass


class SimpleYamlVisual(PythonVisualBase[list[str], SimpleYamlContext]):
    config_model = SimpleYamlConfig
    context_model = SimpleYamlContext
    name = "Simple YAML Visual"

    def build_dataset(
        self,
        pipeline: VisualPipeline[SimpleYamlContext],
        config: SimpleYamlConfig,
        schema_artifact,
        context: ExecutionContext[SimpleYamlContext],
    ) -> DatasetArtifact[list[str]]:
        return DatasetArtifact(value=[config.message], filename="message.json")

    def render(
        self,
        pipeline: VisualPipeline[SimpleYamlContext],
        config: SimpleYamlConfig,
        schema_artifact,
        dataset_artifact: DatasetArtifact[list[str]],
        context: ExecutionContext[SimpleYamlContext],
        outputs: list[OutputTarget],
    ) -> RenderOutcome:
        return RenderOutcome(outputs=[])
