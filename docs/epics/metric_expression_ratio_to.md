# Epic: Metric Expressions `ratio_to()`

> Status: **Complete**

This page preserves the detailed phase record for adding `ratio_to()` to
Praeparo's metric expression language.

Current developer guidance lives in:

- [Visuals / Metric Expressions](../visuals/metric_expressions.md)
- [Metrics / Metric -> DAX Builder](../metrics/metric_dax_builder.md)

## Scope

Phase 1 added first-class `ratio_to()` calls inside inline expressions and
expression-backed metrics.

The code landed in the expression parser, DAX compiler, and mock evaluator, but
the epic remains useful because it documents the parser contract, error
handling, dependency rules, and test expectations that explain why the feature
looks the way it does.

## Context And Problem

Praeparo already supported presentation-time `ratio_to` for visual bindings,
applied after query execution. That worked for charts and dashboard rows, but
it was not enough when expression authors needed ratios to participate inside
larger formulas.

The motivating problem was weighted formulas of the form:

```python
ratio_to(requests_processed.within_1_day) * 0.85 +
ratio_to(requests_processed.within_2_days) * 1.0
```

Without `ratio_to()` in the expression language, authors had to create extra
percent metrics purely so arithmetic formulas could refer to them.

Because expressions are parsed as Python, syntax like `metric:ratio_to` was not
viable. A native function call was the lowest-risk extension.

## Goals

The phase set out to:

1. add a first-class `ratio_to()` function to the expression language
2. mirror existing ratio semantics
3. preserve parity between DAX compilation and mock evaluation
4. keep existing expressions backwards-compatible

The epic explicitly did not try to:

- change the existing visual-level `ratio_to` behavior
- introduce a second DSL
- add extra syntactic sugar before the core contract existed

## Proposed UX

Expressions may call `ratio_to` with one or two positional arguments:

```yaml
expression: |
  ratio_to(requests_processed.within_1_day) * 0.85 +
  ratio_to(requests_processed.within_2_days, "requests_processed") * 1.0
```

Rules from the original phase:

- `ratio_to(<metric_ref>)` infers the denominator from the immediate parent of
  a dotted key
- `ratio_to(<metric_ref>, "<denominator_key>")` uses an explicit denominator
- keyword arguments are rejected
- nested calls are technically allowed but expected to stay rare

The user-facing validation mattered because the shorthand only works when the
numerator key is dotted.

## Design Record

### Parser and AST contract

The original design extended the expression visitor to accept `ast.Call` nodes
where:

- `node.func` is `ratio_to`
- there are one or two positional arguments
- the first argument resolves to a metric identifier
- the optional second argument is a non-empty string metric key

The phase also introduced the idea that a metric reference may carry an
optional `ratio_to_ref`, so dependency resolution can track both numerator and
denominator even when the denominator is not otherwise referenced.

### DAX compilation

The chosen DAX emission was deliberately simple:

- render the numerator from the resolved metric substitution
- render the denominator from the resolved denominator substitution
- emit `DIVIDE(numerator, denominator)` for blank-safe and zero-safe behavior

That decision avoided divide-by-zero surprises and kept the compiler aligned
with the semantics already used elsewhere in Praeparo.

### Dependency resolution

One subtle but important part of the phase was dependency discovery:

- `resolve_expression_metric` had to resolve denominator identifiers introduced
  by `ratio_to()`
- denominator dependencies needed to be carried even if they were not otherwise
  referenced in the expression tree

Without that, the compiler could emit a `DIVIDE` call that referenced a metric
the plan had never compiled.

### Mock-evaluation parity

The mock evaluator had to grow the same function surface:

- resolve numerator and denominator values from the environment
- apply the same divide-by-zero handling used by runtime semantics

The phase record also captured an open question that mattered at the time:
whether divide-by-zero or missing-denominator cases should produce `0.0` or
`None` for strict parity with post-processing semantics.

### Error messaging

The phase explicitly called for clear user-facing diagnostics, including:

- `ratio_to()` requires a dotted metric key when inferring a parent denominator
- the second argument must be a non-empty string metric key

That guidance mattered because the feature expands the parser surface rather
than living in schema validation alone.

## Tests And Validation

The original test matrix covered:

1. parent inference from a dotted key
2. explicit denominator override
3. presence of `DIVIDE` in compiled DAX
4. parity between mock evaluation and compiled semantics
5. friendly failures for invalid calls

The phase also captured the expected validation slices:

- expression parsing tests
- mock evaluation tests
- Pyright over the touched expression and dataset files

## Recorded Phase Milestones

The original phase changelog recorded three important milestones:

- the initial Phase 1 draft for native `ratio_to()` support
- the explicit decision to drop any follow-on suffix sugar and keep
  `ratio_to()` as the sole planned syntax
- the completion note that tied implementation to both upstream docs and
  downstream developer-facing documentation

## Risks And Open Questions

The original phase record called out:

- denominator dependencies being silently dropped from the plan
- formatting responsibility staying with the caller rather than the function
- parity between expression-level ratios and presentation-time `ratio_to`
- the question of how much nested `ratio_to()` use should be tolerated

## Lasting Design Decisions

These choices survived and still explain the current contract:

- `ratio_to()` stayed Python-compatible instead of introducing a second syntax
- dependency resolution treats ratio denominators as first-class references
- `DIVIDE` is the canonical DAX emission
- the result is numeric ratio output, while formatting remains a caller concern

This epic page preserves that design record. For current behavior, use
[Visuals / Metric Expressions](../visuals/metric_expressions.md).
