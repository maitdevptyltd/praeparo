# Metric Expressions (Arithmetic + `ratio_to()` + `min/max`)

Praeparo supports lightweight **metric expressions** anywhere a config accepts
an `expression:` field, such as inline visual series, registry expression
metrics, and pack metric bindings.

Expressions are parsed with Python's `ast` module and compiled into DAX by
swapping metric references for their compiled measure expressions.

This is the compile-time step in the flow: `MetricDaxBuilder` resolves the
referenced metrics first, then the visual pipeline renders the resulting DAX
through shared helpers such as `render_visual_plan`. Visual-specific naming,
ratio-to-parent presentation, and SLA decoration happen after compilation in
the visual layer.

## Syntax

- Allowed operators: `+`, `-`, `*`, `/`, parentheses.
- Identifiers refer to **metric keys** and **variant keys** using dotted notation.

Because expressions are parsed as Python, dotted identifiers must be written as
attribute chains, which mirrors dotted YAML keys:

```text
response_time.within_target
```

## `ratio_to()` in expressions

Use `ratio_to()` when you want a ratio inside an expression without creating a
separate percent metric.

Supported forms:

- `ratio_to(numerator)` – infer the denominator as the immediate parent of the dotted numerator key.
- `ratio_to(numerator, "denominator.key")` – use an explicit denominator metric key.
- `ratio_to(numerator, fallback)` – infer the denominator and use `fallback` when the denominator is blank/zero.
- `ratio_to(numerator, "denominator.key", fallback)` – explicit denominator with fallback.

Examples:

```yaml
expression: |
  ratio_to(response_time.within_target) * 0.85 +
  ratio_to(response_time.within_slightly_late) * 1.0
```

```yaml
expression: |
  1 - ratio_to(completion_rate, "total_completions")
```

```yaml
expression: |
  min(ratio_to(throughput.within_threshold, "throughput.total", 1) / 1.0, 1)
```

Semantics:

- `ratio_to()` compiles to a DAX `DIVIDE` call:
  - without fallback: `DIVIDE(numerator, denominator)`
  - with fallback: denominator-guarded `IF` + `DIVIDE` so fallback is returned whenever denominator is blank/zero.
- The inferred denominator is the **immediate parent** (`a.b.c → a.b`).
- `ratio_to()` produces a numeric ratio (usually `0–1`), so format it as a
  percent where that reads better.
- Fallback applies when the denominator is blank or zero (including zero-volume cases where both numerator and
  denominator are blank). If denominator is present and numerator is blank, the ratio remains blank.

Validation rules:

- Supported function calls: `ratio_to()`, `min()`, `max()` (plus aliases `MIN()` and `MAX()`).
- No keyword arguments.
- `ratio_to()` expects 1 to 3 positional args:
  - First argument must be a metric reference (a bare identifier or dotted attribute chain).
  - If using the 1-arg form, the numerator must be dotted so the denominator can be inferred.
  - 2-arg form:
    - string second arg => explicit denominator metric key.
    - numeric second arg => fallback value with inferred denominator.
  - 3-arg form:
    - second argument must be a non-empty string metric key.
    - third argument must be a numeric literal fallback value.
- `min()` / `max()` expect 2+ positional arguments.

## Pipeline Fit

- Compile expression metrics once from the shared metric catalog, then reuse
  them in the visual pipeline.
- DAX-backed visuals should consume the prepared
  `ExecutionContext.dataset_context` instead of finding the same roots again for
  each visual.
- Use expression `ratio_to()` when the ratio sits inside a larger arithmetic
  expression; use the series-level `ratio_to` feature when the ratio is only
  needed after query execution.

## Notes and related features

- Series-level `ratio_to` is a separate feature that computes ratios after the
  query for simple numerator/denominator pairs. Use expression `ratio_to()`
  when you need the ratio inside a larger arithmetic expression.
- `min()/max()` compilation uses a blank-safe pattern: if any argument
  evaluates to `BLANK()` (for example a missing `ratio_to()` denominator), the
  result is `BLANK()` rather than silently falling back to the non-blank
  argument.
