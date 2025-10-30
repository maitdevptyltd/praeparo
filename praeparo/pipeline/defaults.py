"""Default visual pipeline registrations for Praeparo."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from praeparo.data import MatrixResultSet
from praeparo.dax import DaxQueryPlan
from praeparo.models import BaseVisualConfig, MatrixConfig
from praeparo.rendering import matrix_figure, matrix_html, matrix_png

from .core import ExecutionContext, VisualPipeline, _ensure_parent_directory
from .outputs import OutputKind, OutputTarget, PipelineOutputArtifact
from .providers.matrix import MatrixQueryPlanner
from .registry import (
    DatasetArtifact,
    RenderOutcome,
    SchemaArtifact,
    VisualPipelineDefinition,
    default_json_writer,
    register_visual_pipeline,
)


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


def register_default_pipelines() -> None:
    definition = VisualPipelineDefinition(
        schema_builder=_matrix_schema_builder,
        dataset_builder=_matrix_dataset_builder,
        renderer=_matrix_renderer,
    )
    register_visual_pipeline("matrix", definition, overwrite=True)


__all__ = ["register_default_pipelines"]
