# Epic: Pack Live Data Mode Default for DAX-Backed Visuals (Phase GM‑2)

> Status: **Implemented** – pack runs default DAX-backed visuals to live data mode (while standalone `praeparo visual` remains mock-first), using Praeparo’s typed pipeline options (2025-12-13).

- Canonical developer docs live in `docs/projects/pack_runner.md`.

## 1. Problem

After visual-driven DAX-backed pack flows landed, custom visuals can run
directly from their own YAML and the Praeparo metric catalogue, and packs can
include them alongside Power BI visuals.

However, the **data mode defaults** differ by design:

- Power BI visuals in packs are inherently **live** (they call the Power BI
  ExportTo APIs).
- DAX-backed/custom visuals default to **mock** for
  standalone `praeparo visual ...` commands, but packs default to **live** when
  `--data-mode` is omitted.

Without a pack-specific default, this leads to inconsistent packs:

- Power BI slides show live production data.
- DAX-backed visuals show seeded mock values unless
  the pack runner is explicitly told to use live mode.

For pack consumers, the expectation is that a pack represents a **single,
coherent view** of a period (e.g. month) using consistent data sources.

## 2. Goal

Phase GM‑2 delivers:

- Default **pack-driven** executions (via `praeparo pack run`) to **live data
  mode** for all DAX-backed/custom visuals, including:
  - Any DAX-based visual types that honour `data_mode` / `PipelineDataOptions`.
- Avoid changing the default for standalone `visual` commands
  (`praeparo visual ...`), which can remain `mock`-first for local iteration.
- Keep `--data-mode` explicit overrides working:
  - `--data-mode mock` should still force mock mode even for packs.
- Make this behaviour flow through **typed framework plumbing** only:
  - `PipelineOptions.data` / `PipelineDataOptions` determine datasource vs mock.
  - Visuals treat `use_mock` and datasource as
    inputs from the framework, not bespoke flags.

In short: **packs default to live** for DAX-backed visuals, individual visuals
default to mock, and visual-specific code does not re-implement data-mode
plumbing the framework already provides.

## 3. Behaviour – `praeparo pack run`

### 3.1 Defaults

When a caller runs:

```bash
poetry run praeparo pack run \
  registry/packs/example.yaml \
  --artefact-dir .tmp/example/pack_png
```

without an explicit `--data-mode`:

- The pack runner should:
  - Use `data_mode="live"` for DAX-backed/custom visuals (e.g. cartesian
    charts and plugin-defined DAX visuals).
  - Continue to treat Power BI exports as live (unchanged).
- Internally, this means:
  - `PipelineOptions.data.provider_key` should be `None` (live).
  - `PipelineOptions.data.datasource_override` should be set according to
    Praeparo’s existing rules for live mode (e.g. default datasource).

### 3.2 Overrides

- When the user supplies `--data-mode` explicitly, that value must win:

  ```bash
  # Force mock mode for all visuals in the pack (useful for local debugging).
  poetry run praeparo pack run \
    registry/packs/example.yaml \
    --artefact-dir .tmp/example/pack_png \
    --data-mode mock
  ```

  - In this case, DAX-backed visuals should use mock data providers, and Power
    BI behaviour remains controlled by its own config.

- If Praeparo also supports a `PRAEPARO_DATA_MODE` env var, the resolution
  order should be documented and respected:
  - `--data-mode` > env var > pack default (`live`).

## 4. Implementation Sketch (Praeparo)

> The code changes for GM‑2 landed in Praeparo. This epic records the
> implementation history and the behavioural contract.

### 4.1 CLI defaults for packs

In `praeparo/cli/__init__.py`:

- `_prepare_pack_metadata` currently normalises `data_mode` similarly to
  visual commands (defaulting to "mock").
- `_build_pipeline_options` calls `_normalise_data_mode` which returns `"mock"`
  when no explicit value is provided.

Phase GM‑2 expects:

- For the **pack** command (only):
  - If `args.data_mode` is `None` and no env override is present:
    - Treat `data_mode` as `"live"` instead of `"mock"`.
  - If `args.data_mode` is set, continue to honour it exactly.

Implementation options (in Praeparo):

- Introduce a pack-specific normalisation helper, e.g.
  `_normalise_pack_data_mode`, that defaults to `"live"` when unset.
- Or, adjust `_prepare_pack_metadata` to inject `"live"` into `metadata["data_mode"]` when
  no explicit mode is given, while leaving `_normalise_data_mode` (used by `visual` and
  `python-visual` commands) unchanged.
- In either case, keep **all** data-mode resolution inside Praeparo’s CLI +
  `PipelineOptions.data`:
  - DAX-backed visuals should not parse `data_mode`
    strings themselves; they should read:
    - `ExecutionContext.options.data.provider_key`
    - `ExecutionContext.options.data.datasource_override`
    - `ExecutionContext.options.metadata["ignore_placeholders"]`
      when they need those specifics.

### 4.2 Downstream usage

The change should be **plumbed through**, not duplicated:

- `PipelineOptions.data` is already constructed based on normalised
  `data_mode` via `_build_pipeline_options`.
- DAX-backed pipelines should derive their
  behaviour from `ExecutionContext`:
  - `context.options.data` for data mode and datasource overrides.
  - `context.options.metadata` only for genuinely visual-specific knobs.
- No custom-visual-specific `data_mode` / datasource plumbing should exist;
  the framework surfaces are the single source of truth.

## 5. Downstream impact

Downstream project docs should note that:

- packs default to live mode for DAX-backed visuals;
- developers can force mock mode for local runs via `--data-mode mock`.

## 6. Validation Expectations

With the feature implemented:

- From a downstream project root, the following should behave as described:

  ```bash
  # Live mode by default for packs
  poetry run praeparo pack run \
    ./registry/packs/example.yaml \
    --plugin your_project \
    ./.tmp/example/pack_png

  # Forced mock mode for packs
  poetry run praeparo pack run \
    ./registry/packs/example.yaml \
    --plugin your_project \
    ./.tmp/example/pack_png_mock \
    --data-mode mock
  ```

  The top-level form (`poetry run praeparo --plugin your_project pack run ...`)
  remains valid; prefer the inline `pack run ... --plugin ...` form when invoking
  packs so the command aligns with other pack flags.

- We should see:
  - DAX-backed visuals producing real values in the first case.
  - DAX-backed visuals using seeded mock values in the second case.

Any additional test coverage (e.g. in Praeparo’s test suite) should confirm
that:

- Pack commands default to live data mode.
- Visual commands (`praeparo visual ...`) retain their existing mock default.
