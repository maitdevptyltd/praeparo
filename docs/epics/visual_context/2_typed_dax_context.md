# Epic: Typed DAX Context for Global Calculate/Define (Phase 2)

> Status: **Complete** – global DAX `calculate` / `define` context now flows through typed models in Praeparo.

- Canonical developer docs live in `docs/visuals/visual_context_model.md`, `docs/projects/context_layers.md`, and `docs/visuals/python_metric_dataset_builder.md`.

## 1. Problem

Global DAX context (visual- or pack-level `calculate` / `define`) used to be
carried around as weakly typed metadata:

- the Praeparo CLI accepted:
  - `--calculate EXPR` flags,
  - `--define EXPR` flags, and
  - a `--context` file whose payload could include:
    - `calculate: [...]`
    - `define: | ...`
- `_prepare_context_payload` merged those into a `metadata["context"]` dict;
- downstream planners and pipelines read `metadata["context"]` and manually
  normalized it into:
  - `global_filters` for DAX `CALCULATE` wrappers, and
  - `define_blocks` for `DEFINE` statements.

This had several drawbacks:

- **Weak typing** – `context` was just `dict[str, object]`; filters and define
  blocks were normalized at the edges using helpers like
  `normalise_filter_group` and `normalise_define_blocks`.
- **Duplicated parsing** – visual pipelines and dataset builders repeatedly
  pulled out `context["calculate"]` / `context["define"]` and normalized them,
  instead of consuming a single typed model.
- **Mixed responsibilities** – CLI, dataset builders, and visuals each knew a
  little bit about context structure, but there was no single, typed source of
  truth for “this is the DAX context for this visual”.

After Phase 1, custom visuals received a typed `visual_context` model
(`VisualContextModel`) via `ExecutionContext`, but DAX context still flowed
through `metadata["context"]`.

## 2. Goal

Phase 2 should:

1. Introduce a **typed DAX context model** in Praeparo that captures global
   `calculate` / `define` for a visual in a strongly typed, validated form.
2. Have the CLI build and attach this DAX context exactly once from:
   - `--calculate` / `--define` flags;
   - `--context` file payload (when present).
3. Make `MetricDatasetBuilderContext.discover(...)` and downstream dataset
   builders consume this typed DAX context instead of re-parsing
   `metadata["context"]`.
4. Remove manual parsing of `context["calculate"]` / `context["define"]` from
   typed DAX-backed pipelines and instead:
   - read global filters and define blocks from the typed DAX context attached
     to `ExecutionContext` / `MetricDatasetBuilderContext`.
5. Keep backwards compatibility for visuals and plugins that still rely on
   `metadata["context"]`, while encouraging migration to the typed model.

The end state: global DAX context is a **first-class, typed object** passed
through the pipeline, not an ad-hoc dict.

## 3. Proposed Architecture

### 3.1 DAXContextModel in Praeparo

In Praeparo (for example `praeparo/visuals/dax_context.py`), introduce a typed
DAX context model:

```python
from typing import Tuple
from pydantic import BaseModel, Field


class DAXContextModel(BaseModel):
    """Global DAX context (calculate/define) for a visual execution."""

    calculate: Tuple[str, ...] = Field(default_factory=tuple)
    define: Tuple[str, ...] = Field(default_factory=tuple)
```

Responsibilities:

- represent the fully normalized global DAX context for a visual run:
  - `calculate` – a tuple of filter expressions suitable for `CALCULATE`;
  - `define` – a tuple of `DEFINE` blocks;
- provide a single place to:
  - enforce any syntactic validation we want for DAX fragments, and/or
  - apply normalization helpers once (for example deduplicating filters).

### 3.2 Integrate DAXContextModel with VisualContextModel

Extend `VisualContextModel` (introduced in Phase 1) so typed visual contexts
carry DAX context via composition rather than duplicated fields:

```python
from pathlib import Path
from typing import Tuple
from pydantic import BaseModel, Field


class VisualContextModel(BaseModel):
    metrics_root: Path = Field(default=Path("registry/metrics"))
    seed: int = 42
    scenario: str | None = None
    ignore_placeholders: bool = False
    grain: Tuple[str, ...] | None = None

    # New in Phase 2: strongly-typed DAX context attached to every visual.
    dax: DAXContextModel = Field(default_factory=DAXContextModel)

    class Config:
        arbitrary_types_allowed = True
```

Callers then access global DAX context as `ctx.dax.calculate` and
`ctx.dax.define`, keeping the DAX-specific fields encapsulated in a dedicated
model while still making them easy to consume from the visual context.

### 3.3 CLI: build DAX context once

In `praeparo/cli/__init__.py`, adjust `_prepare_context_payload` and
`_prepare_metadata` to:

1. continue to support existing behavior:
   - `--calculate` / `--define` flags;
   - `--context` file with `calculate` / `define` keys;
2. instead of writing a nested `metadata["context"]` blob and expecting each
   visual to re-interpret it, populate the DAX fields on the visual context
   model:

   - when constructing `raw_context` for the visual’s `context_model`, include:

     ```python
     raw_context["dax"] = {
         "calculate": tuple(all_calculate_filters),
         "define": tuple(all_define_blocks),
     }
     ```

   - `all_calculate_filters` and `all_define_blocks` should be the merged
     result of:
     - CLI `--calculate` / `--define` flags;
     - context file `calculate` / `define` entries.

3. for backwards compatibility, `metadata["context"]` can still be populated
   as before (for visuals that do not opt into typed context), but DAX-aware
   visuals should prefer `visual_context.dax`.

### 3.4 MetricDatasetBuilderContext consumes typed DAX context

In `praeparo/datasets/context.py` and `praeparo/datasets/builder.py`:

1. extend `MetricDatasetBuilderContext.discover(...)` to accept the typed DAX
   context directly:

   ```python
   @dataclass(frozen=True)
   class MetricDatasetBuilderContext:
       ...
       global_filters: tuple[str, ...] = field(default_factory=tuple)
       define_blocks: tuple[str, ...] = field(default_factory=tuple)
       ...

       @classmethod
       def discover(
           cls,
           *,
           project_root: str | Path | None = None,
           metrics_root: str | Path | None = None,
           ...
           calculate: Sequence[str] | str | None = None,
           define: Sequence[str] | str | None = None,
           visual_context: VisualContextModel | None = None,
       ) -> "MetricDatasetBuilderContext":
           ...
   ```

2. resolution rules:

   - if `visual_context` is provided and has DAX context:
     - use those values as the primary sources for `global_filters` /
       `define_blocks`;
   - fallback:
     - honor explicit `calculate` / `define` parameters if present;
     - continue to normalize them via `normalise_filters` /
       `normalise_define_blocks`.

3. `MetricDatasetBuilder` should continue to use `context.global_filters` and
   `context.define_blocks` as before; the difference is only where those fields
   are populated from.

### 3.5 DAX-backed pipelines use typed DAX context

Once Phase 2 is in place, DAX-backed visuals should:

- stop reading `metadata.get("context", ...)` for global calculate/define;
- pass the typed visual context into `MetricDatasetBuilderContext.discover(...)`
  so the builder inherits global DAX state directly;
- remove helper functions that parse `metadata["context"]` solely to derive
  calculate/define fragments.

The only remaining visual-specific DAX decisions should be filters that are
truly owned by that visual or declared directly in authored YAML.

## 4. Migration & Backwards Compatibility

### 4.1 Visuals without typed context

For visuals that do not yet have a `context_model`:

- CLI should continue to populate `metadata["context"]` as before;
- dataset builders can continue to read and normalize `metadata["context"]`;
- Phase 2 should not break existing behavior; it should only provide a
  higher-quality path for visuals that opt into typed context.

### 4.2 Typed visual pipelines and datasets

Migration steps for typed DAX-backed visuals:

1. implement the Praeparo-side DAX context changes;
2. update dataset builders to use `visual_context` for:
   - global DAX filters (`dax.calculate`);
   - global `DEFINE` blocks (`dax.define`);
3. remove context-extraction helpers that read `metadata["context"]` solely to
   derive calculate/define fragments.

## 5. Validation

Once Phase 2 is implemented:

- typed contexts:
  - `VisualContextModel.dax.calculate` / `.define` should reflect merged global
    filters and define blocks for:
    - `praeparo visual ... --calculate/--define`;
    - `praeparo visual ... --context global_context.yaml`;
    - pack-driven runs (`praeparo pack run ...`) where context is defined at
      the pack or slide level;
- dataset builder:
  - `MetricDatasetBuilderContext.global_filters` and `define_blocks` should
    match those typed fields;
  - dataset tests should assert that global DAX filters are correctly applied
    via the typed context, not via metadata parsing.

## 6. Completion Notes

This phase is now implemented in Praeparo:

- `VisualContextModel` carries `dax: DAXContextModel`;
- CLI and pack-run flows populate typed calculate/define once;
- `MetricDatasetBuilderContext` consumes that typed DAX state;
- DAX-backed pipelines can rely on `visual_context.dax` instead of reparsing
  `metadata["context"]`.
