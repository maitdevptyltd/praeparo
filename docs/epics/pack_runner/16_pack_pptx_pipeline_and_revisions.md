# Phase 16: Pack PPTX Pipeline And Revisions

> Status: **Implemented** – pack runs can assemble PPTX outputs, allocate revisions, and bind template/image placeholders from the resolved slide artifacts.

Use this page as implementation history for the foundational PPTX/revision
flow. For the current supported contract, start with [Projects / Pack Runner](../../projects/pack_runner.md).

## 1. Purpose

This phase extended the pack runner from "pack -> PNG artifacts" to
"pack -> PNG artifacts plus PPTX output" and established the first revision
semantics for generated decks.

The core goals were:

- keep one pack YAML as the source of truth for slide ordering,
- compose PPTX output from already-rendered slide artifacts,
- support template-driven slide assembly,
- and let repeated runs allocate or infer revision-aware result names.

## 2. Scope

This phase covers:

- PPTX generation for a single pack,
- revision-aware result naming and manifest-backed allocation,
- template slide selection through `template` / placeholder bindings,
- and the CLI/result-path contract around `dest`, `--artefact-dir`, and
  `--result-file`.

It does not redefine artifact naming or template geometry. Later phases refined
those contracts.

## 3. Desired Behavior

### 3.1 Inputs

The PPTX layer consumes:

- the pack YAML with ordered slides,
- the slide PNG artifacts produced by `praeparo pack run`,
- and an optional PPTX template with `TEMPLATE_TAG=<template_id>` notes.

Slides may use either:

- a single `visual` shorthand for one image target, or
- a `placeholders` map for multi-slot templates.

### 3.2 Outputs

Praeparo writes:

- one PPTX file per pack run,
- with slides assembled in pack order,
- using existing slide PNG artifacts rather than re-running visual execution.

Slides without images may still participate as template-only slides when the
template contract supports them.

### 3.3 Template And Placeholder Binding

For PPTX assembly, Praeparo:

- resolves `template` against the PPTX template deck,
- clones the matching template slide,
- applies the pack slide title and templated text,
- and binds either:
  - the slide PNG into the single detected picture placeholder, or
  - placeholder-specific visuals/images/text into named placeholders.

This phase established the template-driven assembly model that later geometry
and placeholder phases built on.

## 4. Revision Contract

Revision inputs may come from:

- `--revision <token>`,
- manifest-backed `--revision-strategy {full,minor}`,
- or pack context fallback when no explicit override is supplied.

The revision flow determines:

- the effective revision/minor pair,
- the suggested PPTX filename,
- and the persisted `_revisions/manifest.json` state used by future runs.

Examples of supported flags:

```bash
poetry run praeparo pack run projects/example/pack.yaml --result-file out/example/report.pptx
poetry run praeparo pack run projects/example/pack.yaml out/example --revision-strategy full
poetry run praeparo pack run projects/example/pack.yaml out/example --revision-dry-run
```

## 5. Result Path Semantics

This phase established the current split between output deck location and
artifact location:

- positional directory `dest` -> `<dest>/_artifacts` plus a default PPTX under
  `<dest>/`,
- positional `.pptx` `dest` -> an inferred artifact folder under
  `<parent>/<stem>/_artifacts`,
- explicit `--result-file` -> exact deck path, with inferred artifacts when
  `--artefact-dir` is omitted.

Later phases refined naming, revision defaults, and restitch behavior without
changing that overall shape.

## 6. Relationship To Later Pack Phases

This phase introduced the PPTX/revision foundation. Later pack-runner phases
then refined:

- slide artifact naming (Phase 9),
- revision modes and restitch flows (Phase 11),
- and template geometry / visual sizing (Phase 12).

Use those later phase records and the active pack-runner docs for the
authoritative current contract.
