# Epic: Slide Metric Context Bindings (Phase 6)

> Status: **Complete** – packs support `context.metrics` bindings (pack-level and slide-level) so metric KPIs are fetched via DAX and exposed as Jinja variables for PPTX/text rendering (2025-12-13).

- Implementation landed upstream in `praeparo/models/pack.py` (typed `context.metrics` models + validation) and `praeparo/pack/metric_context.py` (binding resolution + context injection).
- Canonical operator docs live in `docs/projects/pack_runner.md` (“Metric Context Bindings (`context.metrics`)”).

## 1. Problem

Text placeholders (Phase 1) and YAML-authored shapes (Phases 4–5) rely on the slide context to render metric values (e.g., `{{ count_docs_sent }}`). Today authors must inject those values manually via ad-hoc context or hard-coded expressions in PPTX, which means:

- No validation: typos in metric names silently render empty strings.
- Non-reproducible: each slide duplicates logic to fetch metrics from the semantic model.
- Hard to share: dashboards/slides that need the same KPIs have to copy/paste DAX or spreadsheets.

We want (and now have) a declarative `context.metrics` block that lists the
catalogue metrics a slide needs so Praeparo can fetch them once and make them
available to every placeholder/shape/table on that slide.

## 2. Goals

1. Add slide-level `context.metrics` declaration that lists metric keys and optional aliases.
2. Allow both mapping (`metric_key: alias`) and list (`- metric_key`) shorthand forms for declaring bindings.
3. Add a wrapper shape that can also carry metrics-only query scoping (e.g., to force a single-row grain).
4. During pack assembly, automatically run the metric builder for those keys and inject the results into the slide context as scalar values.
5. Surface friendly validation errors for unknown keys or duplicate aliases.
6. Keep the feature optional and backwards compatible—slides without `context.metrics` continue using existing context.
7. Mirror the same syntax at the **pack root** so common KPIs can be fetched once and reused across slides.
8. Leave room for ergonomics we rely on elsewhere in Praeparo (variants, scoped calculate predicates, formatter hints, expression metrics).

Out of scope for this phase: applying extra filters/variants per binding, fetching time-series arrays, or caching across slides (can follow later if needed).

See also:
- Phase 7: `7_ratio_to_in_metric_context_bindings.md`
- Phase 8: `8_formatted_metric_binding_values.md`

## 3. Proposed UX

```yaml
context:
  customer: "Example Bank"
  metrics:
    bindings:
      instructions_received: total_instructions
      documents_sent: total_documents

slides:
  - title: "{{ customer }} Dashboard Highlights"
    template: "governance_matrix_highlights"
    context:
      metrics:
        calculate:
          month: |
            'dim_calendar'[month] = DATEVALUE("{{ month }}")
        bindings:
          instructions_received: count_instructions
          documents_sent: count_docs_sent
          matters_settled: count_settlements
      governance_highlights: |
        We received {{ count_instructions | number }} instructions this month.
        {{ count_docs_sent | number }} document packs were sent in the same window.
```

Shorthand when aliases aren’t needed (list form is treated as `bindings`):

```yaml
    context:
      metrics:
        bindings:
          - documents_verified
          - documents_verified.within_1_day
```

Resolution rules:
- `context.metrics` accepts either:
  - A wrapper object with `bindings` and optional `calculate`, or
  - A shorthand mapping/list that is interpreted as `bindings` directly.
- Binding mapping form: key = catalogue metric identifier, value = alias that becomes the Jinja variable.
- Binding list form: key doubles as alias after converting dots to underscores (`documents_sent_to_custodian` → `documents_sent_to_custodian`).
- `context.metrics.calculate` scopes the **metric-context query only** (outer `CALCULATETABLE` / grain shaping), not the slide visuals.
- Validation enforces unique aliases (after normalization), and ensures each metric exists in `registry/metrics/**`.
- Root-level metrics are resolved once and merged into every slide’s context; slide-level bindings can override or extend the global aliases.
- Extended binding form (future-friendly, but safe to accept early):

  ```yaml
      metrics:
        bindings:
          - key: documents_verified
            alias: verified_total
            variant: within_1_day
            format: "percent:0"
          - key: documents_sent
            alias: pct_sent
            expression: documents_sent.within_2_business_days_from_file_ready / documents_sent
            calculate:
              customer:
                define: |
                  'dim_customer'[CustomerName] = "Example Bank"
              period:
                evaluate: |
                  'Time Intelligence'[Period] = "Current Month"
  ```

  This object form lets us support:
  - `variant`: shortcut for `key.variant` so authors don’t need dotted keys.
  - `calculate.*.define`: extra filters applied inside the adhoc measure.
  - `calculate.*.evaluate`: extra filters applied around the measure reference in `SUMMARIZECOLUMNS`.
  - `format`: downstream hint (mirrors `value_axes.format` conventions).
  - `expression`: inline arithmetic referencing other metrics or previously declared aliases, matching Praeparo visual expression semantics.

### 3.3 Nested Jinja in slide context values (important)

Some packs store display text in the slide context (for example, `governance_highlights`) and then reference it from PPTX/YAML-authored shapes:

```yaml
context:
  metrics:
    bindings:
      instructions_received: count_instructions
  governance_highlights: |
    - Instruction volume has increased by {{ count_instructions }} since last month.
```

Jinja does **not** render templates recursively by default, so Praeparo must ensure these slide-context string values are rendered **after** metric bindings are resolved and injected into the slide context. Otherwise, `{{ governance_highlights }}` will expand to a string that still contains `{{ count_instructions }}`.

## 4. Design

### 4.1 Schema (`praeparo.models.pack`)

- Extend the pack-level `context` model and `PackSlideContext` with a `metrics` field that can accept either:
  - a wrapper object (recommended), or
  - legacy shorthand (`dict`/`list`) treated as `bindings`.
- Normalize on model validation:
  - If `bindings` is a list, convert to `{metric_key: default_alias(metric_key)}`.
  - Dict bindings remain as-is.
  - Object entries support optional fields (`alias`, `variant`, `calculate`, `format`, `expression`, `override`).
- Add validators to ensure aliases are valid Jinja identifiers (letters, numbers, underscores) and unique per scope. If a slide reuses a root alias, require `override: true` to make intent explicit.

### 4.2 Assembly pipeline (`praeparo.pack.context` / `praeparo.pack.runner`)

1. Build a `MetricDatasetBuilder` scoped to the pack and reuse it for root + slide runs when possible.
2. Resolve root-level metrics first. For expression bindings, evaluate them after their dependencies are loaded (similar to Praeparo’s chart expressions).
3. For each slide:
   - Copy the global alias dict.
   - Add slide-specific bindings, respecting `override`.
   - Run the builder for any metric keys/variants not already resolved globally.
   - Evaluate expressions in dependency order.
4. Inject resolved values into the slide context and merge with user-provided entries.
5. If compilation/execution fails, surface whether the binding came from root or slide scope and include alias + metric key/expression text in the error.

### 4.3 CLI / Validation updates

- `pack validate` should confirm that each `context.metrics` key maps to a known metric before runtime (reuse customer validator logic if possible).
- Consider emitting a warning if a metric alias collides with existing context keys (authors can override intentionally, but we should log it).

## 5. Testing

- Schema tests verifying mapping vs list forms and alias normalization.
- Pack runner integration test: create a dummy pack with root + slide metrics (including expression bindings), run the pack pipeline, and assert rendered PPTX text contains values from both scopes.
- Negative tests for unknown metric keys and duplicate aliases.

## 6. Validation commands (Praeparo)

```bash
poetry run pytest tests/pack/test_pack_runner.py::test_slide_metric_context
poetry run pyright praeparo/models/pack.py praeparo/pack/context.py
poetry run python -m praeparo.schema --pack schemas/pack.json
```

## 7. Risks / Follow-ups

- **Performance:** each slide introduces more metric queries. Mitigate by batching requests per slide with one builder run.
- **Metric filters:** future enhancements may need per-binding overrides (e.g., load a variant). We can extend the schema once Phase 6 proves out.
- **Naming collisions:** alias normalization should be predictable; document the default underscore behavior clearly.

## 8. Next Steps

1. Socialize the UX with pack maintainers (align on alias normalization).
2. Implement schema + builder pipeline.
3. Land tests and schema regen.
4. Update `docs/projects/pack_runner.md` with authoring guidance + examples.
```
