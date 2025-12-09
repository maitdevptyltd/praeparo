from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar, cast

from praeparo.models import BaseVisualConfig
from praeparo.visuals.context_models import VisualContextModel

from .core import ExecutionContext, VisualPipeline
from .outputs import OutputTarget
from .registry import (
    DatasetArtifact,
    DatasetBuilder,
    RenderOutcome,
    SchemaArtifact,
    SchemaBuilder,
    Renderer,
    VisualPipelineDefinition,
)

SchemaT = TypeVar("SchemaT")
DatasetT = TypeVar("DatasetT")
ConfigT = TypeVar("ConfigT", bound=BaseVisualConfig)
ContextT = TypeVar("ContextT", bound=VisualContextModel)


@dataclass
class VisualPipelineDefinitionBase(Generic[SchemaT, DatasetT, ConfigT, ContextT]):
    """Ergonomic base for defining visual pipeline stages with type hints."""

    def build_schema(
        self,
        pipeline: VisualPipeline[ContextT],
        config: ConfigT,
        context: ExecutionContext[ContextT],
    ) -> SchemaArtifact[SchemaT]:
        raise NotImplementedError

    def build_dataset(
        self,
        pipeline: VisualPipeline[ContextT],
        config: ConfigT,
        schema_artifact: SchemaArtifact[SchemaT],
        context: ExecutionContext[ContextT],
    ) -> DatasetArtifact[DatasetT]:
        raise NotImplementedError

    def render(
        self,
        pipeline: VisualPipeline[ContextT],
        config: ConfigT,
        schema_artifact: SchemaArtifact[SchemaT],
        dataset_artifact: DatasetArtifact[DatasetT],
        context: ExecutionContext[ContextT],
        outputs: Sequence[OutputTarget],
    ) -> RenderOutcome:
        raise NotImplementedError

    def to_definition(self) -> VisualPipelineDefinition[SchemaT, DatasetT, ConfigT, ContextT]:
        return VisualPipelineDefinition(
            schema_builder=cast(SchemaBuilder[SchemaT, ConfigT, ContextT], self.build_schema),
            dataset_builder=cast(DatasetBuilder[SchemaT, DatasetT, ConfigT, ContextT], self.build_dataset),
            renderer=cast(Renderer[SchemaT, DatasetT, ConfigT, ContextT], self.render),
        )
