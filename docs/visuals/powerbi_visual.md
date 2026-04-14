# Power BI Visual (Design)

> **Status:** Implemented for the shared visual pipeline and pack runner.

## What it is

`type: powerbi` is a declarative visual that snapshots an existing Power BI
asset, such as a report page, a single visual, or a paginated report, into an
image and optional sidecar files (`PPTX`, `XLSX`, `CSV`, `PDF`). It lets deck
and dashboard pipelines reuse the same visual definitions found in
`registry/visuals/**` while keeping the export steps inside Praeparo.

## Key behaviours

- Calls the Power BI Export-to-File API with the supplied workspace
  (`group_id`), report (`report_id`), and target (`page` or `visual_id`).
- Supports paginated reports by emitting multiple formats and attaching the
  generated URLs or artefacts to the resolved visual.
- Normalises filters (dict or list) with the same merge rules used by the pack
  runner: pack-level filters merge into placeholder filters unless
  `filters_merge_strategy: replace` is set.
- Can keep Power BI exports as PPTX while also extracting a PNG sidecar from
  the slide images, including crop metadata and overlap trimming.
- Uses concurrency guards and retry-friendly polling so multiple visuals can
  export safely in parallel.

## Environment and default resolution

Power BI visuals are meant to stay concise in YAML. Praeparo resolves export
identifiers and render defaults in a predictable order so authors can skip
repeating boilerplate when the environment already supplies it.

Resolution is:

1. explicit YAML values in the visual definition,
2. runtime overrides supplied by the caller,
3. environment defaults,
4. model fallbacks.

The most common defaults are:

- `source.group_id` falls back to `PRAEPARO_PBI_WORKSPACE_ID`.
- `source.report_id` falls back to `PRAEPARO_PBI_DEFAULT_REPORT_ID`.
- `render.format` falls back to `PRAEPARO_PBI_DEFAULT_EXPORT_FORMAT`.
- `render.stitch_slides` falls back to `PRAEPARO_PBI_DEFAULT_STITCH_SLIDES`.

Fields that identify the asset slice itself, such as `source.page` and
`source.visual_id`, stay in YAML because they describe the report content
rather than the environment. That keeps the reusable defaults focused on
credentials and export policy.

Example with environment-provided workspace and report identifiers:

```yaml
type: powerbi
mode: report
source:
  page: Overview
render:
  format: png
```

In that form, Praeparo can export the visual without repeating workspace or
report identifiers in every file.

## YAML contract (proposed)

```yaml
# registry/visuals/powerbi/performance_dashboard.yaml
type: powerbi
title: Operations dashboard
mode: report          # one of: report (default), visual, paginated
source:
  group_id: "42db434f-7c50-4396-9db5-96a9558c3823"   # optional when PRAEPARO_PBI_WORKSPACE_ID is set
  report_id: "657ff06c-2149-4e25-9476-05ef1e2ebe5e"   # optional when PRAEPARO_PBI_DEFAULT_REPORT_ID is set
  page: "f562abbe88c0759b4f20"   # omit for paginated
  visual_id: null                 # optional when mode=visual

filters:
  team: "dim_team/TeamId eq {{ team_id }}"
  dates: "{{ odata_months_back_range('dim_calendar/month', month, 3) }}"
filters_merge_strategy: merge      # merge (default) or replace

# Paginated-only
parameters:
  - name: Months
    value: "{{ strftime(month, '%Y-%m-%d') }}"
export_formats: ["xlsx"]          # paginated sidecars to emit

render:
  format: png                      # png (default) or pptx
  stitch_slides: true              # combine multiple slide images vertically
  max_concurrency: 20              # optional override of global semaphore
```

## Field reference

- `mode`: selects the export flavour. `report` targets a whole page;
  `visual` targets a specific `visual_id`; `paginated` uses the paginated
  endpoint and honours `parameters`/`export_formats`.
- `source.group_id`: workspace identifier. If omitted, Praeparo falls back to
  `PRAEPARO_PBI_WORKSPACE_ID`.
- `source.report_id`: report identifier. If omitted, Praeparo falls back to
  `PRAEPARO_PBI_DEFAULT_REPORT_ID`.
- `source.page`: required when `mode=report`; ignored for paginated.
- `source.visual_id`: optional; only used when `mode=visual` is supported by the
  export API.
- `filters`: dict or list of OData predicates. Dict keys are labels; values are
  combined with `and` when serialized.
- `filters_merge_strategy`: `merge` to append pack-level filters; `replace` to
  drop them.
- `parameters`: paginated parameter list (name/value), templated with the same
  Jinja context as other visuals.
- `export_formats`: sidecar formats for paginated exports. Defaults to `['xlsx']`.
- `render.format`: the primary file format requested from Power BI. When this is
  `pptx`, Praeparo preserves the deck and also extracts a PNG sidecar when the
  PPTX contains slide images.
- `render.stitch_slides`: when true, multiple slide images are stitched into one
  PNG with overlap detection (mirrors the current pack runner behaviour).
- `render.max_concurrency`: optional per-visual cap; falls back to the global
  semaphore in the engine.

## Execution flow

1) **Load** – YAML is validated against `PowerBIVisualConfig` (marked by
   `type: powerbi`) and registered in `VisualConfigUnion`.
2) **Plan** – the planner builds the export payload using the configured format
   (or the `.env` default), then resolves filters and parameters with the
   provided context and pack-level defaults.
3) **Export** – the Power BI client polls `ExportToFile` until `Succeeded`,
   then downloads the artefact to a predictable local folder such as
   `build/pbi_exports/...`.
4) **Extract** – when the downloaded artefact is a PPTX, Praeparo reads the
   deck, crops the largest picture on each slide, and optionally stitches those
   segments vertically to avoid clipping multi-section visuals.
5) **Attach** – the resolved visual exposes `image_path`, `pptx_path`, and
   optional `artifacts` so downstream pack builders and PPTX renderers can drop
   them into placeholders.

## Credentials & security

- Uses the existing `PRAEPARO_PBI_CLIENT_ID`, `PRAEPARO_PBI_CLIENT_SECRET`,
  `PRAEPARO_PBI_TENANT_ID`, and `PRAEPARO_PBI_REFRESH_TOKEN` environment
  variables resolved by `praeparo.powerbi.PowerBISettings`. No extra auth
  dependencies are required beyond the built-in HTTPX-based client.
- Export defaults can be supplied via `.env`:
  - `PRAEPARO_PBI_WORKSPACE_ID=<workspace-guid>`
  - `PRAEPARO_PBI_DEFAULT_REPORT_ID=<report-guid>`
  - `PRAEPARO_PBI_DEFAULT_EXPORT_FORMAT=png|pptx|pdf`
  - `PRAEPARO_PBI_DEFAULT_STITCH_SLIDES=true|false`
  - `PRAEPARO_PBI_EXPORT_POLL_INTERVAL=<seconds>`
  - `PRAEPARO_PBI_EXPORT_TIMEOUT=<seconds>`
- Avoid embedding secrets in YAML; keep credentials in env/Key Vault and load
  them via `python-dotenv` or host-specific secret managers.
- Exports are cached locally; callers should ensure the chosen export
  cache or output directory is excluded from distribution archives unless it is
  needed for audit.

## Failure modes to handle

- 401/403 on export → surface actionable message about missing workspace access
  or invalid client credentials.
- 404 on report/page/visual → include the missing identifiers in the error.
- Polling timeout → raise with elapsed time and retry-after hints; allow the
  caller to configure max waits.
- No pictures in PPTX export → fallback to saving the PPTX only and flag the
  absence in logs.

## Interop with packs

- Packs can reference Power BI visuals by path and supply context parameters
  (for example, `team_id`, `month`) that feed filter templates in
  `filters`.
- Pack-level filters (defined in the pack YAML) are rendered via the same Jinja
  helpers (`odata_months_back_range`, etc.) and merged with slide-level
  `visual.filters` before being passed to the Power BI visual pipeline via
  `metadata["powerbi_filters"]`.
- Pack-level DAX `define` blocks are consumed by DAX-backed pipelines (matrix,
  cartesian, etc.) and are **not** used by Power BI visuals.
- This lets existing visual definitions (`type: powerbi` under `visuals/`) be
  reused across multiple slides and packs without rewriting filters or export
  logic.

## Current limits

- Direct PNG export from the Power BI API is still supported, but PPTX remains
  the more robust path when the service clips tall visuals.
- The per-visual `max_concurrency` field is still a placeholder; pack-level
  concurrency is controlled via `--max-pbi-concurrency` /
  `PRAEPARO_PBI_MAX_CONCURRENCY`.
- Standalone `visual run` already works through the shared registry; there is
  no dedicated `powerbi`-only CLI shim yet.
