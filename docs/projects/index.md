# Praeparo Projects

Praeparo uses a predictable workspace layout so the CLI can find metrics,
datasources, shared settings, visuals, and packs without extra setup. In the
default layout, authored files live under `registry/**` at the workspace root.

## Default Workspace Convention

```text
<workspace-root>/
  praeparo.yaml
  registry/
    context/
    datasources/
    metrics/
    visuals/
    packs/
      pack_template.pptx
```

- **`registry/metrics/`** is the default metrics folder for DAX-backed visuals
  and dataset builders.
- **`registry/context/`** holds shared settings that Praeparo can find
  automatically during visual, explain, and pack runs.
- **`registry/datasources/`** is a standard datasource folder in the default
  workspace layout.
- **`registry/visuals/`** and **`registry/packs/`** hold authored visual and
  pack YAML files. Repos can add deeper domain- or project-specific folders
  beneath those roots.
- Generated HTML, PNG, and PPTX outputs usually land in an ignored build or
  output folder chosen by the project.

## Portable Example Layout

Some docs still use a compact `projects/<project>/...` tree when a small,
standalone example is easier to follow:

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

Praeparo can run a file directly in either layout. The `registry/` layout
matters when Praeparo needs to find related files for you automatically, such
as shared settings or the usual metrics folder.

## Key concepts

- **Visuals** are standard Praeparo YAML files (for example `type: matrix` or
  `type: frame`). In the default workspace they usually live under
  `registry/visuals/`; in portable examples they may live under
  `projects/<project>/visuals/`.
- **Datasources** (see [Datasource Definitions](../datasources/index.md))
  describe how to fetch project data. Praeparo resolves named datasources from
  the supported datasource folders available in the current workspace.
- **Build outputs** are generated files, not authored inputs. Keep them in an
  ignored folder so the authored registry stays clean.

## CLI workflow

1. Author or update a visual or pack in the workspace.
2. Run Praeparo against that explicit file path.
3. Review the generated output in your chosen folder or wire the command into
   CI.

For example:

```bash
poetry run praeparo registry/visuals/example.yaml
poetry run praeparo pack run registry/packs/example.yaml ./out/example
```

Planned project-aware features include `praeparo dev <project>` for live
reloads, project-level defaults for shared styling, and optional deployment
metadata. For a concrete example, see [Team Activity](../examples/team_activity.md).

## Shared Context

When a project needs shared settings across multiple visuals or packs, start
with [Context Layers](context_layers.md). That page covers the merge order,
supported file shapes, and schema generation for standalone context payloads.

## Pack Runner (Pack → PNG)

Packs let you run several visuals together. A pack YAML defines shared
context, optional global filters, and an ordered list of slides; each slide
references an existing visual YAML and can add its own filters or calculate
clauses.

Use `praeparo pack run` to execute a pack:

```bash
poetry run praeparo pack run projects/example/pack.yaml --artefact-dir out/example/pack_png
```

Prefer the explicit flags for clarity, but you can use a positional shorthand:
`praeparo pack run projects/example/pack.yaml out/report.pptx` maps artefacts to
`out/report/_artifacts/` and the PPTX to `out/report.pptx`; a directory
`dest` maps to `dest/_artifacts/` plus `dest/<pack-slug>.pptx`.

Each visual slide is loaded and run through the matching visual path; PNGs
land in `<artefact-dir>/[NN]_<slide-slug>.png` with per-slide outputs under
`<artefact-dir>/[NN]_<slide-slug>/`. Pack CLI logging defaults to `INFO` for
Praeparo logs while suppressing INFO/DEBUG output from dependencies unless
they are `WARNING` or higher. Override Praeparo verbosity with `--log-level`
or `PRAEPARO_LOG_LEVEL`, and restore dependency logs with
`--include-third-party-logs` or `PRAEPARO_INCLUDE_THIRD_PARTY_LOGS=1` (see [Pack Runner](pack_runner.md)
for details).

## Python Metric Dataset Builder (Notebook API)

The `praeparo.datasets.MetricDatasetBuilder` is the code-first companion to YAML visuals.

- **Current status:** the core builder API is available; planner refactors and deeper notebook examples remain in progress.
- **How to use it:** see [`docs/visuals/python_metric_dataset_builder.md`](../visuals/python_metric_dataset_builder.md).
- **Roadmap / design history:** see [`docs/projects/python_metric_dataset_builder_plan.md`](python_metric_dataset_builder_plan.md).

## Metrics

Need to compile registry YAML into canonical DAX snippets (for example to power a visual planner or a TMDL generator)?
Start with:

- [Metric → DAX Builder](../metrics/metric_dax_builder.md)
- [TMDL Generation](../metrics/tmdl_generation.md)
