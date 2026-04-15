# Epic: Pack Static Images And Logos (Phase 10)

> Status: **Implemented** - packs can bind static images at slide level (`image`) and placeholder level (`placeholders.*.image`) for PPTX assembly without requiring dedicated visuals (2025-12-13).

- Canonical developer docs live in `docs/projects/pack_runner.md`.

## Scope

Phase 10 is implemented upstream. This phase record remains as implementation
history for static image bindings in pack-authored PPTX slides.

## 1. Problem

PPTX assembly handled data-driven slides well, but some deck layouts need static
assets such as:

- covers
- logos
- divider marks
- mixed static/visual two-up layouts

Without a dedicated binding surface, authors had to create unnecessary visuals
or manual deck edits for simple image slots.

## 2. Goals

1. Allow slide-level `image` bindings for single-slot templates
2. Allow placeholder-level `image` bindings for multi-slot templates
3. Keep validation strict and mutually exclusive with `visual`/`text` bindings

## 3. Completion Notes

Implementation evidence lives in:

- `praeparo/models/pack.py`
- `praeparo/pack/runner.py`
- `tests/pack/test_pack_runner.py`
- `docs/projects/pack_runner.md`

## 4. Acceptance Criteria

1. Slide-level `image` bindings work for template-backed slides
2. Placeholder-level `image` bindings work alongside visual placeholders
3. Missing or empty image paths fail clearly during pack execution
