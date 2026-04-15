# Epic: Metric Expressions `min()` / `max()`

> Status: **Complete**

This page preserves the detailed phase record for adding `min()` and `max()`
helpers to Praeparo's metric expression language.

Current developer guidance lives in:

- [Visuals / Metric Expressions](../visuals/metric_expressions.md)
- [Metrics / Metric -> DAX Builder](../metrics/metric_dax_builder.md)

## Scope

Phase 1 added scalar `min()` / `max()` helpers, plus optional uppercase aliases
for portability when porting workbook formulas.

The core helpers landed upstream, but the phase record remains useful because
it captures the clamp-driven use cases, N-ary DAX strategy, blank-handling
concerns, and rollout expectations that motivated the design.

## Context And Problem

Praeparo already supported arithmetic expressions and `ratio_to(...)`, but it
did not provide a safe way to clamp or bound terms inside those expressions.

The motivating downstream use case was a weighted-attainment formula where each
component should be capped at `1.0` before averaging. Without `min()` / `max()`
support, authors had to drop into raw DAX `define:` blocks or accept formulas
that could exceed 100%.

## Goals

The original phase aimed to:

1. support `min(...)` and `max(...)` as first-class expression calls
2. optionally accept `MIN(...)` / `MAX(...)` for workbook portability
3. require two or more positional arguments
4. preserve dependency discovery for nested metric references
5. keep DAX compilation and mock evaluation in parity
6. avoid behavioral changes for existing valid expressions

Explicitly out of scope:

- a dedicated `clamp(value, lower, upper)` helper
- a non-Python DSL
- table or column semantics beyond scalar measure expressions

## Proposed UX

The original epic used clamp-style expressions such as:

```yaml
expression: |
  (
      min(ratio_to(requests_processed.within_1_day) / 0.85, 1) +
      min(ratio_to(requests_processed.within_2_days) / 1.0, 1)
  ) / 2
```

Rules:

- supported functions in the phase were `ratio_to`, `min`, and `max`
- `MIN` / `MAX` were optional aliases
- keyword arguments were rejected
- `min/max` required at least two arguments
- arguments could be nested expressions, including arithmetic and `ratio_to()`

## Design Record

### Parser changes

The phase extended the expression visitor so `visit_Call` could recognise:

- `ratio_to(...)`
- `min(...)`
- `max(...)`
- optional uppercase aliases

The validation requirements were explicit:

- reject keyword arguments
- reject one-argument calls
- keep error messages user-facing and list the supported functions

### DAX compilation

The original design chose an N-ary DAX strategy instead of trying to chain
binary `MIN`/`MAX` calls ambiguously.

Recommended emission:

- `min(a, b, c)` -> `MINX({a, b, c}, [Value])`
- `max(a, b, c)` -> `MAXX({a, b, c}, [Value])`

That decision made the implementation symmetric for arbitrary arity and kept
the compiler logic consistent across both helpers.

### Mock-evaluation parity

The mock evaluator needed the same function surface:

- recursively evaluate every argument
- return `min(values)` or `max(values)` when values are present
- decide explicitly how blanks or missing identifiers should behave

One important open question recorded by the phase was whether missing inputs
should propagate as `None` or fall back to `0.0`, because that decision can
change clamp semantics substantially.

### Docs and schemas

The phase deliberately kept the schema impact small:

- no schema changes were required when expressions were already strings
- the active documentation needed to list `min/max` as supported calls
- validation messaging needed to stay aligned with the expanded parser surface

## Tests And Rollout

The original test plan covered:

- successful parsing of `min(a, b)` and `max(a, b)`
- N-ary DAX emission
- rejection of invalid arity or keyword arguments
- mock evaluation for numeric substitutions
- nested usage such as `min(ratio_to(a.b) / 0.85, 1)`

The rollout plan also captured a downstream follow-up:

- once the helper shipped upstream, the affected weighted-attainment metric
  should be updated to clamp each term with `min(..., 1)`
- downstream validations and regenerated documentation would then confirm the
  new formula no longer exceeded 100% in outperforming periods

## Recorded Phase Milestones

The original phase changelog captured the main shape of the rollout:

- the initial Phase 1 draft for `min()` / `max()`
- the addition of an explicit handoff checklist and validation commands
- the implementation milestone, including blank-safe DAX emission and
  downstream clamp adoption
- later cleanup notes that adjusted renamed example metric keys and retired
  outdated validation commands

## Risks And Open Questions

The phase record explicitly called out:

- DAX blank semantics versus workbook blank semantics
- the trade-off of supporting both lowercase and uppercase aliases
- the need for the Python evaluator to stay close to DAX behavior for blanks
  and missing values

## Lasting Design Decisions

These choices survived and explain the current contract:

- the helpers extend the existing Python-compatible grammar instead of adding a
  special clamp syntax
- the implementation remained scalar-only and measure-oriented
- N-ary helper calls are part of the expression compiler, not an external macro
- the active docs stayed on the expression page rather than splitting off a
  second "advanced formulas" surface

This epic page preserves that design record. For current behavior, use
[Visuals / Metric Expressions](../visuals/metric_expressions.md).
