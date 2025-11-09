"""Implementation of the metric dataset builder."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from praeparo.datasources import DataSourceConfigError, ResolvedDataSource, resolve_datasource
from praeparo.metrics import MetricDaxBuilder, load_metric_catalog
from praeparo.powerbi import PowerBIClient, PowerBISettings
from praeparo.visuals.dax import (
    DEFAULT_MEASURE_TABLE,
    MetricCompilationCache,
    combine_filter_groups,
    generate_measure_names,
    normalise_define_blocks,
    render_visual_plan,
    resolve_expression_metric,
    resolve_metric_reference,
    slugify,
    split_metric_identifier,
    wrap_expression_with_filters,
)
from praeparo.visuals.dax.planner_core import MeasurePlan, NameStrategy, VisualPlan, default_name_strategy

from .context import MetricDatasetBuilderContext, normalise_filters
from .models import MetricDatasetPlan, MetricDatasetResult, lookup_column


@dataclass
class _MetricDatasetSeries:
    """Internal description of each metric/expression added to the builder."""

    series_id: str
    reference: str
    label: str
    filters: tuple[str, ...]
    allow_placeholder: bool
    source: str
    expression: str | None = None
    value_type: str | None = None


class MetricDatasetBuilder:
    """Fluent API for composing and executing metric-backed datasets."""

    def __init__(
        self,
        context: MetricDatasetBuilderContext | None = None,
        *,
        project_root: str | Path | None = None,
        metrics_root: str | Path | None = None,
        slug: str | None = None,
        name_strategy: NameStrategy | None = None,
    ) -> None:
        # Resolve context eagerly so subsequent operations stay lightweight.
        # Resolve project context immediately so subsequent calls only mutate in-memory state.
        self._context = context or MetricDatasetBuilderContext.discover(
            project_root=project_root,
            metrics_root=metrics_root,
        )

        # Builder state: track declarative inputs until plan() compiles them into DAX.
        self._series: list[_MetricDatasetSeries] = []
        self._grain: tuple[str, ...] = ("'dim_calendar'[Month]",)
        self._global_filters: list[str] = []
        self._define_blocks: list[str] = []
        self._datasource_name: str | None = self._context.default_datasource
        self._resolved_datasource: ResolvedDataSource | None = None
        self._use_mock = self._context.use_mock
        self._ignore_placeholders = self._context.ignore_placeholders
        self._slug = slugify(slug or self._context.project_root.name or "metric_dataset")
        self._name_strategy = name_strategy or default_name_strategy
        self._plan_cache: MetricDatasetPlan | None = None
        self._last_result: MetricDatasetResult | None = None

    # ------------------------------------------------------------------
    # Fluent configuration surface: mutate state without triggering I/O.

    def grain(self, *columns: str) -> "MetricDatasetBuilder":
        self._grain = tuple(str(column).strip() for column in columns if column) or self._grain
        self._invalidate_plan()
        return self

    def metric(
        self,
        key: str,
        *,
        alias: str | None = None,
        label: str | None = None,
        calculate: Sequence[str] | str | None = None,
        allow_placeholder: bool = False,
        value_type: str | None = None,
    ) -> "MetricDatasetBuilder":
        identifier = self._allocate_series_id(alias or key)
        series = _MetricDatasetSeries(
            series_id=identifier,
            reference=key,
            label=label or alias or key,
            filters=normalise_filters(calculate),
            allow_placeholder=allow_placeholder,
            source="metric",
            value_type=value_type,
        )
        self._series.append(series)
        self._invalidate_plan()
        return self

    def expression(
        self,
        identifier: str,
        expression: str,
        *,
        alias: str | None = None,
        label: str | None = None,
        calculate: Sequence[str] | str | None = None,
        value_type: str | None = None,
    ) -> "MetricDatasetBuilder":
        series_id = self._allocate_series_id(alias or identifier)
        series = _MetricDatasetSeries(
            series_id=series_id,
            reference=identifier,
            label=label or alias or identifier,
            filters=normalise_filters(calculate),
            allow_placeholder=False,
            source="expression",
            expression=expression,
            value_type=value_type,
        )
        self._series.append(series)
        self._invalidate_plan()
        return self

    def calculate(self, filters: Sequence[str] | str | None) -> "MetricDatasetBuilder":
        self._global_filters.extend(normalise_filters(filters))
        self._invalidate_plan()
        return self

    def define(self, blocks: Sequence[str] | str | None) -> "MetricDatasetBuilder":
        self._define_blocks.extend(normalise_define_blocks(blocks))
        self._invalidate_plan()
        return self

    def datasource(self, name: str | None) -> "MetricDatasetBuilder":
        self._datasource_name = name
        self._resolved_datasource = None
        return self

    def with_datasource(self, datasource: ResolvedDataSource | None) -> "MetricDatasetBuilder":
        self._resolved_datasource = datasource
        return self

    def use_mock(self, flag: bool = True) -> "MetricDatasetBuilder":
        self._use_mock = flag
        return self

    def name_strategy(self, strategy: NameStrategy) -> "MetricDatasetBuilder":
        self._name_strategy = strategy
        self._invalidate_plan()
        return self

    def slug(self, value: str) -> "MetricDatasetBuilder":
        self._slug = slugify(value)
        self._invalidate_plan()
        return self

    # ------------------------------------------------------------------
    # Planning and execution

    def plan(self) -> MetricDatasetPlan:
        if self._plan_cache is None:
            self._plan_cache = self._build_plan()
        return self._plan_cache

    def render(self) -> str:
        return self.plan().statement

    def execute(self) -> list[dict[str, object]]:
        try:
            result = asyncio.run(self.aexecute())
        except RuntimeError as exc:  # pragma: no cover
            msg = (
                "MetricDatasetBuilder.execute() cannot run inside an active event loop; "
                "call .aexecute() instead."
            )
            raise RuntimeError(msg) from exc
        return result.rows

    async def aexecute(self) -> MetricDatasetResult:
        plan = self.plan()
        datasource = self._resolve_datasource()

        # Execute the plan against either mock data or Power BI depending on context.
        start = time.perf_counter()
        if self._use_mock or datasource.type == "mock":
            raw_rows = self._build_mock_rows(plan)
        else:
            raw_rows = await self._execute_powerbi(plan, datasource)
        execution_time = time.perf_counter() - start

        # Cache the normalised result so `.to_df()` can reuse it without rerunning DAX.
        rows = self._normalise_rows(raw_rows, plan)
        result = MetricDatasetResult(
            rows=rows,
            raw_rows=tuple(raw_rows),
            measure_map=dict(plan.measure_map),
            placeholders=plan.placeholders,
            datasource=datasource,
            execution_time=execution_time,
            plan=plan,
        )
        self._last_result = result
        return result

    def to_df(self):  # pragma: no cover - convenience wrapper
        if not self._last_result:
            self.execute()
        assert self._last_result is not None
        return self._last_result.to_dataframe()

    async def ato_df(self):  # pragma: no cover
        result = await self.aexecute()
        return result.to_dataframe()

    # ------------------------------------------------------------------
    # Internal helpers

    def _invalidate_plan(self) -> None:
        self._plan_cache = None
        self._last_result = None

    def _allocate_series_id(self, preferred: str) -> str:
        candidate = preferred or f"series_{len(self._series) + 1}"
        existing = {series.series_id for series in self._series}
        if candidate not in existing:
            return candidate
        suffix = 2
        while f"{candidate}_{suffix}" in existing:
            suffix += 1
        return f"{candidate}_{suffix}"

    def _build_plan(self) -> MetricDatasetPlan:
        if not self._series:
            raise ValueError("MetricDatasetBuilder requires at least one metric or expression.")

        # Load the metric catalog once and reuse a compilation cache to avoid redundant work.
        catalog = load_metric_catalog([self._context.metrics_root])
        builder = MetricDaxBuilder(catalog)
        cache = MetricCompilationCache()

        placeholders: list[str] = []
        measure_references: list[str] = []
        measure_plans: list[MeasurePlan] = []
        measure_map: dict[str, str] = {}

        for series in self._series:
            resolved_reference, expression = self._resolve_expression(series, builder, cache, placeholders)
            measure_references.append(resolved_reference)
            measure_plans.append(
                MeasurePlan(
                    reference=resolved_reference,
                    measure_name="",
                    expression=expression,
                    display_name=series.label,
                    metric_filters=series.filters,
                    group_filters=(),
                )
            )

        measure_names = generate_measure_names(
            measure_references,
            visual_slug=self._slug,
            name_strategy=self._name_strategy,
        )

        populated_measures: list[MeasurePlan] = []
        for plan_entry, measure_name, series in zip(measure_plans, measure_names, self._series):
            populated = MeasurePlan(
                reference=plan_entry.reference,
                measure_name=measure_name,
                expression=plan_entry.expression,
                display_name=plan_entry.display_name,
                metric_filters=plan_entry.metric_filters,
                group_filters=plan_entry.group_filters,
            )
            populated_measures.append(populated)
            measure_map[series.series_id] = measure_name

        global_filters = combine_filter_groups(self._context.global_filters, self._global_filters)
        define_blocks = tuple(self._define_blocks) + tuple(self._context.define_blocks)
        grain_columns = self._grain
        measure_table = self._context.measure_table or DEFAULT_MEASURE_TABLE

        # Assemble the canonical VisualPlan shared with YAML planners, then render DAX.
        visual_plan = VisualPlan(
            slug=self._slug,
            measures=tuple(populated_measures),
            grain_columns=grain_columns,
            define_blocks=tuple(normalise_define_blocks(define_blocks)),
            global_filters=global_filters,
            placeholders=tuple(placeholders),
        )
        statement = render_visual_plan(visual_plan, measure_table=measure_table)

        return MetricDatasetPlan(
            slug=self._slug,
            measures=visual_plan.measures,
            measure_map=dict(measure_map),
            series_order=tuple(series.series_id for series in self._series),
            grain_columns=grain_columns,
            define_blocks=visual_plan.define_blocks,
            global_filters=global_filters,
            placeholders=visual_plan.placeholders,
            statement=statement,
            measure_table=measure_table,
        )

    def _resolve_expression(
        self,
        series: _MetricDatasetSeries,
        builder: MetricDaxBuilder,
        cache: MetricCompilationCache,
        placeholders: list[str],
    ) -> tuple[str, str]:
        try:
            if series.source == "expression":
                assert series.expression is not None
                definition = resolve_expression_metric(
                    metric_key=series.reference,
                    expression=series.expression,
                    builder=builder,
                    cache=cache,
                    label=series.label,
                    value_type=series.value_type or "number",
                )
                base_expression = definition.expression
                resolved_reference = series.reference
            else:
                base_key, variant_path = split_metric_identifier(series.reference)
                resolved_reference, definition = resolve_metric_reference(
                    builder=builder,
                    cache=cache,
                    metric_key=base_key,
                    variant_path=variant_path,
                )
                base_expression = definition.expression
        except (KeyError, ValueError):
            if not (series.allow_placeholder or self._ignore_placeholders):
                raise
            placeholders.append(series.series_id)
            base_expression = "0"
            resolved_reference = series.reference

        wrapped = wrap_expression_with_filters(base_expression, series.filters) if series.filters else base_expression
        return resolved_reference, wrapped

    def _resolve_datasource(self) -> ResolvedDataSource:
        if self._resolved_datasource is not None:
            return self._resolved_datasource

        # Datasource discovery mirrors cartesian planners: honour explicit overrides first.
        reference = self._datasource_name or self._context.default_datasource
        dummy_visual_path = self._context.project_root / "metric_dataset_builder.yaml"
        datasource = resolve_datasource(reference, visual_path=dummy_visual_path)
        self._resolved_datasource = datasource
        return datasource

    async def _execute_powerbi(
        self,
        plan: MetricDatasetPlan,
        datasource: ResolvedDataSource,
    ) -> list[Mapping[str, object]]:
        dataset_id = datasource.dataset_id
        if not dataset_id:
            msg = f"Data source '{datasource.name}' missing dataset_id; cannot execute plan."
            raise DataSourceConfigError(msg)

        # Power BI client handles auth + transport; we simply await the row payload.
        settings = datasource.settings or PowerBISettings.from_env()
        async with PowerBIClient(settings) as client:
            rows = await client.execute_dax(dataset_id, plan.statement, group_id=datasource.workspace_id)
        return list(rows)

    def _build_mock_rows(self, plan: MetricDatasetPlan) -> list[Mapping[str, object]]:
        # Simple deterministic mock payload so notebooks/tests can run without Power BI access.
        rows: list[Mapping[str, object]] = []
        for index in range(1, 5):
            record: dict[str, object] = {}
            for column in plan.grain_columns or ("__row__",):
                record[column] = f"{column}:{index}"
            for measure_name in plan.measure_map.values():
                record[measure_name] = float(index * 100)
            rows.append(record)
        return rows

    def _normalise_rows(
        self,
        raw_rows: Sequence[Mapping[str, object]],
        plan: MetricDatasetPlan,
    ) -> list[dict[str, object]]:
        # Re-shape raw DAX rows into user-friendly records keyed by series ids.
        normalised: list[dict[str, object]] = []
        for raw in raw_rows:
            record: dict[str, object] = {}
            for column in plan.grain_columns:
                record[column] = lookup_column(raw, column)
            for series_id, measure_name in plan.measure_map.items():
                record[series_id] = raw.get(measure_name)
            normalised.append(record)
        return normalised


__all__ = ["MetricDatasetBuilder"]
