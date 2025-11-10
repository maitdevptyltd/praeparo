"""Cartesian chart planner backed by the metric dataset builder."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Mapping, Sequence

from praeparo.data import ChartResultSet
from praeparo.datasets import MetricDatasetBuilder, MetricDatasetBuilderContext
from praeparo.datasets.models import MetricDatasetPlan
from praeparo.datasets.context import normalise_filters
from praeparo.dax import DaxQueryPlan
from praeparo.datasources import DataSourceConfigError, ResolvedDataSource, resolve_datasource
from praeparo.models import CartesianChartConfig
from praeparo.visuals.dax import DEFAULT_MEASURE_TABLE, slugify

from .base import ChartPlannerResult, ChartQueryPlanner

if __name__ == "__main__":  # pragma: no cover - module import guard
    raise SystemExit("This module is intended to be imported, not executed directly.")


class DaxBackedChartPlanner(ChartQueryPlanner):
    """Plans cartesian visuals by delegating metric compilation to the DAX builder."""

    def __init__(
        self,
        *,
        datasource_resolver: Callable[[str | None, Path], ResolvedDataSource] | None = None,
    ) -> None:
        if datasource_resolver is None:
            def _default_resolver(reference: str | None, visual_path: Path) -> ResolvedDataSource:
                return resolve_datasource(reference, visual_path=visual_path)

            self._resolve_datasource = _default_resolver
        else:
            self._resolve_datasource = datasource_resolver

    def plan(self, config: CartesianChartConfig, *, context) -> ChartPlannerResult:  # type: ignore[override]
        # Delegate DAX generation to the shared metric dataset builder so cartesian visuals
        # and notebooks stay in lockstep.
        builder, dataset_plan = self._configure_builder(config, context)

        dax_plan = DaxQueryPlan(
            statement=dataset_plan.statement,
            rows=tuple(),
            values=tuple(dataset_plan.measure_map.get(series.id, series.id) for series in config.series),
            define=None,
        )

        dataset = self._resolve_dataset(config, builder, context)

        return ChartPlannerResult(
            plan=dax_plan,
            dataset=dataset,
            measure_map=dict(dataset_plan.measure_map),
            placeholders=dataset_plan.placeholders,
        )

    def _configure_builder(
        self,
        config: CartesianChartConfig,
        context,
    ) -> tuple[MetricDatasetBuilder, MetricDatasetPlan]:
        metadata = context.options.metadata

        # Resolve builder context (metrics root, project root, optional overrides).
        raw_metrics_root = metadata.get("metrics_root")
        if isinstance(raw_metrics_root, (str, Path)):
            metrics_root = Path(raw_metrics_root)
        else:
            metrics_root = Path("registry/metrics")

        project_root: Path
        if context.project_root is not None:
            project_root = context.project_root
        elif context.config_path is not None:
            project_root = context.config_path.parent
        else:
            project_root = Path.cwd()

        metrics_root = metrics_root.expanduser().resolve(strict=False)

        ignore_placeholders = bool(metadata.get("ignore_placeholders", False))
        context_payload = metadata.get("context") if isinstance(metadata.get("context"), Mapping) else {}
        context_filters = context_payload.get("calculate") if isinstance(context_payload, Mapping) else None
        context_define = context_payload.get("define") if isinstance(context_payload, Mapping) else None

        calculate_filters = context_filters if isinstance(context_filters, (str, Sequence)) else None
        define_blocks = context_define if isinstance(context_define, (str, Sequence)) else None

        measure_table = metadata.get("measure_table")
        if not isinstance(measure_table, str) or not measure_table.strip():
            measure_table = DEFAULT_MEASURE_TABLE

        visual_slug = slugify(config.title or config.description or "cartesian")
        # Configure a builder that mirrors the planner's slug, filters, and measure table.
        builder_context = MetricDatasetBuilderContext.discover(
            project_root=project_root,
            metrics_root=metrics_root,
            measure_table=measure_table,
            ignore_placeholders=ignore_placeholders,
            calculate=calculate_filters,
            define=define_blocks,
        )
        builder = MetricDatasetBuilder(builder_context, slug=visual_slug)

        # Harvest grain/filters from metadata + visual definition before compiling.
        grain_override = metadata.get("grain")
        if isinstance(grain_override, str):
            grain_columns = (grain_override,)
        elif isinstance(grain_override, Sequence):
            grain_columns = tuple(grain_override)
        else:
            grain_columns = (config.category.field,)
        builder.grain(*grain_columns)

        builder.calculate(config.calculate)
        builder.define(config.define)

        mock_values = getattr(config.category, "mock_values", None)
        if mock_values:
            builder.mock_column(config.category.field, tuple(mock_values))
            builder.mock_rows(len(mock_values))

        # Translate each visual series into either a builder metric or expression.
        for series in config.series:
            metric_config = series.metric
            display_label = series.label or metric_config.label or series.id
            calculate = normalise_filters(metric_config.calculate)

            if metric_config.mock:
                builder.mock_series(
                    series.id,
                    mean=metric_config.mock.mean,
                    trend=metric_config.mock.trend,
                    trend_range=metric_config.mock.trend_range,
                    factory=metric_config.mock.factory,
                )

            if metric_config.expression:
                identifier = metric_config.key or series.id
                builder.expression(
                    identifier,
                    metric_config.expression,
                    alias=series.id,
                    label=display_label,
                    calculate=calculate,
                )
            else:
                key = metric_config.key or series.id
                builder.metric(
                    key,
                    alias=series.id,
                    label=display_label,
                    calculate=calculate,
                )

        dataset_plan = builder.plan()
        return builder, dataset_plan

    def _resolve_dataset(
        self,
        config: CartesianChartConfig,
        builder: MetricDatasetBuilder,
        context,
    ) -> ChartResultSet:
        data_options = context.options.data
        dataset_override = getattr(data_options, "dataset_id", None)
        workspace_override = getattr(data_options, "workspace_id", None)
        datasource_override = getattr(data_options, "datasource_override", None)
        provider_key = self._resolve_provider_key(context, data_options)

        if dataset_override:
            override = ResolvedDataSource(
                name="pipeline_override",
                type="powerbi",
                dataset_id=dataset_override,
                workspace_id=workspace_override,
            )
            builder.with_datasource(override)
        elif datasource_override:
            builder.with_datasource(self._resolve_datasource_override(datasource_override, context))
        elif getattr(config, "datasource", None):
            builder.with_datasource(self._resolve_datasource_override(config.datasource, context))

        if provider_key == "mock":
            builder.use_mock(True)

        dataset_result = asyncio.run(builder.aexecute())
        return dataset_result.to_chart_result(config)

    def _resolve_provider_key(self, context, data_options) -> str | None:
        case_key = context.case_key
        overrides = getattr(data_options, "provider_case_overrides", {}) or {}
        if case_key and case_key in overrides:
            candidate = overrides[case_key].strip().lower()
            if candidate:
                return candidate
        provider_key = getattr(data_options, "provider_key", None)
        if provider_key:
            candidate = provider_key.strip().lower()
            if candidate:
                return candidate
        return None

    def _resolve_datasource_override(self, reference: str | None, context) -> ResolvedDataSource:
        if reference is None:
            msg = "Datasource override cannot be empty."
            raise DataSourceConfigError(msg)

        visual_path = context.config_path
        if visual_path is None:
            msg = "Cartesian execution requires a config_path to resolve datasources."
            raise DataSourceConfigError(msg)

        return self._resolve_datasource(reference, visual_path)

__all__ = ["DaxBackedChartPlanner"]
