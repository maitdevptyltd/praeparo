"""Implementation of the metric dataset builder."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping, Sequence

from praeparo.dax import DaxQueryPlan
from praeparo.datasources import DataSourceConfigError, ResolvedDataSource, resolve_datasource
from praeparo.metrics import MetricDaxBuilder, load_metric_catalog
from praeparo.powerbi import PowerBIClient, PowerBISettings
from praeparo.pipeline.registry import DatasetArtifact
from praeparo.visuals.dax import expressions as dax_expressions
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
from praeparo.visuals.dax.expressions import ParsedExpression, parse_metric_expression

from .context import MetricDatasetBuilderContext, normalise_filters
from .expression_eval import evaluate_expression
from .models import MetricDatasetPlan, MetricDatasetResult, lookup_column
from .mock import MockSeriesConfig, iterate_mock_values


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
    ratio_to_ref: str | None = None


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
        ignore_placeholders: bool | None = None,
    ) -> None:
        # Resolve context eagerly so subsequent operations stay lightweight.
        # Resolve project context immediately so subsequent calls only mutate in-memory state.
        if context is None:
            self._context = MetricDatasetBuilderContext.discover(
                project_root=project_root,
                metrics_root=metrics_root,
                ignore_placeholders=bool(ignore_placeholders),
            )
            self._ignore_placeholders = self._context.ignore_placeholders
        else:
            self._context = context
            self._ignore_placeholders = (
                ignore_placeholders if ignore_placeholders is not None else context.ignore_placeholders
            )

        # Builder state: track declarative inputs until plan() compiles them into DAX.
        self._series: list[_MetricDatasetSeries] = []
        self._grain: tuple[str, ...] = ("'dim_calendar'[month]",)
        self._global_filters: list[str] = []
        self._define_blocks: list[str] = []
        self._datasource_name: str | None = self._context.default_datasource
        self._resolved_datasource: ResolvedDataSource | None = None
        self._use_mock = self._context.use_mock
        self._slug = slugify(slug or self._context.project_root.name or "metric_dataset")
        self._name_strategy = name_strategy or default_name_strategy
        self._plan_cache: MetricDatasetPlan | None = None
        self._last_result: MetricDatasetResult | None = None
        self._mock_row_count: int | None = None
        self._mock_column_values: dict[str, Sequence[object]] = {}
        self._mock_series_profiles: dict[str, MockSeriesConfig] = {}
        self._expression_cache: dict[str, dax_expressions.ParsedExpression] = {}
        self._reference_measure: dict[str, str] = {}

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
        allow_placeholder: bool | None = None,
        value_type: str | None = None,
        ratio_to: bool | str | None = None,
    ) -> "MetricDatasetBuilder":
        ratio_to_ref: str | None = None

        raw_ratio_to = getattr(ratio_to, "value", ratio_to)

        if isinstance(raw_ratio_to, bool):
            if raw_ratio_to:
                if "." not in key:
                    msg = "ratio_to=True requires a dotted metric key to infer base metric."
                    raise ValueError(msg)
                ratio_to_ref = key.rsplit(".", 1)[0]
        elif isinstance(raw_ratio_to, str):
            candidate = raw_ratio_to.strip()
            if not candidate:
                raise ValueError("ratio_to metric key cannot be empty.")
            ratio_to_ref = candidate
        elif raw_ratio_to is not None:
            raise TypeError("ratio_to must be bool, str, or None.")

        if ratio_to_ref is not None and value_type is None:
            value_type = "percent"

        identifier = self._allocate_series_id(alias or key)
        effective_allow_placeholder = allow_placeholder if allow_placeholder is not None else self._ignore_placeholders
        series = _MetricDatasetSeries(
            series_id=identifier,
            reference=key,
            label=label or alias or key,
            filters=normalise_filters(calculate),
            allow_placeholder=bool(effective_allow_placeholder),
            source="metric",
            value_type=value_type,
            ratio_to_ref=ratio_to_ref,
        )
        self._series.append(series)

        if ratio_to_ref is not None:
            self._ensure_ratio_denominator(ratio_to_ref)

        self._invalidate_plan()
        return self

    def _ensure_ratio_denominator(self, denominator_key: str) -> None:
        """Register a supporting denominator metric if it was not declared explicitly."""

        existing_metric_refs = {
            series.reference for series in self._series if series.source == "metric"
        }
        if denominator_key in existing_metric_refs:
            return

        sanitised_key = denominator_key.replace(".", "_").replace("-", "_")
        alias_candidate = f"__ratio_denom_{sanitised_key}"
        series_id = self._allocate_series_id(alias_candidate)

        supporting = _MetricDatasetSeries(
            series_id=series_id,
            reference=denominator_key,
            label=denominator_key,
            filters=(),
            allow_placeholder=bool(self._ignore_placeholders),
            source="metric",
        )
        self._series.append(supporting)

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
        effective_allow_placeholder = self._ignore_placeholders
        series = _MetricDatasetSeries(
            series_id=series_id,
            reference=identifier,
            label=label or alias or identifier,
            filters=normalise_filters(calculate),
            allow_placeholder=bool(effective_allow_placeholder),
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

    def mock_rows(self, count: int | None) -> "MetricDatasetBuilder":
        """Override the number of mock rows emitted when `use_mock(True)` is active."""

        if count is not None and count <= 0:
            raise ValueError("mock rows must be positive when provided")
        self._mock_row_count = count
        self._invalidate_plan()
        return self

    def mock_column(self, column: str, values: Sequence[object]) -> "MetricDatasetBuilder":
        """Register deterministic mock values for a grain column."""

        self._mock_column_values[column] = tuple(values)
        self._invalidate_plan()
        return self

    def mock_series(
        self,
        series_id: str,
        *,
        mean: float | None = None,
        trend: float | None = None,
        trend_range: tuple[float, float] | None = None,
        factory: str | None = None,
    ) -> "MetricDatasetBuilder":
        """Apply a mock profile to a series so pipeline visuals can control trends/means."""

        self._mock_series_profiles[series_id] = MockSeriesConfig(
            factory=factory or "count",
            mean=mean,
            trend=trend,
            trend_range=trend_range,
        )
        self._invalidate_plan()
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

    def to_dataset_artifact(
        self,
        filename: str | None = None,
    ) -> DatasetArtifact[list[dict[str, object]]]:
        """Execute the builder plan and wrap it as a DatasetArtifact.

        Python visuals can return a MetricDatasetBuilder directly; this helper
        converts the compiled plan and executed rows into the artifact shape
        expected by the visual pipeline so JSON datasets and .dax plans are
        emitted alongside other outputs.
        """

        plan = self.plan()
        rows = self.execute()

        define_block = "\n".join(plan.define_blocks) if plan.define_blocks else None
        dax_plan = DaxQueryPlan(
            statement=plan.statement,
            rows=tuple(),
            values=tuple(),
            define=define_block,
        )

        dataset_filename = filename or f"{plan.slug}.data.json"

        return DatasetArtifact(
            value=rows,
            filename=dataset_filename,
            plans=[dax_plan],
        )

    # ------------------------------------------------------------------
    # Internal helpers

    def _invalidate_plan(self) -> None:
        self._plan_cache = None
        self._last_result = None
        self._expression_cache.clear()
        self._reference_measure.clear()

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

        reference_to_series_id: dict[str, str] = {
            series.reference: series.series_id for series in self._series if series.source == "metric"
        }
        for series in self._series:
            if series.ratio_to_ref and series.ratio_to_ref not in reference_to_series_id:
                msg = (
                    f"Metric '{series.reference}' declares ratio_to='{series.ratio_to_ref}' "
                    "but no matching denominator metric was added to this builder."
                )
                raise ValueError(msg)

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
            if series.source == "expression" and series.expression:
                # Cache the parsed AST so the mock evaluator can reuse it without reparsing.
                try:
                    self._expression_cache[series.series_id] = dax_expressions.parse_metric_expression(series.expression)
                except Exception:  # pragma: no cover - validation handled earlier
                    # Drop any stale entry so failed parses don't linger between plan rebuilds.
                    self._expression_cache.pop(series.series_id, None)
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
            self._reference_measure[series.reference] = measure_name

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

        mock_values = {column: tuple(values) for column, values in self._mock_column_values.items()} or None
        row_count = self._mock_row_count

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
            mock_rows=row_count,
            mock_values=mock_values,
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

    def _build_mock_rows(self, plan: MetricDatasetPlan) -> list[dict[str, object]]:
        # Simple deterministic mock payload so notebooks/tests can run without Power BI access.
        mock_count = plan.mock_rows or self._mock_row_count or 4
        rows: list[dict[str, object]] = []
        series_profiles: dict[str, MockSeriesConfig] = {}
        for series_id in plan.series_order:
            series_profiles[series_id] = self._mock_series_profiles.get(series_id, MockSeriesConfig())

        column_values = plan.mock_values or self._mock_column_values or {}

        # Generate base mock rows using series-level hints, then layer expression values on top.
        for record in iterate_mock_values(
            count=mock_count,
            columns=plan.grain_columns,
            column_values=column_values,
            measure_map=plan.measure_map,
            series_mocks=series_profiles,
        ):
            rows.append(record)
        self._apply_expression_mocks(rows, plan)
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

        # Apply ratio_to semantics once base metric values have been mapped into the dataset.
        reference_to_series_id = {series.reference: series.series_id for series in self._series}
        for series in self._series:
            if not series.ratio_to_ref:
                continue

            numerator_id = series.series_id
            denominator_id = reference_to_series_id.get(series.ratio_to_ref)
            if not denominator_id:
                continue  # Safeguard; upstream validation should prevent this path.

            for record in normalised:
                numerator_value = record.get(numerator_id)
                denominator_value = record.get(denominator_id)

                if not isinstance(numerator_value, (int, float)) or not isinstance(denominator_value, (int, float)):
                    record[numerator_id] = None
                    continue
                if denominator_value == 0:
                    record[numerator_id] = None
                    continue

                record[numerator_id] = float(numerator_value) / float(denominator_value)
        return normalised

    def _apply_expression_mocks(
        self,
        rows: list[dict[str, object]],
        plan: MetricDatasetPlan,
    ) -> None:
        """Recompute expression-driven series so mock datasets mirror live behaviour.

        Mock generation happens in two stages: (1) emit deterministic values for each base metric
        via `iterate_mock_values`, and (2) replay every expression using the cached AST so derived
        series (ratios, shares, etc.) stay consistent with those base values. Skipping this second
        pass would leave expression series pegged at zero whenever mocks are enabled.
        """

        if not self._expression_cache:
            return

        for series in self._series:
            if series.source != "expression":
                continue
            parsed = self._expression_cache.get(series.series_id)
            measure_name = plan.measure_map.get(series.series_id)
            if parsed is None or measure_name is None:
                continue
            for row in rows:
                substitutions: dict[str, float] = {}
                for reference, measure in self._reference_measure.items():
                    value = row.get(measure)
                    if isinstance(value, (int, float)):
                        substitutions[reference] = float(value)
                row[measure_name] = evaluate_expression(parsed, substitutions)


__all__ = ["MetricDatasetBuilder"]
