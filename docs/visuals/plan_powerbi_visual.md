# Power BI Visual – Implementation Plan

> **Purpose:** Land `type: powerbi` as a first-class Praeparo visual that exports
> Power BI reports/paginated content to PNG/PPTX with reusable YAML definitions.

## Scope

- Pydantic config + loader registration (`PowerBIVisualConfig` in the visual
  union) with schema export updates.
- Export engine that wraps Power BI `ExportToFile`, supports report/visual/
  paginated modes, and exposes stitched PNG plus sidecar artefacts.
- Planner and resolver that honour filter merge semantics, templating, and
  per-visual concurrency caps.
- CLI wiring for standalone renders and pack integration (deck pipeline).
- Tests (unit + mocked integration) and developer docs.

## Work Breakdown

| # | Task | Status | Notes/Decisions |
| - | ---- | ------ | --------------- |
| 1 | Model: add `PowerBIVisualConfig` (mode, source, filters, parameters, render) and include in `VisualConfigUnion`; update JSON schemas. | Not started | Reuse existing filter merge helpers; keep `filters` as dict|list. |
| 2 | Payload builder: helper to build ExportTo payloads (report/visual/paginated) with validation of mutually exclusive fields. | Not started | Mirror Slick’s `build_export_payload`/`build_paginated_export_payload`. |
| 3 | Export service: async client that polls `ExportToFile`, downloads artefacts, and caches under `.tmp/pbi_exports/...`; add concurrency semaphore + retry/backoff knobs. | Not started | Reuse `praeparo.powerbi` HTTPX client; no new deps; emit structured errors (401/404/timeout). |
| 4 | PPTX extractor: stitch largest pictures per slide, apply crop metadata, and return PNG blob + PPTX path; unit-test with fixtures. | Not started | Port logic from Slick with coverage for multi-slide and no-picture cases. |
| 5 | Planner integration: resolve filters/parameters with templating, respect `filters_merge_strategy`, attach paths to resolved visual for pack renderers. | Not started | Align merge semantics with governance pack. |
| 6 | CLI: `praeparo visuals render powerbi <file>` (standalone) and pack support so PPTX builders can drop in rendered images. | Not started | Keep deterministic `.tmp/pbi_exports` paths; revision/manifest handling is out of scope. |
| 7 | Tests: unit (model validation, payload builder, extractor), mocked integration (export polling), snapshot for stitched PNG. | Not started | Gate real API tests behind env flag; keep offline fixtures. |
| 8 | Docs: developer guide (`docs/visuals/powerbi_visual.md`), architecture touchpoints, CLI help text. | In progress | This doc + reference page drafted. |
| 9 | Follow-ups: add to the examples registry and pack templates; coordinate with downstream repos for registry/packs migration. | Not started | Depends on pack schema landing in Praeparo. |

## Risks & Dependencies

- Power BI export API limits (rate limits, file size); need graceful backoff and
  user-visible error messages.
- Credentials via env (`PRAEPARO_PBI_CLIENT_ID`, `PRAEPARO_PBI_CLIENT_SECRET`,
  `PRAEPARO_PBI_TENANT_ID`, `PRAEPARO_PBI_REFRESH_TOKEN`) must be present; add a
  credential check with clear errors.
- PNG extraction assumes slides contain at least one picture; require a guard
  path when exports only include shapes.
- Schema exports and Pyright must be updated alongside code changes to avoid
  breaking downstream IntelliSense.

## Validation Plan

- Unit tests for model validation, payload builder, filter merge strategy, and
  PPTX stitching (fixture PPTX with multiple slides and crops).
- Mocked export flow: fake `ExportToFile` responses exercised via httpx/pytest
  fixtures; verify polling and error cases (401, 404, timeout).
- CLI smoke: dry-run render writes PNG + PPTX to `.tmp/pbi_exports/...` without
  hitting the API when `PRAEPARO_RUN_POWERBI_TESTS` is unset.

## Open Questions

- Should we allow direct PNG export when the API supports it, or standardise on
  PPTX+extract for consistency?
- Do we need per-visual cache invalidation controls (force rerender) in the CLI?

## Out of Scope (for this iteration)

- Embedding Power BI authentication flows beyond service principal/refresh
  token.
- Live Power BI “embed” visuals; this visual type focuses on export-to-image.
- Plotly/native charts; covered by other visual types.
