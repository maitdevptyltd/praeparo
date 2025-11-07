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

## Python Metric Dataset Builder (Planned)

Prefer a notebook workflow over YAML when sketching visuals? Review the
[Python Metric Dataset Builder](python_metric_dataset_builder.md) design notes.
The builder wraps the metric catalog, DAX planner, and datasource resolution so
code-first clients can call `dataset.execute()` / `dataset.to_df()` (or `await dataset.ato_df()` in async workflows) while
staying aligned with the same registry definitions.
