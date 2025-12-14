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
- Optional pack-level `define` (DAX DEFINE block) rendered with the same context,
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
  metrics:
    instructions_received: total_instructions
    documents_sent: total_documents

define: |
  DEFINE VAR LenderId = {{ lender_id }}

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
  `lender_id`, `month`, `customer`). May also include a `metrics` block that
  declaratively fetches catalogue KPIs into Jinja variables.
- `define` – optional DAX DEFINE block (single string). Rendered via Jinja using
  `context` and forwarded to DAX-backed pipelines through
  `metadata["context"]["define"]`. Ignored by Power BI visuals.
- `calculate` – DAX filters, expressed as:
  - a single string,
  - a list of strings, or
  - a dict of named filters (`{name: expression}`).
  These are merged using pack semantics: when both pack-level and slide-level
  `calculate` supply a mapping, slide-level keys override pack-level keys (last
  writer wins). Unlabelled filters (string/list entries) are appended in order.
  The resulting list is forwarded to DAX-backed pipelines through the metadata
  context.
- `filters` – OData filters for Power BI, expressed as:
  - a single string,
  - a list of strings, or
  - a dict of named filters (`{name: expression}`).
  These are treated as **pack-level defaults**; slide-level `visual.filters`
  can extend or override them. Named overrides apply when both sides are
  mappings (slide-level keys override pack-level keys). If either side uses a
  sequence form, Praeparo falls back to concatenating the effective lists of
  filter expressions (dropping names).
- `slides` – ordered slide definitions:
  - `id` – optional stable identifier (used for filtering and slug generation).
  - `title` – human-readable slide title.
  - `notes` – free-form author notes.
  - `context` – optional per-slide context merged over the pack context,
    including optional `context.metrics` bindings.
  - `template` – optional PPTX template identifier (`TEMPLATE_TAG`) used during
    deck assembly.
  - `visual.ref` – path to a visual YAML (matrix, frame, Power BI, etc.).
    By default this is relative to the pack file, but `@/…` anchors the path
    to the project `registry/` directory.
  - `visual.filters` – slide-level OData filters (merged with pack-level
    `filters`).
  - `visual.calculate` – slide-level DAX filters (merged with pack-level
    `calculate`).
  - `image` – optional static image path (relative to the pack file) used for
    PPTX slides that do not declare a visual. Requires `template`.
  - `placeholders` – optional map of placeholder ids to bindings for multi-slot
    templates (for example a two-up slide). Each placeholder must define
    exactly one of:
    - `visual` (render a visual into the placeholder),
    - `image` (bind a static image path), or
    - `text` (bind text into a named text shape).

## Metric Context Bindings (`context.metrics`)

Packs can declare scalar KPI dependencies under `context.metrics`. Praeparo
fetches these values via DAX and injects them as top-level Jinja variables so
text placeholders, YAML shapes, and tables can reference them directly.

Root-level metrics are resolved **once per pack** and inherited by every slide.
Slides may extend the inherited metric dict or override an alias only when
`override: true` is set.

Metric-context scoping (`context.metrics.calculate`) is also inherited by slides.
Slide-level `context.metrics.calculate` may add new named predicates or override
root predicates by name (and by scope) without duplicating every slide.

Templating note:

- Slide context values (excluding `context.metrics`) are rendered **once** after
  metric bindings are injected, so nested templates inside slide strings (for
  example `governance_highlights: "MoM is {{ count_instructions_mom }}"`) can
  reference binding aliases. This render pass is not affected by
  `--ignore-placeholders`.

### Display formatting (`bindings[].format`)

Metric binding aliases always resolve to **raw numeric values** for execution
surfaces (DAX/config templating, visual execution contexts).

For display-only rendering, Praeparo automatically applies `bindings[].format`
by swapping metric aliases for small wrapper objects that stringify using the
format token.

Display-only fields (Phase 8):

- PPTX text run rendering (`{{ ... }}` inside slide templates and placeholder text blocks).
- Nested render of slide `context` values after metric injection, excluding keys named
  `calculate`, `filters`, `define`, or `expression` (so execution surfaces keep raw numbers).

Default behaviour:

- `{{ count_instructions }}` renders formatted output when `format` is set.
- `{{ count_instructions.value }}` returns the raw numeric value (float/int/None).

Examples:

```yaml
context:
  metrics:
    bindings:
      - key: instructions_received
        alias: count_instructions
        format: number:0
```

```jinja2
We received {{ count_instructions }} instructions. (Raw: {{ count_instructions.value }})
```

Percent formatting treats inputs as 0–1 and multiplies by 100 for display:

```yaml
format: percent:0
```

Recommended wrapper form (bindings + optional metrics-only calculate):

```yaml
context:
  metrics:
    calculate:
      month: "'dim_calendar'[month] = DATEVALUE(\"{{ month }}\")"
      period:
        evaluate: "'Time Intelligence'[Period] = \"Current Month\""
    bindings:
      instructions_received: total_instructions
      documents_sent: total_documents
```

Shorthand still accepted (Praeparo treats these as `bindings`):

```yaml
slides:
  - title: Highlights
    context:
      metrics:
        - documents_verified
        - documents_verified.within_1_day
```

Object form (future-ready; accepted now):

```yaml
context:
  metrics:
    bindings:
      - key: documents_verified
        alias: verified_total
        variant: within_1_day
        calculate:
          - dim_customer[CustomerName] = "{{ customer }}"
        format: "percent:0"
      - key: documents_verified.within_1_day
        alias: pct_verified_1d
        ratio_to: true
        format: "percent:0"
      - key: documents_verified.within_1_day
        alias: pct_verified_1d_against_total
        ratio_to: documents_verified
        format: "percent:0"
      - alias: pct_verified_1d
        expression: documents_verified.within_1_day / documents_verified
        format: "percent:0"
      - key: documents_sent
        alias: total_documents
        override: true
```

Notes:

- `variant` is a shortcut for `key.variant` and is disallowed when `key` is already dotted.
- `ratio_to` computes a deterministic 0–1 ratio and injects it under the binding alias.
  - `ratio_to: true` requires a dotted numerator key and infers the base denominator (before the first dot).
  - `ratio_to: "<metric_key>"` uses that catalogue metric key as the denominator (metric keys only; aliases are rejected to avoid ambiguity).
  - When `format` is omitted, `ratio_to` bindings default to `percent:0` for display-only rendering.
  - Denominators are auto-included in the metric-context query plan; authors should not duplicate denominator bindings.
- Expression bindings require an `alias` and may reference catalogue keys and/or previously
  resolved aliases. Cycles and unknown identifiers fail validation.
- Per-binding `calculate` filters apply only to that binding and do not implicitly
  affect other identifiers used in expressions.
- Named `calculate` entries default to DEFINE scope (inside the adhoc MEASURE). To
  apply a predicate at EVALUATE scope (around the measure reference in
  `SUMMARIZECOLUMNS`), use `calculate.<name>.evaluate`:
  ```yaml
  bindings:
    - key: instructions_received
      alias: count_instructions
      calculate:
        period:
          evaluate: "'Time Intelligence'[Period] = \"Current Month\""
  ```
- For `ratio_to` bindings, `calculate.*.evaluate` applies to both numerator and denominator,
  while `calculate.*.define` applies only to the numerator (the denominator does not inherit it).
- `metrics.calculate` (pack root and/or slide context) adds DAX predicates to the
  metric-context query. Shorthand entries default to DEFINE scope:
  - `context.metrics.calculate.<name> = <predicate>` applies in DEFINE scope as
    outer dataset scoping (CALCULATETABLE wrapping SUMMARIZECOLUMNS).
  - `context.metrics.calculate.<name>.evaluate = <predicate>` applies in EVALUATE
    scope around every bound series (via SUMMARIZECOLUMNS value filters), which
    is required for calculation groups like Time Intelligence.
  Root calculate entries are inherited by slides; slide entries may add or override
  root entries by name and by scope (slide DEFINE replaces root DEFINE only when
  the slide supplies a DEFINE predicate for that key; likewise for EVALUATE).
  These predicates affect only `context.metrics` resolution, not slide visuals.
- `context.calculate` is a deprecated alias for `metrics.calculate` and will be removed
  in a future release.

## CLI usage

Once a pack YAML exists, run:

```bash
poetry run praeparo pack run \
  projects/example/pack.yaml \
  --artefact-dir .tmp/example/pack_png
```

You can optionally supply a positional `dest` to derive defaults for `--artefact-dir`
and a PPTX `--result-file`:

- `praeparo pack run projects/example/pack.yaml out/ing` writes artefacts to
  `out/ing/_artifacts/` and defaults the PPTX to
  `out/ing/<pack-slug>_<revision>.pptx` when a revision is available (revision
  flags or `context.month`), otherwise `out/ing/<pack-slug>.pptx`.
- `praeparo pack run projects/example/pack.yaml out/ing_governance.pptx` writes
  artefacts to `out/ing_governance/_artifacts/` and the PPTX to
  `out/ing_governance.pptx`.

Explicit flags still win: if you pass `--artefact-dir` or `--result-file`, those
values override anything derived from the positional `dest`.

Key flags:

- `pack run <path>` – path to the pack YAML. Can be absolute or relative to the
  current working directory.
- `--project-root` – override the project root used for metrics/datasources discovery
  and default build paths. Defaults to the current working directory. When a slide’s
  visual declares a typed context model, its `metrics_root` still takes precedence.
- `--artefact-dir` – root directory for pack artefacts:
  - PNGs are written as `<artefact-dir>/[NN]_<slide-slug>.png` where `NN` is
    the 1-based slide position padded to two digits.
  - Visual-specific artefacts (for example Power BI exports) land under
    `<artefact-dir>/[NN]_<slide-slug>/`.
    - Power BI dataset manifests (`data.json`) include `export_payload`, the
      ExportTo request body used for the primary export, so failed exports can be
      reproduced without needing access to live logs.
  - Omit this flag only when using the positional `dest` shorthand; the derived
    `artefact_dir` will be `dest/_artifacts` (or `<dest-stem>/_artifacts` when
    `dest` ends with `.pptx`).
- `--result-file` – optional PPTX destination. If `--artefact-dir` is omitted,
  it is inferred as `<result-file.parent>/<result-file.stem>/_artifacts`. When
  paired with revisions, defaults to `<dest>/<pack-slug>_<revision>.pptx`.
- `--revision`, `--revision-strategy {full,minor}`, `--revision-dry-run` –
  allocate or preview a revision token/minor counter for the run (see
  “PPTX & revisions” below).
- `--slides` – optional list of slide ids/titles/slugified titles to restrict
  execution:

  ```bash
  poetry run praeparo pack run projects/example/pack.yaml \
    --artefact-dir .tmp/example/pack_png \
    --slides overview digital_broker
  ```

  When `--slides` is used alongside `--result-file`, Praeparo still assembles the
  PPTX even if the skipped slides or placeholders have no PNG artefacts yet. Any
  existing PNGs for skipped slides are reused; otherwise Praeparo logs a warning
  and leaves the template placeholders unchanged/blank. Full runs and
  `--pptx-only` restitches remain strict about missing PNGs.
- `--max-pbi-concurrency` – maximum number of Power BI exports in flight at
  once. Defaults to `5` when not supplied; can also be set via
  `PRAEPARO_PBI_MAX_CONCURRENCY` (the CLI flag wins when both are provided).

- `--data-mode` – datasource mode (`mock`, `live`, etc.). `praeparo pack run`
  defaults to **live** when omitted so DAX-backed visuals hit real datasets by
  default; pass `--data-mode mock` to force mock providers. Visual and
  python-visual commands remain mock-first.

- `--plugin MODULE` – import one or more modules before resolving registrations
  so custom visuals, pipelines, or DAX compilers become available:

  ```bash
  poetry run praeparo pack run projects/example/pack.yaml \
    --plugin your_project \
    --artefact-dir .tmp/example/pack_png
  ```

  The same flag can be supplied at the top level if preferred:

  ```bash
  poetry run praeparo --plugin your_project pack run projects/example/pack.yaml --artefact-dir .tmp/example/pack_png
  ```

- `--png-scale`, `--datasource`, and other global options – share semantics with
  `praeparo visual run` via `PipelineOptions`.

> Tip: use `--plugin` whenever packs rely on project-specific registrations; the
> flag works both at the top level and on the `pack run` command.

**Placeholder handling**

- `--ignore-placeholders` flows into each slide’s visual context. YAML DAX visuals and Python visuals that build datasets via `MetricDatasetBuilder(context.dataset_context, ...)` will treat missing metrics as placeholders without needing per-series flags.

### Data mode examples

```bash
# Live by default when omitted
poetry run praeparo pack run projects/example/pack.yaml \
  --artefact-dir .tmp/example/pack_live

# Force mock providers for every slide in the pack
poetry run praeparo pack run projects/example/pack.yaml \
  --artefact-dir .tmp/example/pack_mock \
  --data-mode mock
```

### Logging

`praeparo pack run` emits structured logs via Python’s logging module. The CLI
defaults to `DEBUG` for Praeparo’s own logs to aid pack debugging. To keep pack
output readable, logs from other libraries are suppressed unless they are
WARNING+ by default. Opt in to full dependency logging with
`--include-third-party-logs` or `PRAEPARO_INCLUDE_THIRD_PARTY_LOGS=1`.

Adjust the Praeparo log level with either:

```bash
poetry run praeparo pack run projects/example/pack.yaml \
  --artefact-dir .tmp/example/pack_png \
  --log-level INFO
```

or by setting the environment variable:

```bash
PRAEPARO_LOG_LEVEL=INFO poetry run praeparo pack run projects/example/pack.yaml --artefact-dir .tmp/example/pack_png
```

Log records include the pack path, slide slug/title, resolved visual type,
filter key counts, and PNG/artefact destinations to help pinpoint long-running
slides and timeouts.

## Execution model

At a high level, `praeparo pack run` does the following:

1. **Load & validate** the pack YAML into `PackConfig`.
2. **Build a Jinja environment** mirroring Data.Slick helpers:
   - `odata_date`, `odata_between`, `odata_months_back_range`, `relativedelta`,
     etc.
3. **Resolve root metric context**:
   - Pack-level `context.metrics` bindings are fetched once and merged into the
     pack context as top-level Jinja variables.
4. **Resolve per-slide context and render templates**:
   - Slide-level `context` values are merged over the pack context.
   - Slide-level `context.metrics` bindings are fetched (reusing root values
     when compatible) and merged into the slide context.
   - Pack-level `filters`, `calculate`, and `define` are rendered using the pack
     context.
   - Slide-level `visual.filters` and `visual.calculate` are rendered using the
     full slide context.
5. **Merge filters**:
   - For Power BI visuals:
     - Pack-level and slide-level filters are merged (dict + dict, list + list,
       string coerced to list) and passed via `metadata["powerbi_filters"]`.
   - For DAX-backed visuals:
     - Pack-level and slide-level `calculate` filters are normalised and
       combined in order (pack first, then slide overrides).
     - Pack-level `define` (once rendered) is included alongside the merged
       `calculate` list in `metadata["context"]` so DAX planning has a single
       source of truth.
    - Power BI visuals ignore `define`; they rely on the merged OData filters in
      `metadata["powerbi_filters"]`.
6. **Resolve visuals**:
   - Each `visual.ref` is resolved to a `BaseVisualConfig` via the YAML loader.
   - A shared `VisualPipeline` uses the visual type and registry registrations
     to select the correct pipeline.
7. **Execute and persist**:
   - Each slide’s visual is executed with per-slide options:
     - PNG outputs are targeted at `<artefact-dir>/[NN]_<slide-slug>.png`.
     - `options.artefact_dir` is set to `<artefact-dir>/[NN]_<slide-slug>/` so
       visual-specific artefacts (Power BI exports, datasets) remain grouped.
   - The pack run prints a summary of how many PNGs were written.

Slides whose visuals do not emit PNGs are skipped with a warning; the pack run
never fails solely because a visual lacks a PNG renderer.

## Power BI export queue

Phase 4 adds a bounded Power BI export queue so pack runs can process multiple
Power BI slides concurrently:

- Only visuals with `type: powerbi` are queued; all other visual types continue
  to run synchronously on the main thread.
- Concurrency is capped by `--max-pbi-concurrency` (or
  `PRAEPARO_PBI_MAX_CONCURRENCY`), defaulting to `5` when neither is set.
- The runner enqueues Power BI slides first, executes non-PowerBI slides
  inline, then waits for all queued exports to complete before returning.
- If any Power BI export fails, the pack run exits non-zero after reporting the
  failed slide slugs.

Example with three exports in flight:

```bash
poetry run praeparo pack run projects/example/pack.yaml \
  --artefact-dir .tmp/example/pack_png \
  --max-pbi-concurrency 3
```

Artefact layout: `<artefact-dir>/[NN]_<slide-slug>.png` for the main PNG plus
per-slide artefacts under `<artefact-dir>/[NN]_<slide-slug>/`. The ordinal
prefix is only used for filenames/directories; `--slides` continues to match
ids/titles/unprefixed slugs.

### Debugging failing pack slides

When one or more Power BI slides fail, the runner now surfaces a detailed summary:

```
1 Power BI slide(s) failed:
  - discharges_dashboard (Discharges Dashboard): HttpError: DAX error: Token Eof expected near '!='
Hint: re-run with --slides "Discharges Dashboard" --max-pbi-concurrency 1 for focused debugging.
```

Use these flags to narrow failures and keep successful outputs:

- `--slides` – filter by slide title, id, or slugified equivalent to focus on one slide at a time.
- `--max-pbi-concurrency 1` – force serial Power BI exports to avoid concurrency noise while debugging.
- `--allow-partial` – keep successful slide artefacts and print the summary without a traceback; exit code remains non-zero so automation can detect the failure.

For DAX-backed visuals (matrix/cartesian and Python visuals that return a `MetricDatasetBuilder`), Praeparo writes the compiled `.dax` plans to each slide’s `artefact_dir` *before* execution. Check `<artefact-dir>/[NN]_<slide-slug>/*.dax` even when a slide fails.

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

## PPTX & revisions

PPTX assembly is now part of `pack run` when `result_file` is present in pipeline
metadata (automatically set via positional `dest`, `--result-file`, or a revision
allocation). Templates are resolved in order:

- `pack_template.pptx` next to the pack file,
- parent folders, or
- `registry/packs/pack_template.pptx`.

Slides without a `template` are skipped; slides with a template but no visual or
placeholders now pass through untouched so “static” template-only pages do not
break the run.

### Template geometry → render size hints (`width` / `height`)

When a pack uses a PPTX template, Praeparo can derive **render-time** size hints
from the template’s picture placeholders and attach them to each slide’s
`PipelineOptions.metadata` as `width`/`height` pixel values.

This is primarily for locally-rendered visuals (for example Python visuals,
governance matrix, and other non-PowerBI renderers) so they can size their PNG
canvas to match the template viewport before PPTX best-fit placement runs.

Rules:

- Hints are derived from the template’s placeholder dimensions (EMUs) and
  converted to pixels at a nominal 96 DPI.
- Pack CLI overrides win: explicit `--width` / `--height` are never overwritten
  by template-derived hints.
- Placeholder visuals (e.g. `slide.placeholders.left_chart.visual`) receive the
  placeholder’s size; slide-level visuals receive the template’s single-slot
  size when available.

Example (Python visuals can consume the hints):

```python
width = context.options.metadata.get("width")
height = context.options.metadata.get("height")
if width or height:
    fig.update_layout(width=width, height=height)
```

### Static images and placeholder bindings

Packs can bind static images into PPTX templates without creating a dedicated
visual:

- Slide-level `image` — use when the template has a single picture slot.
- Placeholder-level `image` — use when the template has multiple picture slots.

Slide-level image example (path is resolved relative to the pack file):

```yaml
slides:
  - id: home
    title: Home
    template: home
    image: ./assets/customer_logo.png
```

Placeholder-level image example (mix static images with visuals):

```yaml
slides:
  - id: dashboard_two_up
    title: Lodgement vs Discharges
    template: two_up
    placeholders:
      left_chart:
        visual:
          ref: ./visuals/powerbi/lodgement.yaml
      right_chart:
        image: ./assets/digital_first_logo.png
```

Notes:

- Slide-level `image` is mutually exclusive with `visual` and requires `template`.
- Placeholders are mutually exclusive per entry: each placeholder must define
  exactly one of `visual`, `image`, or `text`.
- When `--slides` is used and a skipped slide is missing PNGs, Praeparo leaves
  its template placeholders unchanged/blank; template-only slides still pass
  through unchanged.

### Text placeholders (`placeholders.*.text`)

Packs can bind **text** into PPTX templates without embedding inline `{{ ... }}`
tokens inside the PowerPoint file.

To use text placeholders:

1. In the PPTX template, set the target text shape’s **Name** to the placeholder
   id (for example `display_date_text`).
2. In the pack YAML, bind `text` for that placeholder:

```yaml
slides:
  - id: home
    title: Home
    template: home
    placeholders:
      display_date_text:
        text: "{{ month }}"
      subtitle_text:
        text:
          - "Customer: {{ customer }}"
          - "Month: {{ month }}"
```

Notes:

- `text` can be a string or a list of strings (lists are joined with `\\n`).
- Placeholder entries are mutually exclusive: each placeholder must define
  exactly one of `visual`, `image`, or `text`.
- String shorthand is supported for placeholders:
  - Path-like strings (containing `/` or ending in `.png`/`.jpg`/etc.) are treated as `image`.
  - Other strings are treated as `text`.

Shorthand example (equivalent to the long-form binding above):

```yaml
slides:
  - id: home
    title: Home
    template: home
    placeholders:
      display_date_text: "{{ month }}"
      subtitle_text: "Customer: {{ customer }}"
```
- Text placeholders render using the same slide context as the rest of the pack
  templating flow (including `context.metrics` bindings and display formatting),
  so you can reference metric aliases directly in the text value.

### Revision-aware defaults

- `--revision` – supply an explicit revision token (e.g. `2025-12`, `r17`).
- `--revision-strategy {full,minor}` – manifest-backed allocation under
  `<dest>/_revisions/manifest.json`:
  - `full` bumps/sets the revision (month from pack context when available) and
    resets minor to `1`.
  - `minor` keeps the current revision and increments the minor counter.
- `--revision-dry-run` – print the next revision (including the suggested PPTX
  name) and exit without executing visuals.

When a revision is present and no explicit `--result-file` is supplied, the
default PPTX name becomes `<pack-slug>_<revision>.pptx` (minor revisions append
`_rN`). If neither revision flag is set, the runner still attempts to use the
pack `context.month` as the revision token; otherwise it falls back to the
legacy `<pack-slug>.pptx`.

### Output location defaults

- Positional `dest` keeps the existing shorthand:
  - directory path → `<dest>/_artifacts` and `<dest>/<pack-slug>.pptx` (or
    `<pack-slug>_<revision>.pptx` when revisions apply).
  - `.pptx` path → `<dest-parent>/<dest-stem>/_artifacts` and the provided PPTX
    path.
- `--result-file` alone now implies an artefact root:
  `<result-file.parent>/<result-file.stem>/_artifacts`, so you no longer need
  to supply `dest` or `--artefact-dir` when you only care about a specific PPTX
  path.

## Changelog

- 2025-12-12: Inherit `context.metrics.calculate` into slide metric-context execution, with DEFINE/EVALUATE scoping preserved and per-slide by-name overrides.
- 2025-12-12: Added `ratio_to` support for `context.metrics.bindings` so packs can inject scalar rates/attainment values without duplicating expression bindings.
- 2025-12-12: Apply `bindings[].format` automatically for display-only Jinja rendering (PPTX text + `governance_highlights`), with `.value` escape hatch for raw numbers.
