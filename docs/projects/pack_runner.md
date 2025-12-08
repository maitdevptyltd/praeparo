# Pack Runner – Pack → PNG Pipeline

## Purpose

Packs let you orchestrate **multiple visuals as a single unit**: a pack YAML
describes slides, shared context, and per-slide overrides, and the
`praeparo pack run` command uses the existing visual registry and pipelines to
emit PNG artefacts for each slide.

The pack runner is intentionally type-agnostic:

- Each slide references an existing visual YAML via `visual.ref`.
- Praeparo resolves the visual config and delegates execution to the registered
  visual pipeline (matrix, frame, Power BI, etc.).
- Pack-level context and filters are rendered via Jinja and merged with
  slide-level overrides before reaching the visual pipeline.

This keeps pack orchestration thin while reusing the same visual definitions
and pipelines your project already depends on.

## Pack YAML shape

A pack configuration is a small YAML document with:

- A schema/id,
- Shared `context` used for templating,
- Optional pack-level `calculate` filters (for DAX-backed visuals),
- Optional pack-level `filters` (for OData / Power BI),
- An ordered list of `slides`, each optionally referencing a visual.

Example:

```yaml
schema: example-pack-draft-1

context:
  customer: "Example Bank"
  lender_id: 201
  month: "2025-10-01"

calculate:
  lender: "'dim_lender'[LenderId] = {{ lender_id }}"

filters:
  lender: "dim_lender/LenderId eq {{ lender_id }}"
  dates: "{{ odata_months_back_range('dim_calendar/month', month, 3) }}"

slides:
  - id: overview
    title: "Performance Overview"
    visual:
      ref: visuals/performance_matrix.yaml   # type: matrix

  - id: digital_broker
    title: "Digital Documents – Broker"
    visual:
      ref: visuals/digital_docs_adoption.yaml   # type: powerbi
      filters:
        dates: "{{ odata_months_back_range('dim_calendar/month', month, 6) }}"
        funding_channel_type: "dim_funding_channel_type/FundingChannelTypeName eq 'Broker'"
```

### Fields

- `schema` – free-form identifier for the pack contract.
- `context` – key/value pairs exposed to Jinja templates (for example,
  `lender_id`, `month`, `customer`).
- `calculate` – DAX filters, expressed as:
  - a single string,
  - a list of strings, or
  - a dict of named filters (`{name: expression}`).
  These are normalised to a list and made available to DAX-backed pipelines
  through the metadata context; slide-level `visual.calculate` can extend this
  set.
- `filters` – OData filters for Power BI, expressed as:
  - a single string,
  - a list of strings, or
  - a dict of named filters (`{name: expression}`).
  These are normalised and treated as **pack-level defaults**; slide-level
  `visual.filters` can extend or override them.
- `slides` – ordered slide definitions:
  - `id` – optional stable identifier (used for filtering and slug generation).
  - `title` – human-readable slide title.
  - `notes` – free-form author notes.
  - `visual.ref` – path (relative to the pack file) to a visual YAML
    (matrix, frame, Power BI, etc.).
  - `visual.filters` – slide-level OData filters (merged with pack-level
    `filters`).
  - `visual.calculate` – slide-level DAX filters (merged with pack-level
    `calculate`).

## CLI usage

Once a pack YAML exists, run:

```bash
poetry run praeparo pack run \
  projects/example/pack.yaml \
  --artefact-dir .tmp/example/pack_png
```

Key flags:

- `pack run <path>` – path to the pack YAML. Can be absolute or relative to the
  current working directory.
- `--artefact-dir` – root directory for pack artefacts:
  - PNGs are written as `<artefact-dir>/<slide-slug>.png`.
  - Visual-specific artefacts (for example Power BI exports) land under
    `<artefact-dir>/<slide-slug>/`.
- `--slides` – optional list of slide ids/titles/slugified titles to restrict
  execution:

  ```bash
  poetry run praeparo pack run projects/example/pack.yaml \
    --artefact-dir .tmp/example/pack_png \
    --slides overview digital_broker
  ```

- `--png-scale`, `--data-mode`, `--datasource`, and other global options – share
  semantics with `praeparo visual run` via `PipelineOptions`.

> Tip: pass `--plugin your_project` when packs reference custom visual types
> registered in your project.

## Execution model

At a high level, `praeparo pack run` does the following:

1. **Load & validate** the pack YAML into `PackConfig`.
2. **Build a Jinja environment** mirroring Data.Slick helpers:
   - `odata_date`, `odata_between`, `odata_months_back_range`, `relativedelta`,
     etc.
3. **Render templates**:
   - Pack-level `filters` and `calculate` are rendered using the pack
     `context`.
   - Slide-level `visual.filters` and `visual.calculate` are rendered using the
     same context.
4. **Merge filters**:
   - For Power BI visuals:
     - Pack-level and slide-level filters are merged (dict + dict, list + list,
       string coerced to list) and passed via `metadata["powerbi_filters"]`.
   - For DAX-backed visuals:
     - Pack-level and slide-level `calculate` filters are normalised and
       combined in order (pack first, then slide overrides) and exposed in the
       metadata context so matrix/governance pipelines can consume them.
5. **Resolve visuals**:
   - Each `visual.ref` is resolved to a `BaseVisualConfig` via the YAML loader.
   - A shared `VisualPipeline` uses the visual type and registry registrations
     to select the correct pipeline.
6. **Execute and persist**:
   - Each slide’s visual is executed with per-slide options:
     - PNG outputs are targeted at `<artefact-dir>/<slide-slug>.png`.
     - `options.artefact_dir` is set to `<artefact-dir>/<slide-slug>/` so
       visual-specific artefacts (Power BI exports, datasets) remain grouped.
   - The pack run prints a summary of how many PNGs were written.

Slides whose visuals do not emit PNGs are skipped with a warning; the pack run
never fails solely because a visual lacks a PNG renderer.

## Integration with existing visuals

Because the pack runner delegates to the visual registry:

- **Matrix and frame visuals** work unchanged; packs simply provide additional
  context and calculate filters via metadata.
- **Power BI visuals** (`type: powerbi`) reuse the `PowerBIVisualConfig`
  contract:
  - Pack filters are merged with visual-level `filters` and applied via
    `metadata["powerbi_filters"]`, using the same `_merge_filters` logic as
    standalone visual runs.
  - Exported artefacts are written under the per-slide `artefact_dir`, with the
    primary PNG copied to `<artefact-dir>/<slide-slug>.png`.
- **Custom visuals** registered via `register_visual_type` participate
  automatically as long as they honour the standard `VisualPipeline` contracts
  and optionally consume context/metadata.

This makes packs a thin orchestration layer over the existing visual ecosystem
rather than a parallel execution path.

## Future: PPTX & revisions

The pack runner currently focuses on PNG outputs and per-slide artefacts. A
future PPTX layer can build on this by:

- Using the pack definition as the single source of truth for slide order,
  titles, and visuals.
- Treating `--artefact-dir` as the revision root for visual artefacts.
- Writing a PPTX (or zipped revision) to a separate, explicit result path
  (e.g. `--output-pptx`) that mirrors the revision semantics used in existing
  deck builders.

By keeping pack orchestration separate from PPTX composition, Praeparo can
service both notebook/automation workflows (PNG-only) and full deck pipelines
with minimal duplication.

