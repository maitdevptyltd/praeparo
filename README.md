# Praeparo

_Slides, prepared._

## What is Praeparo?

Praeparo is a framework for building **complete PowerPoint decks from live business data** — using nothing more than simple YAML files and a project structure that feels as easy as editing a website.

It takes inspiration from **Power BI’s simplicity** (drag fields, drop measures, build visuals) but adds the **flexibility of Plotly** to customize every table, chart, and layout. The result is a developer-friendly way for organizations to:

- Stop manually copying charts into slides
- Keep presentations **up-to-date automatically**
- Ensure every deck aligns with corporate branding
- Version-control and collaborate on reports like real code

## Why does this matter?

Many businesses today are on a journey toward **Power BI adoption**. But in practice:

- Teams still spend hours building **complex decks in PowerPoint** for board packs, executive reports, and client updates.
- Power BI visuals are powerful but **constrained** — some tables, layouts, and formatting just can’t be achieved in the UI.
- Reporting processes become brittle: a change in data or a new KPI often means **manual re-work in slides**.

Praeparo bridges this gap. It lets you keep using Power BI as the **data engine** (via DAX queries), but express your visualizations as **YAML components** that can be composed into polished, automated decks.

## How it works

- **YAML components** — Each chart, table, or matrix is a small `.yaml` file.
- **Composition** — Just like pages in a web framework, you compose components into slides.
- **Customization** — Plotly rendering gives full control over styling, formatting, and layouts.
- **Export** — The build process generates **ready-to-share PPTX decks**, fully branded and up to date.
- **Builder-first execution** — Both YAML planners and inline notebooks feed the same `MetricDatasetBuilder`, so live Power BI runs and deterministic mock previews stay in sync without duplicating DAX logic.

## Example

Define a matrix once:

```yaml
title: "Team Activity"
type: matrix
rows:
  - template: "{{QueueName}} ({{DeliveryMode}})"
    label: "Team Activity"
values:
  - id: "tasks_completed_pct"
    show_as: "Percent of column total"
    label: "% completed"
    format: "percent:0"
  - id: "avg_completion_seconds"
    label: "hh:mm:ss"
    format: "duration:hms"
totals: row
```

Compose it with another matrix in a slide:

```yaml
type: group
title: "Average time to complete work"
layout: vertical
children:
  - ref: "./team_activity_auto.yaml"
  - ref: "./team_activity_manual.yaml"
```

Run the build, and you’ll get a finished PowerPoint deck — no copy-pasting, no manual formatting.

Matrix configs also support top-level `define:` and `calculate:` blocks. Use `define:` to stage DAX tables or measures before `EVALUATE`, and `calculate:` to inject slicer-style predicates into the generated `CALCULATETABLE` call. Those definitions can be referenced from row templates and filters (see `examples/team_activity/visuals/team_activity.yaml`). Filters accept either `field`/`include` pairs or direct `expression` strings for complex predicates. Rows can also be marked `hidden: true` to remain in queries while disappearing from rendered tables. Compose lists and top-level `parameters` let base YAML power variants like self-service vs specialist workflow runs.

Auto-sized visuals: matrix and frame YAMLs expose an `autoHeight` flag (defaulting to `true`) so Plotly figures match their tabular content when exported to PNG, removing the dead space beneath stacked tables.

## Who is it for?

- **Business leaders** who want decks that always reflect the latest numbers.
- **BI teams** looking to standardize reporting while moving toward Power BI.
- **Consultants & analysts** tired of re-building the same charts in PowerPoint.
- **Developers** who want to treat reporting like code: versioned, reusable, automated.

## Benefits

- **Save time** — automate recurring decks
- **Consistency** — every chart and slide follows the same definitions and styles
- **Transparency** — YAML is human-readable and version-controlled
- **Flexibility** — Plotly unlocks custom visuals not possible in Power BI
- **Scalability** — add new KPIs or slides with just a YAML file

## Proof-of-Concept Workflow

1. Define a matrix visual in YAML (see `examples/team_activity/visuals/team_activity.yaml`).
2. Validate and render it with the CLI (HTML defaults to `<project>/build/<name>.html`):
   - `poetry run praeparo examples/team_activity/visuals/team_activity.yaml --png-out examples/team_activity/build/team_activity.png --print-dax`
   - Add `--data-source powerbi` to reuse the example Power BI descriptor when live credentials are available.
3. Regenerate visual snapshots with `poetry run pytest --snapshot-update`; inspect the HTML/PNG artifacts under `tests/__snapshots__/test_pipeline/`.

The CLI orchestrates YAML validation (via Pydantic), field extraction, DAX query generation, and a mock data provider before building a Plotly table. The DAX output is printed when `--print-dax` is supplied so you can copy it into live environments later.

### IntelliSense Support
### Power BI Integration

#### Integration Tests

Run live verification manually (skipped by default):

```
PRAEPARO_RUN_POWERBI_TESTS=1 poetry run pytest -m integration
```

Set the following environment variables (see `.env`) to enable live DAX queries:
- `PRAEPARO_PBI_CLIENT_ID`
- `PRAEPARO_PBI_CLIENT_SECRET`
- `PRAEPARO_PBI_TENANT_ID`
- `PRAEPARO_PBI_REFRESH_TOKEN`
- Optional: `PRAEPARO_PBI_SCOPE` (defaults to Power BI API scope)

The CLI automatically calls `load_dotenv()` before inspecting the environment, so a `.env` file anywhere in the current working tree (or its parents) will be discovered and loaded once per process. Explicitly exported variables still take precedence because `override=False` is used.

Render a YAML visual against a real dataset:

```
poetry run praeparo examples/team_activity/visuals/team_activity.yaml --data-source powerbi --png-out examples/team_activity/build/team_activity.png --print-dax
```

The CLI exchanges the refresh token for an access token, issues the DAX statement via the Power BI `executeQueries` API, and snapshots the response for regression tests.

When `--dataset-id` is omitted the mock provider remains available for offline development.


Generate the umbrella visual schema with:

```bash
poetry run praeparo schema
poetry run praeparo schema ./schemas/visual_umbrella.schema.json
```

That default command writes `schemas/visual_umbrella.schema.json`, which can be
attached to stable visual YAML families in your editor. Keep the advanced
`python -m praeparo.schema --matrix|--charts|--metrics|--components|--pack ...` path for
specialized exports only.

Metric components use the same advanced export path:

```bash
poetry run python -m praeparo.schema --components schemas/components.json
```

That refreshes the committed `schemas/components.json` artifact and mirrors the
current `registry/components/**` contract: `schema: component-draft-1` plus the
supported top-level `explain` payload.

Generic context layers use a dedicated advanced export as well:

```bash
poetry run python -m praeparo.schema --context-layer schemas/context_layer.json
```

That refreshes the committed `schemas/context_layer.json` artifact for
`registry/context/**/*.yaml|yml` authoring. The schema stays permissive for
repo-specific values like `month` or `business_time`, while reusing Praeparo’s
existing `context.metrics.*` models so nested `bindings`, `calculate`, and
`allow_empty` IntelliSense matches runtime behaviour.

For downstream workspaces, declare repo-local plugins in a root `praeparo.yaml`
manifest:

```yaml
plugins:
  - my_project_plugin
```

Praeparo now auto-loads plugins in this order: explicit `--plugin`, then
`PRAEPARO_PLUGINS`, then `praeparo.yaml`, then opt-in package metadata.

### Metric definitions (preview)

The metrics Pydantic models live in `praeparo.metrics`. Export their JSON schema or validate a registry via:

```
poetry run praeparo-metrics schema --out schemas/metrics.json
poetry run praeparo-metrics validate path/to/metrics
```

- Use `load_metric_catalog([...])` to parse a directory of metric YAML into a `MetricCatalog`. It exposes helpers such as `metric_keys()`, `variant_keys()`, and `contains()` so consumer tooling (e.g. customer registry validation) can confirm that a metric or variant exists before publishing dashboards.
- `load_metric_catalog` raises `MetricDiscoveryError` when duplicate keys, YAML issues, or broken `extends` chains are encountered. The CLI above now uses the same loader, so command-line validation and Python workflows stay consistent.
- For direct file discovery logic, reuse `discover_metric_files([...])` rather than rolling custom globbing.
- Use `define` to capture the canonical expression (e.g., DAX `CALCULATE(...)`) for a base metric. Variants and extending metrics can then layer additional `calculate` predicates without duplicating the core definition.
- Use `extends` in a metric YAML when a definition builds on another metric (e.g. discharge metrics inherit the base instructions filters). Inheritance is validated by the CLI and reflected in the generated JSON schema.
- Use YAML `compose` when you need to merge multiple files before validation (e.g. sharing large configuration scaffolds). Compose is a loader-level feature and complements logical inheritance.

## Documentation

Start with [`docs/index.md`](docs/index.md), then drill into:

- Packs: [`docs/projects/pack_runner.md`](docs/projects/pack_runner.md)
- Visuals + CLI: [`docs/visuals/index.md`](docs/visuals/index.md)
- Metrics: [`docs/metrics/metric_dax_builder.md`](docs/metrics/metric_dax_builder.md)
- Registry -> TMDL generation: [`docs/metrics/tmdl_generation.md`](docs/metrics/tmdl_generation.md)
- Datasources: [`docs/datasources/index.md`](docs/datasources/index.md)
