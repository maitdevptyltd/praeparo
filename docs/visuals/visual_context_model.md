# Visual Context Models

Praeparo now supports typed visual context objects that are instantiated at the CLI boundary and attached to `ExecutionContext.visual_context`.

- **Base model:** `VisualContextModel` (`praeparo.visuals.context_models`) captures generic knobs used by DAX-backed visuals:
  - `metrics_root: Path = Path("registry/metrics")`
  - `seed: int = 42`
  - `scenario: str | None = None`
  - `ignore_placeholders: bool = False`
  - `grain: tuple[str, ...] | None = None`
  - `dax: DAXContextModel` – merged global DAX fragments:
    - `calculate: tuple[str, ...]`
    - `define: tuple[str, ...]`
- **Visual-specific models:** custom visuals can extend the base model to add their own fields. Register them via `register_visual_type(..., context_model=MyContextModel)`.
- **Lifecycle:** the CLI merges CLI flags, context files (`--context`), and metadata into a raw dictionary, validates it against the registered context model, and stores the result on `ExecutionContext.visual_context`. Pipelines and builders can then rely on the typed model instead of parsing `options.metadata`.

Use this pattern whenever a visual needs structured context—start by subclassing `VisualContextModel` and let Praeparo handle instantiation and validation.

## Context Files (`--context`)

`praeparo visual ... --context <file>` accepts JSON/YAML payloads and merges them into the visual metadata context.

- **Templating:** the CLI renders `calculate`, `define`, and `filters` using the same Jinja environment as the pack runner, so shared helpers (for example `odata_months_back_range`) behave consistently between `praeparo pack run` and `praeparo visual ...`.
- **Pack-shaped payloads:** if the supplied file looks like a pack (contains `schema` and `slides`), the CLI flattens `context.*` into the base mapping and uses that same `context` mapping as the Jinja template context.
- **Named calculate overrides:** `calculate` supports string/list/dict inputs; when dicts are used, later sources override earlier keys (last-writer-wins) before the final list is normalised for DAX execution.

Example (pack-shaped context file used with `praeparo visual ...`):

```yaml
schema: example_pack
context:
  lender_id: 201
calculate:
  lender: "'dim_lender'[LenderId] = {{ lender_id }}"
slides: []
```
