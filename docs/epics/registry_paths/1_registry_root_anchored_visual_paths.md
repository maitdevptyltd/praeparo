# Epic: Registry-Root Anchored Visual Paths (`@/`) (Phase RP-1)

> Status: **Draft** – introduce a registry-root anchor prefix for visual references so packs and YAML visuals can reference `registry/**` assets without deep relative paths.

## 1. Problem

Visual references in Praeparo projects are currently resolved **relative to the file that declares them**:

- Pack slides: `slides[].visual.ref` is relative to the pack YAML file.
- YAML visuals: `type: ./path/to/visual.py` (Python-backed visuals) is relative to the YAML visual file.

This creates two recurring issues:

1. **Deep relative paths are brittle**
   - Example: `registry/customers/<customer>/visuals/dashboard/*.yaml` often needs `type: ./../../../../visuals/dashboard_chart.py`.
   - Moving a file between folders breaks references even when the target remains within `registry/`.

2. **Review and authoring friction**
   - It is hard to visually validate a relative path’s intent when it contains many `../` hops.
   - The same shared visual assets (for example under `registry/visuals/**`) are repeatedly referenced with different relative spellings depending on the caller’s folder depth.

We want a way to reference assets under `registry/**` with an “absolute within registry” anchor.

## 2. Goals

Phase RP-1 introduces a new prefix:

- `@/` means “resolve this path from the **registry root**” (the folder named `registry`).

This phase should:

1. Support `@/` for **pack slide visual refs** (`PackVisualRef.ref`).
2. Support `@/` for **YAML Python visual module paths** declared via `type: "<path>.py"`.
3. Remain fully backwards compatible:
   - Existing `./` and `../` paths keep working unchanged.
   - Only strings starting with `@/` get special handling.

## 3. Non-goals (for RP-1)

- No migration of existing YAML files in downstream projects to use `@/` (that becomes a follow-up phase).
- No new “metrics root” or “project root” semantics; `@/` is purely a file-path alias.
- No changes to other path-bearing fields unless explicitly called out (for example `compose`, frame child sources, or other loaders).

## 4. Proposed Syntax

### 4.1 Anchor prefix

- Any string path beginning with `@/` is interpreted as a registry-root anchored path.
- The portion after `@/` is a **posix-style relative path** inside `registry/`.

Examples:

```yaml
visual:
  ref: "@/visuals/powerbi/matters_on_hold.yaml"
```

```yaml
type: "@/visuals/dashboard_chart.py"
```

### 4.2 YAML note: quoting is optional but recommended

`@/` does not conflict with YAML comment syntax, so quoting is not required.

We still recommend quoting paths for consistency and to avoid accidental parsing surprises when users later add `:` or other punctuation to path-like strings.

## 5. Registry Root Discovery

The runtime needs to map “the current file” -> “the registry root path” deterministically.

### 5.1 Discovery rules (ordered)

Given a `context_path` (the YAML file currently being processed):

1. Walk upwards from `context_path.parent`:
   - If a directory named exactly `registry` is encountered, that directory is the registry root.
2. Otherwise, walk upwards and look for a child folder `registry/`:
   - If `candidate / "registry"` exists and is a directory, use that child as the registry root.
3. If neither rule finds a root, raise a clear `ValueError` explaining:
   - the anchor path supplied
   - the `context_path` used for discovery
   - that no `registry` directory could be found in ancestors

### 5.2 Normalisation and safety

Anchored paths must not escape the registry root:

- Reject `@/../...` and any path that resolves outside the registry root.
- Prefer explicit error messages over silently normalising unsafe paths.

## 6. Resolution semantics by surface

### 6.1 Pack runner: `PackVisualRef.ref`

When resolving `slides[].visual.ref` during pack execution:

- If it starts with `@/`, compute:
  - `registry_root / <anchor_path_without_prefix>`
- Otherwise keep existing behaviour:
  - `(pack_path.parent / ref).resolve()`

### 6.2 YAML visual loader: Python-backed `type: "<path>.py"`

When a YAML visual’s `type` field is a Python module path (ends in `.py` and looks like a path):

- If it starts with `@/`, compute:
  - `registry_root / <anchor_path_without_prefix>`
- Otherwise keep existing behaviour:
  - `(yaml_path.parent / raw_type).resolve()`

## 7. Implementation Plan

### 7.1 Upstream implementation (Praeparo)

Code changes:

1. Add a small reusable helper (proposed location: `praeparo/paths/registry_root.py` or similar):
   - `resolve_registry_root(context_path: Path) -> Path`
   - `resolve_registry_anchored_path(anchor: str, context_path: Path) -> Path`
2. Update pack runner resolution:
   - `praeparo/pack/runner.py` where `visual_ref.ref` becomes a `Path`.
3. Update Python visual loader resolution:
   - `praeparo/pipeline/python_visual_loader.py`

Documentation:

- Add a note to `../projects/pack_runner.md` explaining `@/` and quoting requirements.

### 7.2 Adoption in downstream projects (follow-up phase)

Once RP-1 ships in Praeparo, downstream projects can incrementally migrate YAML to use the anchor:

- Replace deep relative `ref:` and `type:` strings with `@/...` equivalents.
- Prefer migrating high-churn files first (dashboard visuals and pack visual refs).

This should be tracked as a separate phase (RP-2) to keep diffs reviewable and avoid mixing framework and registry content changes.

## 8. Acceptance Criteria

Functional:

1. `ref: "@/visuals/powerbi/matters_on_hold.yaml"` in a pack slide resolves to `<repo_root>/registry/visuals/powerbi/matters_on_hold.yaml`.
2. `type: "@/visuals/dashboard_chart.py"` in a YAML visual resolves to `<repo_root>/registry/visuals/dashboard_chart.py`.
3. Existing relative paths continue to work unchanged.

Safety:

4. Anchored paths cannot escape `registry/` via `..` traversal; such configs fail fast with a clear error.

Docs:

5. The developer documentation explains the `@/` anchor and recommends quoting for consistency.

## 9. Validation & Test Plan

Add tests in Praeparo:

1. Pack runner test:
   - Create a temporary tree containing `tmp/registry/customers/foo/pack.yaml`.
   - Use `PackVisualRef(ref=\"@/visuals/powerbi/pbi.yaml\")`.
   - Assert the loader sees `tmp/registry/visuals/powerbi/pbi.yaml`.

2. YAML Python visual loader test:
   - Create `tmp/registry/visuals/simple_yaml_visual.py` defining a minimal `PythonVisualBase` subclass.
   - Create a YAML visual under `tmp/registry/customers/foo/visuals/dashboard/visual.yaml` with `type: \"@/visuals/simple_yaml_visual.py\"`.
   - Assert `load_visual_config` successfully loads and assigns `type == PYTHON_VISUAL_TYPE`.

## 10. Risks & Mitigations

- **YAML quoting habits:** quoted paths are still recommended for consistency even though `@/` avoids comment pitfalls.
- **Ambiguous “repo root”**: in non-standard layouts, discovery could fail.
  - Mitigation: use explicit discovery rules and fail fast with actionable error messages.
- **Security / traversal**: `@/../` could escape registry.
  - Mitigation: enforce “must resolve within registry root” invariant.

## 11. Rollout / Migration Notes

- Land RP-1 in Praeparo first with tests and docs.
- After release, downstream projects can optionally migrate YAML to reduce deep relative paths (RP-2).
- During migration, keep changes mechanical and reviewable (one customer or domain at a time).
