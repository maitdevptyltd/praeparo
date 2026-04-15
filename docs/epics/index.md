# Framework Epics

This folder keeps phase records for framework features whose design
work originally lived in downstream consumer epics.

Use these pages for implementation history, trade-off summaries, and migration
context. For current behavior and supported contracts, start with the linked
developer-facing docs instead of treating these notes as the source of truth.

Current topics:

- [Registry Expression Metrics / Phase 1](registry_expression_metrics/1_expression_metrics_in_registry.md)
  Status: **Complete** for Phase 1; [Phase 2](registry_expression_metrics/2_variant_expressions_and_migration.md) remains **Draft**
- [Registry-Root Anchored Visual Paths](registry_paths/1_registry_root_anchored_visual_paths.md)
  Status: **Draft**
- [Context Layers](context_layers.md)
  Status: **Implemented**
  Active docs: [Projects / Context Layers](../projects/context_layers.md)
- [Metric Debugging And Bindings](metric_explain_and_bindings.md)
  Status: **Implemented**
  Active docs: [Metrics / Metric Debugging](../metrics/metric_debugging.md),
  [Metrics / Metric Explain](../metrics/metric_explain.md),
  [Metrics / Metric Components](../metrics/metric_components.md),
  [Projects / Pack Runner](../projects/pack_runner.md)
- [Metric Expressions: `ratio_to()`](metric_expression_ratio_to.md)
  Status: **Complete**
  Active docs: [Visuals / Metric Expressions](../visuals/metric_expressions.md)
- [Metric Expressions: `min()` / `max()`](metric_expression_min_max.md)
  Status: **Complete**
  Active docs: [Visuals / Metric Expressions](../visuals/metric_expressions.md)
