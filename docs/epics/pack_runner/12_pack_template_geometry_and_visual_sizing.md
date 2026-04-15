# Epic: Pack Template Geometry And Visual Sizing (Phase 12)

> Status: **Implemented** - geometry hints flow from PPTX templates into pack slide metadata so locally rendered visuals can size themselves to the template viewport (2025-12-13).

- Canonical developer docs live in `docs/projects/pack_runner.md`.

## Scope

Phase 12 is implemented upstream. This phase record remains as implementation
history for template-derived render-size hints.

## 1. Problem

The pack -> PPTX pipeline knew where visuals land via template slots, but not
how large those slots were at render time.

That made locally rendered visuals rely on generic or guessed canvas sizes
before PPTX best-fit placement, which could lead to cramped or padded charts.

## 2. Goals

1. Derive render-time `width` / `height` hints from PPTX template geometry
2. Flow those hints into slide metadata for local renderers
3. Keep explicit CLI `--width` / `--height` overrides authoritative

## 3. Completion Notes

Implementation evidence lives in:

- `praeparo/pack/runner.py`
- `tests/pack/test_pack_runner.py`
- `docs/projects/pack_runner.md`

## 4. Acceptance Criteria

1. Slide-level visuals receive template-derived size hints when available
2. Placeholder visuals receive placeholder-specific size hints
3. Packs without templates skip geometry derivation cleanly
