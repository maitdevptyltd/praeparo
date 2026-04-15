# Epic: Visual Umbrella Schema CLI

> Status: **Implemented** – Praeparo now exposes `praeparo schema`, shared plugin auto-discovery applies across the CLI surface, and downstream projects can consume the generated umbrella schema as an editor-facing artifact.

- Canonical developer docs live in `docs/visuals/visual_umbrella_schema.md` and `docs/visual_model_architecture.md`.

## 1. Problem Statement

VS Code IntelliSense for YAML is strongest when a project can point a file family at a single schema and let the schema itself decide which contract applies. The current narrow visual mapping in downstream workspaces is a useful guardrail, but it is still a stopgap:

- it relies on path allowlists in `.vscode/settings.json`;
- it only covers one narrow project-specific visual slice;
- it does not scale cleanly as new visual families are added;
- it keeps type knowledge split between editor settings and schema authorship.

The better end state is a Praeparo-generated umbrella schema that is attached by path/glob and branches on the YAML `type` property inside the schema itself.

## 2. Why The Current Allowlist Is Only A Stopgap

The narrowed allowlist is better than broad coverage, but it still leaves the repository with a manual editor mapping model:

- every new visual family requires a settings change;
- a path move can silently break IntelliSense even when the underlying contract is unchanged;
- the mapping has to be curated by humans instead of being derived from the authored YAML contract;
- the repo cannot express family-specific completion behavior from one shared schema entry.

That makes the allowlist a safe interim state, not the final design.

## 3. Implemented CLI Surface

The feature now lives in Praeparo so schema ownership stays with the framework that already knows the models.

Implemented shape:

```bash
poetry run praeparo schema
poetry run praeparo schema project_schemas/generated/visual_umbrella.schema.json
```

Implemented behavior:

- `praeparo schema` writes the umbrella schema to `./schemas/visual_umbrella.schema.json`.
- `praeparo schema <dest>` writes the umbrella schema to an explicit destination.
- Flags exist for advanced scenarios only, not as the primary UX.
- `--plugin MODULE` remains an escape hatch for unusual setups or explicit override/debug scenarios.

The key requirement is that the CLI should generate a reusable schema artifact without downstream repositories hand-authoring a second copy of the contract.

### 3.1 Automatic Plugin Discovery

The normal command path should auto-load Praeparo plugins that are available in the active environment or declared by the workspace, so workspace-local custom visuals do not depend on someone remembering an explicit `--plugin`.

Discovery is deterministic and layered, not magical:

1. `--plugin MODULE` takes precedence and is additive for explicit overrides, debugging, or uncommon setups.
2. `PRAEPARO_PLUGINS` comes next for environment-driven configuration in local shells and CI.
3. A workspace manifest at repo root `praeparo.yaml` comes next as the host-agnostic source of truth for shared workspaces.
4. Convention-based scan comes last and only picks up opt-in package roots.

Implemented behavior:

- Praeparo discovers and loads the plugin(s) needed to build the umbrella schema automatically when `praeparo schema` runs.
- The root `praeparo.yaml` manifest can declare plugin modules for normal auto-loading.
- Workspace-local custom visual families should be visible through the normal schema export path.
- `--plugin MODULE` remains available for explicit override/debug scenarios.
- The fallback behavior should be predictable if auto-discovery finds nothing, so the user gets a clear error instead of a silent partial schema.

### 3.2 Convention-Based Scan

The scan should support the current repo layout and the later `packages/*/` layout without treating every Python package as a plugin.

Implemented rules:

- treat the current workspace root package as loadable when its package root opts in;
- treat `packages/*/` package roots the same way after the later structure move;
- only auto-load a package root if it declares an explicit Praeparo plugin marker in its own `pyproject.toml` or equivalent package metadata;
- do not infer plugin status from `__init__.py` or importability alone;
- prefer a stable module name declared by the package over path guessing.

This keeps the default path simple while making discovery predictable across the current and future repository layouts.

## 4. Repo Consumption Path

Downstream projects can consume the generated artifact after Praeparo emits it.

Proposed repo-owned generated location:

- `project_schemas/generated/visual_umbrella.schema.json`

That keeps the editor-facing schema artifact alongside the other repo-owned generated schemas and makes the VS Code mapping a simple file reference instead of a broad manual rule.

## 5. Supported First Visual Families

The first umbrella should cover only the visual families with a real shared contract:

- `matrix`
- `frame`
- `powerbi`
- cartesian `column` and `bar`
- plugin-defined visual families that register a schema branch explicitly

The umbrella schema should branch on `type` and use JSON Schema conditionals or equivalent discriminators to route each family to the right shape.

Representative authored examples include:

- matrix visuals under a workspace `registry/visuals/**`
- frame visuals that compose or reference child visuals
- Power BI visuals under a workspace `registry/visuals/powerbi/**`
- cartesian chart visuals that use `column` or `bar`

## 6. Explicit Exclusions For v1

Python-backed module-path visuals should stay out of the first umbrella.

Reason:

- they do not share one stable config model today;
- the `type` values can be module paths rather than a clean family name;
- a fake fallback branch would give false IntelliSense confidence.

Those visuals can be addressed later, either by a separate schema strategy or by an explicit contract refactor.

## 7. Landed Implementation

### 7.1 Praeparo Work

Praeparo now owns the schema generation logic:

- add a visual schema builder alongside the existing matrix and cartesian helpers;
- branch the generated schema on `type` for the supported families;
- expose the new schema through `praeparo schema`;
- auto-load the relevant plugins before schema generation so workspace-local visual families are available without an explicit `--plugin` flag, using the layered discovery order above;
- write the schema to `./schemas/visual_umbrella.schema.json` unless the caller overrides it with `praeparo schema <dest>`.

### 7.2 Downstream Follow-Up Work

Downstream projects can now:

- generate and commit `project_schemas/generated/visual_umbrella.schema.json`;
- update editor settings to attach the umbrella schema by path/glob;
- remove narrow family-specific editor stopgaps once the umbrella is validated;
- keep Python-backed module-path visuals unmapped until they have a reliable shared schema.

## 8. Validation And Acceptance Criteria

This slice is ready when all of the following are true:

- `praeparo schema` writes a valid umbrella schema to Praeparo's default output location.
- `praeparo schema` writes a valid umbrella schema to `./schemas/visual_umbrella.schema.json`.
- `praeparo schema <path>` writes the same schema to the requested location.
- the command auto-loads the relevant plugin(s) in the normal path so workspace-local visual families do not require an explicit `--plugin`.
- plugin resolution is deterministic in the documented order: explicit flag, `PRAEPARO_PLUGINS`, root `praeparo.yaml`, then opt-in convention scan.
- the convention scan supports the current root package and the future `packages/*/` layout without loading unrelated Python packages.
- the generated schema validates representative authored YAML for the supported families.
- the schema branches correctly on `type` for matrix, frame, powerbi, and cartesian `column`/`bar` visuals.
- Python-backed module-path visuals are not accidentally admitted into the first umbrella.
- a downstream project can consume the emitted artifact from `project_schemas/generated/`.

## 9. Remaining Risks

- What is the best long-term strategy for module-path visuals that do not share one schema model?
- Will the umbrella remain performant enough for editor IntelliSense if more visual families are added later?
- The root `praeparo.yaml` manifest is the current source of truth; unusual workspace layouts may still need an override strategy later if that becomes a real use case.

## 10. Example Commands

Generate the default umbrella schema:

```bash
poetry run praeparo schema
```

This writes to `./schemas/visual_umbrella.schema.json` unless you pass an explicit destination.

Generate to an alternate location:

```bash
poetry run praeparo schema /tmp/visual_umbrella.schema.json
```

Generate the artifact the repo will later commit and reference:

```bash
poetry run praeparo schema project_schemas/generated/visual_umbrella.schema.json
```

Force a specific plugin only when auto-discovery is not enough:

```bash
poetry run praeparo --plugin my_project.plugin schema project_schemas/generated/visual_umbrella.schema.json
```
