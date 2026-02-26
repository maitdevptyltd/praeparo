# Metric Expressions (Arithmetic + `ratio_to()` + `min/max`)

Praeparo supports lightweight **metric expressions** anywhere a config accepts an `expression:` field (for example inline visual series, registry expression metrics, and pack metric bindings).

Expressions are parsed using Python's `ast` module and compiled into DAX by substituting referenced metric identifiers with their compiled measure expressions.

## Syntax

- Allowed operators: `+`, `-`, `*`, `/`, parentheses.
- Identifiers refer to **metric keys** and **variant keys** using dotted notation.

Because expressions are parsed as Python, dotted identifiers must be written as attribute chains (which mirrors YAML dotted keys):

```text
documents_sent.within_1_business_day_from_file_ready
```

## `ratio_to()` in expressions

Use `ratio_to()` when you want a ratioed value inside an expression without defining an extra percent variant.

Supported forms:

- `ratio_to(numerator)` – infer the denominator as the immediate parent of the dotted numerator key.
- `ratio_to(numerator, "denominator.key")` – use an explicit denominator metric key.
- `ratio_to(numerator, fallback)` – infer the denominator and use `fallback` when the denominator is blank/zero.
- `ratio_to(numerator, "denominator.key", fallback)` – explicit denominator with fallback.

Examples:

```yaml
expression: |
  ratio_to(documents_sent.within_1_business_day_from_file_ready) * 0.85 +
  ratio_to(documents_sent.within_2_business_days_from_file_ready) * 1.0
```

```yaml
expression: |
  1 - ratio_to(missed_settlements_by_msa, "matters_settled")
```

```yaml
expression: |
  min(ratio_to(documents_sent.within_5_minutes_automated, "documents_sent.automated", 1) / 1.0, 1)
```

Semantics:

- `ratio_to()` compiles to a DAX `DIVIDE` call:
  - without fallback: `DIVIDE(numerator, denominator)`
  - with fallback: denominator-guarded `IF` + `DIVIDE` so fallback is returned whenever denominator is blank/zero.
- The inferred denominator is the **immediate parent** (`a.b.c → a.b`).
- `ratio_to()` produces a numeric ratio (typically `0–1`), so format as percent where appropriate.
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

## Notes and related features

- Series-level `ratio_to` (a separate feature) computes ratios post-query for simple numerator/denominator pairs without embedding the ratio in DAX. Use expression `ratio_to()` when you need ratioed values inside a larger arithmetic expression.
- `min()/max()` compilation uses a blank-safe pattern: if any argument evaluates to `BLANK()` (for example a missing `ratio_to()` denominator), the `min/max` result is `BLANK()` rather than silently falling back to the non-blank argument.
