# Phase 18: Pack Concurrent Exports For DAX-Backed Visuals

> Status: **Draft** – design for concurrent execution of non-Power BI pack visuals without breaking artifact determinism or downstream snapshot/render pipelines.

Use this page as implementation history for the proposed non-Power BI pack
concurrency work. The current supported pack contract still lives in
[Projects / Pack Runner](../../projects/pack_runner.md).

## 1. Purpose

Phase 15 introduced a bounded Power BI export queue for `type: powerbi`
slides. Packs that mix Power BI slides with DAX-backed visuals can still spend
most of their wall-clock time on serial execution of the non-Power BI visuals.

This phase proposes bounded concurrent execution for DAX-backed/non-Power BI
pack visuals so packs can:

- plan once,
- execute more than one eligible visual at a time,
- and preserve the same artifact and PPTX contracts used by the existing pack
  runner.

## 2. Background

Current behavior:

- Power BI visuals are enqueued into the existing bounded export queue.
- Non-Power BI visuals still execute synchronously on the main thread.

This phase focuses on the second category while keeping the existing Power BI
queue intact.

## 3. Scope

### 3.1 In scope

1. Concurrent execution for non-Power BI visuals during pack runs.
2. DAX-backed visual types as the primary target, including:
   - matrix/cartesian planners,
   - Python visuals that execute shared metric/dataset builders,
   - placeholder-bound visuals in multi-slot templates.
3. Deterministic result ordering and stable artifact output paths.

### 3.2 Out of scope

- metric logic changes,
- schema changes,
- a full async/`asyncio` pack runner rewrite,
- unbounded concurrency.

## 4. Target Behavior

### 4.1 Planning remains single-pass

For a given `praeparo pack run <pack.yaml>`:

1. Resolve layered context and pack context.
2. Resolve root and slide-level metric bindings when present.
3. Render templated `filters`, `calculate`, and `define`.
4. Resolve each `visual.ref` to a typed visual config.
5. Prepare one execution job per slide/placeholder visual.

### 4.2 Execution fans out after planning

After planning:

- Power BI visuals continue to use the existing queue.
- Eligible non-Power BI visuals are submitted to a separate bounded queue.
- The runner drains both queues, then assembles the final slide/placeholder
  result maps in pack order.

The goal is concurrency in execution, not concurrency in planning or output
assembly.

### 4.3 Failure semantics

The runner should keep the same pack-friendly failure model:

- aggregate failures into a final summary,
- keep successful outputs when partial-mode workflows allow it,
- avoid first-failure-wins behavior that makes concurrent runs harder to debug.

## 5. Concurrency Model

### 5.1 Thread-based execution

This phase assumes a bounded thread-pool model, matching the existing Power BI
queue, rather than making the pack runner itself asynchronous.

### 5.2 Concurrency knobs

Illustrative contract:

- `--max-visual-concurrency N`
- optional env var such as `PRAEPARO_PACK_MAX_VISUAL_CONCURRENCY`
- conservative default, likely `1` until downstream renderers are validated
  under concurrency

`--max-pbi-concurrency` remains a separate knob for Power BI exports.

### 5.3 Shared backend pressure

If DAX-backed visuals and Power BI exports both execute concurrently, shared
backend pressure may still need an additional limiter inside Praeparo's
execution layer. That is an upstream concern and remains unresolved in this
draft.

## 6. Downstream Visual Safety

Before this phase can be enabled by default, downstream snapshot/render
pipelines need to be concurrency-safe.

Known classes of blockers include:

- fixed preview/server ports that collide across concurrent jobs,
- per-render rebuild steps that mutate the same build output folder,
- and non-thread-safe renderer state in custom visual implementations.

Until those surfaces are safe, this phase should remain behind an explicit
concurrency flag or allowlist.

## 7. Work Breakdown

### 7.1 Upstream work

1. Generalize or complement the existing queue abstraction for non-Power BI
   visuals.
2. Integrate queue submission/draining into the pack runner while preserving
   slide ordering.
3. Add CLI flags/help text and pack-runner docs.
4. Add tests for ordering, error aggregation, and bounded execution.

### 7.2 Downstream work

Consumers with custom snapshot/render pipelines need to:

1. make preview/build steps safe under concurrency,
2. avoid fixed shared ports/output directories where possible,
3. and validate that concurrent runs remain deterministic.

## 8. Validation Plan

Suggested validation once implemented:

```bash
poetry run praeparo pack run \
  projects/example/pack.yaml \
  --artefact-dir out/example/pack \
  --max-pbi-concurrency 5 \
  --max-visual-concurrency 3
```

Acceptance criteria:

- no renderer/build collisions,
- stable artifact paths,
- results still returned in slide order,
- and clear aggregated error summaries when failures occur.

## 9. Risks And Rollback

Risks include:

- shared backend throttling,
- CPU/RAM pressure from concurrent renderers,
- and non-thread-safe visual implementations.

The safe rollback path is to keep concurrent non-Power BI execution disabled by
default and document serial debugging mode with both concurrency flags set to
`1`.
