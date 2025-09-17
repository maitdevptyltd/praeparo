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

## Example

Define a matrix once:

```yaml
title: "Automatic Documents"
type: matrix
rows:
  - template: "{{MortMgrName}} ({{FundingChannelTypeName}})"
    label: "Automatic Documents"
values:
  - id: "percent_sent"
    show_as: "Percent of column total"
    label: "% sent"
    format: "percent:0"
  - id: "avg_time_sec"
    label: "hh:mm:ss"
    format: "duration:hms"
totals: row
```

Compose it with another matrix in a slide:

```yaml
type: group
title: "Average time to prepare documents"
layout: vertical
children:
  - ref: "./matrix_auto.yaml"
  - ref: "./matrix_manual.yaml"
```

Run the build, and you’ll get a finished PowerPoint deck — no copy-pasting, no manual formatting.

Matrix configs also support a top-level `define:` block for staging DAX tables or measures before `EVALUATE`. Those definitions can be referenced from row templates and global filters (see `tests/visuals/matrix/auto.yaml`). Filters accept either `field`/`include` pairs or direct `expression` strings for complex predicates. Rows can also be marked `hidden: true` to remain in queries while disappearing from rendered tables. Compose lists and top-level `parameters` let base YAML power variants like digital vs manual document runs.

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

1. Define a matrix visual in YAML (see `tests/visuals/matrix/auto.yaml`).
2. Validate and render it with the CLI:
   - `praeparo tests/visuals/matrix/auto.yaml --out build/matrix.html --print-dax`
   - Add `--png-out build/matrix.png` to capture a static snapshot for slide decks (requires Kaleido: `poetry add kaleido`).
3. Regenerate visual snapshots with poetry run pytest --snapshot-update; inspect the HTML/PNG artifacts under 	ests/__snapshots__/test_pipeline/.

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

Render a YAML visual against a real dataset:

```
praeparo tests/visuals/matrix/auto.yaml --dataset-id <dataset_guid> --workspace-id <workspace_guid> --out build/matrix.html --png-out build/matrix.png --print-dax
```

The CLI exchanges the refresh token for an access token, issues the DAX statement via the Power BI `executeQueries` API, and snapshots the response for regression tests.

When `--dataset-id` is omitted the mock provider remains available for offline development.


Run `python -m praeparo.schema` to regenerate `schemas/matrix.json`. Import this schema into your editor to unlock auto-complete and validation for matrix YAML files.




