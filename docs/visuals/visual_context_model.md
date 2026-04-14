# Visual Context Models

Praeparo supports typed visual context objects. They are created at the CLI
boundary and attached to `ExecutionContext.visual_context`.

The base model assumes Praeparo’s default workspace layout, where authored
assets live under `registry/**` relative to the workspace root. In that layout,
`registry/metrics` is the default metric catalogue root and `registry/context/**`
supplies shared context layers before visual-specific overrides are applied.

- **Base model:** `VisualContextModel` (`praeparo.visuals.context_models`)
  captures the common settings used by DAX-backed visuals:
  - `metrics_root: Path = Path("registry/metrics")` – defaults to the standard
    workspace metrics root. Override it when Praeparo runs in a different
    layout or in a portable example tree.
  - `seed: int = 42`
  - `scenario: str | None = None`
  - `ignore_placeholders: bool = False`
  - `grain: tuple[str, ...] | None = None`
  - `dax: DAXContextModel` – merged global DAX fragments:
    - `calculate: tuple[str, ...]`
    - `define: tuple[str, ...]`
- **Visual-specific models:** custom visuals can extend the base model to add
  their own fields. Register them via
  `register_visual_type(..., context_model=MyContextModel)`.
- **Lifecycle:** the CLI merges flags, context files (`--context`), and
  metadata into one payload, validates it against the registered context model,
  and stores the result on `ExecutionContext.visual_context`. Pipelines and
  builders can then rely on the typed model instead of reading `options.metadata`
  directly.

Use this pattern whenever a visual needs structured context. Start by
subclassing `VisualContextModel` and let Praeparo handle instantiation and
validation.

## Context Files (`--context`)

`praeparo visual ... --context <file>` accepts JSON or YAML payloads and merges
them into the visual context.

For the full layered merge order, supported file shapes, and schema-generation
details, see [Context Layers](../projects/context_layers.md).

The typed model still works the same way: the CLI merges the effective payload,
validates it against the registered visual context model, and stores the
result on `ExecutionContext.visual_context`.

Example (pack-shaped context file used with `praeparo visual ...`):

```yaml
schema: example_pack
context:
  project_id: 201
  project_name: "Example Project"
calculate:
  project: "'dim_project'[ProjectId] = {{ project_id }}"
slides: []
```
