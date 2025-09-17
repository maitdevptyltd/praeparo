# Visual Model Architecture

Praeparo parses YAML into Pydantic models that describe each visual. The loader operates against a discriminated union so new visuals can be added without bespoke loader functions.

## Base Concepts

- `BaseVisualConfig` (in `praeparo.models.visual_base`) provides shared fields (`type`, `title`, `description`) and a `resolve()` hook that can load nested visuals.
- Concrete visuals such as `MatrixConfig` and `FrameConfig` inherit from `BaseVisualConfig` and specify `type: Literal[...]` so the union can discriminate between them.
- The YAML loader merges `compose` chains, applies overrides, renders any templated values, then validates the payload through a single `TypeAdapter` built from the union.

## Adding a New Visual Type

1. Create a Pydantic model that subclasses `BaseVisualConfig`.
   ```python
   class ColumnConfig(BaseVisualConfig):
       type: Literal["column"]
       dataset: str
       series: list[SeriesConfig]
   ```
2. Implement any normalisation or validation logic with Pydantic validators.
3. Override `resolve()` only when the visual needs to recursively load referenced visuals or external resources.
4. Update `VisualConfigUnion` in `praeparo/io/yaml_loader.py` to include the new model so the loader recognises it.
5. Add tests and documentation for the new visual type.

## Parameters vs Overrides

When a visual references another YAML file (for example inside a frame), two mechanisms control the child payload:

- **Parameters** – merged into the child’s `parameters` mapping, converted to strings, and used as template context before validation. Parameters do not alter the schema; they purely affect templated fields.
- **Overrides** – any additional keys on the child definition that are not `ref` or `parameters`. Overrides are deep-merged into the child YAML before validation and stored on `FrameChildConfig.overrides` for traceability.

Use parameters for contextual values (e.g. labels, filter expressions) and overrides for structural tweaks (e.g. swapping the child title or adding an extra filter block).
