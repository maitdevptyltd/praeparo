# Epic: Metric Debugging And Bindings

> Status: **Implemented** for Phases 1 and 2. Phase 1.5 informed the final `compose` contract, and Phase 3 remains a documented design follow-on.

This page preserves the full multi-phase design history for metric evidence
exports, binding-qualified explains, reusable explain composition, and
context-driven augmentations.

Current developer guidance lives in:

- [Metrics / Metric Debugging](../metrics/metric_debugging.md)
- [Metrics / Metric Explain](../metrics/metric_explain.md)
- [Metrics / Metric Components](../metrics/metric_components.md)
- [Projects / Context Layers](../projects/context_layers.md)
- [Projects / Pack Runner](../projects/pack_runner.md)

## Why This Epic Family Existed

Headline KPI values were not enough for reconciliation work. Analysts and
engineers needed reproducible row-level evidence that explained:

- which rows were included
- which timestamps and deltas were used
- why a variant or SLA check passed or failed
- how a visual or pack binding changed the effective metric context

The design problem was broader than "debug this one metric". In practice,
metric behavior is compiled from inheritance, variant filters, context layers,
binding overrides, ratio relationships, and reporting windows. The framework
needed a repeatable way to explain that *effective plan* without requiring
bespoke DAX per metric or per visual binding.

## Phases At A Glance

This epic family evolved in four linked phases:

1. **Phase 1**: per-metric `explain:` specs and `praeparo-metrics explain`
2. **Phase 1.5**: reusable metric components and explain-scoped helpers
3. **Phase 2**: visual- and pack-qualified binding explains
4. **Phase 3**: context-driven composition augmentations

Current status:

- Phase 1 is implemented
- Phase 1.5 informed the final `compose` contract
- Phase 2 is implemented
- Phase 3 remains a design follow-on

## Phase 1: Explain CLI + Per-Metric Explain Specs

Status: **Implemented**.

### Problem framing

The initial phase treated "debugging a metric" as debugging a compiled metric
context:

- base definition plus inherited filters
- variant filters
- context-layer and CLI filters
- ratio relationships
- current date window

The core requirement was a framework-owned evidence export, not legacy
comparison logic or bespoke queries.

### `explain:` schema

The original phase defined a small, merge-friendly surface:

```yaml
explain:
  define:
    <name>: <dax define fragment>
  from: <table_ref>
  where:
    - <dax_predicate>
  grain: <dax_column_ref_or_mapping>
  select:
    <label>: <dax_expr>
```

Key rules from the phase record:

- `select` is a mapping so outputs stay named and merge predictably
- `grain` may be a single column reference or a mapping of names to refs
- `where` is append-only and intentionally small
- `define` is explain-only and must not affect compiled metric measures
- labels prefixed with `__` are reserved for framework-owned fields

### Merge semantics

The original deep-merge contract mattered:

- `from`: last-writer-wins
- `grain` in mapping form: merge by key, last-writer-wins
- `select`: merge by key, last-writer-wins
- `where`: append-only
- `define`: named entries last-writer-wins, unlabelled entries append with
  de-duplication

The phase also treated variant inheritance carefully:

- variants inherit base explain config by default
- variants patch rather than replace the whole explain block

### CLI contract

The intended command shape was:

```bash
poetry run praeparo-metrics explain <metric_key> [dest] \
  --metrics-root <metrics_root> \
  --context <context YAML> \
  --calculate <extra filters> \
  --limit 50000
```

Important ergonomics preserved in the epic record:

- explain uses positional input and output like the pack runner
- month or date windows come from context, not a standalone `--month`
- `dest` may be omitted, a directory, or a file path
- outputs include the evidence file plus an artefacts directory

### Outputs and default columns

The phase specified three outputs:

- `explain.dax`
- `evidence.csv` or equivalent evidence export
- `summary.json`

It also called for framework-owned columns such as:

- `__metric_key`
- `__metric_value`
- `__grain_table`
- `__grain_key`
- `__grain`
- `__passes_variant` when explaining a variant against its base population
- numerator and denominator fields when ratios are involved

### Query shape

The original design deliberately preferred a row-based evidence export:

- build a rowset with `CALCULATETABLE(...)`
- export requested fields with `SELECTCOLUMNS(...)`
- compute headline metric values once and repeat them as constant columns

That decision was recorded explicitly because a grouped "measure-per-row"
approach would have been slower and harder to interpret.

### Risks and unresolved questions

Phase 1 called out several key risks:

- extracting population filters from arbitrary `define` blocks is brittle
- not all metrics are event-backed, so default grain assumptions can mislead
- large periods can produce oversized evidence exports

Those concerns are part of why the final explain surface stayed intentionally
small.

### Recorded Phase 1 milestones

The original changelog for Phase 1 captured a useful sequence:

- an early `debug:` draft before the surface settled on `explain:`
- the shift to a row-based `CALCULATETABLE + SELECTCOLUMNS` design
- guidance to prefer `calculate` over parsing arbitrary `define` blocks
- the CLI ergonomics uplift to match pack runner conventions
- the later introduction of explain-only `define` helpers and the
  implementation milestone for the final Phase 1 contract

## Phase 1.5: Metric Composition Components

Status: **Implemented in outcome** through the final `compose` contract, with
the original phase record retained here because it explains why the component
surface stayed generic.

### Why composition was introduced

Once per-metric `explain:` specs existed, the next pain point was repeated
diagnostic columns and explain-only helper measures scattered across many
metrics and variants.

The original phase wanted a way to:

- define explain logic once
- reuse it across metrics, variants, and bindings
- keep the effective explain query deterministic and reviewable
- avoid inventing a one-off "debug-only" extension system

### `compose:` contract

The phase introduced a metric-level `compose:` list:

```yaml
compose:
  - "@/registry/components/explain/default_event_metric.yaml"
```

Rules from the phase record:

- `compose` is ordered
- `@/` paths are anchored to the project root
- non-anchored paths resolve relative to the declaring YAML file
- missing paths fail fast with a clear diagnostic

### Explain-scoped helpers

The phase also added `explain.define` as an explain-only helper surface:

```yaml
explain:
  define:
    __latest_event_key: |
      MEASURE 'adhoc'[__latest_event_key] = MAX(fact_events[EventKey])
```

The reasoning mattered:

- helpers should travel with the explain logic that needs them
- explain-only helpers must not leak into the compiled metric measure
- conflicts must be deterministic and easy to debug

### Component files and merge order

The phase proposed dedicated component files outside the discovered metrics
root, with a small schema and deterministic merge order:

1. resolve the `extends` chain
2. apply components in listed order
3. apply the metric's own fields last
4. apply variant overrides on top

For explain surfaces:

- `explain.grain`: mapping keys merge, string replaces
- `explain.select`: merge by label
- `explain.define`: merge by helper name

### Why it stayed generic

This phase record is important because it explains a major design choice:
reusable explain fragments were handled through generic metric components, not
through a bespoke "debug augmentation" surface. That decision set up Phase 3.

### Recorded Phase 1.5 milestones

The original changelog for Phase 1.5 recorded:

- the first draft for metric composition components
- the removal of an extra `kind` field from the component examples
- the rename from a later-numbered phase to Phase 1.5 once
  `explain.define` and `compose` became clearly tied to the earlier explain
  work

## Phase 2: Explain Visual Metric Bindings

Status: **Implemented**.

### Problem framing

Analysts rarely validate only the raw catalogue metric. They validate the exact
value rendered in a visual or pack, where binding-level `calculate`, `ratio_to`,
section context, slide context, and reporting-window overrides may all change
the effective value.

The phase therefore moved from "explain a metric key" to "explain a specific
binding instance".

### Selector grammar

The original phase preserved a concrete selector model:

```bash
poetry run praeparo-metrics explain <visual_path>#<binding_selector...> [dest]
poetry run praeparo-metrics explain <pack_path>#<slide_id>#<binding_selector...> [dest]
poetry run praeparo-metrics explain <pack_path>#<slide_id>#<placeholder_id>#<binding_selector...> [dest]
```

Key behaviors:

- selector identity is binding-oriented, not metric-key-oriented
- pack slide selectors may use ids or 0-based numeric fallbacks
- placeholder-based slides require an explicit placeholder segment
- discovery helpers are part of the contract, not an afterthought

### Discovery helpers

The phase explicitly included:

- `--list-slides` for packs
- `--list-bindings` for visuals
- `--list-bindings` for pack-qualified visuals

This mattered because binding ids are the stable way to target one concrete
instance when the same metric appears multiple times with different overrides.

### Output contract

Phase 2 preserved the Phase 1 outputs and added binding-aware metadata columns
such as:

- `__visual_path`
- `__binding_id`
- `__binding_metric_key`
- `__binding_label`
- `__ratio_to`

For ratio bindings, the phase record also required:

- `__numerator_key` / `__numerator_value`
- `__denominator_key` / `__denominator_value`
- `__ratio_value`

### Binding planning semantics

The phase documented a specific merge order for calculate scopes:

1. registry metric calculate
2. registry variant calculate
3. section calculate, when applicable
4. binding calculate
5. CLI `--calculate` fragments

It also preserved a critical design decision: ratio semantics for binding
explains must align with the runtime semantics used by the dataset builder, not
with any bespoke explain-only implementation.

### Runtime integration notes

The phase record also captured several decisions that would otherwise be easy
to lose:

- explain should accept plugin-loaded visuals and bindings adapters
- discovery and explain should work across visual types through an adapter
  layer, not hard-coded governance-matrix logic
- output path derivation should match pack-style ergonomics

### Recorded Phase 2 milestones

The original changelog for Phase 2 captured the path from draft to
implementation:

- the first binding-explain draft for visual bindings
- the decision to use `praeparo-metrics explain <path>#<selector...>` rather
  than a separate CLI
- the addition of pack-qualified selectors and 0-based index fallbacks
- discovery flags for slides and bindings
- the final implementation milestone covering selector parsing, discovery,
  bindings adapters, and binding-aware explain planning

## Phase 3: Composition Augmentations Via Context

Status: **Design follow-on**.

### Why a new phase was needed

Phases 1 and 2 made evidence exports possible. Phase 1.5 made explain fragments
reusable. The next design problem was how to apply those reusable components
automatically when the effective binding context clearly signaled a feature.

The original example was a calc-group selection that changes which event in a
series counts toward the metric. Analysts often need additional row-level flags
when such a selector is active, but that need should not force a bespoke
"debug-only" augmentation mechanism.

### `composition:` context surface

The phase proposed a context-level composition surface:

```yaml
composition:
  compose:
    - "@/registry/components/<path>.yaml"
  augmentations:
    <augmentation_id>:
      enabled: true
      priority: 0
      when:
        calculate_keys_any: ["latest_event_mode"]
        dax_tables_any: ["Calculation Mode"]
        dax_contains_any: ["'Calculation Mode'[Instance]"]
      requires:
        grain_table: fact_events
      compose:
        - "@/registry/components/explain/default_event_metric.yaml"
```

The design goals were:

- let any layered context contribute composition behavior
- match against simple signals first
- remain deterministic and reviewable
- expose traceability in `summary.json`

### Effective composition plan

The original merge order was:

1. start with the metric's own `compose` list
2. append unconditional `composition.compose` entries from layered contexts
3. evaluate `composition.augmentations` against the effective calculate stack
4. apply matching augmentations in stable priority and id order
5. emit traceability for detected signals, applied augmentations, and final
   component refs

The phase also allowed later layers to disable earlier augmentation ids by
redeclaring them with `enabled: false`.

### Why this stayed a draft

This phase record is important because it records what was intentionally not
done:

- no full DAX parser for signal extraction
- no general query language for augmentation conditions
- no attempt to auto-infer the right explain grain for every metric type

That restraint explains why the final active surfaces stayed smaller and more
predictable.

### Recorded Phase 3 milestones

The original changelog for Phase 3 recorded:

- the first draft as an explain-only auto-select mechanism
- the later refocus toward a general composition augmentor driven by context
- follow-on alignment with Phase 1.5 component naming and `@/` path rules

## Lasting Design Decisions

Across the whole epic family, these ideas survived:

- the framework explains compiled context, not a downstream workbook format
- binding identity is selector-based because metric keys are not unique enough
- reusable explain fragments belong in generic components
- layered context is part of explain semantics, not a separate concern

This epic page preserves the design history and the phase-level contracts that
led to the current implementation surfaces. For current behavior, start with
[Metrics / Metric Debugging](../metrics/metric_debugging.md).
