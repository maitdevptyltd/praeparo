"""Cartesian chart planner backed by the metric DAX engine."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Mapping, Sequence

from praeparo.data import ChartResultSet, mock_chart_data, powerbi_chart_data
from praeparo.dax import DaxQueryPlan
from praeparo.datasources import DataSourceConfigError, ResolvedDataSource, resolve_datasource
from praeparo.metrics import MetricDaxBuilder, load_metric_catalog
from praeparo.models import CartesianChartConfig
from praeparo.visuals.dax import (
    MetricCompilationCache,
    combine_filter_groups,
    generate_measure_names,
    normalise_define_blocks,
    normalise_filter_group,
    render_visual_plan,
    resolve_expression_metric,
    resolve_metric_reference,
    slugify,
    split_metric_identifier,
    wrap_expression_with_filters,
    DEFAULT_MEASURE_TABLE,
)
from praeparo.visuals.dax.planner_core import MeasurePlan, VisualPlan

from .base import ChartPlannerResult, ChartQueryPlanner

if __name__ == "__main__":  # pragma: no cover - module import guard
    raise SystemExit("This module is intended to be imported, not executed directly.")


@dataclass
class _SeriesCandidate:
    series_id: str
    reference: str
    display_name: str
    expression: str
    metric_filters: tuple[str, ...]
    group_filters: tuple[str, ...]
    placeholder: bool = False


class DaxBackedChartPlanner(ChartQueryPlanner):
    """Plans cartesian visuals by delegating metric compilation to the DAX builder."""

    def __init__(
        self,
        *,
        datasource_resolver: Callable[[str | None, Path], ResolvedDataSource] | None = None,
        mock_provider: Callable[[CartesianChartConfig, Mapping[str, str]], ChartResultSet] = mock_chart_data,
    ) -> None:
        self._mock_provider = mock_provider
        if datasource_resolver is None:
            def _default_resolver(reference: str | None, visual_path: Path) -> ResolvedDataSource:
                return resolve_datasource(reference, visual_path=visual_path)

            self._resolve_datasource = _default_resolver
        else:
            self._resolve_datasource = datasource_resolver

    def plan(self, config: CartesianChartConfig, *, context) -> ChartPlannerResult:  # type: ignore[override]
        metadata = context.options.metadata
        raw_metrics_root = metadata.get("metrics_root")
        if isinstance(raw_metrics_root, (str, Path)):
            metrics_root = Path(raw_metrics_root)
        else:
            metrics_root = Path("registry/metrics")
        catalog = load_metric_catalog([metrics_root])
        builder = MetricDaxBuilder(catalog)
        cache = MetricCompilationCache()

        ignore_placeholders = bool(metadata.get("ignore_placeholders", False))
        context_payload = metadata.get("context") if isinstance(metadata.get("context"), Mapping) else {}
        if isinstance(context_payload, Mapping):
            context_filters = context_payload.get("calculate")
            context_define = context_payload.get("define")
        else:
            context_filters = None
            context_define = None

        if not isinstance(context_filters, (str, Sequence)):
            context_filters = None
        if not isinstance(context_define, (str, Sequence)):
            context_define = None

        visual_slug = slugify(config.title or config.description or "cartesian")

        candidates: list[_SeriesCandidate] = []
        placeholders: list[str] = []

        for series in config.series:
            metric_config = series.metric
            reference = metric_config.key or series.id
            display_name = series.label or metric_config.label or reference
            metric_filters = normalise_filter_group(metric_config.calculate)

            try:
                if metric_config.expression:
                    definition = resolve_expression_metric(
                        metric_key=metric_config.key or series.id,
                        expression=metric_config.expression,
                        builder=builder,
                        cache=cache,
                        label=metric_config.label or series.label,
                    )
                    base_expression = definition.expression
                else:
                    base_key, variant_path = split_metric_identifier(metric_config.key)
                    reference, definition = resolve_metric_reference(
                        builder=builder,
                        cache=cache,
                        metric_key=base_key,
                        variant_path=variant_path,
                    )
                    base_expression = definition.expression
            except (KeyError, ValueError):
                if not ignore_placeholders:
                    raise
                placeholders.append(metric_config.key or series.id)
                candidates.append(
                    _SeriesCandidate(
                        series_id=series.id,
                        reference=metric_config.key or series.id,
                        display_name=display_name,
                        expression="0",
                        metric_filters=metric_filters,
                        group_filters=(),
                        placeholder=True,
                    )
                )
                continue

            expression = base_expression
            if metric_filters:
                expression = wrap_expression_with_filters(expression, metric_filters)

            candidates.append(
                _SeriesCandidate(
                    series_id=series.id,
                    reference=reference,
                    display_name=display_name,
                    expression=expression,
                    metric_filters=metric_filters,
                    group_filters=(),
                )
            )

        measure_names = generate_measure_names(
            [candidate.reference for candidate in candidates],
            visual_slug=visual_slug,
        )

        measure_plans: list[MeasurePlan] = []
        measure_map: dict[str, str] = {}
        for candidate, measure_name in zip(candidates, measure_names):
            measure_plans.append(
                MeasurePlan(
                    reference=candidate.reference,
                    measure_name=measure_name,
                    expression=candidate.expression,
                    display_name=candidate.display_name,
                    metric_filters=candidate.metric_filters,
                    group_filters=candidate.group_filters,
                )
            )
            measure_map[candidate.series_id] = measure_name

        grain_override = metadata.get("grain")
        if isinstance(grain_override, str):
            grain_columns = (grain_override,)
        elif isinstance(grain_override, Sequence):
            grain_columns = tuple(grain_override)
        else:
            grain_columns = (config.category.field,)

        global_filters = combine_filter_groups(config.calculate, context_filters)

        define_blocks = list(normalise_define_blocks(config.define))
        if context_define:
            define_blocks.extend(normalise_define_blocks(context_define))

        visual_plan = VisualPlan(
            slug=visual_slug,
            measures=tuple(measure_plans),
            grain_columns=grain_columns,
            define_blocks=tuple(define_blocks),
            global_filters=global_filters,
            placeholders=tuple(placeholders),
        )

        measure_table = metadata.get("measure_table")
        if not isinstance(measure_table, str) or not measure_table.strip():
            measure_table = DEFAULT_MEASURE_TABLE

        statement = render_visual_plan(
            visual_plan,
            measure_table=measure_table,
        )

        plan = DaxQueryPlan(
            statement=statement,
            rows=tuple(),
            values=tuple(item.measure_name for item in measure_plans),
            define=None,
        )

        dataset = self._resolve_dataset(config, plan, measure_map, context)

        return ChartPlannerResult(
            plan=plan,
            dataset=dataset,
            measure_map=measure_map,
            placeholders=tuple(placeholders),
        )

    def _resolve_dataset(
        self,
        config: CartesianChartConfig,
        plan: DaxQueryPlan,
        measure_map: Mapping[str, str],
        context,
    ) -> ChartResultSet:
        data_options = context.options.data
        dataset_override = getattr(data_options, "dataset_id", None)
        workspace_override = getattr(data_options, "workspace_id", None)
        provider_key = self._resolve_provider_key(context, data_options)

        if dataset_override:
            result = powerbi_chart_data(
                config,
                plan,
                measure_map=measure_map,
                dataset_id=dataset_override,
                group_id=workspace_override,
            )
            return self._resolve_result(result)

        if provider_key == "mock":
            return self._mock_provider(config, measure_map)

        return self._execute_from_datasource(config, plan, measure_map, context, data_options)

    def _execute_from_datasource(
        self,
        config: CartesianChartConfig,
        plan: DaxQueryPlan,
        measure_map: Mapping[str, str],
        context,
        data_options,
    ) -> ChartResultSet:
        reference = getattr(data_options, "datasource_override", None) or config.datasource
        visual_path = context.config_path
        if visual_path is None:
            msg = "Cartesian execution requires a config_path to resolve datasources."
            raise DataSourceConfigError(msg)

        datasource = self._resolve_datasource(reference, visual_path)
        if datasource.type == "mock":
            return self._mock_provider(config, measure_map)

        dataset_id = datasource.dataset_id
        if not dataset_id:
            title = config.title or "cartesian"
            msg = f"Data source '{datasource.name}' for {title} lacks a dataset_id."
            raise DataSourceConfigError(msg)

        result = powerbi_chart_data(
            config,
            plan,
            measure_map=measure_map,
            dataset_id=dataset_id,
            group_id=datasource.workspace_id,
            settings=datasource.settings,
        )
        return self._resolve_result(result)

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

    def _resolve_result(
        self,
        result: ChartResultSet | Awaitable[ChartResultSet],
    ) -> ChartResultSet:
        if inspect.isawaitable(result):
            try:
                resolved = asyncio.run(result)  # type: ignore[arg-type]
            except RuntimeError as exc:  # pragma: no cover
                msg = (
                    "DAX execution returned an awaitable while an event loop is already running. "
                    "Provide a synchronous client or adapt the call site to handle async planners."
                )
                raise RuntimeError(msg) from exc
        else:
            resolved = result
        if not isinstance(resolved, ChartResultSet):
            msg = "DAX execution client must return a ChartResultSet."
            raise TypeError(msg)
        return resolved


__all__ = ["DaxBackedChartPlanner"]
