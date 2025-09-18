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
