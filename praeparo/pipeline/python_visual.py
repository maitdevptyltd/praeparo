"""Helper base class for authoring Python-backed visuals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, Type, TypeVar, cast

from praeparo.models import BaseVisualConfig
from praeparo.visuals.context_models import VisualContextModel

from .core import ExecutionContext, VisualPipeline
from .outputs import OutputTarget
from .registry import DatasetArtifact, RenderOutcome, SchemaArtifact
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

    # Optional human-friendly name used when building default configs.
    name: str | None = None

    def __post_init__(self) -> None:
        """Reuse subclass-declared context models when instantiating visuals."""

        declared_model = getattr(type(self), "context_model", None)
        if declared_model is not None and self.context_model is VisualContextModel:
            self.context_model = declared_model

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
    ) -> DatasetArtifact[DatasetT]:
        raise NotImplementedError

    def render(
        self,
        pipeline: VisualPipeline[ContextT],
        config: BaseVisualConfig,
        schema_artifact: SchemaArtifact[None],
        dataset_artifact: DatasetArtifact[DatasetT],
        context: ExecutionContext[ContextT],
        outputs: Sequence[OutputTarget],
    ) -> RenderOutcome:
        raise NotImplementedError

    def to_config(self) -> BaseVisualConfig:
        """Return a minimal config stub compatible with the visual pipeline."""

        return BaseVisualConfig(type=PYTHON_VISUAL_TYPE, title=self.name)


__all__ = ["PythonVisualBase", "PYTHON_VISUAL_TYPE"]
