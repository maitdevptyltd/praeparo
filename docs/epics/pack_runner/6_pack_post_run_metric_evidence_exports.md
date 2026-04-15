# Epic: Pack Post-Run Metric Evidence Exports (Phase 6)

> Status: **Implemented** - packs can now declare post-run evidence exports for selected visual bindings, reusing the same selector and explain surfaces as `praeparo-metrics explain` (2026-04-15).

- Canonical developer docs live in `docs/projects/pack_runner.md` and `docs/metrics/metric_explain.md`.

## Scope

Phase 6 is implemented upstream. This phase record remains as implementation
history for the evidence-export contract, binding-selection model, and output
layout used during pack execution.

## 1. Problem

Pack runs export slide PNGs but do not automatically emit row-level explain
evidence for the KPI/SLA values shown on those slides.

In practice, when analysts ask "show your working" for a headline KPI/SLA,
engineers must:

- manually identify the metric binding as used by the pack slide, including
  slide or placeholder overrides
- run `praeparo-metrics explain` using a pack-qualified selector
- decide where to store the resulting CSV, `explain.dax`, and `summary.json`

This is slow, error-prone, and easy to drift:

- a binding is not just a metric key; binding-level `calculate` and `ratio_to`
  can materially change the value
- pack or slide context, templated month windows, and merged filters must be
  included or the evidence will not match the rendered number

## 2. Goals

Phase 6 introduced a pack-authored configuration surface that:

1. **Declares what evidence to export in YAML**
   - pack authors opt into evidence export at pack level, then target specific
     slide visual instances including placeholders

2. **Selects bindings via simple, plugin-defined attributes**
   - packs select bindings by metadata keys such as `sla` or `ratio_to`
     attached by the visual's bindings adapter

3. **Guarantees "same semantics as the rendered value"**
   - evidence is generated for the pack-qualified binding instance using the
     same effective pack, slide, and visual context as rendering

4. **Writes outputs alongside the pack artefacts**
   - evidence is stored under the pack artefact directory with a manifest for
     traceability

5. **Is safe and ergonomic for operators**
   - support idempotent reruns, bounded concurrency, and explicit controls for
     variant handling

## 3. Non-goals

- Defining or interpreting what an SLA means in business terms
- Replacing `praeparo-metrics explain` as an interactive debugging tool
- Evidence for non-metric-backed visuals

## 4. Pack YAML Surface

### 4.1 Pack-level defaults (`pack.evidence`)

```yaml
evidence:
  enabled: true
  output_dir: "_evidence"
  when: "pack_complete"
  on_error: "fail"
  explain:
    limit: 50000
    variant_mode: "flag"
    max_concurrency: 1
    skip_existing: true
```

### 4.2 Slide/placeholder targeting

Because a visual can be reused with different slide or placeholder context,
evidence attaches to the pack visual instance:

```yaml
slides:
  - id: performance_dashboard
    visual:
      ref: ./visuals/performance_dashboard.yaml
    evidence:
      bindings:
        select: [sla]
```

For placeholders:

```yaml
slides:
  - id: performance_dashboard_follow_up
    placeholders:
      top_left:
        visual:
          ref: "@/visuals/example_dashboard.yaml"
        evidence:
          bindings:
            select: [ratio_to]
```

### 4.3 Binding selectors (`evidence.bindings`)

```yaml
evidence:
  bindings:
    select: [sla, ratio_to]
    select_mode: all
    include: ["document_verification#documents_verified.within_2_days"]
    exclude: ["root#weighted_average"]
```

Notes:

- `select` is matched against `VisualMetricBinding.metadata`
- `select_mode` defaults to `all`
- `include` and `exclude` refine selection after metadata matching

## 5. Binding Metadata Contract

To make attribute selection possible, `VisualMetricBinding` carries a generic
metadata bag:

- `VisualMetricBinding.metadata: Mapping[str, object]`

Bindings adapters populate this. Examples:

- a visual row with `sla:` metadata can expose `metadata["sla"]`
- a binding that declares `ratio_to:` can expose `metadata["ratio_to"]`

This keeps core Praeparo generic while allowing custom visual types to project
their own binding attributes into pack evidence selection.

## 6. Execution Semantics

Evidence export reuses the same planning and execution surfaces as
`praeparo-metrics explain`:

- pack-qualified binding explains ensure the evidence matches pack or slide
  context
- explain outputs include:
  - `evidence_<metric_slug>.csv`
  - `explain.dax`
  - `summary.json`

### 6.1 Variant handling

- `flag`: export base population and add `__passes_variant` when possible
- `filter`: apply variant filters to the evidence rowset

### 6.2 Idempotency (`skip_existing`)

When `skip_existing: true`, Praeparo skips only when the prior
`manifest.json` records a matching inputs fingerprint. The fingerprint captures
the binding selector, effective calculate or define context, explain options,
and datasource identity so reruns do not quietly reuse stale evidence.

### 6.3 Non-catalog bindings

Bindings that do not reference a catalog metric key are skipped with manifest
warnings instead of being treated as evidence rows by default.

## 7. Output Layout

Evidence is written under the pack artefact directory:

- `<artefact_dir>/<output_dir>/manifest.json`
- `<artefact_dir>/<output_dir>/<slide_slug>/<binding_slug>/evidence_<metric_slug>.csv`
- `<artefact_dir>/<output_dir>/<slide_slug>/<binding_slug>/_artifacts/explain.dax`
- `<artefact_dir>/<output_dir>/<slide_slug>/<binding_slug>/_artifacts/summary.json`
- placeholder-based slides insert the placeholder id into the path

The manifest records the resolved binding metadata, selector matches, timings,
fingerprints, and output paths so evidence runs remain traceable and
reproducible.

## 8. Completion Notes

Implementation evidence lives in:

- `praeparo/models/pack_evidence.py`
- `praeparo/pack/evidence.py`
- `praeparo/pack/runner.py`
- `tests/pack/test_pack_evidence_exports.py`
- `docs/projects/pack_runner.md`
- `docs/metrics/metric_explain.md`

## 9. Acceptance Criteria

1. Packs can opt into evidence exports with pack-level `evidence` config.
2. Binding selection uses metadata keys attached by bindings adapters.
3. Pack-qualified bindings produce evidence with the same effective context as
   rendering.
4. Evidence outputs land under the pack artefact directory with a manifest.
5. Skip-existing behavior is fingerprint-based rather than file-existence-only.
