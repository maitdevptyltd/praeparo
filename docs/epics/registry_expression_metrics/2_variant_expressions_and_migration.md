# Epic: First-Class Expression Metrics in Registry (Phase 2)

> Status: **Draft** – extend expression support to variants and provide migration helpers for existing inline expressions.

## 1. Context

Phase 1 introduces base-metric `expression` in the registry and compilation in
Praeparo.

Some projects and dashboards may require:
- Variant-specific arithmetic (e.g., “automated weighted score”).
- Smooth migration from inline visual expressions to registry keys without
  breaking existing packs.

## 2. Goals

Phase 2 SHOULD:

1. Allow `expression` on `MetricVariant`.
2. Support variant-level inheritance (nested variants) for expressions.
3. Provide a migration path for inline expressions:
   - author in registry,
   - reference by key in visuals/packs,
   - delete inline expression once parity is proven.
4. Add validation to prevent ambiguous mixes of `define`/`expression` across
   variants.

Out of scope:
- A bespoke DSL or non-Python grammar.

## 3. Design

### 3.1 MetricVariant expressions

File: `praeparo/metrics/models.py`

- Add `expression: str | None` to `MetricVariant`.
- Mutually exclusive with `define` overrides on that variant (if supported).

### 3.2 Builder behaviour

File: `praeparo/metrics/dax.py`

- When compiling a variant:
  - If variant (or an ancestor variant) defines `expression`, compile that as
    the variant’s base, then apply combined filters.
  - Else fall back to base metric’s compiled expression/define as Phase 1.

### 3.3 Migration helpers

Docs + lightweight tooling:
- Add a doc section showing:
  - how to lift an inline visual expression into a registry metric.
  - how to swap visuals to reference the new key.
  - how to validate parity (mock/live artefacts).
- Optional: a CLI warning when a visual defines an inline expression whose key
  matches a registry metric, nudging authors to consolidate.

## 4. Tests

- Variant expression compilation.
- Inheritance precedence with nested variants.
- Backwards compatibility for variants without expressions.

## 5. Validation

Same as Phase 1 plus any new fixtures for variant expressions.

## 6. Risks / Open Questions

- **Complexity creep:** keep rules explicit to avoid surprising inheritance.
- **Author ergonomics:** ensure errors clearly point to variant paths.
