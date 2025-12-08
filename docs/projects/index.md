# Praeparo Projects

Praeparo projects group related visuals, datasources, and build artefacts into a reusable workspace. The layout mirrors modern web-app frameworks so teams can version control reporting assets and run the CLI with minimal ceremony.

```text
projects/
  <project-name>/
    datasources/
      <data-source>.yaml
    visuals/
      <visual>.yaml
    build/
      (generated HTML/PNG assets, typically ignored)
```

## Key concepts

- **Visuals** live under `visuals/` and are standard Praeparo YAML files (for example `type: matrix` or `type: frame`). Use the optional `datasource` field to reference a datasource by name.
- **Datasources** (see [Datasource Definitions](../datasources/index.md)) sit alongside visuals and describe how to fetch project data. When a visual omits `datasource`, the CLI falls back to the mock provider for offline development.
- **Build** contains generated HTML and PNG artefacts. The CLI writes outputs here by default, so add a `.gitignore` entry to keep repositories clean.

## CLI workflow

1. Author or update a visual in `visuals/`.
2. Run `poetry run praeparo projects/<project>/visuals/<visual>.yaml`.
3. Inspect the generated files in `build/` or wire the command into CI.

Planned project-aware features include `praeparo dev <project>` for live reloads, project-level defaults for shared styling, and optional deployment metadata. For a concrete example, see [Automatic Documents](../examples/automatic_documents.md).

## Pack Runner (Pack → PNG)

Packs orchestrate multiple visuals as a single unit. A pack YAML defines shared
context, optional global filters, and an ordered list of slides; each slide
references an existing visual YAML and can apply additional filters or
calculate clauses.

Use `praeparo pack run` to execute a pack:

```bash
poetry run praeparo pack run projects/example/pack.yaml --artefact-dir .tmp/example/pack_png
```

Each visual slide is executed via the normal visual registry and pipelines;
PNGs land in `<artefact-dir>/<slide-slug>.png` with per-slide artefacts under
`<artefact-dir>/<slide-slug>/`. Pack CLI logging defaults to `DEBUG`; override
with `--log-level` or `PRAEPARO_LOG_LEVEL` (see [Pack Runner](pack_runner.md)
for details).

## Upcoming: Python Metric Dataset Builder

Notebook-first metric exploration will lean on the planned [Metric Dataset Builder design](python_metric_dataset_builder_plan.md). The document tracks the scope, API surface, and implementation phases before work begins.
