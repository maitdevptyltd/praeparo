# Epic: Registry Context Layers Expose Template Variables (Phase 3)

> Status: **Implemented** - `registry/context/**` layers now hoist `context:` variables into the merged Jinja payload while preserving the nested `context` mapping for compatibility (2026-04-15).

- Active docs for the surrounding contract already live in `docs/projects/context_layers.md` and `docs/projects/pack_runner.md`.

## Scope

Phase 3 is implemented upstream. This phase record remains useful as the
historical problem statement, intended contract, and acceptance criteria that
drove the final behavior.

The active developer-facing contract now lives in:

- `docs/projects/context_layers.md`
- `docs/projects/pack_runner.md`

## 1. Problem

We wanted to move stable “default” template variables (for example `month` or
`display_date`) out of individual packs and into shared registry context
layers:

- `registry/context/month.yaml`

Before implementation, when a pack stopped defining `month` inline and relied
on the registry layer instead, pack rendering failed because Jinja could not
resolve the variable.

This is typically triggered via pack-level templated helpers like:

- `odata_months_back_range(..., month, ...)`
- `strftime(month, ...)`

because `month` is missing from the Jinja render context.

## 2. Original Repro

1. Define defaults in `registry/context/month.yaml`:

```yaml
context:
  month: "2025-11-01"
  display_date: "November 2025"
```

2. Remove `month` / `display_date` from `registry/packs/example/example_pack.yaml`.

3. Run a pack that uses `month` in templated filters:

```bash
poetry run praeparo pack run ./registry/packs/example/example_pack.yaml ./.tmp/packs/example
```

Expected: the pack resolves `month` and runs with the registry default.

Observed at the time: Jinja saw `month` as undefined, and date helpers failed.

## 3. Root Cause

Praeparo’s registry context layer loader treats non-pack-shaped YAML layers
differently:

- it loads the YAML as-is into the merged payload (including the top-level
  `context:` key);
- it uses `context:` only as the templating source for that layer’s own
  `calculate` / `define` / `filters` blocks;
- it does **not** hoist `context:` variables into the merged payload as
  top-level keys.

So, `registry/context/month.yaml` contributes:

- `payload["context"]["month"]`

but pack templating expects:

- `payload["month"]`

## 4. Goals

1. **Expose registry context variables as top-level Jinja vars**
   - Any `registry/context/**` layer with a `context:` mapping should
     contribute those keys to the merged payload (last-writer-wins).
   - After the change, `resolve_layered_context_payload(...)` includes `month`
     and `display_date` as top-level keys when defined by a layer.

2. **Preserve existing context-layer behavior for DAX fragments**
   - Layer `define` / `calculate` / `filters` blocks still render using that
     layer’s own `context:` mapping.

3. **Remain backwards compatible for existing packs**
   - Packs that define `month` inline continue to override the registry
     default.

## 5. Non-goals

- Do not add cross-layer templating dependencies unless explicitly designed;
  keep the current “layer renders using its own context” rule.
- Do not force packs to reference `context.month` in templates.
- Do not rename common pack variable conventions such as `month` or
  `display_date`.

## 6. Implemented Behavior

Praeparo now makes the non-pack-shaped layer load path behave like the
pack-shaped adapter:

- if a layer has a `context:` mapping, hoist its keys into the layer base
  payload (top-level);
- keep the original `context` mapping in the merged payload for backwards
  compatibility.

Illustrative result for `registry/context/month.yaml`:

```python
{
  "month": "2025-11-01",
  "display_date": "November 2025",
  ...
}
```

This mirrors the existing behavior of the pack-shaped adapter where `context:`
is already hoisted.

## 7. Completion Notes

Implementation evidence lives in:

- `praeparo/visuals/context_layers.py`, where `_load_context_layer(...)`
  hoists `context:` keys for non-pack layers.
- `tests/visuals/test_context_layers.py`, including coverage for hoisted keys
  and templated helpers resolving against registry-provided values.

## 8. Acceptance Criteria

- A pack can omit `context.month` / `context.display_date` and still resolve
  `{{ month }}` / `{{ display_date }}` from `registry/context/month.yaml`.
- Existing packs that still define `month` inline keep working and take
  precedence over registry defaults.
- Unit tests cover:
  - hoisting `context` keys into the merged payload;
  - pack templating successfully rendering a filter that calls
    `odata_months_back_range(..., month, ...)`.

## 9. Risks / Notes

- This change adds new top-level keys (for example `month`) that duplicate
  values already present under `context.*` for non-pack-shaped layers. If any
  downstream code is sensitive to key collisions, ensure pack or CLI overrides
  remain last-writer-wins and document expected precedence.
- There is a latent circular import hazard when importing context-layer code
  directly, because it touches pack-templating helpers. Tests should import via
  stable entry points or the import graph should be simplified as part of
  implementation.
