from __future__ import annotations

from typing import Sequence

from praeparo.pipeline import OutputTarget, PythonVisualBase
from praeparo.pipeline.core import ExecutionContext, VisualPipeline
from praeparo.pipeline.outputs import OutputKind, PipelineOutputArtifact
from praeparo.pipeline.registry import DatasetArtifact, RenderOutcome
from praeparo.visuals.context_models import VisualContextModel


class TestContext(VisualContextModel):
    report_title: str | None = None


class SimpleVisual(PythonVisualBase[list[int], TestContext]):
    context_model = TestContext
    name = "Simple Python Visual"

    def build_dataset(
        self,
        pipeline: VisualPipeline[TestContext],
        config,
        schema_artifact,
        context: ExecutionContext[TestContext],
    ) -> DatasetArtifact[list[int]]:
        return DatasetArtifact(value=[1, 2, 3], filename="numbers.json")

    def render(
        self,
        pipeline: VisualPipeline[TestContext],
        config,
        schema_artifact,
        dataset_artifact: DatasetArtifact[list[int]],
        context: ExecutionContext[TestContext],
        outputs: Sequence[OutputTarget],
    ) -> RenderOutcome:
        report_title = getattr(context.visual_context, "report_title", None)
        emitted: list[PipelineOutputArtifact] = []

        for target in outputs:
            target.path.parent.mkdir(parents=True, exist_ok=True)
            if target.kind is OutputKind.HTML:
                target.path.write_text(f"<h1>{report_title or 'untitled'}</h1>", encoding="utf-8")
            elif target.kind is OutputKind.PNG:
                target.path.write_bytes(b"PNG")
            emitted.append(PipelineOutputArtifact(kind=target.kind, path=target.path))

        return RenderOutcome(outputs=emitted)
