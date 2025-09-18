"""Core execution engine for Praeparo visuals."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Mapping, Protocol, Sequence, cast

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
from .providers.matrix import MatrixQueryPlanner


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
    figure: go.Figure | None
    plans: List[DaxQueryPlan]
    datasets: List[object]
    outputs: List[PipelineOutputArtifact]
    children: List["VisualExecutionResult"] = field(default_factory=list)


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
        self.register_strategy("matrix", _MatrixStrategy(self, self._planner_provider))
        self.register_strategy("frame", _FrameStrategy(self))

    def resolve_planner(self, visual: BaseVisualConfig, context: ExecutionContext):
        """Resolve a planner for the supplied visual configuration."""
        return self._planner_provider.resolve(visual, context)

    def register_strategy(self, visual_type: str, strategy: VisualPipelineStrategy) -> None:
        self._strategies[visual_type] = strategy

    def execute(self, config: BaseVisualConfig, context: ExecutionContext) -> VisualExecutionResult:
        strategy = self._strategies.get(config.type)
        if strategy is None:
            raise ValueError(f"No pipeline strategy registered for visual type '{config.type}'.")
        return strategy.execute(config, context)

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


class _MatrixStrategy:
    """Executes matrix visuals end-to-end."""

    def __init__(self, pipeline: VisualPipeline, planner_provider: QueryPlannerProvider) -> None:
        self._pipeline = pipeline
        self._planner_provider = planner_provider

    def execute(self, config: BaseVisualConfig, context: ExecutionContext) -> VisualExecutionResult:
        if not isinstance(config, MatrixConfig):
            raise TypeError("Matrix strategy requires a MatrixConfig instance.")

        matrix_config = config
        planner = self._planner_provider.resolve(matrix_config, context)
        if not isinstance(planner, MatrixQueryPlanner):
            raise TypeError("Resolved planner is not a MatrixQueryPlanner.")

        planner_result = planner.plan(matrix_config, context=context)
        plan = planner_result.plan
        dataset = planner_result.dataset

        options = context.options
        if options.sort_rows and dataset.rows:
            sorted_rows = sorted(
                dataset.rows,
                key=lambda row: tuple(str(row.get(field.placeholder)) for field in dataset.row_fields),
            )
            dataset = MatrixResultSet(rows=sorted_rows, row_fields=dataset.row_fields)

        if options.ensure_non_empty_rows and not dataset.rows:
            raise AssertionError("Matrix data provider returned no rows.")

        if options.ensure_values_present and dataset.rows:
            first_row = dataset.rows[0]
            for value in matrix_config.values:
                alias = value.label or value.id
                if first_row.get(alias) is None:
                    raise AssertionError(f"Value '{alias}' missing from dataset row")

        if options.validate_define:
            config_define = (matrix_config.define or "").strip() or None
            if config_define:
                assert plan.define == config_define
            else:
                assert plan.define is None

        figure = matrix_figure(matrix_config, dataset)

        outputs = self._pipeline._emit_outputs(
            visual=matrix_config,
            dataset_payload=dataset,
            figure=figure,
            targets=options.outputs,
            png_scale=options.png_scale,
        )

        return VisualExecutionResult(
            config=matrix_config,
            figure=figure,
            plans=[plan],
            datasets=[dataset],
            outputs=outputs,
        )


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
