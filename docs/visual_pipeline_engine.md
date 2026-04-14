# Visual Pipeline Engine

## Purpose

Praeparo needs one path that can take a visual definition and turn it into
output, whether that output is HTML, PNG, or another artefact. Earlier work
spread the same steps across the CLI, tests, and helper code. Keeping that
flow in one place makes new visuals easier to add and keeps data resolution
consistent. This document describes the public shape of that flow so future
changes follow the same pattern.

## Developer API Overview

- `praeparo.pipeline.core.VisualPipeline` is the entry point. Callers pass a
  resolved visual config and an `ExecutionContext`. The pipeline uses a
  `QueryPlannerProvider` to choose the right planner and returns a
  `VisualExecutionResult` with the generated plans, written files, and rendered
  output.
- Visuals register through `praeparo.pipeline.register_visual_pipeline`. Each
  registration supplies a **schema builder**, **dataset builder**, and
  **renderer** so new visual types can plug into the same flow without changing
  Praeparo core code.
- `QueryPlannerProvider` maps a visual config to the right planner
  (`MatrixQueryPlanner`, `ColumnQueryPlanner`, and so on). That keeps the
  engine focused on the shared flow instead of any one visual type.
- Visual-specific behaviour lives in strategy classes registered against
  `VisualPipeline`. Strategies handle planning, data collection, and rendering
  as one sequence.
- Runtime switches live in `PipelineOptions`. This includes desired outputs,
  validation flags, and `PipelineDataOptions`, which stores datasource
  overrides and planner hints.
- `ExecutionContext.dataset_context` carries the already-discovered dataset
  environment for DAX-backed visuals. Reuse it across schema, dataset, planner,
  and renderer stages instead of finding the same roots again in each visual.
- Query planning and data collection are split into two parts:
  - **`MatrixQueryPlanner` (and future `ColumnQueryPlanner`, etc.)** builds the `DaxQueryPlan`, calls a `DaxExecutionClient`, and turns the response into the dataset the visual expects. Planners know the visual rules but not the transport details.
  - **`DaxExecutionClient`** runs the DAX and returns raw rows. It owns authentication, HTTP clients, retries, and environment setup. The planner sends a plan and gets rows back.
- `praeparo.metrics.MetricDaxBuilder` compiles YAML metric definitions into
  reusable DAX snippets. Visual pipelines should pass those snippets to
  `praeparo.visuals.dax.render_visual_plan` rather than building DAX by hand,
  then apply any visual-specific naming, ratio, or SLA rules after compilation.
- `praeparo.pipeline.providers` will be restructured as a package:
  - `provider.py`: definitions for `QueryPlannerProvider`, plus the default implementation that VisualPipeline consumes.
  - `matrix/planners/`: concrete matrix planners (mock, DAX-backed) that adhere to a generic planner protocol.
  - `column/planners/`, etc.: future planner modules for other visual types.
  - `dax/clients/`: implementations of `DaxExecutionClient` such as `PowerBIDaxClient`, Fabric adapters, or fixtures that replay captured responses.
  - `registry.py` / `resolvers.py`: helpers used by planners that still need case-based overrides or datasource lookups (wrapping todays registry/resolver behaviour).
- Output creation remains decoupled through `OutputTarget` instances. The core engine renders a Plotly figure once and hands it to whichever output adapters were requested in `PipelineOptions`, including browser-readable HTML bundles and PNG captures.

## Artefacts and Outputs

Visual runs produce a small bundle of files rather than a single opaque export.

- The schema builder and dataset builder write their outputs into the chosen
  artefact folder first. The renderer, CLI, and preview tools then reuse those
  same files.
- HTML exports are meant to be opened from a folder. The entry page sits beside
  the schema, data, and copied assets so the bundle can be moved or served
  locally without rerunning the visual.
- PNG exports capture the rendered figure after Praeparo resolves the data,
  layout, and sizing. They usually live in the same folder as the HTML bundle
  so preview and capture flows stay together.
- Shared preview workflows should use the same artefact folder for a given
  visual run. That keeps HTML, PNG, and diagnostics together and makes it easy
  to compare the rendered result with the underlying data.
- `praeparo visual artifacts <visual-type> <visual.yaml> [dest]` is the command
  to use when you only need the artefact bundle.
- `praeparo visual run <visual-type> <visual.yaml> [dest]` is the command to
  use when you want Praeparo to render the visual from that bundle in the same
  run.

## Example Usage

```python
from pathlib import Path

from praeparo.io.yaml_loader import load_visual_config
from praeparo.pipeline import (
    ExecutionContext,
    OutputTarget,
    PipelineDataOptions,
    PipelineOptions,
    VisualPipeline,
)
from praeparo.pipeline.providers.dax.clients import PowerBIDaxClient
from praeparo.pipeline.providers.matrix.planners.dax import DaxBackedMatrixPlanner
from praeparo.pipeline.providers.provider import DefaultQueryPlannerProvider

# Build the shared DAX execution client once (reads env configuration).
dax_client = PowerBIDaxClient.from_env()

# Register planners the engine knows about.
planner_provider = DefaultQueryPlannerProvider(
    planners={
        "matrix": DaxBackedMatrixPlanner(dax_client=dax_client),
        # "column": ColumnQueryPlanner(...), etc.
    }
)

pipeline = VisualPipeline(
    planner_provider=planner_provider,
)

config_path = Path("visuals/matrix/base.yaml")
config = load_visual_config(config_path)
context = ExecutionContext(
    config_path=config_path,
    options=PipelineOptions(
        data=PipelineDataOptions(datasource_override="sales-live"),
        outputs=[
            OutputTarget.html(Path("build/base.html")),
            OutputTarget.png(Path("build/base.png"), scale=2.0),
        ],
    ),
)

result = pipeline.execute(config, context)
for artifact in result.outputs:
    print(f"Wrote {artifact.kind.value} to {artifact.path}")
```

Tests can swap in `DefaultQueryPlannerProvider` with `MockMatrixPlanner` while leaving the DAX client untouched. Integration suites reuse the same planners but swap the client for `PowerBIDaxClient` plus per-case overrides drawn from environment variables.

When a visual already runs inside a populated `ExecutionContext`, prefer `context.dataset_context` over calling `MetricDatasetBuilderContext.discover(...)` again. That keeps schema generation, metric compilation, and rendering aligned to the same resolved environment.

## Behaviour Summary

1. Load and validate the visual config through the YAML loader.
2. The strategy asks the injected `QueryPlannerProvider` for the appropriate planner.
3. The planner (e.g. `MatrixQueryPlanner`) builds the `DaxQueryPlan`, invokes its configured `DaxExecutionClient` (or mock), and normalises the response into the correct dataset shape.
4. The pipeline writes the schema and dataset builders' outputs to the configured artefact directory (JSON by default) before invoking the renderer.
5. The renderer receives the schema value, dataset value, and requested `OutputTarget`s; it is responsible for producing HTML/PNG snapshots (or other custom artefacts) and returns a `RenderOutcome` that includes the primary figure plus any emitted files. Shared helpers such as `render_visual_plan` keep the DAX query shape centralised, while the visual wrapper keeps downstream naming and presentation rules local to the visual. When the output is HTML, the renderer should preserve schema/data sidecars beside the entry page so the bundle remains inspectable outside the CLI.
6. The pipeline returns a `VisualExecutionResult` that captures the schema value, dataset value, persisted paths, generated plans, and renderer outputs for further processing.

## Provider Architecture

```
QueryPlannerProvider
+-- MatrixQueryPlanner (mock | DAX-backed)
    +-- Builds DaxQueryPlan
    +-- Normalises rows into MatrixResultSet
    +-- Uses DaxExecutionClient
        +-- Authentication / configuration
        +-- Executes DAX and returns raw rows
+-- ColumnQueryPlanner (future)
    +-- Builds column-specific queries
    +-- Shapes column datasets
    +-- Uses DaxExecutionClient or other execution clients
```

This layering keeps business logic (plan building, dataset normalisation) separate from transport logic. New DAX backends (Power BI, Fabric, direct JSON fixtures) simply implement `DaxExecutionClient`. New visual types register their own planners with the `QueryPlannerProvider`.

## Progress

- `VisualPipeline` strategies centralise orchestration for matrix and frame visuals, tested via CLI and snapshot suites.
- Documentation now spells out the planner-provider pattern (`QueryPlannerProvider`, planner interfaces, execution clients) needed before we refactor the runtime.
- DAX-backed visuals now share a single prepared execution context, so schema, dataset, and renderer stages can stay in sync without repeating discovery.
- The artefact bundle contract is now documented as a reusable local-folder export shape for HTML and PNG preview flows.

## Next Steps

1. Implement `QueryPlannerProvider` and refactor `VisualPipeline` to resolve planners through that abstraction rather than the current matrix resolver.
2. Extract `MatrixQueryPlanner` from todays resolver/provider code and introduce a thin adapter so behaviour stays identical while the new interface beds in.
3. Introduce concrete `DaxExecutionClient` implementations (starting with Power BI) and ensure planners depend on clients rather than direct data calls.
4. Offer a convenience builder for environment-driven planner overrides (the integration suite still assembles overrides manually).
5. Introduce planner interfaces for upcoming visuals (e.g. `ColumnQueryPlanner`) and keep them generic so they can return different dataset shapes without touching the pipeline core.
6. Harden output handling with dedicated tests around PNG fallbacks and filesystem failures now that the logic lives in the pipeline.

## Blockers & Risks

- Event loop management must stay centralised; attempting to `asyncio.run()` inside an active loop will raise. Planners should rely on sync wrappers around async clients to avoid nested event loops.
- Misconfigured datasource references will surface as planner/provider errors. Providing first-class helpers for datasource discovery and case overrides is essential.
- Power BI-specific failures should remain quarantined inside the `DaxExecutionClient`. Leaking those exceptions into planners would undo the layering and complicate testing.
- Output targets perform real filesystem writes; tests should continue using temporary directories or disabling outputs to keep snapshot runs deterministic.
