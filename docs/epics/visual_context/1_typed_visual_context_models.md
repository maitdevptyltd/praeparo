# Epic: Typed Visual Context Models (Phase 1)

> Status: **Complete** – typed visual context models now flow from Praeparo into custom visuals; ad hoc metadata parsing for generic context is no longer required.

- Canonical developer docs live in `docs/visuals/visual_context_model.md` and `docs/visual_model_architecture.md`.

## 1. Problem

After the early visual-driven DAX-backed pipeline work, custom visual pipelines
were:

- visual-driven (`BaseVisualConfig` + metric catalogue),
- backed by Praeparo’s `MetricDatasetBuilder`,
- integrated with Praeparo’s `ExecutionContext` and `PipelineOptions`.

However, there was still an extra mapping layer in downstream projects:

- custom visuals defined their own local context objects and discovery helpers,
  which:
  - re-parsed `ExecutionContext.options.metadata` and
    `ExecutionContext.options.data` into custom dataclasses,
  - duplicated generic concepts such as `metrics_root`, `seed`, `scenario`,
    `ignore_placeholders`, and `grain`.
- the rights and responsibilities were blurred:
  - Praeparo was already the place where CLI arguments and pack context were
    resolved into an `ExecutionContext` with `PipelineOptions` /
    `PipelineDataOptions`,
  - yet each custom visual still had to do its own metadata parsing and
    normalization whenever it needed metrics roots, seeds, scenario, or grain.

This led to:

- **Double handling** – visuals re-derived values from metadata that Praeparo
  already had or could reasonably know.
- **Weak typing at the edge** – visuals received a raw `Dict[str, object]` for
  metadata and had to remember which keys meant what.
- **Boilerplate in every custom visual** – each visual needed helpers to
  normalize filters, flags, and paths from metadata instead of receiving a
  typed context object.

The net effect: pipelines spent non-trivial effort “parsing context” instead of
focusing on schema, dataset, and rendering.

## 2. Goal

Phase 1 should:

1. **Introduce typed visual context models in Praeparo**:
   - a base `VisualContextModel` holding generic context fields used by many
     DAX-backed visuals (for example `metrics_root`, `seed`, `scenario`,
     `ignore_placeholders`, `grain`);
   - a mechanism for each visual type to register a context model that extends
     the base with visual-specific fields.
2. **Have the Praeparo CLI construct and attach a typed context instance**:
   - CLI parses arguments, context files, and meta flags once;
   - it instantiates the context Pydantic model for the visual and stores it on
     `ExecutionContext` (for example `ExecutionContext.visual_context`).
3. **Simplify custom visuals to consume the typed context directly**:
   - remove local context-discovery helpers for generic concerns;
   - in visual pipelines and builders, consume `context.visual_context`
     directly.
4. **Avoid further metadata parsing for generic concerns**:
   - custom visuals should not read individual keys from
     `context.options.metadata` for generic framework concepts;
   - metadata dictionaries should become a legacy/escape hatch rather than a
     primary API.

The end state: **Pydantic models at the framework edge**, custom visuals focus
on the three pillars (schema, dataset, rendering) using a typed context, and
metadata dictionaries are no longer the primary contract for generic context.

## 3. Proposed Architecture

### 3.1 VisualContextModel in Praeparo

In Praeparo core (for example `praeparo/visuals/context_models.py`), introduce:

```python
from pathlib import Path
from typing import Tuple
from pydantic import BaseModel, Field


class VisualContextModel(BaseModel):
    """Base typed context passed to visual pipelines."""

    metrics_root: Path = Field(default=Path("registry/metrics"))
    seed: int = 42
    scenario: str | None = None
    ignore_placeholders: bool = False
    grain: Tuple[str, ...] | None = None

    class Config:
        arbitrary_types_allowed = True
```

Responsibilities:

- represent common, cross-cutting context that:
  - currently flows through `ExecutionContext.options.metadata` and/or
    `MetricDatasetBuilderContext.discover(...)`,
  - should be validated once at the CLI boundary;
- serve as a base class for visual-specific context models.

### 3.2 Visual-specific context models

Custom visuals can extend the base model with fields that only make sense for
that visual family:

```python
from datetime import date
from typing import Literal

from praeparo.visuals.context_models import VisualContextModel


class CustomVisualContextModel(VisualContextModel):
    column_strategy: Literal["registry", "trailing_months"] = "registry"
    trailing_months: int = 3
    reference_date: date | None = None
    customer: str | None = None
```

Notes:

- generic fields (`metrics_root`, `seed`, `scenario`, `ignore_placeholders`,
  `grain`) are inherited from `VisualContextModel` and are not re-declared;
- visual-specific fields live only on the derived model.

### 3.3 Extend visual registration to accept a context model

In Praeparo’s visual registry (for example `praeparo/visuals/registry.py`),
extend `VisualTypeRegistration` to include an optional `context_model`:

```python
from typing import Type
from praeparo.visuals.context_models import VisualContextModel


class VisualTypeRegistration(BaseModel):  # or dataclass
    ...
    context_model: Type[VisualContextModel] | None = None
```

When a project registers a custom visual, it can provide:

```python
register_visual_type(
    "custom_visual",
    loader=_custom_visual_loader,
    overwrite=True,
    cli=_CUSTOM_CLI_OPTIONS,
    context_model=CustomVisualContextModel,
)
```

This signals to the CLI that it should construct a
`CustomVisualContextModel` instance when preparing to execute that visual.

### 3.4 Attach typed context to ExecutionContext

Enhance `ExecutionContext` in Praeparo (`praeparo/pipeline/core.py`) to carry
an optional, per-visual context instance that is strongly typed:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, Optional, TypeVar

from praeparo.visuals.context_models import VisualContextModel


ContextT = TypeVar("ContextT", bound=VisualContextModel)


@dataclass
class ExecutionContext(Generic[ContextT]):
    config_path: Path | None = None
    project_root: Path | None = None
    case_key: str | None = None
    options: PipelineOptions = field(default_factory=PipelineOptions)
    visual_context: Optional[ContextT] = None
```

In the CLI (`praeparo/cli/__init__.py`), after building `metadata` and
`PipelineOptions`, resolve and instantiate the context model (if any):

1. look up the visual registration and its `context_model`;
2. build a `raw_context` dict from:
   - CLI args (`--metrics-root`, `--seed`, `--scenario`, `--grain`,
     `--ignore-placeholders`, visual-specific flags),
   - context file payload (merged via existing `--context` handling),
   - any metadata keys that remain relevant;
3. instantiate the model:

   ```python
   if context_model is not None:
       visual_context = context_model.model_validate(raw_context)
   else:
       visual_context = None
   ```

4. construct `ExecutionContext` with `visual_context` populated inside
   Praeparo:

   ```python
   context = ExecutionContext(
       config_path=args.config,
       project_root=_project_root_for(args.config),
       case_key=args.config.stem,
       options=options,
       visual_context=visual_context,
   )
   ```

From this point on, custom pipelines can cast `context.visual_context` to
their own Pydantic model and avoid touching raw `metadata` for generic
concerns.

### 3.5 Custom pipelines consume typed context

Once typed context is available:

- downstream projects can remove local context dataclasses and discovery
  helpers used only for generic concerns;
- schema, dataset, and DAX builders can consume `context.visual_context`
  directly:

  ```python
  from praeparo.pipeline import ExecutionContext


  def _schema_builder(..., context: ExecutionContext) -> SchemaArtifact[...]:
      custom_ctx = context.visual_context
      if not isinstance(custom_ctx, CustomVisualContextModel):
          raise TypeError("Expected CustomVisualContextModel in ExecutionContext.visual_context.")

      # Use custom_ctx.metrics_root, custom_ctx.seed, custom_ctx.reference_date, etc.
      ...
  ```

- dataset and render builders can likewise consume the typed model directly,
  instead of re-parsing generic metadata.

## 4. Validation

Once implemented:

- Praeparo tests should confirm:
  - typed `VisualContextModel` instances are created from CLI/context-layer
    inputs,
  - `ExecutionContext.visual_context` carries the registered model,
  - custom visuals can consume the typed context without bespoke metadata
    parsing.
- downstream visual tests should confirm local context-discovery helpers for
  generic concerns are no longer required.

Run:

- Praeparo:
  - `poetry run pytest`
  - `poetry run pyright`

## 5. Follow-ups

- Extend the typed context model with more shared surfaces when additional
  generic context becomes stable.
- Keep active documentation in `docs/visuals/visual_context_model.md` aligned
  with the concrete model fields and lifecycle.
