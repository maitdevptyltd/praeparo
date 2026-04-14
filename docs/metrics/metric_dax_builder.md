# Metric → DAX Builder

Praeparo turns YAML-defined metrics into reusable DAX expressions.
Use it when you want the same metric logic to power visuals, snapshots, or other outputs without rebuilding inheritance, variants, or expression handling yourself.

## Quick start

```python
from pathlib import Path

from praeparo.metrics import MetricDaxBuilder, load_metric_catalog

catalog = load_metric_catalog([Path("registry/metrics")])
builder = MetricDaxBuilder(catalog)

plan = builder.compile_metric("sample_metric")

print(plan.base.expression)
for path, variant in plan.variants.items():
    print(path, "→", variant.expression)
```

What you get back is **DAX expressions**, not registered measures. You decide:

- which table to place them in,
- how to name them, and
- how to write them out (TMDL, ad-hoc queries, visual plans, and so on).

Visual pipelines can pass those DAX snippets into `praeparo.visuals.dax.render_visual_plan` and add visual-specific naming, ratio, or SLA presentation rules on top. The builder stays focused on metric compilation.

## Inputs (registry YAML)

The builder reads metric YAML from your metrics root (for example `registry/metrics/**`).
Each metric can supply its base formula as either:

- `define:` — raw DAX (a measure expression or a DEFINE block, depending on the caller’s usage), or
- `expression:` — arithmetic over other metrics and variants (compiled into DAX by Praeparo; see [Metric Expressions](../visuals/metric_expressions.md)).

Variants and inherited filters are still applied on top of either base formula.

When a visual pipeline already has a prepared `ExecutionContext.dataset_context`, reuse it instead of looking up roots again inside each visual. That keeps the metric catalog, datasource environment, and renderer aligned for the run.

## Behaviour

### Inheritance (`extends`)

- The builder walks the `extends` chain and composes the **effective** metric definition.
- The leaf-most base formula wins:
  - a child `expression:` overrides a parent `define:`, and vice versa.
- Every `calculate:` predicate across the chain is accumulated parent → child.

### Scoped `calculate:`

Registry metrics support scoped calculate filters, mirroring the visual `ScopedCalculateFilters` model:

```yaml
calculate:
  define:
    - dim_status.IsActive = TRUE()
  evaluate:
    - dim_region.RegionCode = "A"
```

- `calculate` provided as a string or list of strings is treated as **DEFINE-scoped** filters (backwards compatible).
- **DEFINE** filters are baked into the compiled measure expression by wrapping the base formula in `CALCULATE(...)`.
- **EVALUATE** filters are attached to the compiled plan and applied when binding measures in queries (for example: wrapping the measure reference inside `SUMMARIZECOLUMNS`).

If a circular `extends` chain is detected, compilation fails with a friendly error.

### Variants

- Variants become additional compiled measure definitions.
- Nested variants are supported, and filters cascade by variant nesting order.

### `expression:` metrics

When a metric declares `expression:`, Praeparo:

1. Parses the expression AST and identifies referenced metric identifiers.
2. Compiles those referenced metrics/variants into DAX.
3. Substitutes the referenced DAX snippets into the expression.
4. Applies inherited `calculate:` predicates, and later variant predicates, by wrapping the result in `CALCULATE(...)` when needed.

Expression dependencies are validated:

- Unknown identifiers fail fast.
- Circular expression dependencies are detected and surfaced.

## Common patterns

### Compile a base metric plus variants

```python
plan = builder.compile_metric("sample_metric")
base = plan.base.expression
within_1d = plan.variants["within_1_day"].expression
```

### Compile a registry expression metric

If your YAML uses `expression:`, the builder returns a compiled base DAX snippet as normal:

```python
plan = builder.compile_metric("weighted_average_metric")
print(plan.base.expression)
```

## Notes and related features

- If you need rows rather than just compiled measures, use the dataset builder APIs (for example `MetricDatasetBuilder`) documented under `docs/visuals/`.
- If you need the full DAX statement for a visual, compile with `MetricDaxBuilder` first and let the visual pipeline render the query shape; `render_visual_plan` already handles the measure binding.
- For arithmetic expressions, including `ratio_to()`, see [Metric Expressions](../visuals/metric_expressions.md).
