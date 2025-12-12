"""Helper base class for authoring Python-backed visuals."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from dataclasses import dataclass
from typing import Any, Generic, Sequence, Type, TypeVar, cast

import plotly.graph_objects as go

from praeparo.dax import DaxQueryPlan
from praeparo.datasets import MetricDatasetBuilder
from praeparo.models import BaseVisualConfig
from pydantic import BaseModel
from praeparo.visuals.context_models import VisualContextModel

from .core import ExecutionContext, VisualPipeline
from .outputs import OutputKind, OutputTarget, PipelineOutputArtifact
from .registry import DatasetArtifact, RenderOutcome, SchemaArtifact, VisualPipelineDefinition
from .visual_definition import VisualPipelineDefinitionBase

DatasetT = TypeVar("DatasetT")
ContextT = TypeVar("ContextT", bound=VisualContextModel)

PYTHON_VISUAL_TYPE = "python"


@dataclass
class PythonVisualBase(
    VisualPipelineDefinitionBase[None, DatasetT, BaseVisualConfig, ContextT],
    Generic[DatasetT, ContextT],
):
    """Lightweight base for Python-backed visuals.

    Subclass this to define two hooks:
    - build_dataset: produce the dataset you want to render.
    - render: consume that dataset and emit outputs (PNG/HTML/etc.).
    """

    # Implementers must declare which VisualContextModel they expect.
    context_model: Type[ContextT] = cast(Type[ContextT], VisualContextModel)
    # Optional config model used when validating YAML-driven Python visuals.
    config_model: Type[BaseModel] | None = None

    # Optional human-friendly name used when building default configs.
    name: str | None = None

    def __post_init__(self) -> None:
        """Reuse subclass-declared context models when instantiating visuals."""

        declared_model = getattr(type(self), "context_model", None)
        if declared_model is not None and self.context_model is VisualContextModel:
            self.context_model = declared_model

        declared_config = getattr(type(self), "config_model", None)
        if declared_config is not None and self.config_model is None:
            self.config_model = declared_config

        if self.name is None:
            declared_name = getattr(type(self), "name", None)
            if declared_name:
                self.name = declared_name

    def build_schema(
        self,
        pipeline: VisualPipeline[ContextT],
        config: BaseVisualConfig,
        context: ExecutionContext[ContextT],
    ) -> SchemaArtifact[None]:
        # Python visuals skip schema generation; callers can override if needed.
        return SchemaArtifact(value=None)

    def build_dataset(
        self,
        pipeline: VisualPipeline[ContextT],
        config: BaseVisualConfig,
        schema_artifact: SchemaArtifact[None],
        context: ExecutionContext[ContextT],
    ) -> DatasetArtifact[DatasetT] | MetricDatasetBuilder:
        raise NotImplementedError

    def render(
        self,
        pipeline: VisualPipeline[ContextT],
        config: BaseVisualConfig,
        schema_artifact: SchemaArtifact[None],
        dataset_artifact: DatasetArtifact[DatasetT],
        context: ExecutionContext[ContextT],
        outputs: Sequence[OutputTarget],
    ) -> RenderOutcome | go.Figure:
        raise NotImplementedError

    def to_config(self) -> BaseVisualConfig:
        """Return a minimal config stub compatible with the visual pipeline."""

        return BaseVisualConfig(type=PYTHON_VISUAL_TYPE, title=self.name)

    def to_definition(self) -> VisualPipelineDefinition[None, DatasetT, BaseVisualConfig, ContextT]:
        """Normalise Python visual dataset builders.

        build_dataset may return either a DatasetArtifact directly or a
        MetricDatasetBuilder. The latter is executed and wrapped so the core
        pipeline can emit JSON datasets and .dax plans without extra visual
        boilerplate. The render hook may return a RenderOutcome explicitly or
        a bare Plotly Figure, which will be written to all requested outputs.
        """

        base_definition = super().to_definition()
        original_builder = self.build_dataset
        original_render = self.render

        def _dataset_builder_wrapper(
            pipeline: VisualPipeline[ContextT],
            config: BaseVisualConfig,
            schema: SchemaArtifact[None],
            context: ExecutionContext[ContextT],
        ) -> DatasetArtifact[DatasetT]:
            raw = original_builder(pipeline, config, schema, context)

            if isinstance(raw, DatasetArtifact):
                return raw

            if isinstance(raw, MetricDatasetBuilder):
                artifact = _builder_to_dataset_artifact(raw, case_key=context.case_key or "python_visual")
                return cast(DatasetArtifact[DatasetT], artifact)

            raise TypeError(
                "Python visual build_dataset must return DatasetArtifact or MetricDatasetBuilder, "
                f"got {type(raw)!r}"
            )

        def _render_wrapper(
            pipeline: VisualPipeline[ContextT],
            config: BaseVisualConfig,
            schema: SchemaArtifact[None],
            dataset: DatasetArtifact[DatasetT],
            context: ExecutionContext[ContextT],
            outputs: Sequence[OutputTarget],
        ) -> RenderOutcome:
            raw = original_render(pipeline, config, schema, dataset, context, outputs)

            if isinstance(raw, RenderOutcome):
                return raw

            if isinstance(raw, go.Figure):
                # If the visual did not explicitly size the figure, apply any
                # width/height hints from the execution metadata (for example,
                # PPTX placeholder geometry from a pack run).
                meta = context.options.metadata or {}
                width_meta = meta.get("width")
                height_meta = meta.get("height")
                layout_update: dict[str, int | bool] = {}
                current_width = getattr(raw.layout, "width", None)
                current_height = getattr(raw.layout, "height", None)
                if isinstance(width_meta, (int, float)) and current_width is None:
                    layout_update["width"] = int(width_meta)
                if isinstance(height_meta, (int, float)) and current_height is None:
                    layout_update["height"] = int(height_meta)
                if layout_update:
                    layout_update.setdefault("autosize", False)
                    cast(Any, raw).update_layout(**layout_update)

                emitted: list[PipelineOutputArtifact] = []
                for target in outputs:
                    target.path.parent.mkdir(parents=True, exist_ok=True)
                    if target.kind is OutputKind.HTML:
                        raw.write_html(str(target.path), include_plotlyjs="cdn", full_html=True)
                    elif target.kind is OutputKind.PNG:
                        scale = target.scale if target.scale is not None else context.options.png_scale
                        raw.write_image(str(target.path), scale=scale)
                    emitted.append(PipelineOutputArtifact(kind=target.kind, path=target.path))
                return RenderOutcome(figure=raw, outputs=emitted)

            if raw is None:
                return RenderOutcome()

            raise TypeError(
                "Python visual render must return RenderOutcome, Figure, or None, "
                f"got {type(raw)!r}"
            )

        def _builder_to_dataset_artifact(
            builder: MetricDatasetBuilder,
            *,
            case_key: str,
        ) -> DatasetArtifact[list[dict[str, object]]]:
            """Execute a MetricDatasetBuilder, avoiding asyncio.run in active loops."""

            plan = builder.plan()

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                rows = builder.execute()
            else:
                rows = _execute_builder_async(builder, case_key=case_key)

            define_block = "\n".join(plan.define_blocks) if plan.define_blocks else None
            dax_plan = DaxQueryPlan(
                statement=plan.statement,
                rows=tuple(),
                values=tuple(),
                define=define_block,
            )
            filename = f"{plan.slug}.data.json"
            return DatasetArtifact(value=rows, filename=filename, plans=[dax_plan])

        def _execute_builder_async(
            builder: MetricDatasetBuilder,
            *,
            case_key: str,
        ) -> list[dict[str, object]]:
            """Run builder.aexecute() on a dedicated thread and block for rows."""

            future: concurrent.futures.Future[list[dict[str, object]]] = concurrent.futures.Future()

            def _runner() -> None:
                try:
                    result = asyncio.run(builder.aexecute())
                    future.set_result(result.rows)
                except Exception as exc:  # noqa: BLE001
                    future.set_exception(exc)

            thread = threading.Thread(
                target=_runner,
                name=f"praeparo_python_visual_{case_key}",
                daemon=True,
            )
            thread.start()
            return future.result()

        return VisualPipelineDefinition(
            schema_builder=base_definition.schema_builder,
            dataset_builder=_dataset_builder_wrapper,
            renderer=_render_wrapper,
        )


__all__ = ["PythonVisualBase", "PYTHON_VISUAL_TYPE"]
