# Visual Registry & Shared Models

Praeparo exposes a small `praeparo.visuals` package for registering custom
visual types without rewriting the shared loading logic. The same surface also
backs `praeparo visual artifacts` and `praeparo visual run`, so the CLI can
prepare the files it needs before it renders HTML or PNG output.

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

The registry blocks duplicate registrations. Use `overwrite=True` only while
iterating locally; keep the default in shared code so one visual type does not
silently replace another.

## Loading Definitions

```python
from praeparo.visuals import load_visual_definition

config = load_visual_definition("visuals/combo/monthly.yaml")
assert config.type == "combo"
```

`load_visual_definition` resolves relative paths, prevents circular references,
and raises clear errors when a YAML file is missing `type` or points at an
unregistered visual.

## Shared Model Primitives

The package also publishes reusable Pydantic models for visual YAML:

- `VisualMetricConfig`: references a metric key or inline expression and
  supports additional filters via `calculate` along with mock configuration.
- `VisualGroupConfig`: groups metrics together and applies a shared `calculate`
  block to every metric (or nested group) inside.
- `VisualMockConfig` and friends (`VisualMetricMock`,
  `VisualMetricMockScenario`, `VisualMetricMockScenarioOverride`) allow visual
  definitions to include deterministic mock data paths alongside live
  datasources.

These helpers stay lightweight so downstream projects can extend them with
project-specific fields while still relying on Praeparo’s validation and
loader utilities.

When a visual needs extra run-time settings such as a metrics root, scenario,
or visual-specific switch, subclass `VisualContextModel` and register it with
`context_model=` on `register_visual_type`. See
`visual_context_model.md` for the base fields and lifecycle.

For deeper implementation context (how planners, execution clients, and output
handling fit together), see the pipeline reference in
[`docs/visual_pipeline_engine.md`](../visual_pipeline_engine.md).

## Relationship to Metric Catalog

Visuals can list metric keys directly, or they can group them with
`MetricGroupConfig` (from `praeparo.metrics`) when several metrics share the
same filters. That lets Praeparo apply presentation-time filters without
creating new metric variants in the catalog.

Future visuals (combo charts, scorecards, and similar patterns) should reuse
these helpers instead of duplicating calculate or mock handling in each
project.

## DAX Planning Helpers

When a visual needs to emit DAX, reuse the helpers under
`praeparo.visuals.dax`:

- `MetricCompilationCache` caches metric plans after they have been compiled so
  multiple visuals can reuse the same `MetricDaxBuilder` without redundant
  work.
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
  example, `project_`) without duplicating slug logic.
- `iter_group_metrics` flattens `VisualGroupConfig` hierarchies into
  `(group, metric)` pairs so planners can inherit filters before calling the
  renderer.
- `normalise_define_blocks` cleans registry `DEFINE` fragments into a tuple that
  can be passed directly to `render_visual_plan`.

`MeasurePlan.group_filters` carries presentation-time filters derived from
`VisualGroupConfig` (or other grouping constructs) so visuals can model
hierarchies without Praeparo needing to understand project-specific group
labels. Keep group concepts inside visual definitions and let the shared
planner surface the resulting filters to the renderer.

These utilities intentionally avoid naming or ratio rules. The visual decides
how measures should be named and presented. Downstream projects can combine
these helpers with their own planners while Praeparo handles the repeated work.

If you want the compiled statements to be visible, register a compiler through
`praeparo.visuals.dax_compilers.register_dax_compiler`. That makes
`praeparo visual dax <type>` available alongside the existing `run` and
`artifacts` commands.

## Python-Backed Visuals

- Use `PythonVisualBase` for code-first visuals; override `build_dataset` and
  `render`.
- Run them with `praeparo python-visual run path/to/module.py [dest]` or
  simply `praeparo path/to/module.py [dest]` if you want the shorter form.
- YAML visuals can also set `type: ./module.py`; Praeparo validates the
  remaining YAML fields with the Python visual's `config_model`.
- Context models stay typed, and the pipeline still discovers metrics and
  datasources for you.
- See [python_visuals.md](python_visuals.md) for the full quickstart.

## CLI workflow and destinations

Both YAML and Python visual runs accept an optional positional `dest` so you
can avoid a long list of `--output-*` flags. Flags always override anything
derived from `dest`.

Use `praeparo visual artifacts` when you only need the artefact bundle. Use
`praeparo visual run` when you want Praeparo to render the visual from that
bundle in the same command.

Examples:

- Directory or extension-less `dest`:

  ```bash
  praeparo visual run <visual-type> visuals/<visual>.yaml ./exports/
  ```

  Defaults to:
  - HTML: written to the requested destination directory
  - PNG: written to the requested destination directory
  - Artefacts: written beside the rendered output in the same folder

- `.png` `dest`:

  ```bash
  praeparo visual run <visual-type> visuals/<visual>.yaml ./exports/report.png
  ```

  Defaults to:
  - PNG: `./exports/report.png`
  - HTML: written alongside the PNG when enabled
  - Artefacts: written beside the rendered output in the same folder

When a visual produces browser-backed output, keep the HTML entry page and its
schema or data files in the same directory so the bundle stays portable and
easy to inspect from a local folder or static server.

Python auto-detection:

- `praeparo path/to/visual.py [dest]` and `praeparo visual run path/to/visual.py [dest]`
  are routed to `praeparo python-visual run ...` automatically.

## Preview and capture

Browser-driven visuals should be previewed and captured from the same artefact
bundle that the CLI emits. That keeps sizing, schema, and data aligned between
interactive review and PNG export.

- First generate the bundle with `praeparo visual artifacts <visual-type>
  <visual.yaml> [dest]`.
- Then render or capture with `praeparo visual run <visual-type>
  <visual.yaml> [dest]` using the same visual definition and destination.
- If the visual depends on browser automation, make sure the required browser
  toolchain is installed before running the command.

## Python Metric Dataset Builder

Prefer a notebook workflow over YAML when sketching visuals? Review the
[Python Metric Dataset Builder](python_metric_dataset_builder.md) design notes.
The builder wraps the metric catalog, DAX planner, and datasource resolution so
code-first clients can call `dataset.execute()` / `dataset.to_df()` (or
`await dataset.ato_df()` in async workflows) while staying aligned with the
same registry definitions.
