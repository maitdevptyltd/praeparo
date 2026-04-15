# Epic: First-Class Expression Metrics in Registry (Phase 1)

> Status: **Complete** – registry metrics can declare `expression:` (instead of `define:`) and Praeparo compiles them into DAX measures with dependency and cycle validation (2025-12-13).

- Implementation landed in `praeparo/metrics/models.py` (adds `expression`) and `praeparo/metrics/dax.py` (compiles registry expressions via `resolve_expression_metric`).
- Expression grammar (including `ratio_to(...)`) is documented in `../visuals/metric_expressions.md`.

## 1. Context

Praeparo’s metric catalogue supports:
- Base measures via `define` (raw DAX).
- Variants via additional `calculate` filters.
- Derived ratios via `ratios`.

Arithmetic expressions can be authored at both:

- **Registry definition time** (`registry/metrics/**` via `expression:`), and
- **Use-site** time (visual series or project registry expression rows).

Projects can contain repeated use-site expressions (for example, weighted SLA
averages) that would benefit from being defined once in the registry and reused.

## 2. Problem

Expression metrics are currently:
- Ad hoc per visual/pack.
- Not reusable or inheritable.
- Harder to validate centrally.

We need to support **first-class expression metrics** inside the registry so
they compile like any other metric and can be referenced by key across visuals.

## 3. Goals

Phase 1 SHOULD:

1. Extend Praeparo metric definitions with an optional `expression` field.
2. Compile `expression` into a DAX measure using the existing expression grammar.
3. Support inheritance (`extends`) for expression metrics.
4. Preserve variants and filters on top of compiled expressions.
5. Detect and surface circular dependencies between expression metrics.
6. Keep all existing `define` metrics backwards-compatible.

Out of scope:
- Variant-level expressions (Phase 2).
- Syntactic sugar DSLs beyond the current Python-AST expression grammar.

## 4. Proposed UX

Example metric YAML:

```yaml
key: weighted_average.example
display_name: Weighted Average from File Ready
section: dashboard
description: Weighted SLA-style average across timeliness metrics.

expression: |
  (
    ratio_to(documents_sent.within_1_business_day_from_file_ready) * 0.85 +
    ratio_to(documents_sent.within_2_business_days_from_file_ready) * 1.0
  ) / 1.85

format: percent:1
```

Rules:
- `expression` is mutually exclusive with `define` on the same effective metric.
  - In an extends chain, the **leaf** may override by supplying either `expression`
    or `define`, but not both at the same level.
- `expression` uses the same grammar as inline visuals, including `ratio_to()`.
- `calculate` filters still wrap the compiled expression in `CALCULATE`.
- Variants continue to add filters on top of the base expression.

## 5. Design

### 5.1 Metric models

File: `praeparo/metrics/models.py`

- Add `expression: str | None` to `MetricDefinition`.
- Normalise and validate:
  - strip, non-empty if present.
  - reject defining both `define` and `expression` on the same metric document.

### 5.2 Expression compiler refactor

Today, expression compilation lives in:
`praeparo/visuals/dax/expressions.py`
and depends on metrics types, which would create circular imports if used by
`MetricDaxBuilder`.

Refactor to a neutral module, e.g.:
`praeparo/expressions/metrics.py`
containing:
- `MetricReference`
- `ParsedExpression`
- `parse_metric_expression`
- `compile_expression_measure` (current `resolve_expression_metric`)

Keep `visuals/dax/expressions.py` as a thin re-export to preserve API stability.

### 5.3 MetricDaxBuilder support

File: `praeparo/metrics/dax.py`

- Resolve inheritance chain as today.
- Determine the effective base formula:
  1. last non-empty `expression` in the chain, else
  2. last non-empty `define` in the chain, else error.
- If using `expression`:
  - Compile to DAX via the shared expression compiler.
  - Then apply inherited `calculate` filters via existing `_compose_calculate`.
- Variants:
  - Reuse the compiled base expression.
  - Add variant filters on top, exactly as today.

### 5.4 Dependency + cycle detection

Expression metrics can reference other expression metrics.

File: `praeparo/visuals/dax/cache.py`

- Extend `MetricCompilationCache.get_plan` with an “in-progress” sentinel set.
  - If a metric is requested while already in progress, raise a clear circular
    dependency error naming the chain.

### 5.5 Schema + validation

- Update Praeparo metrics JSON schema to include `expression`.
- `praeparo-metrics validate` must accept `define` or `expression`.
- Update any docs that reference `define` as mandatory.

## 6. Tests

Files:
- `tests/metrics/test_dax_builder.py`
- `tests/visuals/dax/test_expressions.py` (if module refactor needs it)

Add cases for:
1. Registry expression metric compiles to DAX (including ratio_to()).
2. Expression metric with variants applies base expression + variant filters.
3. Expression metric inheriting via `extends` resolves leaf formula correctly.
4. Circular dependency between expression metrics raises friendly error.
5. Existing define-based metrics unchanged.

## 7. Validation

```bash
poetry run pytest tests/metrics/test_dax_builder.py
poetry run pytest tests/visuals/dax/test_expressions.py
poetry run pyright praeparo/metrics \
  praeparo/expressions/metrics.py \
  praeparo/visuals/dax/expressions.py
poetry run praeparo-metrics validate <metrics_root>
```

## 8. Risks / Open Questions

- **Inheritance precedence:** confirm leaf `expression` vs `define` priority.
- **Error clarity:** circular errors must be actionable for analysts.
- **Performance:** expression compilation may re-resolve many measures; rely on
  cache to avoid quadratic rebuilds.

## 9. Next Steps

- Land expression compiler refactor.
- Add `expression` field and MetricDaxBuilder path.
- Add tests + schema updates + docs.
