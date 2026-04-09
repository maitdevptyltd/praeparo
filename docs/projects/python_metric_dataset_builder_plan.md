# Metric Dataset Builder & Notebook API — Design Plan

## Summary

Praeparo currently requires YAML visuals plus the `DaxBackedChartPlanner` to turn registry metrics into datasets. Iterating on bespoke visuals (for example Plotly notebooks) means authors must either reimplement planner logic or hand-write DAX. This design introduces a code-first `MetricDatasetBuilder` that reuses the metric catalog, compilation cache, and datasource resolution stack so notebook experiments stay aligned with production YAML visuals.

The builder exposes a fluent API for adding metrics, inline expressions, shared filters, and grain columns, then renders the same `SUMMARIZECOLUMNS` query produced by the existing planners. Callers can synchronously fetch tabular results (`list[dict[str, object]]`) via `.execute()`, run async workloads with `.aexecute()`, and convert results to pandas either synchronously via `.to_df()` or asynchronously with `await .ato_df()`.

## Goals

- Reuse Praeparo’s metric catalog, DAX compilation, and datasource resolution inside notebooks or other Python hosts.
- Decouple chart configuration from DAX planning so YAML planners and code-first clients share a single implementation.
- Provide both synchronous (`execute`, `to_df`) and asynchronous (`aexecute`, `ato_df`) execution paths. `.execute()` should return `list[dict]` by default, `.to_df()` should return a pandas DataFrame synchronously (when pandas is available), and `.ato_df()` should offer the awaitable equivalent.
- Auto-detect datasources and registry paths using the existing `datasources/*.yaml` conventions, while allowing explicit overrides for advanced scenarios.
- Land the builder upstream in Praeparo first so downstream repos simply bump the submodule.

## Non-Goals

- Replacing YAML visuals or the CLI. The builder complements them for exploratory/developer use.
- Implementing new datasource types. We rely on the existing `resolve_datasource` contract.
- Shipping Plotly bindings inside Praeparo. Examples may show Plotly usage, but the core API stays framework-agnostic.

## Background & Current State

- Metric DAX compilation (`MetricDaxBuilder`, `MetricCompilationCache`) already turns YAML metrics/variants into reusable DAX expressions.
- `DaxBackedChartPlanner` (cartesian) mixes metric compilation, measure naming, visual metadata, datasource resolution, and dataset execution inside a single method, which makes it hard to reuse outside YAML visuals.
- Developers experimenting in notebooks need to read YAML visuals or cut/paste DAX statements, slowing iteration and inviting drift from the canonical metric registry.

## Proposed Architecture

### Builder Lifecycle

1. **Context setup** — `MetricDatasetBuilderContext.discover(...)` resolves the metrics root (`registry/metrics`), datasource search roots (project folder, repo root), and optional execution metadata (case key, mock overrides). When callers instantiate `MetricDatasetBuilder()` without explicitly passing a context, the builder performs this discovery automatically using the current working directory.
2. **Dataset creation** — `builder = MetricDatasetBuilder(context)` (or simply `MetricDatasetBuilder()` for implicit discovery) produces a dataset handle. Callers chain `.grain(...)`, `.metric(...)`, `.expression(...)`, `.calculate(...)`, etc. Each call stores declarative inputs (metric ids, inline expressions, filters).
3. **Planning** — `builder.plan()` compiles referenced metrics via `MetricDaxBuilder`, applies metric-level filters, assigns measure names via `generate_measure_names`, and creates a reusable `MetricDatasetPlan` (slug, grain columns, define blocks, measure map, placeholders).
4. **Execution** — `.execute()` (sync) or `.aexecute()` (async) render the plan through `render_visual_plan`, resolve datasources via `resolve_datasource`, and run the query using `PowerBIClient`. The result is normalised into a `MetricDatasetResult` containing `rows: list[dict[str, object]]`, `measure_map`, and metadata.
5. **Downstream consumption** — developers feed the rows into Plotly (`px.bar(result.rows, x="dim_calendar_month", y="documents_sent")`) or call `builder.to_df()` / `await builder.ato_df()` for pandas integration.

### Key Components

| Component | Responsibility |
| --- | --- |
| `MetricDatasetBuilderContext` | Holds resolved paths (metrics root, datasources root, optional default datasource), case key, metadata overrides, and mock flags. The builder can auto-create this context from the current working directory when none is provided. |
| `MetricDatasetBuilder` | Fluent API for declaring metrics, inline expressions, filters, grain, and metadata. |
| `MetricDatasetSeries` | Internal data class capturing the user-facing id, reference, label, expression, value type, and per-series filters. |
| `MetricDatasetPlan` | Immutable structure with measure plans, grain columns, define blocks, placeholders, rendered query text, and datasources hints. |
| `MetricDatasetResult` | User-facing container with `rows`, `measure_map`, placeholder info, execution metadata, and helper methods (`to_dataframe`, `to_chart_result`). |
| `DatasetDatasourceResolver` | Thin wrapper around `resolve_datasource` that also inspects project-local `datasources/*.yaml`. |

### API Surface (Draft)

```python
from praeparo.datasets import MetricDatasetBuilder, MetricDatasetBuilderContext

context = MetricDatasetBuilderContext.discover(
    project_root="projects/example_client",
    metrics_root="registry/metrics",
    datasources_root="projects/example_client/datasources",
)

dataset = (
    MetricDatasetBuilder(context)
    .grain("'dim_calendar'[Month]")
    .metric("documents_sent", label="Documents Sent")
    .metric("documents_sent.automated", alias="automated_docs", label="Automated")
    .expression("automation_share", "documents_sent.automated / documents_sent", label="Automation Share")
    .calculate(["'dim_calendar'[IsCurrent] = TRUE()"])
)

rows = dataset.execute()           # list[dict[str, object]]
df = dataset.to_df()               # pandas.DataFrame (requires pandas installed)
# Async notebooks can call:
# df_async = await dataset.ato_df()

# Tip: Calling `MetricDatasetBuilder()` with no context argument triggers the same
# discovery logic based on the current working directory. Pass a context explicitly
# when you want to override the inferred project layout.
```

Additional notes:

- `.metric()` accepts either a `str` key or a `MetricDefinition` object. Passing `allow_placeholder=True` lets notebooks keep moving when a metric is missing (mirrors `ignore_placeholders` metadata).
- `.expression()` compiles inline expressions using `resolve_expression_metric`.
- `.calculate()` (global) and per-series `calculate` reuse `normalise_filter_group`.
- `.define()` lets users append custom DEFINE blocks (e.g. DM partition hints) before rendering.
- `.datasource(name="example_powerbi")` overrides auto detection per dataset.

### Datasource Resolution

- Default behaviour mirrors the existing planner: start with dataset-level override, fall back to config-provided datasource, then `resolve_datasource(reference=None, visual_path=discrete_path)`.
- `MetricDatasetBuilderContext.discover()` takes an optional `datasource_file` parameter for notebook-only cases (e.g. `context = ...discover(datasource_file="projects/example_client/datasources/live.yaml")`).
- Manual injection points: `.with_datasource(config)` accepts a `ResolvedDataSource` instance, skipping file resolution entirely.

### Execution & Async Model

- `.execute()` returns `list[dict[str, object]]`. Under the hood it calls `asyncio.run(self.aexecute())`.
- `.aexecute()` resolves datasources and awaits `PowerBIClient.execute_dax`, returning a `MetricDatasetResult`.
- `.to_df()` runs synchronously, calling `.execute()` (or reusing cached rows) before converting to a DataFrame. If pandas is missing, it raises a descriptive error.
- `.ato_df()` is the awaitable counterpart that awaits `.aexecute()` and then returns a DataFrame.
- Mock provider parity: `.use_mock()` instructs the builder to route through `mock_chart_data` (still yields list/dict rows). Useful for offline iteration.

### Integration with YAML Planners

- Refactor `DaxBackedChartPlanner` to instantiate `MetricDatasetBuilder` internally:
  1. Builder inherits `grain` from `CartesianChartConfig.category.field`.
  2. Each `series` becomes either `.metric(...)` or `.expression(...)`.
  3. Planner-specific features (group filters, stacking metadata) remain inside the planner, but DAX/rendering is delegated to the builder.
- Benefits: notebook builder and YAML planner stay in lockstep; tests exercise one code path.

## Implementation Phases

> **Progress (Nov 7, 2025):** Phases 1–3 are now implemented upstream (`praeparo.datasets`). Planner refactor (phase 4) plus downstream docs/notebooks (phases 5–6) remain in backlog.
>
> **Progress (Dec 12, 2025):** `MetricDatasetBuilder` now auto-registers missing ratio denominators so callers can declare `ratio_to` without also adding the base metric as a plotted series.

1. **Context & Builder Scaffolding**
   - Add `praeparo/datasets/__init__.py` with context + builder classes.
   - Implement fluent API (metrics, expressions, filters, grain, metadata, datasource overrides).
   - Write unit tests for builder state transitions.
2. **Planning & Rendering**
   - Implement `MetricDatasetPlan` plus renderer integration (generate measure names, compile DAX, track placeholders).
   - Add serialization helpers for plan metadata (for logging/debugging).
3. **Execution Layer**
   - Introduce `MetricDatasetResult` with `.rows`, `.measure_map`, `.to_dataframe()`, `.to_chart_result()`.
   - Add `.execute()`, `.aexecute()`, `.to_df()`, `.ato_df()`, and `mock` hooks.
   - Ensure Q1/Q2 requirements: sync returns `list[dict]`/DataFrame, async API exported explicitly.
4. **Planner Refactor**
   - Update `DaxBackedChartPlanner` to use the builder.
   - Maintain existing behaviour (sorting, transforms) by adapting `ChartResultSet` creation logic to consume `MetricDatasetResult`.
5. **Docs & Examples**
   - Publish developer docs (see companion doc).
   - Add a notebook under `examples/` showing Plotly usage.
6. **Validation & Release**
   - Add tests (builder planning, placeholder handling, datasource overrides, async execution stubbed via mock client).
   - Run Pyright + pytest.
   - Ship upstream PR; downstream repos bump the submodule (per Q4).

## Testing Strategy

- **Unit tests** for each builder method ensuring metric references, aliasing, filter inheritance, and placeholder behaviour.
- **Integration tests** using the mock provider to assert `.execute()` and `.aexecute()` output shapes.
- **Datasource resolution tests** verifying autodetect vs manual overrides.
- **Regression tests** for `DaxBackedChartPlanner` to prove refactor keeps existing datasets identical (snapshot DAX statements & measure maps).

## Risks & Mitigations

- **Async execution inside running event loops**: mirror existing planner by raising a helpful error when `.execute()` is called from an active loop; document `.aexecute()` for async contexts.
- **Pandas dependency bloat**: keep DataFrame conversion optional and raise friendly errors if pandas is missing.
- **Metric drift between YAML and notebooks**: mitigated by reusing the shared builder and metric catalog directly.
- **Datasource ambiguity in notebooks**: discovery logic will search `datasources/` relative to the provided project root and default to mock when unresolved; provide explicit override hooks.

## Open Questions

- Should we expose a lower-level `builder.render()` that returns just the DAX statement without executing it? **Yes — include a `render()` helper so power users can inspect the DAX or feed it into other tooling without triggering execution.**
- Do we need pluggable name strategies per dataset (e.g. user-provided prefixes) or is the default slugging sufficient? **Yes — expose an optional name-strategy hook so callers can inject prefixes or alternative slug logic when needed.**
- How much metadata should `MetricDatasetResult` retain (execution time, datasource name, etc.) for notebook diagnostics? **Keep a prudent amount of metadata (execution duration, datasource id/name, measure table, placeholder list) so notebooks can log/diagnose issues without turning the result into a full trace payload.**

Feedback on the above will shape the final API before implementation begins.
