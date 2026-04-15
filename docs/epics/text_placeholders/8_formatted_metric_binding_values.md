# Epic: Formatted Metric Binding Values for Display Jinja (Phase 8)

> Status: **Complete** – display-only Jinja rendering automatically applies `bindings[].format`, with a `.value` escape hatch for raw numbers (2025-12-13).

- Implementation landed upstream in `praeparo/pack/metric_context.py` (format map + payload shaping) and `praeparo/pack/formatted_values.py` (formatted wrapper).
- Canonical operator docs live in `docs/projects/pack_runner.md` (“Display formatting (`bindings[].format`)”).

## 1. Context

Packs can declare scalar KPI dependencies under `context.metrics.bindings`, and
Praeparo resolves these values via DAX and injects them as Jinja variables.

Bindings already accept:
- `format` tokens (e.g., `number:0`, `percent:0`) as a downstream hint.
- Expressions and scoped calculate predicates (DEFINE/EVALUATE).

However, the current output is a raw numeric value, so authors must either:
- Accept default float stringification (often noisy in PPTX text), or
- Manually format in templates (filter/helper), which is error-prone and inconsistent.

## 2. Problem

Pack authors want simple display ergonomics:

```yaml
bindings:
  - key: instructions_received
    alias: count_instructions
    format: number:0
```

And then in display text:

```jinja2
- We received {{ count_instructions }} instructions this month.
```

Today, `{{ count_instructions }}` renders a raw float (e.g., `54.0`) unless the
author adds explicit formatting logic.

At the same time, the same slide context is used for non-display templating
surfaces (DAX filters/define blocks, visual configuration), where auto-formatting
numbers into strings can cause subtle breakage.

We need a solution that is:
- **Simple** for authors writing display text.
- **Robust** for advanced users and non-display templating.
- **Backwards compatible**.

## 3. Goals

This phase SHOULD:

1. Apply binding `format` automatically when rendering display-only Jinja fields.
2. Preserve raw numeric binding values for execution surfaces (DAX/config templating).
3. Provide a clear escape hatch for advanced users to access raw values in display templates.
4. Remain backwards compatible for packs that omit `format` or do not use display text features.

Out of scope (future phases):
- Global locale configuration (thousand separators, currency symbols, etc.).
- Automatic formatting for non-binding values in the slide context.
- UI format rendering (separate epic family).

## 4. Proposed UX

Given a binding with a format token:

```yaml
context:
  metrics:
    bindings:
      - key: instructions_received
        alias: count_instructions
        format: number:0
```

Display templates should render formatted output automatically:

```jinja2
{{ count_instructions }}
```

Advanced users can access raw values explicitly:

```jinja2
{{ count_instructions.value }}
```

## 5. Design

### 5.1 Two-context rendering (raw vs display)

Praeparo SHOULD maintain two parallel contexts during pack execution:

- **Raw context**
  - Used for DAX/config templating and execution.
  - Binding aliases are stored as raw numeric values (`float | None`).

- **Display context**
  - Used only for display-oriented Jinja rendering:
    - PPTX text placeholders (`{{ ... }}` in text runs).
    - YAML-authored text blocks (e.g., `governance_highlights`).
    - Any template fields explicitly documented as “display-only”.
  - Binding aliases are replaced with a wrapper that stringifies according to `format`.

This prevents formatted strings from leaking into DAX predicates or visual config
fields where numeric values may be required.

### 5.2 Metric binding wrapper

Introduce a lightweight wrapper (conceptual `FormattedMetricValue`) that:
- Holds the raw numeric value and the format token.
- Implements `__str__` / formatting hooks so Jinja renders it as formatted text.
- Exposes `.value` to retrieve the raw number.

Examples:
- `number:0` → integer-like formatting with 0 decimals.
- `percent:0` → 0–1 values shown as percent with 0 decimals.

Notes:
- For `None` values, the wrapper should render as an empty string by default
  (or a sentinel like `—` if we introduce a global setting later).

### 5.3 Format directive grammar

This phase SHOULD reuse Praeparo’s existing format directive grammar used in
visuals, keeping the same prefix + precision rules:
- `number[:N]`
- `percent[:N]`
- `currency[:N]` (symbol handling may be deferred; still format decimals consistently)

Unsupported tokens should raise a friendly validation error when used in
bindings (validation-first).

## 6. Implementation notes (Praeparo upstream)

Files (indicative):
- `praeparo/pack/runner.py` (or pack assembly): build both raw and display contexts.
- `praeparo/pack/pptx.py` / templating: use display context when rendering text.
- `praeparo/pack/metric_context.py`: return both raw values and per-alias format tokens.
- A shared formatting helper module (avoid duplicating logic).

Key invariant:
- DAX templating and visual execution must use raw values, not formatted strings.

## 7. Tests

Add tests that:
1. Binding with `format: number:0` renders without decimals in display text.
2. `.value` returns the raw float in display templates.
3. Raw context remains numeric when used for DAX/config templating.
4. Unknown format tokens fail validation with a clear message.

## 8. Validation commands

Praeparo:

```bash
poetry run pytest tests/pack -k metric_context
poetry run pyright praeparo/pack praeparo/models
poetry run python -m praeparo.schema --pack schemas/pack.json
```

## 9. Risks / Open Questions

- **Where is “display-only”?** We need an explicit list of pack fields that use
  display context (e.g., `slide.title`, PPTX placeholders, specific YAML shape fields),
  and keep DAX/config fields on raw context.
- **Currency semantics:** if `currency:0` is used, decide whether to include symbols
  or leave that to downstream templates.
- **None handling:** default to empty string vs `—` and whether that should be configurable.

## 10. Next steps

- Confirm the list of “display-only” pack fields that should render with display context.
- Implement wrapper + dual context plumbing in Praeparo.
- Add a short note to Phase 6 metric context epic linking to this phase.
