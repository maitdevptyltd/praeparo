"""Visual pipeline public interface."""

from .core import (
    ExecutionContext,
    PipelineDataOptions,
    PipelineOptions,
    VisualExecutionResult,
    VisualPipeline,
)
from .outputs import OutputKind, OutputTarget, PipelineOutputArtifact
from .registry import (
    DatasetArtifact,
    DatasetBuilder,
    RenderOutcome,
    SchemaArtifact,
    SchemaBuilder,
    VisualPipelineDefinition,
    get_visual_pipeline_definition,
    register_visual_pipeline,
)
from .providers import (
    DefaultQueryPlannerProvider,
    QueryPlannerProvider,
    build_default_query_planner_provider,
)
from .defaults import register_default_pipelines

register_default_pipelines()

__all__ = [
    "DefaultQueryPlannerProvider",
    "ExecutionContext",
    "OutputKind",
    "OutputTarget",
    "PipelineDataOptions",
    "PipelineOptions",
    "PipelineOutputArtifact",
    "QueryPlannerProvider",
    "VisualExecutionResult",
    "VisualPipeline",
    "build_default_query_planner_provider",
    "DatasetArtifact",
    "DatasetBuilder",
    "RenderOutcome",
    "SchemaArtifact",
    "SchemaBuilder",
    "VisualPipelineDefinition",
    "get_visual_pipeline_definition",
    "register_visual_pipeline",
]
