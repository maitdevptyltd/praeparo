# Epic: Centralise MetricDatasetBuilderContext in Praeparo Pipeline (Phase 3)

> Status: **Complete** – Praeparo now derives `MetricDatasetBuilderContext` once per run and attaches it to `ExecutionContext.dataset_context`.

- Canonical developer docs live in `docs/visual_pipeline_engine.md`, `docs/visuals/python_visuals.md`, and `docs/visuals/python_metric_dataset_builder.md`.

## 1. Problem

After Phases 1 and 2, custom visuals received:

- a typed visual config;
- a typed visual context attached to `ExecutionContext.visual_context`,
  including:
  - generic fields such as `metrics_root`, `seed`, `scenario`,
    `ignore_placeholders`, `grain`;
  - DAX context via `dax.calculate` / `dax.define`.

However, dataset plumbing still required each visual to know how to construct
its own `MetricDatasetBuilderContext` by calling `.discover(...)` directly.

- DAX-backed visuals did this in a typed way, passing `visual_context` and
  letting Praeparo derive global filters, define blocks, and `metrics_root`:

  ```python
  builder_context = MetricDatasetBuilderContext.discover(
      project_root=project_root,
      metrics_root=metrics_root,
      default_datasource=data_options.datasource_override,
      case_key=execution.case_key,
      ignore_placeholders=visual_ctx.ignore_placeholders,
      visual_context=visual_ctx,
      metadata=metadata,
      use_mock=use_mock,
  )
  ```

  This was correct, but it still forced each visual to know when and where to
  call `.discover(...)`.

As a result:

- every DAX-backed visual that used `MetricDatasetBuilderContext` repeated the
  same `.discover(...)` pattern in its dataset builder;
- the orchestration layer inside each custom visual still carried boilerplate
  that could live in one framework-level helper.

## 2. Goal

Phase 3 should:

1. Move responsibility for constructing `MetricDatasetBuilderContext` from
   custom visuals into the Praeparo pipeline layer.
2. Give dataset builders a **prepared dataset context** they can use directly,
   rather than expecting them to call `.discover(...)` themselves.
3. Replace manual wiring of `MetricDatasetBuilderContext` with simple
   consumption of the pre-built dataset context.
4. Continue to respect:
   - visual context (`VisualContextModel`) including `metrics_root`, `grain`,
     `scenario`, `ignore_placeholders`, and DAX context;
   - pipeline options (`PipelineOptions.data`) including datasource overrides
     and provider selection.

The end state: custom visuals focus on **what** dataset they want (metrics,
expressions, grain) rather than **how** to create the underlying
`MetricDatasetBuilderContext`.

## 3. Proposed Architecture

### 3.1 Dataset context helper in Praeparo

In Praeparo’s dataset layer (for example `praeparo/datasets/context.py`),
introduce a helper that derives a `MetricDatasetBuilderContext` from existing
execution state instead of requiring each visual to call `.discover(...)`
itself:

- `ExecutionContext[ContextT]` (with a `VisualContextModel`);
- the visual config (`ConfigT`), if needed for grain hints.

For example:

```python
from praeparo.pipeline import ExecutionContext
from praeparo.visuals.context_models import VisualContextModel

def discover_dataset_context(
    execution: ExecutionContext[VisualContextModel],
    *,
    default_grain: Sequence[str] | None = None,
) -> MetricDatasetBuilderContext:
    ...
```

Responsibilities:

- resolve `project_root` and `metrics_root` using the values already on the
  execution context:
  - `execution.project_root` and/or `execution.config_path`;
  - `execution.visual_context.metrics_root` (already normalized by
    `VisualContextModel`);
- derive:
  - `use_mock` from `PipelineOptions.data` (`provider_key` / case overrides);
  - `ignore_placeholders` from `visual_context.ignore_placeholders`;
  - `global_filters` / `define_blocks` from `visual_context.dax.calculate` /
    `.dax.define` (Phase 2);
- carry through `metadata` and any additional execution metadata needed by the
  dataset builder.

### 3.2 Wire discover_dataset_context into VisualPipeline

Once `discover_dataset_context(...)` exists, the VisualPipeline execution
strategy can use it for DAX-backed visuals:

- for visuals that use `MetricDatasetBuilder`, the pipeline can:

  ```python
  dataset_context = discover_dataset_context(
      context,
      default_grain=resolved_default_grain_for_visual,
  )
  ```

- the pipeline then passes this `dataset_context` into the dataset builder,
  instead of requiring the builder to call `.discover(...)` itself.

The recommended implementation is:

1. **Attach dataset context to `ExecutionContext`.**
   - Extend `ExecutionContext` with:

     ```python
     dataset_context: MetricDatasetBuilderContext | None
     ```

   - Resolve it once per run (before schema, dataset, and renderer execute)
     using `discover_dataset_context(...)` and store it on the context so all
     pipeline stages can see the same dataset environment.

2. **Plumb the shared dataset context through all three pillars.**
   - `schema_builder` can ignore it or use it for hints (for example measure
     table);
   - `dataset_builder` uses `context.dataset_context` directly instead of
     calling `.discover(...)`;
   - `renderer` can read `context.dataset_context` when decisions depend on
     dataset-level knobs (for example mock vs live, datasource metadata).

Phase 3 is primarily concerned with getting the **discovery logic** out of
custom visuals; there should be a single framework-level place where
`MetricDatasetBuilderContext.discover(...)` is called, and all three pillars
consume the resulting context via `ExecutionContext`.

### 3.3 DAX-backed visuals consume dataset context

After Phase 3, DAX-backed dataset builders should:

- stop calling `MetricDatasetBuilderContext.discover(...)` directly;
- accept a pre-built `MetricDatasetBuilderContext` (via either
  `ExecutionContext.dataset_context` or an explicit parameter), created by the
  shared helper in Praeparo;
- use that context to construct `MetricDatasetBuilder`:

  ```python
  builder = MetricDatasetBuilder(dataset_context, slug=...)
  ```

- apply only visual-specific details:
  - local date filters or reporting-window logic;
  - metric- or section-level filters declared in the visual YAML;
  - mock series profiles where the visual declares them.

The discover step (`project_root`, `metrics_root`, DAX context, ignore
placeholders, datasource selection) should be entirely framework-owned by this
point; DAX-backed dataset builders should always receive a ready-to-use
`MetricDatasetBuilderContext`.

**2025-12-09 update:** downstream DAX-backed visuals now reject missing
`ExecutionContext` / `dataset_context`, no longer construct those objects
themselves, and tests build the execution + dataset context via Praeparo’s
`discover_dataset_context` helper before invoking artefact builders.

## 4. Migration Plan

1. Implement `discover_dataset_context(...)` and wire it into
   `MetricDatasetBuilderContext.discover(...)` where appropriate.
2. Adopt the helper in at least one reference visual in Praeparo to validate
   the pattern.
3. Update downstream DAX-backed visuals to:
   - use the shared dataset context helper instead of calling `.discover`;
   - remove visual-specific context plumbing that duplicates framework
     knowledge.
4. Document the pattern in Praeparo’s docs so future custom visuals can follow
   it.

## 5. Validation

Once Phase 3 is implemented:

- DAX-backed dataset tests should confirm:
  - `MetricDatasetBuilderContext` is constructed via the new helper;
  - visual code no longer calls `.discover` directly.
- Visuals that adopt the helper should continue to behave identically with less
  boilerplate in their dataset builders.

Run:

- Praeparo tests:
  - `poetry run pytest` under `.submodules/praeparo`;
  - `poetry run pyright` for modified files.
- Downstream tests:
  - build `ExecutionContext` + `dataset_context` via
    `discover_dataset_context(...)` when invoking dataset builders outside the
    pipeline.

Document any remaining DAX-backed visuals or pipelines that still construct
their own `MetricDatasetBuilderContext` so they can be migrated in follow-up
work.
