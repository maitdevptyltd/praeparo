from __future__ import annotations

from pathlib import Path

from praeparo.models.visual_base import BaseVisualConfig
from praeparo.pipeline import (
    ExecutionContext,
    OutputKind,
    PipelineOptions,
    VisualPipeline,
    VisualPipelineDefinition,
    register_visual_pipeline,
)
from praeparo.pipeline.registry import DatasetArtifact, RenderOutcome, SchemaArtifact
from praeparo.visuals.context_models import VisualContextModel


class CustomVisual(BaseVisualConfig):
    type: str = "custom_visual"


def test_registered_pipeline_emits_schema_and_dataset(tmp_path: Path) -> None:
    execution_order: list[str] = []

    def schema_builder(
        pipeline: VisualPipeline[VisualContextModel],
        config: CustomVisual,
        context: ExecutionContext[VisualContextModel],
    ) -> SchemaArtifact[dict[str, object]]:
        execution_order.append("schema")
        return SchemaArtifact(value={"config": config.type}, filename="custom.schema.json")

    def dataset_builder(
        pipeline: VisualPipeline[VisualContextModel],
        config: CustomVisual,
        schema: SchemaArtifact[dict[str, object]],
        context: ExecutionContext[VisualContextModel],
    ) -> DatasetArtifact[dict[str, object]]:
        execution_order.append("dataset")
        return DatasetArtifact(value={"schemaType": schema.value["config"]}, filename="custom.data.json")

    def renderer(
        pipeline: VisualPipeline[VisualContextModel],
        config: CustomVisual,
        schema: SchemaArtifact[dict[str, object]],
        dataset: DatasetArtifact[dict[str, object]],
        context: ExecutionContext[VisualContextModel],
        outputs,
    ) -> RenderOutcome:
        execution_order.append("render")
        return RenderOutcome()

    register_visual_pipeline(
        "custom_visual",
        VisualPipelineDefinition(
            schema_builder=schema_builder,
            dataset_builder=dataset_builder,
            renderer=renderer,
        ),
        overwrite=True,
    )

    pipeline = VisualPipeline()
    context = ExecutionContext(options=PipelineOptions(artefact_dir=tmp_path))
    result = pipeline.execute(CustomVisual(), context)

    assert execution_order == ["schema", "dataset", "render"]
    assert result.schema == {"config": "custom_visual"}
    assert result.dataset == {"schemaType": "custom_visual"}
    assert result.schema_path == tmp_path / "custom.schema.json"
    assert result.dataset_path == tmp_path / "custom.data.json"

    kinds = {artifact.kind for artifact in result.outputs}
    assert OutputKind.SCHEMA in kinds
    assert OutputKind.DATA in kinds
