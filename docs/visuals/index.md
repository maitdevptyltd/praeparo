# Visual Registry & Shared Models

Praeparo now exposes a small `praeparo.visuals` package that downstream
projects can use to register custom visual types without reimplementing the
plumbing that lives in the YAML loader.

## Registering a Visual Type

```python
from pathlib import Path

from praeparo.models.visual_base import BaseVisualConfig
from praeparo.visuals import VisualLoader, register_visual_type


class ComboVisual(BaseVisualConfig):
    type: str = "combo"
    dataset: str


def load_combo(path: Path, payload: dict[str, object], stack: tuple[Path, ...]) -> ComboVisual:
    return ComboVisual.model_validate(payload)


register_visual_type("combo", load_combo)
```

The registry protects against duplicate registrations. Pass `overwrite=True`
when iterating locally, but prefer the default behaviour in shared code to
guard against accidental collisions.

## Loading Definitions

```python
from praeparo.visuals import load_visual_definition

config = load_visual_definition("visuals/combo/monthly.yaml")
assert config.type == "combo"
```

`load_visual_definition` resolves relative paths, prevents circular references,
and surfaces useful error messages when a YAML document is missing a `type` or
references an unregistered visual.

## Shared Model Primitives

The package also publishes reusable Pydantic models for authoring visual YAML:

- `VisualMetricConfig`: references a metric key or inline expression and
  supports additional filters via `calculate` along with mock configuration.
- `VisualGroupConfig`: groups metrics together and applies a shared `calculate`
  block to every metric (or nested group) inside.
- `VisualMockConfig` and friends (`VisualMetricMock`,
  `VisualMetricMockScenario`, `VisualMetricMockScenarioOverride`) allow visual
  definitions to include deterministic mock data paths alongside live
  datasources.

These helpers are intentionally lightweight so downstream projects can extend
them (for example, to add governance-specific metadata) while still relying on
Praeparo’s validation and loader utilities.

When visuals need additional execution-time context (e.g. metrics roots,
scenarios, or visual-specific switches), subclass `VisualContextModel` and
register it via `context_model=` on `register_visual_type`. See
`visual_context_model.md` for the base fields and lifecycle.

For deeper implementation context (planner/provider structure, execution
clients, output handling), see the pipeline reference in
[`docs/visual_pipeline_engine.md`](../visual_pipeline_engine.md).

## Relationship to Metric Catalog

Visuals can list metric keys directly, or they can bundle them with
`MetricGroupConfig` (introduced in `praeparo.metrics`) when multiple metrics
share the same filters. The group abstraction complements `MetricDefinition`
inheritance by applying presentation-time filters without creating new metric
variants in the catalog.

Future visuals (combo charts, scorecards, etc.) should import these shared
helpers instead of duplicating calculate/mocking semantics in each repository.

## DAX Planning Helpers

When a visual needs to emit DAX, reuse the helpers under
`praeparo.visuals.dax`:

- `MetricCompilationCache` caches compiled metric plans so multiple visuals can
  reuse the same `MetricDaxBuilder` without redundant work.
- `resolve_metric_reference` resolves a metric key (and optional variant path)
  to a `MetricMeasureDefinition`.
- `normalise_filter_group`, `combine_filter_groups`, and
  `wrap_expression_with_filters` handle common filter scenarios prior to
  rendering.
- `parse_metric_expression` parses inline expressions and returns a
  `ParsedExpression` struct with referenced metrics so planners can substitute
  compiled DAX fragments safely.
- See `metric_expressions.md` for the expression grammar and the `ratio_to()`
  helper supported inside expressions.
- `resolve_expression_metric` compiles inline expression rows into
  `MetricMeasureDefinition` instances using the same builder/cache workflow as
  catalogue metrics.
- `render_visual_plan` turns a `VisualPlan` into a `SUMMARIZECOLUMNS` query,
  generating `DEFINE` stubs, declaring measures, and applying optional global or
  ad-hoc filters. The renderer expects callers to pass the grain columns
  (defaults to `VisualPlan.grain_columns`) and keeps measure table configuration
  configurable via `measure_table`.
- `generate_measure_names` applies a configurable `NameStrategy` while ensuring
  measure names remain unique. Downstream projects can inject prefixes (for
  example, `msa_`) without duplicating slug logic.
- `iter_group_metrics` flattens `VisualGroupConfig` hierarchies into
  `(group, metric)` pairs so planners can inherit filters before calling the
  renderer.
- `normalise_define_blocks` cleans registry `DEFINE` fragments into a tuple that
  can be passed directly to `render_visual_plan`.

`MeasurePlan.group_filters` carries presentation-time filters derived from
`VisualGroupConfig` (or other grouping constructs) so visuals can model
hierarchies without Praeparo knowing about governance-specific “sections”. Keep
group concepts inside visual definitions and let the shared planner surface the
resulting filters to the renderer.

These utilities intentionally avoid imposing naming or ratio rules—the calling
visual is responsible for assigning measure names, ratio handling, and other
presentation-specific behaviour. Downstream projects can compose these helpers
with their own planners to build custom visuals while sharing the heavy lifting
performed by Praeparo.

Need to surface the compiled statements? Register a compiler via
`praeparo.visuals.dax_compilers.register_dax_compiler` so the shared CLI exposes
`praeparo visual dax <type>` alongside the existing `run` / `artifacts`
subcommands.

## Python-Backed Visuals

- Use `PythonVisualBase` for code-first visuals; override `build_dataset` and `render`.
- Run them with `praeparo python-visual run path/to/module.py [dest]` (or simply `praeparo path/to/module.py [dest]`), keeping `dest` optional for shorthand HTML/PNG placement.
- Context models stay typed (re-use `VisualContextModel` fields plus your own), and the pipeline still discovers metrics/datasources for you.
- See [python_visuals.md](python_visuals.md) for the full quickstart.

## CLI destination shorthand

Both YAML and Python visual runs accept an optional positional `dest` to cut down
on `--output-*` flags. Flags always override any defaults derived from `dest`.

Examples:

- Directory or extension-less `dest`:

  ```bash
  praeparo visual run governance_matrix visuals/performance_dashboard.yaml ./exports/
  ```

  Defaults to:
  - HTML: `./exports/<slug>.html`
  - PNG: `./exports/<slug>.png`
  - Artefacts: `./exports/_artifacts/`

- `.png` `dest`:

  ```bash
  praeparo visual run governance_matrix visuals/performance_dashboard.yaml ./exports/report.png
  ```

  Defaults to:
  - PNG: `./exports/report.png`
  - Artefacts: `./exports/report/_artifacts/`
  - HTML remains enabled by default and follows the usual rules unless overridden.

Python auto-detection:

- `praeparo path/to/visual.py [dest]` and `praeparo visual run path/to/visual.py [dest]`
  are routed to `praeparo python-visual run ...` automatically.

## Visual inspection workflow

Use `praeparo visual inspect` when the goal is verification rather than a quick
ad hoc render. It reuses the normal visual pipeline but tightens the output
contract so downstream tooling can inspect one stable manifest.

```bash
praeparo visual inspect governance_matrix visuals/performance_dashboard.yaml
```

This command:

- executes the visual once through the normal pipeline;
- guarantees a PNG target even when `--output-png` was not supplied;
- guarantees an artefact directory for schema, data, and DAX sidecars;
- writes `render.manifest.json` under the artefact directory; and
- records the emitted HTML, PNG, schema, data, and DAX files in one portable
  manifest.

The manifest also records a stable `baseline_key` derived from the visual file
name. Baseline comparison and approval commands resolve
`<baseline_dir>/<baseline_key>.png`, so the baseline file name stays stable even
when you use a one-off `dest` path during local debugging.

Default paths (when no `dest` or output overrides are supplied):

- HTML: `build/<visual>.html`
- PNG: `build/<visual>.png`
- Artefacts + manifest: `build/<visual>/_artifacts/`

This makes `visual inspect` the preferred primitive for future baseline
comparison, approval, and MCP inspection flows, while `visual run` remains the
lighter-weight execution command.

Once a visual inspection run has produced `render.manifest.json`, use:

```bash
praeparo visual compare .tmp/performance_dashboard/_artifacts \
  --baseline-dir tests/baselines/performance_dashboard
```

This command:

- accepts either an artefact directory or a direct `render.manifest.json`
  path;
- compares the primary PNG to `<baseline_dir>/<baseline_key>.png`;
- writes `compare.manifest.json` plus any diff PNGs under
  `<artefact_dir>/_comparisons` by default; and
- exits non-zero when the visual mismatches, is missing a baseline, or is
  missing its rendered PNG.

When the new render is correct and should become the approved reference, use:

```bash
praeparo visual approve .tmp/performance_dashboard/_artifacts \
  --baseline-dir tests/baselines/performance_dashboard \
  --note "Accept legend sizing update."
```

This command copies the current PNG to `<baseline_dir>/<baseline_key>.png` and
writes or updates `<baseline_dir>/baseline.manifest.json`, preserving any
project-specific top-level metadata already recorded there.

## Python Metric Dataset Builder

Prefer a notebook workflow over YAML when sketching visuals? Review the
[Python Metric Dataset Builder](python_metric_dataset_builder.md) design notes.
The builder wraps the metric catalog, DAX planner, and datasource resolution so
code-first clients can call `dataset.execute()` / `dataset.to_df()` (or `await dataset.ato_df()` in async workflows) while
staying aligned with the same registry definitions.
