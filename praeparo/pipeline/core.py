"""Core execution engine for Praeparo visuals."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Mapping, Protocol, Sequence

import plotly.graph_objects as go

from praeparo.data import MatrixResultSet
from praeparo.dax import DaxQueryPlan
from praeparo.models import BaseVisualConfig, FrameChildConfig, FrameConfig, MatrixConfig
from praeparo.rendering import (
    frame_figure,
    frame_html,
    frame_png,
    matrix_figure,
    matrix_html,
    matrix_png,
)

from .outputs import OutputKind, OutputTarget, PipelineOutputArtifact
from .providers import (
    QueryPlannerProvider,
    build_default_query_planner_provider,
)
from .registry import (
    DatasetArtifact,
    RenderOutcome,
    SchemaArtifact,
    VisualPipelineDefinition,
    default_json_writer,
    get_visual_pipeline_definition,
)


@dataclass
class PipelineDataOptions:
    """Controls how datasets are resolved for a pipeline run."""

    datasource_override: str | None = None
    dataset_id: str | None = None
    workspace_id: str | None = None
    provider_key: str | None = None
    provider_case_overrides: Mapping[str, str] = field(default_factory=dict)


@dataclass
class PipelineOptions:
    """Runtime switches toggled by callers when executing visuals."""

    data: PipelineDataOptions = field(default_factory=PipelineDataOptions)
    outputs: List[OutputTarget] = field(default_factory=list)
    artefact_dir: Path | None = None
    metadata: Dict[str, object] = field(default_factory=dict)
    print_dax: bool = False
    ensure_non_empty_rows: bool = False
    ensure_values_present: bool = False
    validate_define: bool = False
    sort_rows: bool = False
    html_div_id: str | None = None
    png_scale: float = 2.0

    def without_outputs(self) -> "PipelineOptions":
        return replace(self, outputs=[])


@dataclass
class ExecutionContext:
    """Identifies the visual and environment participating in a run."""

    config_path: Path | None = None
    project_root: Path | None = None
    case_key: str | None = None
    options: PipelineOptions = field(default_factory=PipelineOptions)


@dataclass
class VisualExecutionResult:
    """Outcome of executing a single visual."""

    config: BaseVisualConfig
    schema: object | None = None
    dataset: object | None = None
    figure: go.Figure | None = None
    plans: List[DaxQueryPlan] = field(default_factory=list)
    schema_path: Path | None = None
    dataset_path: Path | None = None
    datasets: List[object] = field(default_factory=list)
    outputs: List[PipelineOutputArtifact] = field(default_factory=list)
    children: List["VisualExecutionResult"] = field(default_factory=list)


def _emit_dax_artifacts(
    *,
    plans: Sequence[DaxQueryPlan],
    config: BaseVisualConfig,
    dataset_filename: str,
    directory: Path,
) -> List[PipelineOutputArtifact]:
    emitted: List[PipelineOutputArtifact] = []
    if not plans:
        return emitted

    directory.mkdir(parents=True, exist_ok=True)
    valid_plans = [
        plan
        for plan in plans
        if isinstance(plan, DaxQueryPlan) and isinstance(plan.statement, str) and plan.statement.strip()
    ]
    if not valid_plans:
        return emitted

    total = len(valid_plans)

    for index, plan in enumerate(valid_plans, start=1):
        filename = _build_dax_filename(config, dataset_filename, index, total)
        path = directory / filename
        path.write_text(plan.statement.rstrip() + "\n", encoding="utf-8")
        emitted.append(PipelineOutputArtifact(kind=OutputKind.DAX, path=path))
    return emitted


def _build_dax_filename(
    config: BaseVisualConfig,
    dataset_filename: str,
    index: int,
    total: int,
) -> str:
    candidates: List[str] = []
    visual_type = getattr(config, "type", None)
    if isinstance(visual_type, str):
        candidates.append(visual_type)

    dataset_stem = Path(dataset_filename).stem
    if dataset_stem:
        candidates.append(dataset_stem)

    base = _first_non_empty_candidate(candidates)
    if total > 1:
        return f"{base}.plan{index}.dax"
    return f"{base}.dax"


def _first_non_empty_candidate(candidates: Sequence[str]) -> str:
    for candidate in candidates:
        cleaned = (candidate or "").strip()
        if not cleaned:
            continue
        if "." in cleaned:
            cleaned = cleaned.split(".", 1)[0]
        if cleaned:
            return cleaned
    return "visual"


class VisualPipelineStrategy(Protocol):
    """Strategy executed for each supported visual type."""

    def execute(self, config: BaseVisualConfig, context: ExecutionContext) -> VisualExecutionResult:
        """Render `config` with the provided execution context."""
        ...


class VisualPipeline:
    """Entry point that fans out to visual-type specific strategies."""

    def __init__(
        self,
        *,
        planner_provider: QueryPlannerProvider | None = None,
    ) -> None:
        self._planner_provider = planner_provider or build_default_query_planner_provider()
        self._strategies: Dict[str, VisualPipelineStrategy] = {}
        self.register_strategy("frame", _FrameStrategy(self))

    def resolve_planner(self, visual: BaseVisualConfig, context: ExecutionContext):
        """Resolve a planner for the supplied visual configuration."""
        return self._planner_provider.resolve(visual, context)

    def register_strategy(self, visual_type: str, strategy: VisualPipelineStrategy) -> None:
        self._strategies[visual_type] = strategy

    def execute(self, config: BaseVisualConfig, context: ExecutionContext) -> VisualExecutionResult:
        definition = get_visual_pipeline_definition(config.type)
        if definition is not None:
            return self._execute_definition(definition, config, context)

        strategy = self._strategies.get(config.type)
        if strategy is None:
            raise ValueError(f"No pipeline strategy registered for visual type '{config.type}'.")
        return strategy.execute(config, context)

    def _execute_definition(
        self,
        definition: VisualPipelineDefinition[object, object],
        config: BaseVisualConfig,
        context: ExecutionContext,
    ) -> VisualExecutionResult:
        schema_artifact = definition.schema_builder(self, config, context)
        dataset_artifact = definition.dataset_builder(self, config, schema_artifact, context)

        artefact_dir = context.options.artefact_dir
        schema_path: Path | None = None
        dataset_path: Path | None = None
        metadata_outputs: List[PipelineOutputArtifact] = []

        if artefact_dir is not None:
            schema_writer = schema_artifact.writer or default_json_writer
            dataset_writer = dataset_artifact.writer or default_json_writer
            schema_path = schema_writer(schema_artifact.value, artefact_dir, schema_artifact.filename)
            dataset_path = dataset_writer(dataset_artifact.value, artefact_dir, dataset_artifact.filename)
            metadata_outputs.extend(
                [
                    PipelineOutputArtifact(kind=OutputKind.SCHEMA, path=schema_path),
                    PipelineOutputArtifact(kind=OutputKind.DATA, path=dataset_path),
                ]
            )
            dax_outputs = _emit_dax_artifacts(
                plans=dataset_artifact.plans,
                config=config,
                dataset_filename=dataset_artifact.filename,
                directory=artefact_dir,
            )
            metadata_outputs.extend(dax_outputs)

        render_outcome = definition.renderer(
            self,
            config,
            schema_artifact,
            dataset_artifact,
            context,
            context.options.outputs,
        )

        plans: List[DaxQueryPlan] = []
        for plan in dataset_artifact.plans:
            if isinstance(plan, DaxQueryPlan):
                plans.append(plan)
        outputs = metadata_outputs + list(render_outcome.outputs)

        dataset_value = dataset_artifact.value

        return VisualExecutionResult(
            config=config,
            schema=schema_artifact.value,
            dataset=dataset_value,
            figure=render_outcome.figure,
            plans=plans,
            schema_path=schema_path,
            dataset_path=dataset_path,
            datasets=[dataset_value],
            outputs=outputs,
            children=list(render_outcome.children),
        )

    def _emit_outputs(
        self,
        *,
        visual: BaseVisualConfig,
        dataset_payload: MatrixResultSet | Sequence[tuple[MatrixConfig, MatrixResultSet]],
        figure: go.Figure,
        targets: Sequence[OutputTarget],
        png_scale: float,
    ) -> List[PipelineOutputArtifact]:
        artifacts: List[PipelineOutputArtifact] = []
        is_matrix_payload = isinstance(dataset_payload, MatrixResultSet)
        for target in targets:
            path = target.path
            _ensure_parent_directory(path)
            if target.kind is OutputKind.HTML:
                if is_matrix_payload:
                    matrix_html(visual, dataset_payload, str(path))  # type: ignore[arg-type]
                else:
                    frame_html(visual, dataset_payload, str(path))  # type: ignore[arg-type]
                artifacts.append(PipelineOutputArtifact(kind=OutputKind.HTML, path=path))
            elif target.kind is OutputKind.PNG:
                scale = target.scale if target.scale is not None else png_scale
                if is_matrix_payload:
                    matrix_png(visual, dataset_payload, str(path), scale=scale)  # type: ignore[arg-type]
                else:
                    frame_png(visual, dataset_payload, str(path), scale=scale)  # type: ignore[arg-type]
                artifacts.append(PipelineOutputArtifact(kind=OutputKind.PNG, path=path))
        return artifacts


class _FrameStrategy:
    """Executes frame visuals by delegating to child visuals."""

    def __init__(self, pipeline: VisualPipeline) -> None:
        self._pipeline = pipeline

    def execute(self, config: BaseVisualConfig, context: ExecutionContext) -> VisualExecutionResult:
        if not isinstance(config, FrameConfig):
            raise TypeError("Frame strategy requires a FrameConfig instance.")

        frame_config = config
        child_results: List[VisualExecutionResult] = []
        child_pairs: List[tuple[MatrixConfig, MatrixResultSet]] = []

        for index, child in enumerate(frame_config.children, start=1):
            if not isinstance(child, FrameChildConfig):
                raise TypeError("Frame strategy expects resolved FrameChildConfig entries.")

            child_visual = child.visual
            if not isinstance(child_visual, MatrixConfig):
                raise TypeError("Frame strategy currently supports Matrix child visuals.")

            child_case = _child_case_key(context.case_key, child_visual, child, index)
            child_context = ExecutionContext(
                config_path=child.source,
                project_root=context.project_root,
                case_key=child_case,
                options=context.options.without_outputs(),
            )
            result = self._pipeline.execute(child_visual, child_context)
            child_results.append(result)

            if not result.datasets:
                raise AssertionError("Child visual did not produce a dataset for frame rendering.")
            dataset = result.datasets[0]
            if not isinstance(dataset, MatrixResultSet):
                raise TypeError("Frame children must yield MatrixResultSet datasets.")
            child_pairs.append((child_visual, dataset))

        figure = frame_figure(frame_config, child_pairs)
        outputs = self._pipeline._emit_outputs(
            visual=frame_config,
            dataset_payload=child_pairs,
            figure=figure,
            targets=context.options.outputs,
            png_scale=context.options.png_scale,
        )

        return VisualExecutionResult(
            config=frame_config,
            schema=None,
            dataset=child_pairs,
            figure=figure,
            plans=[],
            datasets=[child_pairs],
            outputs=outputs,
            children=child_results,
        )


def _child_case_key(
    parent_case: str | None,
    child_visual: BaseVisualConfig,
    child_entry: FrameChildConfig,
    index: int,
) -> str | None:
    title = getattr(child_visual, "title", None)
    if title:
        slug = _slugify(title)
    else:
        source = getattr(child_entry, "source", None)
        if isinstance(source, Path):
            slug = _slugify(source.stem)
        else:
            slug = f"child_{index}"
    if parent_case:
        return f"{parent_case}__{slug}"
    return slug


def _slugify(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    filtered = "".join(char for char in normalized if char.isalnum() or char in {"_", "-"})
    return filtered or "section"


def _ensure_parent_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


__all__ = [
    "ExecutionContext",
    "PipelineDataOptions",
    "PipelineOptions",
    "VisualExecutionResult",
    "VisualPipeline",
]
