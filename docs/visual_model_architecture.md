# Visual Model Architecture

Praeparo parses YAML into Pydantic models that describe each visual. Built-in
visual families use a discriminated union where that keeps the loader simple,
while plugin visuals register their runtime loader and schema branch explicitly
without editing Praeparo core unions.

## Developer API Overview

- All visuals inherit from `BaseVisualConfig` (`praeparo.models.visual_base`) which
  defines shared metadata (`type`, `title`, `description`) and a `resolve()` hook
  for deferred loading.
- `praeparo.visuals` provides registration utilities (`register_visual_type`,
  `register_visual_schema`, `load_visual_definition`) and reusable config
  primitives (`VisualMetricConfig`,
  `VisualGroupConfig`, mock helpers) so projects can add custom visuals without
  writing bespoke loader code.
- Concrete visuals such as `MatrixConfig` or `FrameConfig` subclass
  `BaseVisualConfig`, declare `type: Literal["..."]`, and add their visual-specific
  fields.
- `VisualConfigUnion` (in `praeparo.io.yaml_loader`) aggregates the built-in
  core models that still benefit from one shared `TypeAdapter`.
- Plugin visuals are registered through `register_visual_type(...)` for runtime
  loading and `register_visual_schema(...)` for umbrella-schema export.

## Creating a Visual Model

### Pydantic Model Skeleton

```python
from typing import Literal

from praeparo.models.visual_base import BaseVisualConfig


class ColumnConfig(BaseVisualConfig):
    type: Literal["column"]
    dataset: str
    series: list[SeriesConfig]

    def resolve(self, ctx: ResolveContext) -> ResolvedVisual:
        # Only implement when the visual needs to load nested resources.
        return super().resolve(ctx)
```

### YAML Example

```yaml
# visuals/column/revenue.yaml
type: column
title: Quarterly revenue
dataset: finance/revenue
series:
  - label: FY24
    measure: SUM([Revenue])
```

### Loader Flow

1. The YAML loader merges any `compose` chain, applies overrides, and renders
   templated values with the provided parameters.
2. Built-in families are validated through the `TypeAdapter` built from
   `VisualConfigUnion`; plugin families are routed through the explicit visual
   registry after their plugin module is imported.
3. The resulting config is returned as a typed `BaseVisualConfig` subclass which
   can be rendered to DAX or Plotly outputs downstream.

## Parameters vs Overrides

When a visual references another YAML file (for example inside a frame), two
mechanisms control the child payload:

- **Parameters** – merged into the child’s `parameters` mapping, converted to
  strings, and used as template context before validation. Parameters do not
  alter the schema; they purely affect templated fields.
- **Overrides** – any additional keys on the child definition that are not `ref`
  or `parameters`. Overrides are deep-merged into the child YAML before
  validation and stored on `FrameChildConfig.overrides` for traceability.

Matrix visuals expose both `define:` and `calculate:` blocks at the root level.
`define:` behaves like a standard DAX `DEFINE` section for staging measures,
while `calculate:` lets authors declare slicer-style predicates that Praeparo
injects into the generated `CALCULATETABLE`. Both blocks support template
placeholders powered by the merged parameter context.

Downstream visuals can reuse the same split by typing their `calculate` payloads
as `ScopedCalculateFilters`, which accepts shorthand strings/lists as DEFINE
predicates and `{define, evaluate}` mappings for fine-grained scoping.

Use parameters for contextual values (e.g. labels, filter expressions) and
overrides for structural tweaks (e.g. swapping the child title or adding an extra
filter block).

## Status

### Progress

- Core visuals (`MatrixConfig`, `FrameConfig`, and supporting models) are loaded
  through the discriminated union without bespoke resolver code.
- Compose/override handling is exercised in both pipeline and integration tests,
  ensuring parameters and deep merges resolve consistently.

### Next Steps

- Document additional concrete visuals as they land so developers can reference
  the expected fields and example YAML in one place.
- Expand examples to show nested `FrameConfig` scenarios once more child visuals
  are implemented.

### Blockers & Risks

- Plugin visuals now have two explicit registration steps: runtime loading via
  `register_visual_type(...)` and editor/schema support via
  `register_visual_schema(...)`. Skipping either step leads to runtime/editor
  drift for downstream workspaces.
- The loader assumes templates resolve to strings; templated values that should
  remain structured (e.g. lists) need explicit documentation before adoption.
