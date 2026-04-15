# Epic: Pack Inheritance + Slide Operations for Standard Pack Reuse (Phase 2)

> Status: **Implemented** - pack `extends` with declarative slide operations is implemented upstream in Praeparo; broader rollout hardening remains follow-up work (2026-02-18).

- Canonical developer docs live in `docs/projects/pack_runner.md`.

## 1. Problem

We now have canonical base packs plus customer- or project-specific variants.

Today those variants can duplicate most of the same pack structure and slide
definitions, which creates avoidable maintenance and review overhead:

- changes to baseline slide ordering or shared filters must be re-applied
  manually in each variant file;
- PR review diffs are noisy because full copied slide lists obscure the true
  customer-specific deltas;
- drift risk increases over time as baseline and variant files evolve
  independently.

The pack loader (`praeparo/pack/loader.py`) originally loaded one YAML payload
only and had no inheritance semantics comparable to metric `extends`.

## 2. Goals

Phase 2 introduces a reusable pack inheritance model designed for
analyst-friendly YAML authoring:

1. Add pack-level `extends` support.
2. Preserve existing `slides` behavior for non-inherited/base packs.
3. Support declarative slide CRUD-style edits in inherited packs via dedicated
   operation blocks.
4. Keep merge semantics deterministic and strongly validated.
5. Keep migration from copied variant packs small and reviewable.

## 3. Non-goals

- No runtime behavior changes to visual execution, datasource execution, or
  PPTX assembly.
- No new "move" operation in this phase.
- No parameterized slide templating API in this phase (for example
  `slide_params`), which is a future phase.
- No change to downstream customer registry schemas.

## 4. Proposed YAML Contract

### 4.1 New root fields

- `extends: <path>` (optional) - parent pack path resolved relative to current
  pack file.
- `slides_remove: [<slide_id>, ...]` (optional)
- `slides_replace:` (optional list of replacement operations)
- `slides_update:` (optional list of patch operations)
- `slides_insert:` (optional list of insert operations)

### 4.2 Authoring modes (mutually exclusive when `extends` is present)

When `extends` is absent:

- `slides` is required.
- `slides_*` operations are forbidden.

When `extends` is present:

- **Patch mode**: use `slides_*` operations and omit `slides`.
- **Full override mode**: define `slides` and omit all `slides_*` operations.

Validation rule:

- If `slides` and any `slides_*` field are supplied together, fail fast.

### 4.3 Operation shapes

```yaml
extends: ../standard_pack.yaml

slides_remove:
  - matters_on_hold
  - reworks

slides_replace:
  - id: dashboard_charts
    slide:
      id: dashboard_charts
      title: "{{ customer }} Dashboard (cont.)"
      template: "2_by_2_images"
      placeholders: ...

slides_update:
  - id: dashboard
    patch:
      visual:
        ref: "@/visuals/example_dashboard.yaml"

slides_insert:
  - after: dashboard
    slide:
      id: dashboard_charts_follow_up
      title: "{{ customer }} Dashboard (cont.)"
      template: "1_by_2_images"
      placeholders: ...
```

## 5. Merge Semantics

### 5.1 Inheritance resolution

1. Resolve `extends` chain from root parent to leaf.
2. Detect cycles and missing parents before composition.
3. Compose root-level mappings (`context`, `calculate`, `filters`,
   `evidence`) with child override precedence.

### 5.2 Slide list resolution

For `extends` + patch mode, start with inherited effective slides and apply
operations in fixed order:

1. `slides_remove`
2. `slides_replace`
3. `slides_update`
4. `slides_insert`

This deterministic ordering prevents ambiguous output when multiple operations
target the same area.

### 5.3 Update and replace behavior

- `slides_update`: deep-merge mapping fields into existing slide identified by
  `id`.
  - mapping values merge recursively.
  - list/scalar values replace by default.
- `slides_replace`: replace the full slide object for matching `id`.

### 5.4 Insert behavior

- Insert operation must declare exactly one anchor: `before` or `after`.
- `slide.id` for inserted slides must be unique in final effective output.

## 6. Validation Contract

The phase should fail early with clear errors for:

1. `extends` path missing or unreadable.
2. Circular extends graph.
3. Mixed authoring mode (`slides` + `slides_*`).
4. Unknown slide id target in remove/replace/update.
5. `slides_replace.id` mismatch with `slide.id`.
6. Insert with missing/ambiguous anchor (`before` + `after`, or neither).
7. Final effective slide ids not unique.
8. Patch mode on inherited packs where effective slides cannot be safely
   identified by `id`.

## 7. Historical Rollout Plan

### Phase 1 - Specification and Schema Design

Scope:

- Finalize the public YAML contract and operation precedence.
- Define strict validation expectations and error messages.
- Update upstream docs before implementation.

Deliverables:

- `docs/projects/pack_runner.md` updated with `extends` + slide ops contract.
- this phase doc kept current.

Exit criteria:

- API contract and merge order signed off for implementation.

### Phase 2 - Praeparo Models and JSON Schema

Scope:

- Extend pack Pydantic models with typed operation blocks.
- Add mode validation (`slides` vs `slides_*`) and operation payload
  validation.

Deliverables:

- `praeparo/models/pack.py`
- regenerated pack schema

Exit criteria:

- Model validation passes for valid fixtures and rejects invalid modes.

### Phase 3 - Loader Composition Engine

Scope:

- Implement pack `extends` loader composition in `praeparo/pack/loader.py`.
- Apply slide operations with deterministic ordering.
- Keep loader output as one effective `PackConfig` for downstream runners.

Deliverables:

- Loader support for `extends`
- Slide operation merge engine with path-aware error messages

Exit criteria:

- Effective pack composition is deterministic and stable across repeated loads.

### Phase 4 - Upstream Test Coverage

Scope:

- Add focused unit tests for inheritance + operations.

Test cases:

1. Missing parent path error.
2. Circular inheritance error.
3. Patch mode happy path (remove/replace/update/insert).
4. Full override mode happy path.
5. Mixed mode invalid.
6. Duplicate final slide ids invalid.
7. Anchor not found on insert invalid.

Deliverables:

- targeted pack inheritance tests
- any touched runner or CLI regression tests updated as needed

Exit criteria:

- Targeted test suite passes and pack runner regressions remain green.

### Phase 5 - Downstream Adoption

Scope:

- Refactor copied variant packs into thin inherited overlays.
- Replace copied shared sections with operations-only deltas.

Deliverables:

- at least one downstream standard overlay migrated to inherited overlay mode

Exit criteria:

- overlay diff is materially smaller than the previous copied pack and the
  resulting effective pack remains functionally equivalent.

### Phase 6 - Rollout Hardening (Follow-up)

Scope:

- document migration guidance for additional overlays;
- gather any follow-up ergonomics discovered during broader rollout.

## 8. Validation

Run:

- pack schema regeneration and validation in Praeparo;
- targeted pack inheritance tests;
- pack-runner regression checks for inherited packs.

For downstream adoption, compare the effective pack output before and after
migration to confirm slide ordering, overrides, and rendered outputs remain
equivalent.

## 9. Completion Notes

The core contract is implemented upstream in Praeparo:

- pack `extends` is supported;
- slide operation blocks (`slides_remove`, `slides_replace`, `slides_update`,
  `slides_insert`) are validated and applied deterministically;
- active documentation for the feature lives in `docs/projects/pack_runner.md`;
- downstream overlays can now stay thin and reviewable instead of copying full
  pack definitions.
- additional rollout hardening remains separate follow-up work rather than part
  of the implemented core contract.
