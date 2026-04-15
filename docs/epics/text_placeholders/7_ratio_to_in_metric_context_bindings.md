# Epic: `ratio_to` in Metric Context Bindings (Phase 7)

> Status: **Complete** – pack metric bindings support `ratio_to` (inferred or explicit denominator) with deterministic 0–1 results and validated semantics (2025-12-13).

- Implementation landed upstream in `praeparo/models/pack.py` (binding model + validation) and `praeparo/pack/metric_context.py` (denominator inclusion + ratio computation).
- Canonical operator docs live in `docs/projects/pack_runner.md` (“Metric Context Bindings (`context.metrics`)”).

## 1. Context

Packs can declare scalar KPI dependencies under `context.metrics.bindings`, and
Praeparo resolves them via DAX and injects the results as Jinja variables for
text placeholders and YAML-authored shapes.

Praeparo already supports ratio semantics elsewhere:
- Visual metrics can declare `ratio_to` and the dataset builder ensures a
  denominator metric is present, then computes the ratio post-query.
- Expression metrics can compute ratios explicitly (e.g. `a / b`), but this is
  verbose and easy to get wrong when there are additional binding filters.

Authors now need the same ergonomic, validated ratio semantics for pack-level
metric bindings so text placeholders can show rates/attainment consistently
without copy/pasting expressions across packs.

## 2. Problem

Today, pack authors must write explicit expression bindings for ratios:

```yaml
bindings:
  - key: documents_verified.within_1_day
    alias: verified_1d
  - key: documents_verified
    alias: verified_total
  - alias: pct_verified_1d
    expression: verified_1d / verified_total
    format: "percent:0"
```

This has drawbacks:
- **Duplication & inconsistency:** the same ratio is re-authored across packs.
- **Harder validation:** authors can accidentally reference the wrong alias or key.
- **Filter drift:** when bindings apply additional `calculate` predicates (DEFINE/EVALUATE scoped),
  it is unclear whether the denominator should inherit those predicates.

We want (and now have) `ratio_to` as a first-class binding feature so ratios are easy to define,
validate, and compute deterministically.

## 3. Goals

This phase SHOULD:

1. Add optional `ratio_to` to pack metric bindings (`context.metrics.bindings[]`).
2. Ensure `ratio_to` results are computed deterministically (0–1 values) and
   injected as scalar Jinja variables.
3. Validate ratio bindings at pack validate time:
   - Denominator presence/resolution.
   - Unsupported combinations (e.g., ratio over expression-only bindings when not possible).
4. Define clear semantics for how `calculate` scopes interact with denominators.
5. Remain backwards compatible: packs without `ratio_to` behave exactly as today.

Out of scope (future phases):
- Time series ratios (multi-row datasets) for text placeholders.
- Auto-formatting of the injected variables (format remains a hint until formatting is implemented).
- Cross-slide caching beyond existing metric-context reuse rules.

## 4. Proposed UX

### 4.1 Basic ratio against a specific metric key

```yaml
context:
  metrics:
    bindings:
      - key: documents_verified.within_1_day
        alias: pct_verified_1d
        ratio_to: documents_verified
        format: "percent:0"
```

### 4.2 Ratio against inferred base metric

When the binding key is dotted, `ratio_to: true` ratios against the base metric:

```yaml
context:
  metrics:
    bindings:
      - key: documents_verified.within_1_day
        alias: pct_verified_1d
        ratio_to: true
        format: "percent:0"
```

### 4.3 Ratio with scoped calculate predicates

`calculate.<name>.define` applies inside the adhoc measure; `calculate.<name>.evaluate`
wraps the measure reference in `SUMMARIZECOLUMNS`:

```yaml
bindings:
  - key: documents_verified.within_1_day
    alias: pct_verified_1d
    ratio_to: true
    calculate:
      period:
        evaluate: "'Time Intelligence'[Period] = \"Current Month\""
```

## 5. Semantics

### 5.1 Denominator inclusion

`ratio_to` requires both numerator and denominator to be present in the query plan.
Praeparo SHOULD ensure the denominator metric is included automatically when needed.

### 5.2 Filter semantics (critical)

We need a stable rule for what filters apply to denominators.

Proposed rule (explicit, predictable):
- **EVALUATE-scoped filters** (`calculate.*.evaluate`) apply to both numerator and denominator,
  because they wrap the measure reference in `SUMMARIZECOLUMNS` and typically represent
  calculation-group selections / query-time transforms.
- **DEFINE-scoped filters** (`calculate.*.define`) apply only to the binding they are declared on.
  Denominators do **not** inherit them implicitly.

Rationale:
- Prevents silent drift where a numerator-specific slice accidentally changes the denominator.
- Keeps ratios consistent with expression metrics, where `a / b` does not implicitly
  apply `a`'s filters to `b`.

If authors want a denominator-specific slice, they can declare it explicitly via:
- An explicit denominator binding with an alias and its own `calculate`, or
- A ratio binding with an explicit `ratio_to` target that points at that alias/key.

## 6. Design (Praeparo upstream)

### 6.1 Models

File: `praeparo/models/pack.py`

- Add `ratio_to: bool | str | None` to `PackMetricBinding`.
  - `true` means ratio against inferred base metric (requires dotted key).
  - string means ratio against an explicit metric key OR (optionally) an alias.
  - `null` / omitted means no ratio.
- Extend validation:
  - Disallow `ratio_to: true` when `key` is not dotted.
  - Disallow `ratio_to` for expression-only bindings unless a concrete denominator is provided
    and the execution engine can compute it (likely not in this phase).

### 6.2 Planning & execution

Files:
- `praeparo/pack/metric_context.py`
- `praeparo/datasets/builder.py`

Approach:
- Reuse the existing dataset builder ratio machinery:
  - When a binding has `ratio_to`, call `builder.metric(..., ratio_to=...)` so the builder
    ensures a denominator exists and performs post-processing over the single-row dataset.
- Ensure EVALUATE-scoped filters apply consistently to both numerator and denominator:
  - Prefer applying `calculate.*.evaluate` via the builder’s per-series evaluate/group filters,
    or by scoping the whole metric-context query when appropriate.

### 6.3 Validation-first errors

Pack validate should fail early for:
- Unknown denominator keys.
- Missing denominator when `ratio_to: true` cannot infer base.
- Denominator declared but shadowed/overridden incorrectly across root/slide scopes.

## 7. Tests

Add/extend tests to cover:
1. `ratio_to: true` requires dotted keys.
2. `ratio_to: <metric key>` adds denominator automatically and yields 0–1 values.
3. EVALUATE-scoped calculate affects both numerator and denominator.
4. DEFINE-scoped calculate does not implicitly affect denominators.
5. Friendly validation errors for unknown denominators.

## 8. Validation commands

Praeparo:

```bash
poetry run pytest tests/pack -k metric_context
poetry run pyright praeparo/models/pack.py praeparo/pack/metric_context.py
poetry run python -m praeparo.schema --pack schemas/pack.json
```

## 9. Risks / Open Questions

- **Alias vs metric-key denominators:** should `ratio_to` accept aliases, metric keys, or both?
  Accepting both is ergonomic but increases ambiguity; a strict “metric keys only” rule
  is safer for validation.
- **Calc-group semantics:** for Time Intelligence style calculation groups, EVALUATE scoping
  is required; document examples clearly to avoid authors using DEFINE scoping incorrectly.
- **Formatting:** `format` is currently a hint; align with the format standardisation epic before
  promising automatic number formatting for placeholders.

## 10. Next Steps

- Confirm whether `ratio_to` accepts aliases in addition to metric keys.
- Implement in Praeparo upstream; regenerate schema artefacts; add docs examples.
- Add a short note to `6_slide_metric_context.md` pointing to this phase.
