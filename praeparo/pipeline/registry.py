"""Registry for visual pipeline definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generic, Protocol, Sequence, TypeVar, TYPE_CHECKING

from praeparo.data import MatrixResultSet  # noqa: F401 - used by default serializer
from praeparo.models import BaseVisualConfig
from praeparo.visuals.context_models import VisualContextModel

if TYPE_CHECKING:  # pragma: no cover
    from plotly.graph_objects import Figure

    from .core import ExecutionContext, VisualPipeline, VisualExecutionResult
    from .outputs import OutputTarget, PipelineOutputArtifact
    from praeparo.dax import DaxQueryPlan

SchemaT = TypeVar("SchemaT")
DatasetT = TypeVar("DatasetT")
ConfigT = TypeVar("ConfigT", bound=BaseVisualConfig, contravariant=True)
ContextT = TypeVar("ContextT", bound=VisualContextModel)

SchemaWriter = Callable[[SchemaT, Path, str], Path]
DatasetWriter = Callable[[DatasetT, Path, str], Path]


@dataclass
class SchemaArtifact(Generic[SchemaT]):
    """Represents a generated schema artifact prior to persistence."""

    value: SchemaT
    filename: str = "schema.json"
    writer: SchemaWriter[SchemaT] | None = None


@dataclass
class DatasetArtifact(Generic[DatasetT]):
    """Represents a generated dataset artifact prior to persistence."""

    value: DatasetT
    filename: str = "data.json"
    writer: DatasetWriter[DatasetT] | None = None
    plans: Sequence["DaxQueryPlan"] = ()


@dataclass
class RenderOutcome:
    """Outcome returned by a visual renderer."""

    figure: "Figure | None" = None
    outputs: list["PipelineOutputArtifact"] = field(default_factory=list)
    children: list["VisualExecutionResult"] = field(default_factory=list)


class SchemaBuilder(Protocol[SchemaT, ConfigT, ContextT]):
    def __call__(self, pipeline: "VisualPipeline[ContextT]", config: ConfigT, context: "ExecutionContext[ContextT]") -> SchemaArtifact[SchemaT]:
        ...


class DatasetBuilder(Protocol[SchemaT, DatasetT, ConfigT, ContextT]):
    def __call__(
        self,
        pipeline: "VisualPipeline[ContextT]",
        config: ConfigT,
        schema: SchemaArtifact[SchemaT],
        context: "ExecutionContext[ContextT]",
    ) -> DatasetArtifact[DatasetT]:
        ...


class Renderer(Protocol[SchemaT, DatasetT, ConfigT, ContextT]):
    def __call__(
        self,
        pipeline: "VisualPipeline[ContextT]",
        config: ConfigT,
        schema: SchemaArtifact[SchemaT],
        dataset: DatasetArtifact[DatasetT],
        context: "ExecutionContext[ContextT]",
        outputs: Sequence["OutputTarget"],
    ) -> RenderOutcome:
        ...


@dataclass
class VisualPipelineDefinition(Generic[SchemaT, DatasetT, ConfigT, ContextT]):
    """Associates builders and renderers for a visual type."""

    schema_builder: SchemaBuilder[SchemaT, ConfigT, ContextT]
    dataset_builder: DatasetBuilder[SchemaT, DatasetT, ConfigT, ContextT]
    renderer: Renderer[SchemaT, DatasetT, ConfigT, ContextT]


_PIPELINE_DEFINITIONS: Dict[str, VisualPipelineDefinition[Any, Any, Any, Any]] = {}


def register_visual_pipeline(
    type_name: str,
    definition: VisualPipelineDefinition[Any, Any, Any, Any],
    *,
    overwrite: bool = False,
) -> None:
    """Register a visual pipeline definition."""

    if not isinstance(type_name, str) or not type_name.strip():
        raise ValueError("type_name must be a non-empty string.")
    key = type_name.strip().lower()
    if not overwrite and key in _PIPELINE_DEFINITIONS:
        raise ValueError(f"Visual pipeline '{key}' is already registered.")
    _PIPELINE_DEFINITIONS[key] = definition


def get_visual_pipeline_definition(type_name: str) -> VisualPipelineDefinition[Any, Any, Any, Any] | None:
    """Return a registered visual pipeline definition."""

    key = type_name.strip().lower()
    return _PIPELINE_DEFINITIONS.get(key)


def ensure_directory(path: Path) -> None:
    """Ensure *path* exists."""

    path.mkdir(parents=True, exist_ok=True)


def default_json_writer(value: Any, directory: Path, filename: str) -> Path:
    """Write *value* to *directory/filename* using a JSON serializer."""

    ensure_directory(directory)
    output = directory / filename
    payload = _json_ready(value)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output


def _json_ready(value: Any) -> Any:
    """Attempt to convert *value* into a JSON-serialisable payload."""

    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return value.model_dump()

    from dataclasses import asdict, is_dataclass  # local import to avoid global dependency

    if is_dataclass(value):
        return asdict(value)  # type: ignore[arg-type]
    if isinstance(value, MatrixResultSet):
        return {
            "rows": value.rows,
            "rowFields": [_json_ready(field) for field in value.row_fields],
        }
    if isinstance(value, dict):
        return {key: _json_ready(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return {key: _json_ready(val) for key, val in value.__dict__.items()}
    raise TypeError(f"Unable to serialise value of type {type(value)!r} to JSON.")


__all__ = [
    "DatasetArtifact",
    "DatasetBuilder",
    "DatasetWriter",
    "Renderer",
    "RenderOutcome",
    "SchemaArtifact",
    "SchemaBuilder",
    "SchemaWriter",
    "VisualPipelineDefinition",
    "default_json_writer",
    "ensure_directory",
    "get_visual_pipeline_definition",
    "register_visual_pipeline",
]
