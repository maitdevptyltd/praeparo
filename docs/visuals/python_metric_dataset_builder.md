# Python Metric Dataset Builder

> **Status:** Core builder implementation is now available via `praeparo.datasets`. Planner integration remains pending while we validate the standalone API.

## Overview

The Metric Dataset Builder is a code-first companion to Praeparo’s YAML visuals. It lets notebook users (or any Python host) compose metric datasets with the same registry catalog, filters, and datasource resolution used by the CLI planners. The builder focuses on productivity:

- Chain `.metric(...)`, `.expression(...)`, `.calculate(...)`, and `.grain(...)` without touching DAX.
- Auto-detect datasources from the standard `datasources/*.yaml` files, but allow explicit overrides when needed.
- Fetch records as `list[dict[str, object]]` with `.execute()` or await `.aexecute()` for async contexts.
- Convert results to pandas via `builder.to_df()` (sync) or `await builder.ato_df()` and feed them straight into Plotly or other libraries.
- Instantiate `MetricDatasetBuilder()` with no arguments to auto-discover the project layout from the current working directory, or pass an explicit context when you need overrides.
- Call `.render()` to inspect the generated `SUMMARIZECOLUMNS` without executing the dataset.
- Use `.use_mock()` (or context discovery with `use_mock=True`) to keep notebook iterations deterministic without reaching Power BI.

## Quickstart

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
    .expression(
        "automation_share",
        "documents_sent.automated / documents_sent",
        label="Automation Share",
    )
    .calculate(["'dim_calendar'[IsCurrent] = TRUE()"])
)

rows = dataset.execute()      # list[dict[str, object]]
df = dataset.to_df()          # pandas.DataFrame (requires pandas installed)
# Async notebooks can call: df_async = await dataset.ato_df()

# Shortcut: calling `MetricDatasetBuilder()` without the `context` argument triggers
# the same discovery logic based on your current working directory.
# For CLI or pack runs, prefer passing `context.dataset_context` from the pipeline so
# flags like `--ignore-placeholders` flow into the builder automatically.
```

Feed either `rows` or `df` into Plotly:

```python
import plotly.express as px

fig = px.bar(df, x="'dim_calendar'[Month]", y="documents_sent", color="automation_share")
fig.show()
```

## Builder Lifecycle

1. **Context discovery** — `MetricDatasetBuilderContext.discover(...)` inspects the project root to locate the metric registry and datasource definitions. Instantiating the builder with no context runs the same discovery automatically using the current working directory. It mirrors how YAML visuals resolve datasources via `resolve_datasource`.
2. **Dataset declaration** — Chain builder methods to add metrics, inline expressions, filters, and grain columns. Each call simply collects metadata; no DAX runs yet.
3. **Planning** — `builder.plan()` (optional) returns a `MetricDatasetPlan` describing the generated measures, DAX statement, grain columns, measure_map, and placeholder list. YAML planners will reuse this plan under the hood.
4. **Execution** — `.execute()` (sync) returns `list[dict]`, `.aexecute()` (async) returns a `MetricDatasetResult`, `.to_df()` converts rows to a DataFrame synchronously, and `.ato_df()` offers the awaitable equivalent.

## Key Methods

| Method | Description |
| --- | --- |
| `.metric(key, *, alias=None, label=None, calculate=None, allow_placeholder=None, value_type=None, ratio_to=None)` | Adds a registry metric or variant. Filters are merged with the metric’s own inheritance chain. `allow_placeholder=None` inherits the builder/context-level `ignore_placeholders` flag (default `False`); override with `True`/`False` per series when you need to diverge. `ratio_to=True` infers the base key from the dotted metric (e.g., `metric.variant → metric`), or pass `ratio_to="base.metric"` explicitly. Denominators referenced via `ratio_to` are auto-registered if they are not already present in the builder. When `ratio_to` is set and `value_type` is omitted, the builder infers `value_type="percent"`. |
| `.expression(identifier, expression, *, label=None, value_type="number")` | Declares an inline expression built from existing metrics (`documents_sent.automated / documents_sent`). Expressions inherit the builder’s `ignore_placeholders` flag when referenced metrics are missing. |
| `.calculate(filters)` | Appends global filters (string or list) that wrap every measure via `CALCULATE`. |
| `.define(blocks)` | Adds additional DEFINE blocks rendered before SUMMARIZECOLUMNS (useful for session-level calculations). |
| `.grain(*columns)` | Overrides the SUMMARIZECOLUMNS grain (defaults to a single column). |
| `.datasource(name=None)` | Pins the datasource file/key. If omitted, the builder auto-resolves using the same logic as YAML visuals. |
| `.use_mock(flag=True)` | Forces execution through the deterministic mock provider (handy offline). |
| `.mock_rows(count)` | Overrides the number of mock grain rows emitted when mocks are enabled. |
| `.mock_column(column, values)` | Registers deterministic mock values for a grain column (e.g., month labels). |
| `.mock_series(series_id, *, mean=None, trend=None, trend_range=None, factory="count")` | Tunes mock value generation per series (counts, ratios, etc.) so stacked visuals look realistic. |
| `.plan()` | Returns the reusable `MetricDatasetPlan`. |
| `.execute()` | Synchronous convenience wrapper around `.aexecute()`. Returns `list[dict[str, object]]`. |
| `.aexecute()` | Async execution that yields a `MetricDatasetResult` (rows, measure_map, metadata). |
| `.to_df()` | Synchronous helper that returns a pandas DataFrame (imports pandas lazily). |
| `.ato_df()` | Awaitable helper returning a pandas DataFrame. |

## Ratio Metrics

Use `ratio_to` to compute simple ratios directly in the dataset without hand-written expressions:

```python
builder.metric("documents_sent", alias="documents_sent", label="Documents sent")

builder.metric(
    "documents_sent.within_4_hours",
    alias="pct_in_4h",
    label="% Sent in 4 hours",
    ratio_to=True,  # denominator inferred as "documents_sent"
)

builder.metric(
    "documents_sent.within_1_business_day_from_file_ready",
    alias="pct_in_1d",
    label="% Sent in 1 day",
    ratio_to="documents_sent",  # explicit denominator
)
```

- `ratio_to=True` infers the denominator by trimming the last segment of the dotted metric key.
- `ratio_to="<metric_key>"` uses the provided key as the denominator. If that metric was not declared as a series, the builder registers a supporting denominator automatically (still raising if the key is unknown in the registry).
- When `ratio_to` is set and `value_type` is omitted, the builder defaults to `value_type="percent"`.
- Supporting denominators are evaluated under the builder’s global context only; they do not inherit numerator-specific `calculate` filters.
- Dataset values are stored as fractions (`0–1`). Visuals can multiply by 100 when whole-number percentages are required.

## Datasource Resolution

- When `datasource(name=...)` is not called, the builder looks for a datasource definition relative to the provided project root, mirroring the current `resolve_datasource` behaviour.
- The `MetricDatasetBuilderContext.discover()` helper accepts overrides (`metrics_root`, `datasources_root`, `datasource_file`, `default_datasource`) so notebooks can opt into custom layouts.
- Advanced users can pass a `ResolvedDataSource` instance directly via `.with_datasource(resolved)` to bypass file lookup.

## Execution Modes

- **`.execute()`**: returns the raw row payload (`list[dict]`) and blocks the calling thread. Internally it calls `asyncio.run(self.aexecute())`, matching the behaviour of today’s planners.
- **`.aexecute()`**: awaitable flavour that fits naturally inside async notebooks or services. Returns a `MetricDatasetResult` (rows, measure map, placeholders, datasource metadata).
- **`.to_df()`**: synchronous helper that converts the latest rows into a DataFrame. It lazy-imports pandas and raises a descriptive error if pandas is absent.
- **`.ato_df()`**: awaitable helper that pairs with `.aexecute()` for async workflows.

## Mock Controls

Mock datasets are a first-class builder feature, mirroring what Praeparo’s YAML planners rely on when screenshots or Plotly reviews are needed. Combine the helpers below to shape the offline payload:

```python
dataset = (
    MetricDatasetBuilder()
    .grain("'dim_calendar'[Month]")
    .metric("documents_sent")
    .metric("documents_sent.manual", alias="manual")
    .use_mock(True)                    # stay offline
    .mock_rows(3)                      # emit exactly three grain rows
    .mock_column("'dim_calendar'[Month]", ["Jan-25", "Feb-25", "Mar-25"])
    .mock_series("documents_sent", mean=520, trend=35)
    .mock_series("manual", mean=480, trend=-40)
)
rows = dataset.execute()
```

- `.mock_rows(count)` keeps mock row counts stable (defaults to 4 when omitted).
- `.mock_column(column, values)` lets you feed real labels (e.g., month names) so downstream charts read naturally.
- `.mock_series(series_id, mean=..., trend=..., trend_range=(start, end))` tunes per-series value generation.

When YAML visuals define `category.mock_values` or per-series `metric.mock` blocks, the cartesian planner forwards those settings straight into the builder. Notebooks gain the same ergonomics by calling the helper methods directly.

## Plotly & pandas Integration

```python
dataset = (
    MetricDatasetBuilder(context)
    .grain("'dim_calendar'[Month]")
    .metric("documents_sent.total", alias="total")
    .metric("documents_sent.automated")
    .metric("documents_sent.manual")
)

df = dataset.to_df()
fig = px.line(df, x="'dim_calendar'[Month]", y=["documents_sent.automated", "documents_sent.manual"])
fig.update_layout(title="Documents Sent by Automation Channel")
```

Because the builder returns standard tabular data, any analytics library that understands sequences of dictionaries (or DataFrames) works out of the box.

## Placeholder Handling

- Use `allow_placeholder=True` inside `.metric(...)` for ad-hoc experiments. When `allow_placeholder` is omitted, the builder inherits the context-level `ignore_placeholders` flag (default `False`).
- Enable the global switch with either `MetricDatasetBuilder(context, ignore_placeholders=True)` or by running CLI/pack commands with `--ignore-placeholders`. Pipeline-provided contexts (including pack runs) carry this flag into Python visuals as long as you instantiate the builder with `context.dataset_context`.
- Placeholder metrics resolve to `0` and are listed under `MetricDatasetResult.placeholders`. Keep the flag off in production so missing metrics surface early.

## Relationship to YAML Visuals

- `DaxBackedChartPlanner` and future planners will internally instantiate the builder so a single code path handles DAX generation.
- Any improvements to the builder (measure naming, context filters, async execution) automatically benefit YAML visuals after the refactor.

## Roadmap

- Finalise API naming (builder class/module path) and land implementation upstream.
- Add an `examples/notebooks/metric_dataset_builder.ipynb` showing a sample automation dashboard rebuilt in Plotly.
- Update CLI docs once the planner refactor ships.
