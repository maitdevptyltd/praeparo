# Visual Model Architecture

Praeparo parses YAML into Pydantic models that describe each visual. The loader
operates against a discriminated union so new visuals can be added without bespoke
loader functions.

## Developer API Overview

- All visuals inherit from `BaseVisualConfig` (`praeparo.models.visual_base`) which
  defines shared metadata (`type`, `title`, `description`) and a `resolve()` hook
  for deferred loading.
- Concrete visuals such as `MatrixConfig` or `FrameConfig` subclass
  `BaseVisualConfig`, declare `type: Literal["..."]`, and add their visual-specific
  fields.
- `VisualConfigUnion` (in `praeparo.io.yaml_loader`) aggregates the concrete
  models and feeds a single `TypeAdapter` so the YAML loader can validate a
  document without custom branching logic.

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
2. The merged payload is validated through the `TypeAdapter` built from
   `VisualConfigUnion`.
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

- Adding a new visual requires updating both `VisualConfigUnion` and the
  generated JSON schema; skipping either step leads to runtime validation gaps
  and stale IntelliSense for downstream tooling.
- The loader assumes templates resolve to strings; templated values that should
  remain structured (e.g. lists) need explicit documentation before adoption.
