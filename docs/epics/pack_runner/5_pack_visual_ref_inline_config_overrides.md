# Epic: Pack `visual.ref` Inline Config Overrides (Phase 5)

> Status: **Implemented** - pack-authored inline config fields override the referenced visual YAML config when using `visual.ref`, without requiring per-visual adoption (2025-12-14).

- Canonical developer docs live in `docs/projects/pack_runner.md`.

## Scope

Phase 5 is implemented upstream. This phase record remains as implementation
history for the override contract, validation expectations, and adoption
constraints behind file-backed pack visuals.

## 1. Problem

In packs, `slides[].visual.ref` (and placeholder visuals) reference a visual
YAML file on disk:

```yaml
visual:
  ref: "@/visuals/example_dashboard.yaml"
```

Pack authors can already supply execution-scoped overrides:

- `visual.calculate` (DAX filters)
- `visual.filters` (Power BI OData filters)

But other inline fields are ignored when `ref` is used, even though the pack
model permits them (`PackVisualRef` uses `extra="allow"` in Praeparo).

This becomes a problem when a pack needs to reuse a shared visual definition
but adjust presentation for the specific slide context, for example:

- a dashboard chart visual whose `title` should reflect the segment being shown
- a reused visual where the slide title should be different from the base
  visual’s authored `title`

Without this feature, pack authors must either:

- duplicate the visual YAML to change `title`, or
- accept misleading or less-specific titles in rendered outputs

## 2. Goals

Phase 5 introduced a minimal, predictable override mechanism for file-backed
visuals:

1. **Inline overrides for `visual.ref`**
   - When a pack slide uses `visual.ref`, any additional keys in the `visual:`
     block other than the reserved pack keys are treated as config overrides
     and applied on top of the loaded visual config.

2. **Precedence**
   - Pack inline config overrides win over the referenced visual YAML’s fields.

3. **No forced adoption**
   - The feature does not require every visual type to implement special logic.
   - The override only affects fields that already exist on the target visual’s
     Pydantic model.

4. **Typed validation**
   - Overrides are validated by the target visual config model.
   - Unknown keys fail fast with a clear error pointing to the pack + slide +
     visual ref.

5. **Applies equally to slide visuals and placeholder visuals**
   - Works for `slide.visual` and `slide.placeholders.<id>.visual`.

## 3. Non-goals

- Changing any rendering behavior beyond normal config precedence.
- Creating a new override schema per visual type.
- Deep-merging nested structures beyond Pydantic’s normal model validation
  semantics.

## 4. Authoring UX

Pack authors can override presentation fields inline next to `ref`:

```yaml
placeholders:
  top:
    visual:
      ref: "@/visuals/example_dashboard.yaml"
      title: "Dashboard - Complex Segment"
      calculate: |
        'dim_segment'[SegmentName] IN {"Complex"}
```

Expected outcome:

- `title` in the runtime visual config becomes `Dashboard - Complex Segment`,
  even if the referenced YAML visual has a different `title`.
- `calculate` continues to behave as an execution-scoped DAX filter, not a
  config override.

## 5. Implementation Sketch

### 5.1 Reserved keys vs override keys

When interpreting a `PackVisualRef`, these are reserved pack keys and are not
forwarded into the loaded config:

- `ref`
- `type`
- `filters`
- `calculate`
- `series_add`
- `series_update`
- `series_remove`

All other keys present on the `PackVisualRef` instance are treated as config
overrides.

### 5.2 Applying overrides

In `praeparo.pack.runner`:

1. Load the base visual config from `ref`.
2. Build an override payload from the inline `visual:` block excluding reserved
   keys.
3. Merge and re-validate using the base config’s model class so:
   - model-level validation occurs,
   - unknown keys are rejected,
   - and the precedence is `pack > referenced YAML`.

## 6. Edge Cases & Semantics

### 6.1 Unknown override keys

If a pack supplies a key that does not exist on the target visual model:

- fail with a validation error
- include pack path + slide id/title/slug + visual ref in the message

### 6.2 Nested objects

Overrides are a shallow replace at the top-level key:

- overriding a nested object replaces that field according to Pydantic
  validation rules
- Praeparo does not perform deep merges for nested mappings in this phase

### 6.3 Interaction with artifact naming

Some pipelines use `config.title` for slugging and filenames.

Overriding `title` may therefore:

- change export filenames for that slide
- which is generally desirable for distinguishing slide variants

## 7. Completion Notes

Implementation evidence lives in:

- `praeparo/pack/runner.py`, which applies inline override payloads to
  referenced visuals and validates the merged result
- `tests/pack/test_pack_runner.py`, which covers slide overrides, placeholder
  overrides, and failure modes for unknown keys
- `docs/projects/pack_runner.md`, which documents the supported authoring
  contract

## 8. Acceptance Criteria

1. For a file-backed visual referenced via `visual.ref`, an inline `title` in
   the pack overrides the referenced YAML visual’s `title` in the executed
   config.
2. The override mechanism does not require changes in individual visual types.
3. Unknown override fields fail fast with a clear error that identifies the
   pack and slide.
4. Behavior is consistent for both `slide.visual` and
   `slide.placeholders.<id>.visual`.

## 9. Historical Coverage

Focused upstream tests cover:

1. slide visual override
2. placeholder visual override
3. unknown override key failure
