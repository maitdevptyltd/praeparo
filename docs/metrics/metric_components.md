# Metric Components (`compose`)

Metric components let you reuse common metric snippets (starting with explain-only evidence exports) without copy/pasting YAML across many metrics.

Components are **opt-in**: nothing changes unless a metric explicitly lists components under `compose:`.

## Metric YAML: `compose`

Add `compose` at the metric top level:

```yaml
compose:
  - "@/registry/components/explain/default_event_metric.yaml"
```

Rules (Phase 1.5):

- `compose` must be a YAML list (order matters).
- Each entry is a file path.
  - `@/…` paths are anchored to the project root inferred from the declaring metric file.
    - If the metric lives under `registry/metrics/**`, the project root is the parent of `registry/`.
    - If the metric lives under `metrics/**`, the project root is the parent of `metrics/`.
  - Non-anchored paths are resolved relative to the YAML file that declared them.
- Missing component paths fail fast with an error that includes the declaring metric file path and the missing ref.

## Component files (`registry/components/**`)

Components live outside the metrics root so `praeparo-metrics validate <metrics-root>` does not discover them unless referenced.

A component file is a YAML mapping with a schema header:

```yaml
schema: component-draft-1

explain:
  grain: fact_events[EventKey]
  define:
    __latest_event_key: |
      MEASURE 'adhoc'[__latest_event_key] = MAX(fact_events[EventKey])
  select:
    matter_id: fact_events[MatterId]
```

Phase 1.5 support:

- Allowed top-level keys: `explain`
- Forbidden keys: metric identity fields such as `key`, `display_name`, `section`, `define`, `expression`, `variants`, etc.

## Merge order

Composition is applied deterministically alongside inheritance:

1. Resolve the metric `extends` chain (root → leaf).
2. For each metric in that chain:
   - apply its `compose` components in listed order
   - apply the metric’s own fields last (metric overrides component)
3. Apply variant overrides (parent variant → leaf variant).

This keeps component ordering stable and ensures the metric YAML remains the final authority.

