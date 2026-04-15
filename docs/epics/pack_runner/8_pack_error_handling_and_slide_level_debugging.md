# Epic: Pack Error Handling And Slide-Level Debugging (Phase 8)

> Status: **Implemented** - pack runs surface per-slide Power BI failure summaries and support `--allow-partial` so successful artefacts remain usable while the CLI still exits non-zero (2025-12-13).

- Canonical developer docs live in `docs/projects/pack_runner.md`.

## Scope

Phase 8 is implemented upstream. This phase record remains as implementation
history for Power BI failure summaries, partial-success behavior, and the
operator debugging flow around `--slides` and concurrency controls.

## 1. Problem

Once pack runs could execute multiple slides, Power BI failures became harder to
debug quickly:

- slide failures could be buried in a larger pack run
- one failed slide could obscure which outputs had already succeeded
- operators needed a supported way to keep successful artefacts while still
  surfacing a non-zero outcome for automation

## 2. Goals

Phase 8 introduced:

1. **Per-slide failure summaries**
   - failing Power BI slides are reported by slide slug/title with the
     exception type and message

2. **Focused debugging ergonomics**
   - operators can rerun one slide with `--slides`
   - serial Power BI debugging remains available via `--max-pbi-concurrency 1`

3. **Partial-success runs**
   - `--allow-partial` keeps successful artefacts and prints the summary without
     a traceback while still exiting non-zero

## 3. Completion Notes

Implementation evidence lives in:

- `praeparo/pack/runner.py`
- `praeparo/cli/__init__.py`
- `tests/pack/test_pack_runner.py`
- `tests/test_cli_entrypoint.py`

## 4. Acceptance Criteria

1. Pack runs report failing Power BI slides in a clear summary.
2. Successful outputs remain on disk when `--allow-partial` is enabled.
3. The CLI still exits non-zero so automation can detect the failure.
