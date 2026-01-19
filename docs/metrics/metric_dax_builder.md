# Metric → DAX Builder

Praeparo ships a lightweight compiler that turns YAML-defined metrics into reusable DAX expressions.
Use it when you need canonical measures (for example: snapshotting, code-first visuals, or generating downstream artifacts) without re-implementing inheritance, variants, and expression compilation by hand.

## Quick start

```python
from pathlib import Path

from praeparo.metrics import MetricDaxBuilder, load_metric_catalog

catalog = load_metric_catalog([Path("registry/metrics")])
builder = MetricDaxBuilder(catalog)

plan = builder.compile_metric("documents_sent")

print(plan.base.expression)
for path, variant in plan.variants.items():
    print(path, "→", variant.expression)
```

What you get back is **DAX expressions**, not registered measures. Callers decide:

- where to place the measures (which table),
- how to name them, and
- how to emit them (TMDL, ad-hoc queries, visual planners, etc.).

## Inputs (registry YAML)

Metrics are loaded from YAML under your metrics root (for example `registry/metrics/**`).
Each metric can supply its base formula as either:

- `define:` — raw DAX (a measure expression or a DEFINE block, depending on the caller’s usage), or
- `expression:` — arithmetic over other metrics and variants (compiled into DAX by Praeparo; see [Metric Expressions](../visuals/metric_expressions.md)).

Variants and inherited filters are still applied on top of either base formula.

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
    - dim_status.IsComplete = TRUE()
  evaluate:
    - dim_lender.LenderId = 201
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
4. Applies inherited `calculate:` predicates (and later variant predicates) by wrapping in `CALCULATE(...)` as needed.

Expression dependencies are validated:

- Unknown identifiers fail fast.
- Circular expression dependencies are detected and surfaced.

## Common patterns

### Compile a base metric plus variants

```python
plan = builder.compile_metric("documents_sent")
base = plan.base.expression
within_1d = plan.variants["within_1_business_day_from_file_ready"].expression
```

### Compile a registry expression metric

If your YAML uses `expression:`, the builder returns a compiled base DAX snippet as normal:

```python
plan = builder.compile_metric("weighted_average_wave_money")
print(plan.base.expression)
```

## Notes and related features

- If you only need to build and execute a dataset (rows) rather than just compile measures, prefer the dataset builder APIs (for example `MetricDatasetBuilder`) documented under `docs/visuals/`.
- For authoring arithmetic expressions (including `ratio_to()`), see [Metric Expressions](../visuals/metric_expressions.md).
