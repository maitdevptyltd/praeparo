"""Default visual pipeline registrations for Praeparo."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from praeparo.data import ChartResultSet, MatrixResultSet
from praeparo.dax import DaxQueryPlan
from praeparo.models import BaseVisualConfig, CartesianChartConfig, MatrixConfig
from praeparo.rendering import (
    cartesian_figure,
    cartesian_html,
    cartesian_png,
    matrix_figure,
    matrix_html,
    matrix_png,
)

from .core import ExecutionContext, VisualPipeline, _ensure_parent_directory
from .outputs import OutputKind, OutputTarget, PipelineOutputArtifact
from .providers.cartesian import ChartQueryPlanner
from .providers.matrix import MatrixQueryPlanner
from .registry import (
    DatasetArtifact,
    RenderOutcome,
    SchemaArtifact,
    VisualPipelineDefinition,
    default_json_writer,
    register_visual_pipeline,
)


def _coerce_dimension(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if candidate > 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            candidate = int(float(stripped))
        except ValueError:
            return None
        return candidate if candidate > 0 else None
    return None


def _write_matrix_schema(config: MatrixConfig, directory: Path, filename: str) -> Path:
    payload = config.model_dump(mode="json")
    return default_json_writer(payload, directory, filename)


def _write_matrix_dataset(dataset: MatrixResultSet, directory: Path, filename: str) -> Path:
    rows_payload = dataset.rows
    field_payload = [field.__dict__ for field in dataset.row_fields]
    payload = {"rows": rows_payload, "rowFields": field_payload}
    return default_json_writer(payload, directory, filename)


def _matrix_schema_builder(
    pipeline: VisualPipeline,
    config: BaseVisualConfig,
    context: ExecutionContext,
) -> SchemaArtifact[MatrixConfig]:
    if not isinstance(config, MatrixConfig):
        raise TypeError("Matrix pipeline expects a MatrixConfig instance.")
    return SchemaArtifact(value=config, filename="matrix.schema.json", writer=_write_matrix_schema)


def _matrix_dataset_builder(
    pipeline: VisualPipeline,
    config: BaseVisualConfig,
    schema: SchemaArtifact[MatrixConfig],
    context: ExecutionContext,
) -> DatasetArtifact[MatrixResultSet]:
    if not isinstance(config, MatrixConfig):
        raise TypeError("Matrix pipeline expects a MatrixConfig instance.")

    planner = pipeline.resolve_planner(config, context)
    if not isinstance(planner, MatrixQueryPlanner):
        raise TypeError("Resolved planner is not a MatrixQueryPlanner.")

    planner_result = planner.plan(config, context=context)
    dataset = planner_result.dataset
    plan = planner_result.plan

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
        for value in config.values:
            alias = value.label or value.id
            if first_row.get(alias) is None:
                raise AssertionError(f"Value '{alias}' missing from dataset row")

    if options.validate_define:
        config_define = (config.define or "").strip() or None
        if config_define:
            assert plan.define == config_define
        else:
            assert plan.define is None

    return DatasetArtifact(
        value=dataset,
        filename="matrix.data.json",
        writer=_write_matrix_dataset,
        plans=[plan],
    )


def _matrix_renderer(
    pipeline: VisualPipeline,
    config: BaseVisualConfig,
    schema: SchemaArtifact[MatrixConfig],
    dataset: DatasetArtifact[MatrixResultSet],
    context: ExecutionContext,
    outputs: Sequence[OutputTarget],
) -> RenderOutcome:
    matrix_config = schema.value
    matrix_dataset = dataset.value
    figure = matrix_figure(matrix_config, matrix_dataset)

    emitted: list[PipelineOutputArtifact] = []
    for target in outputs:
        path = target.path
        _ensure_parent_directory(path)
        if target.kind is OutputKind.HTML:
            matrix_html(matrix_config, matrix_dataset, str(path))
            emitted.append(PipelineOutputArtifact(kind=OutputKind.HTML, path=path))
        elif target.kind is OutputKind.PNG:
            scale = target.scale if target.scale is not None else context.options.png_scale
            matrix_png(matrix_config, matrix_dataset, str(path), scale=scale)
            emitted.append(PipelineOutputArtifact(kind=OutputKind.PNG, path=path))

    return RenderOutcome(figure=figure, outputs=emitted)


def _write_chart_schema(config: CartesianChartConfig, directory: Path, filename: str) -> Path:
    payload = config.model_dump(mode="json")
    return default_json_writer(payload, directory, filename)


def _normalise_series_values(values: Sequence[object]) -> list[object]:
    cleaned: list[object] = []
    for value in values:
        if isinstance(value, float) and math.isnan(value):
            cleaned.append(None)
        else:
            cleaned.append(value)
    return cleaned


def _write_chart_dataset(dataset: ChartResultSet, directory: Path, filename: str) -> Path:
    payload = {
        "categories": [{"label": category.label, "value": category.value} for category in dataset.categories],
        "series": [
            {
                "id": series.id,
                "measure": series.measure_name,
                "values": _normalise_series_values(series.values),
            }
            for series in dataset.series
        ],
    }
    return default_json_writer(payload, directory, filename)


def _chart_schema_builder(
    pipeline: VisualPipeline,
    config: BaseVisualConfig,
    context: ExecutionContext,
) -> SchemaArtifact[CartesianChartConfig]:
    if not isinstance(config, CartesianChartConfig):
        raise TypeError("Chart pipeline expects a CartesianChartConfig instance.")
    return SchemaArtifact(value=config, filename="chart.schema.json", writer=_write_chart_schema)


def _chart_dataset_builder(
    pipeline: VisualPipeline,
    config: BaseVisualConfig,
    schema: SchemaArtifact[CartesianChartConfig],
    context: ExecutionContext,
) -> DatasetArtifact[ChartResultSet]:
    if not isinstance(config, CartesianChartConfig):
        raise TypeError("Chart pipeline expects a CartesianChartConfig instance.")

    planner = pipeline.resolve_planner(config, context)
    if not isinstance(planner, ChartQueryPlanner):
        raise TypeError("Resolved planner is not a ChartQueryPlanner.")

    planner_result = planner.plan(config, context=context)
    dataset = planner_result.dataset
    plan = planner_result.plan

    options = context.options
    if options.ensure_non_empty_rows and not dataset.categories:
        raise AssertionError("Chart data provider returned no categories.")

    return DatasetArtifact(
        value=dataset,
        filename="chart.data.json",
        writer=_write_chart_dataset,
        plans=[plan],
    )


def _chart_renderer(
    pipeline: VisualPipeline,
    config: BaseVisualConfig,
    schema: SchemaArtifact[CartesianChartConfig],
    dataset: DatasetArtifact[ChartResultSet],
    context: ExecutionContext,
    outputs: Sequence[OutputTarget],
) -> RenderOutcome:
    chart_config = schema.value
    chart_dataset = dataset.value
    metadata = context.options.metadata or {}
    width = _coerce_dimension(metadata.get("width"))
    height = _coerce_dimension(metadata.get("height"))

    figure = cartesian_figure(chart_config, chart_dataset)
    if width is not None or height is not None:
        updates: dict[str, object] = {"autosize": False}
        if width is not None:
            updates["width"] = width
        if height is not None:
            updates["height"] = height
        figure.update_layout(**updates)

    emitted: list[PipelineOutputArtifact] = []
    for target in outputs:
        path = target.path
        _ensure_parent_directory(path)
        if target.kind is OutputKind.HTML:
            cartesian_html(
                chart_config,
                chart_dataset,
                str(path),
                width=width,
                height=height,
            )
            emitted.append(PipelineOutputArtifact(kind=OutputKind.HTML, path=path))
        elif target.kind is OutputKind.PNG:
            scale = target.scale if target.scale is not None else context.options.png_scale
            cartesian_png(
                chart_config,
                chart_dataset,
                str(path),
                scale=scale,
                width=width,
                height=height,
            )
            emitted.append(PipelineOutputArtifact(kind=OutputKind.PNG, path=path))

    return RenderOutcome(figure=figure, outputs=emitted)


def register_default_pipelines() -> None:
    matrix_definition = VisualPipelineDefinition(
        schema_builder=_matrix_schema_builder,
        dataset_builder=_matrix_dataset_builder,
        renderer=_matrix_renderer,
    )
    register_visual_pipeline("matrix", matrix_definition, overwrite=True)

    chart_definition = VisualPipelineDefinition(
        schema_builder=_chart_schema_builder,
        dataset_builder=_chart_dataset_builder,
        renderer=_chart_renderer,
    )
    register_visual_pipeline("column", chart_definition, overwrite=True)
    register_visual_pipeline("bar", chart_definition, overwrite=True)


__all__ = ["register_default_pipelines"]
