# Epic: Pack Artifact Naming Convention (Phase 9)

> Status: **Implemented** - `praeparo pack run` prefixes slide artefacts as `[NN]_<slide-slug>` so outputs sort in pack order while `--slides` filtering still matches unprefixed slugs (2025-12-13).

- Canonical developer docs live in `docs/projects/pack_runner.md`.

## Scope

Phase 9 is implemented upstream. This phase record remains as implementation
history for deterministic pack artefact naming.

## 1. Problem

Pack artefacts originally used slug-only names. That made output folders and PNG
files harder to scan in pack order, especially for larger decks.

The framework needed a naming scheme that:

- preserves a stable slide slug for matching and diagnostics
- sorts artefacts in slide order on disk
- stays consistent across PNG outputs and per-slide artefact directories

## 2. Goals

1. Prefix pack artefacts with a zero-padded ordinal
2. Keep unprefixed slide slugs for matching via `--slides`
3. Preserve deterministic paths for downstream PPTX assembly and operators

## 3. Completion Notes

Implementation evidence lives in:

- `praeparo/pack/runner.py`
- `tests/pack/test_pack_runner.py`
- `docs/projects/pack_runner.md`

## 4. Acceptance Criteria

1. Main PNGs land at `<artefact-dir>/[NN]_<slide-slug>.png`
2. Per-slide artefacts land under `<artefact-dir>/[NN]_<slide-slug>/`
3. `--slides` still matches ids/titles/unprefixed slugs
