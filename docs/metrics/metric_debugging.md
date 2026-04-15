# Metric Debugging

Use this page as the entry point when a metric value, visual binding, or pack
evidence export needs investigation.

Praeparo's active metric-debugging workflow is split across a few focused docs:

- [Metric Explain](metric_explain.md) covers the `explain:` schema, selector
  forms, and `praeparo-metrics explain`.
- [Metric Components](metric_components.md) covers reusable explain helpers via
  `compose:`.
- [Pack Runner](../projects/pack_runner.md) covers pack-qualified evidence
  exports and binding discovery during pack execution.
- [Context Layers](../projects/context_layers.md) covers the layered context
  merge that explain runs and pack evidence exports rely on.
- [Metric Expressions](../visuals/metric_expressions.md) covers inline
  arithmetic helpers such as `ratio_to()`, `min()`, and `max()` when the metric
  behavior itself needs inspection.

## Common Workflows

### Explain a catalogue metric

Start with the raw metric key when you need row-level evidence for a registry
metric or variant:

```bash
poetry run praeparo-metrics explain requests_processed.within_1_day
```

See [Metric Explain](metric_explain.md) for output layout, `--variant-mode`,
`--data-mode`, and `--plan-only`.

### Explain the exact binding a visual or pack renders

Use binding-qualified selectors when the same metric key can appear more than
once with different `calculate`, `ratio_to`, or pack/slide overrides:

```bash
poetry run praeparo-metrics explain projects/example/visual.yaml#series_id
poetry run praeparo-metrics explain projects/example/pack.yaml#0 --list-bindings
poetry run praeparo-metrics explain projects/example/pack.yaml#0#series_id
```

See [Metric Explain](metric_explain.md) for selector syntax and
[Pack Runner](../projects/pack_runner.md) for pack-qualified evidence exports.

### Reuse evidence columns and helpers

Use metric components when multiple metrics need the same explain grain,
diagnostic selects, or explain-only `define:` helpers:

```yaml
compose:
  - "@/registry/components/explain/default_event_metric.yaml"
```

See [Metric Components](metric_components.md) for the component contract and
merge order.

### Keep explain runs aligned with pack semantics

Explain runs use the same layered context model as packs. Shared filters,
defines, and reporting-window payloads should live in context layers rather
than being retyped per command.

See [Context Layers](../projects/context_layers.md) for merge order and layer
shapes.
