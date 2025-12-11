from __future__ import annotations

from typing import Sequence

import plotly.graph_objects as go

from praeparo.pipeline import OutputTarget, PythonVisualBase
from praeparo.pipeline.core import ExecutionContext, VisualPipeline
from praeparo.pipeline.registry import DatasetArtifact
from praeparo.visuals.context_models import VisualContextModel


class FigureContext(VisualContextModel):
    pass


class FigureVisual(PythonVisualBase[list[dict[str, list[int]]], FigureContext]):
    context_model = FigureContext
    name = "Figure Visual"

    def build_dataset(
        self,
        pipeline: VisualPipeline[FigureContext],
        config,
        schema_artifact,
        context: ExecutionContext[FigureContext],
    ) -> DatasetArtifact[list[dict[str, list[int]]]]:
        rows: list[dict[str, list[int]]] = [{"x": [1, 2], "y": [3, 4]}]
        return DatasetArtifact(value=rows, filename="figure_visual.data.json")

    def render(
        self,
        pipeline: VisualPipeline[FigureContext],
        config,
        schema_artifact,
        dataset_artifact: DatasetArtifact[list[dict[str, list[int]]]],
        context: ExecutionContext[FigureContext],
        outputs: Sequence[OutputTarget],
    ) -> go.Figure:
        fig = go.Figure()
        data = dataset_artifact.value[0]
        fig.add_scatter(x=data["x"], y=data["y"])
        return fig
