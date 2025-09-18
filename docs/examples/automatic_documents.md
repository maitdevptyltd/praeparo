# Automatic Documents Example

Praeparo ships with an end-to-end example project that mirrors the former `tests/integration/matrix_auto.yaml` integration case. The example treats Praeparo as an installed dependency so teams can copy the folder outside of this repository when bootstrapping a deliverable.

## Layout

See also: [Praeparo Projects](../projects/index.md).

```text
examples/
  automatic_documents/
    datasources/
      default.yaml
    visuals/
      automatic_documents.yaml
    build/
      (generated html/png assets)
```

- Visuals live in `visuals/` so they flow through the existing loader pipeline.
- Datasources sit beside them under `datasources/` and behave like any other Praeparo YAML file.
- Build artifacts default to `<project>/build/<visual-name>.<ext>`.

### Datasources

See also: [Datasource Definitions](../datasources/index.md).

The default descriptor targets Power BI:

```yaml
# examples/automatic_documents/datasources/default.yaml
type: powerbi
datasetId: "${env:PRAEPARO_PBI_DATASET_ID}"
workspaceId: "${env:PRAEPARO_PBI_WORKSPACE_ID}"
```

- `datasetId` and `workspaceId` support `${env:VAR}` placeholders or literal values.
- Authentication falls back to environment variables when the YAML omits overrides (`PRAEPARO_PBI_CLIENT_ID`, `PRAEPARO_PBI_CLIENT_SECRET`, `PRAEPARO_PBI_TENANT_ID`, `PRAEPARO_PBI_REFRESH_TOKEN`, optional `PRAEPARO_PBI_SCOPE`). Provide explicit values in the YAML if you need to point at alternate credentials.
- Leaving the reference off a visual reverts to the mock provider for quick offline iteration.

### Visual configuration

```yaml
# examples/automatic_documents/visuals/automatic_documents.yaml
type: matrix
title: "Automatic Documents"
datasource: default
```

Override the datasource per visual, or omit the field to render against the mock provider.

### Running the example

```bash
poetry run praeparo examples/automatic_documents/visuals/automatic_documents.yaml       --png-out examples/automatic_documents/build/automatic_documents.png
```

- HTML output defaults to `examples/automatic_documents/build/automatic_documents.html`.
- PNG output is optional; the VS Code launch profile passes `--png-out` automatically.
- Ensure the Power BI environment variables listed above are set so the CLI can resolve credentials.
- Use `--data-source mock` when you want to force deterministic sample data.

### VS Code launch (new)

`.vscode/launch.json` includes **Praeparo: Render Visual** which:

1. Executes the active YAML file via `poetry run praeparo`.
2. Writes HTML/PNG assets into the sibling `build/` directory.
3. Leaves room for a future `praeparo dev` watch mode.

## Progress

- Loader + resolver now handle standalone Power BI datasource YAML files.
- Converted the former integration visual into an example project with a single `default` Power BI descriptor.
- CLI discovers project roots, defaults HTML output paths, and honours per-visual datasource references.
- VS Code launch profile wires the CLI into the example workflow.

## Next steps

- Extend datasource types (e.g. SQL, CSV) and document their schemas alongside Power BI.
- Prototype a `praeparo dev` command that watches the example directories and triggers re-renders.
- Add smoke tests that exercise the example directory end-to-end using the CLI.

## Blockers & risks

- Power BI descriptors rely on environment variables; missing credentials will raise at runtime. Consider a helper command to validate environment readiness.
- When copying the example outside this repo, teams must install Praeparo as a dependency and recreate the `build/` ignore rules.
- Future datasource types need consistent discovery semantics so lookups remain implicit and predictable.
