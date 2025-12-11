from __future__ import annotations

import plotly.graph_objects as go

from praeparo.pipeline import PythonVisualBase
from praeparo.pipeline.core import ExecutionContext, VisualPipeline
from praeparo.pipeline.registry import DatasetArtifact, RenderOutcome
from praeparo.pipeline.outputs import OutputKind, OutputTarget, PipelineOutputArtifact
from praeparo.visuals.context_models import VisualContextModel


class _Ctx(VisualContextModel):
    title: str | None = None


class PackFigureVisual(PythonVisualBase[list[dict[str, int]], _Ctx]):
    context_model = _Ctx

    def build_dataset(
        self,
        pipeline: VisualPipeline[_Ctx],
        config,
        schema_artifact,
        context: ExecutionContext[_Ctx],
    ) -> DatasetArtifact[list[dict[str, int]]]:
        rows = [{"x": 1, "y": 2}]
        return DatasetArtifact(value=rows, filename="rows.json")

    def render(
        self,
        pipeline: VisualPipeline[_Ctx],
        config,
        schema_artifact,
        dataset_artifact: DatasetArtifact[list[dict[str, int]]],
        context: ExecutionContext[_Ctx],
        outputs: list[OutputTarget],
    ) -> RenderOutcome:
        fig = go.Figure()
        fig.add_scatter(x=[1, 2], y=[3, 4], name="demo")

        emitted: list[PipelineOutputArtifact] = []
        for target in outputs:
            target.path.parent.mkdir(parents=True, exist_ok=True)
            if target.kind is OutputKind.PNG:
                fig.write_image(target.path)
            elif target.kind is OutputKind.HTML:
                fig.write_html(target.path)
            emitted.append(PipelineOutputArtifact(kind=target.kind, path=target.path))

        return RenderOutcome(figure=fig, outputs=emitted)
