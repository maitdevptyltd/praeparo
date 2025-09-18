# Visual Pipeline Engine

## Purpose

Praeparo needs a single, reusable execution engine that transforms visual configurations into rendered artefacts regardless of the visual type. Earlier work spread matrix orchestration logic across the CLI, snapshot tests, and integration harnesses. That duplication made it expensive to add visuals (like the upcoming column chart) or to adjust the way datasets are resolved. This document records the intended developer-facing API and layering after the pipeline refactor so future contributors can extend the system consistently.

## Developer API Overview

- `praeparo.pipeline.core.VisualPipeline` is the entry point. Callers provide a resolved visual config plus an `ExecutionContext`. The pipeline depends on a `QueryPlannerProvider` to resolve the appropriate planner for the visual and returns a `VisualExecutionResult` containing generated DAX plans, rendered Plotly figures, dataset objects, and emitted files.
- `QueryPlannerProvider` is the high-level injector that maps a visual configuration to the correct query planner (e.g. `MatrixQueryPlanner`, `ColumnQueryPlanner`). Injecting this provider keeps the engine agnostic of specific visual types and makes new visuals additive rather than invasive.
- Visual-specific behaviour lives in strategy classes registered against `VisualPipeline`. Strategies orchestrate query planning, dataset acquisition, and rendering without duplicating plumbing logic.
- Runtime switches live in `PipelineOptions`. This includes desired outputs, validation flags, and `PipelineDataOptions`, which stores datasource overrides and hints for planner selection.
- Query planning and data acquisition rely on two layers with distinct responsibilities:
  - **`MatrixQueryPlanner` (and future `ColumnQueryPlanner`, etc.)** builds the `DaxQueryPlan`, invokes a `DaxExecutionClient`, and shapes the response into domain-specific datasets. Planners understand visual semantics but assume nothing about the transport.
  - **`DaxExecutionClient`** executes DAX statements and returns raw row data. Clients own authentication, HTTP clients, retry policies, and environment configuration. A planner passes a plan and receives row dictionaries in return.
- `praeparo.pipeline.providers` will be restructured as a package:
  - `provider.py`: definitions for `QueryPlannerProvider`, plus the default implementation that VisualPipeline consumes.
  - `matrix/planners/`: concrete matrix planners (mock, DAX-backed) that adhere to a generic planner protocol.
  - `column/planners/`, etc.: future planner modules for other visual types.
  - `dax/clients/`: implementations of `DaxExecutionClient` such as `PowerBIDaxClient`, Fabric adapters, or fixtures that replay captured responses.
  - `registry.py` / `resolvers.py`: helpers used by planners that still need case-based overrides or datasource lookups (wrapping today’s registry/resolver behaviour).
- Output creation remains decoupled through `OutputTarget` instances. The core engine renders a Plotly figure once and hands it to whichever output adapters (HTML, PNG, JSON) were requested in `PipelineOptions`.

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

## Behaviour Summary

1. Load and validate the visual config through the YAML loader.
2. The strategy asks the injected `QueryPlannerProvider` for the appropriate planner.
3. The planner (e.g. `MatrixQueryPlanner`) builds the `DaxQueryPlan`, invokes its configured `DaxExecutionClient` (or mock), and normalises the response into the correct dataset shape.
4. The strategy renders the Plotly figure(s) and hands them back to `VisualPipeline`.
5. Requested `OutputTarget` adapters serialise the figure into HTML, PNG, JSON, or other artefacts.
6. The pipeline returns a `VisualExecutionResult` suitable for CLI logging, snapshot assertions, or further post-processing.

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

## Next Steps

1. Implement `QueryPlannerProvider` and refactor `VisualPipeline` to resolve planners through that abstraction rather than the current matrix resolver.
2. Extract `MatrixQueryPlanner` from today’s resolver/provider code and introduce a thin adapter so behaviour stays identical while the new interface beds in.
3. Introduce concrete `DaxExecutionClient` implementations (starting with Power BI) and ensure planners depend on clients rather than direct data calls.
4. Offer a convenience builder for environment-driven planner overrides (the integration suite still assembles overrides manually).
5. Introduce planner interfaces for upcoming visuals (e.g. `ColumnQueryPlanner`) and keep them generic so they can return different dataset shapes without touching the pipeline core.
6. Harden output handling with dedicated tests around PNG fallbacks and filesystem failures now that the logic lives in the pipeline.

## Blockers & Risks

- Event loop management must stay centralised; attempting to `asyncio.run()` inside an active loop will raise. Planners should rely on sync wrappers around async clients to avoid nested event loops.
- Misconfigured datasource references will surface as planner/provider errors. Providing first-class helpers for datasource discovery and case overrides is essential.
- Power BI-specific failures should remain quarantined inside the `DaxExecutionClient`. Leaking those exceptions into planners would undo the layering and complicate testing.
- Output targets perform real filesystem writes; tests should continue using temporary directories or disabling outputs to keep snapshot runs deterministic.
