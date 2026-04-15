# Visual Umbrella Schema

`praeparo schema [dest]` exports a single JSON schema that branches on the
top-level `type` field for supported visual YAML families.

Use this when you want editor IntelliSense to attach one schema to a visual
folder and let Praeparo decide which branch applies.

## CLI

Default export:

```bash
poetry run praeparo schema
```

This writes:

```text
schemas/visual_umbrella.schema.json
```

Explicit destination:

```bash
poetry run praeparo schema ./project_schemas/generated/visual_umbrella.schema.json
```

The command prints the final output path after the schema is written.

## What the umbrella includes

The umbrella schema is deterministic and currently includes:

- built-in matrix visuals,
- built-in frame visuals,
- built-in cartesian chart visuals (`column`, `bar`),
- built-in Power BI visuals,
- plugin-defined visual families that register a schema branch through
  `register_visual_schema(...)`.

Praeparo builds the umbrella from the same runtime/schema registry used by the
CLI, so custom branches are available as long as the relevant plugin is loaded
before export.

Branch selection is driven by the top-level `type` discriminator in each
visual schema. Each branch must declare stable discriminator values via
`type.const`, `type.enum`, or `type.default`.

## Plugin auto-discovery

Praeparo bootstraps plugins before the CLI parser snapshots the available
visual/schema registries. Discovery is layered and deterministic:

1. repeatable `--plugin MODULE` flags,
2. `PRAEPARO_PLUGINS`,
3. the nearest workspace manifest (`praeparo.yaml` or `praeparo.yml`),
4. opt-in package metadata in `pyproject.toml` at the workspace root or under
   `packages/*/`.

Workspace manifest example:

```yaml
plugins:
  - my_project.plugin
```

Opt-in package metadata example:

```toml
[tool.praeparo]
plugins = ["my_project.plugin"]
import_root = "."
```

Use `--plugin` when you want an explicit override or you are debugging plugin
loading:

```bash
poetry run praeparo --plugin my_project.plugin schema
```

## Supported families and exclusions

The umbrella schema is designed for visual families with a stable authoring
contract and a stable top-level discriminator.

Module-path Python wrappers such as `type: ./my_visual.py` are not part of the
umbrella contract. Those definitions are validated at runtime using the Python
visual's `config_model` instead of a precomputed umbrella branch. See
[Python-Backed Visuals](python_visuals.md) for that flow.

## Adding a new branch

If you add a plugin-defined visual family, register both the runtime loader and
the schema branch:

```python
from praeparo.visuals import register_visual_schema, register_visual_type

register_visual_type("combo", load_combo_visual)
register_visual_schema("combo", ComboVisualConfig.model_json_schema)
```

Use the optional registration flags when the branch needs them:

- `include_compose=True` to expose the shared `compose` authoring helper.
- `authoring_parameters=True` to expose top-level `parameters`.

If you skip `register_visual_schema(...)`, the visual may run correctly but it
will not appear in `praeparo schema` output.

For the broader loader/model split, see
[Visual Model Architecture](../visual_model_architecture.md).

## Downstream editor consumption

A downstream project will usually:

1. generate the umbrella schema into a committed or generated project path,
2. point the editor at that single schema for visual YAML folders,
3. regenerate the schema whenever visual models or plugin registrations change.

Typical VS Code mapping:

```json
{
  "yaml.schemas": {
    "./project_schemas/generated/visual_umbrella.schema.json": [
      "registry/visuals/**/*.yaml",
      "registry/customers/**/visuals/**/*.yaml"
    ]
  }
}
```

The exact glob paths are project-owned. Praeparo only owns the exported schema
contract.
