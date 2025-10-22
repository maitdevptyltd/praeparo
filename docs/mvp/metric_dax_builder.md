# Metric → DAX Builder

Praeparo now exposes a lightweight compiler that turns metric definition YAML into reusable DAX expressions. Use it when you need canonical measures for downstream tooling (for example, Metrics snapshotting or future matrix planners) without re-implementing inheritance and variant logic by hand.

## Quick start

```python
from pathlib import Path

from praeparo.metrics import (
    MetricDaxBuilder,
    load_metric_catalog,
)

catalog = load_metric_catalog([Path("registry/metrics")])
builder = MetricDaxBuilder(catalog)

plan = builder.compile_metric("documents_sent")

print(plan.base.expression)
# CALCULATE(
#     SUM('fact_events'[DocumentsSent]),
#     dim_status.IsComplete = TRUE()
# )

for path, variant in plan.variants.items():
    print(path, "→", variant.expression)
```

## Behaviour

- **Inheritance aware** – the builder walks the `extends` chain, re-using the most recent `define:` block and stacking every `calculate:` filter from parent → child. Missing `define:` entries raise an error so metrics stay grounded in a DAX expression.
- **Variant support** – any variants declared in the metric YAML (including nested paths) gain their own measure definition. Filters from each variant level cascade in the order they appear within the YAML.
- **Raw expressions** – the builder returns DAX snippets only; callers decide where to register measures (for example `DEFINE MEASURE 'adhoc'[documents_sent] = ...`). This lets downstream systems control naming and table placement.
- **Ratios** – the current API surfaces variant metadata only. Automatic ratio generation will land in a follow-up iteration once the consuming projects lock in naming conventions.

## When to use it

- Generating stable DAX for regression snapshots or bespoke visuals.
- Ensuring derived metrics inherit the same predicates as their parents without copy-pasting filters.
- Powering editor tooling or CLI commands that need to show the final DAX alongside YAML definitions.

## Future work

- Optional helpers for auto-generated ratio measures (`ratios.auto_percent_of_base`, explicit ratio definitions).
- Export hooks that map metric metadata to row descriptors for matrix planners.
- End-to-end notebooks showing how to blend customer registries with compiled metric expressions.
