# Epic: Pack Revision Modes And PPTX Restitch (Phase 11)

> Status: **Implemented** - pack runs support revision allocation and PPTX-only restitching, with defaults for full vs minor revisions and reuse of existing artefacts (2025-12-13).

- Canonical developer docs live in `docs/projects/pack_runner.md`.

## Scope

Phase 11 is implemented upstream. This phase record remains as implementation
history for revision allocation, PPTX naming defaults, and PPTX-only restitch
flows.

## 1. Problem

Once packs could assemble PPTX outputs, operators needed more than one execution
mode:

- a normal full run that re-executes visuals
- a PPTX-only restitch that reuses existing artefacts
- explicit revision allocation so output filenames and manifests remain stable

## 2. Goals

1. Add explicit revision flags and manifest-backed allocation
2. Support PPTX-only restitching from existing artefacts
3. Keep result-file defaults aligned with revision allocation and pack context

## 3. Completion Notes

Implementation evidence lives in:

- `praeparo/pack/revisions.py`
- `praeparo/pack/runner.py`
- `tests/pack/test_pack_revisions.py`
- `tests/pack/test_pack_runner.py`
- `docs/projects/pack_runner.md`

## 4. Acceptance Criteria

1. Full and minor revisions allocate deterministically
2. `--revision-dry-run` previews the next revision without writing manifests
3. PPTX-only restitch reuses existing artefacts and templates correctly
