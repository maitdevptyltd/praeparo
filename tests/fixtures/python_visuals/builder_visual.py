from __future__ import annotations

from typing import Sequence

from praeparo.datasets import MetricDatasetBuilder
from praeparo.pipeline import OutputTarget, PythonVisualBase
from praeparo.pipeline.core import ExecutionContext, VisualPipeline
from praeparo.pipeline.outputs import OutputKind, PipelineOutputArtifact
from praeparo.pipeline.registry import DatasetArtifact, RenderOutcome
from praeparo.visuals.context_models import VisualContextModel


class _CtxModel(VisualContextModel):
    report_title: str | None = None


class BuilderVisual(PythonVisualBase[list[dict[str, object]], _CtxModel]):
    context_model = _CtxModel
    name = "Builder Visual"

    def build_dataset(
        self,
        pipeline: VisualPipeline[_CtxModel],
        config,
        schema_artifact,
        context: ExecutionContext[_CtxModel],
    ) -> DatasetArtifact[list[dict[str, object]]]:
        builder = MetricDatasetBuilder(context.dataset_context, slug="builder_visual")
        builder.use_mock(True)
        builder.metric("documents_sent", alias="documents_sent")
        builder.metric("documents_sent.within_4_hours", alias="pct_in_4h", value_type="ratio")
        return builder

    def render(
        self,
        pipeline: VisualPipeline[_CtxModel],
        config,
        schema_artifact,
        dataset_artifact: DatasetArtifact[list[dict[str, object]]],
        context: ExecutionContext[_CtxModel],
        outputs: Sequence[OutputTarget],
    ) -> RenderOutcome:
        emitted: list[PipelineOutputArtifact] = []
        for target in outputs:
            target.path.parent.mkdir(parents=True, exist_ok=True)
            if target.kind is OutputKind.HTML:
                target.path.write_text("<h1>builder visual</h1>", encoding="utf-8")
            elif target.kind is OutputKind.PNG:
                target.path.write_bytes(b"PNG")
            emitted.append(PipelineOutputArtifact(kind=target.kind, path=target.path))
        return RenderOutcome(outputs=emitted)

