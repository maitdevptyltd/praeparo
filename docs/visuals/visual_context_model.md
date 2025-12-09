# Visual Context Models

Praeparo now supports typed visual context objects that are instantiated at the CLI boundary and attached to `ExecutionContext.visual_context`.

- **Base model:** `VisualContextModel` (`praeparo.visuals.context_models`) captures generic knobs used by DAX-backed visuals:
  - `metrics_root: Path = Path("registry/metrics")`
  - `seed: int = 42`
  - `scenario: str | None = None`
  - `ignore_placeholders: bool = False`
  - `grain: tuple[str, ...] | None = None`
- **Visual-specific models:** custom visuals can extend the base model to add their own fields. Register them via `register_visual_type(..., context_model=MyContextModel)`.
- **Lifecycle:** the CLI merges CLI flags, context files (`--context`), and metadata into a raw dictionary, validates it against the registered context model, and stores the result on `ExecutionContext.visual_context`. Pipelines and builders can then rely on the typed model instead of parsing `options.metadata`.

Use this pattern whenever a visual needs structured context—start by subclassing `VisualContextModel` and let Praeparo handle instantiation and validation.
