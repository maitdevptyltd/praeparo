# Epic: Pre-Execution DAX Artifacts And Pack Error Context (Phase 7)

> Status: **Implemented** - Praeparo writes compiled `.dax` plans before execution on DAX-backed paths and wraps failing pack slides with structured pack, slide, phase, and artifact context (2026-04-15).

- Canonical developer docs live in `docs/projects/pack_runner.md`.

## Scope

Phase 7 is implemented upstream. This phase record remains as implementation
history for early DAX artifact emission and the structured pack error surface
used during debugging.

## 1. Problem

### 1.1 DAX artifacts were written too late

Praeparo originally emitted DAX plan artifacts after dataset execution
returned successfully.

In failure cases such as DAX syntax errors, invalid filters, or missing
columns, the dataset stage raised before the pipeline could persist:

- the compiled DAX statement
- the associated plan metadata

That forced developers to reproduce and rerun with extra logging even though
the DAX plan was usually known before query execution began.

### 1.2 Pack runs could mask the underlying error

In pack execution, failures need to be attributable to a specific:

- pack file
- slide id/title/index
- visual reference and resolved path
- execution phase, for example metric context resolution, slide visual
  execution, or Power BI export

Without that context, debugging questions such as "which slide failed?" or
"where is the DAX artifact?" are much harder to answer quickly.

## 2. Goals

Phase 7 improved debugging ergonomics without changing business logic:

1. **Write `.dax` artifacts before executing DAX**
   - matrix planners, cartesian planners, and Python visuals using
     `MetricDatasetBuilder` persist compiled DAX before execution starts

2. **Preserve the real exception and add pack/slide context**
   - failing pack runs include pack path, slide identity, visual ref/path, and
     the phase where the failure occurred

3. **Point developers to the relevant artifacts**
   - when DAX artifacts exist, the surfaced error can point directly to them

## 3. Non-goals

- Changing DAX semantics, filter merging rules, or metric definitions
- Retry or backoff policy changes for Power BI
- Registry YAML migrations

## 4. Implemented Surfaces

Phase 7 covers the main DAX-backed execution paths used in packs:

1. **Pack metric-context bindings (`context.metrics`)**
   - metric-context DAX is emitted before execution under deterministic
     `metric_context.*.dax` filenames

2. **Matrix visuals**
   - compiled DAX is written before Power BI execution begins

3. **Cartesian chart visuals**
   - compiled DAX is written before dataset resolution runs

4. **Python visuals using `MetricDatasetBuilder`**
   - builder-backed visuals emit the planned DAX before execution

## 5. Implemented Design

### 5.1 Shared early-write helper

Praeparo now uses a shared helper in `praeparo.pipeline.core`:

- `write_dax_plan_files(...)`

This helper is intentionally idempotent and can be called before or after
execution. It uses the same filename semantics across call sites so early and
late emissions target the same files.

### 5.2 Structured pack exceptions

Praeparo now raises `PackExecutionError` to preserve actionable debugging
context:

- `pack_path`
- `slide_index`
- `slide_slug`
- `slide_id`
- `slide_title`
- `visual_ref`
- `visual_path`
- `phase`
- `dax_artifact_paths`
- original exception as `__cause__`

The string form stays single-line and scan-friendly so CLI output remains easy
to read.

### 5.3 CLI behavior

The pack CLI preserves `PackExecutionError` rather than collapsing it into a
generic wrapper, and `--allow-partial` keeps successful artefacts while still
returning a non-zero outcome for automation.

## 6. Completion Notes

Implementation evidence lives in:

- `praeparo/pipeline/core.py`, which provides shared DAX artifact writing
- `praeparo/pipeline/providers/matrix/planners/dax.py`
- `praeparo/pipeline/providers/cartesian/dax.py`
- `praeparo/datasets/builder.py`
- `praeparo/pack/errors.py`
- `praeparo/pack/runner.py`
- `praeparo/cli/__init__.py`

Focused tests cover:

- `tests/test_matrix_planner_dax_artifacts.py`
- `tests/test_cartesian_planner.py`
- `tests/test_metric_dataset_builder.py`
- `tests/pack/test_pack_runner.py`

## 7. Acceptance Criteria

1. When a DAX-backed matrix, cartesian, or Python visual fails during
   execution, the relevant `*.dax` file still exists in the artefact
   directory.
2. Pack-run failures identify pack path, slide identity, visual ref/path, and
   phase.
3. The original failure remains visible through the error chain.
4. Pack debugging docs point developers to the per-slide artifact directory for
   failed DAX-backed slides.
