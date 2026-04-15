# Epic: Visual CLI Ergonomics & Python Auto‑Detection (Phase V‑CLI‑2)

> Status: **Complete** – `visual run` and `python-visual run` support `[config] [dest]` shorthand, and `.py` modules are auto-routed to Python visual execution (2025-12-13).

- Implementation landed upstream in `praeparo/cli/__init__.py` (`dest` positional + `_normalise_argv` `.py` routing) and documented in `docs/visuals/python_visuals.md` and `docs/visuals/index.md`.

## 1. Problem

Praeparo’s CLI has grown along two paths:

- YAML‑backed visuals:
  - `praeparo visual run <type> <config.yaml> [flags…]`
  - Outputs controlled via `--output-html`, `--output-png`, `--artefact-dir`.
- Python‑backed visuals:
  - `praeparo python-visual run <module.py> [flags…]`

Separately, packs now support an ergonomic shorthand:

```bash
praeparo pack run <pack.yaml> <dest>
```

where `<dest>` can be:

- A `.pptx` file path – used as the pack result file, with artefacts under `<parent>/<stem>/_artifacts`.
- A directory or extension‑less path – used as a folder with:
  - artefacts under `<dest>/_artifacts`
  - PPTX result file at `<dest>/<pack-slug>.pptx`.

For day‑to‑day use, the **pack CLI feels much nicer** than the visual CLIs:

- It supports a natural `[input] [dest]` pattern.
- It interprets `dest` intelligently based on whether it looks like a file or folder.

However:

- `visual run` and `python-visual run` still require explicit `--output-*` flags even when the user has already supplied a natural “destination” path.
- Calling `praeparo` with a Python module or YAML visual config still requires explicitly spelling out `visual` vs `python-visual`, even though the file extension/type is unambiguous to the tool.

This leads to minor friction:

- Users mentally juggle three different mental models:
  - `visual run TYPE config.yaml --output-png ...`
  - `python-visual run module.py --output-png ...`
  - `pack run pack.yaml dest`
- Ergonomic conveniences from the pack runner are not available when working on a single visual (YAML or Python).

## 2. Goals

Phase V‑CLI‑2 should:

1. **Unify `[config] [dest]` ergonomics** for single‑visual CLIs:
   - Both `visual run` and `python-visual run` should accept an optional positional `dest`.
   - `dest` should drive default `--output-html`, `--output-png`, and `--artefact-dir` values, with flags still overriding.
2. **Auto‑detect Python visuals from filenames**:
   - `praeparo python-visual run module.py …` remains the explicit form.
   - `praeparo visual run module.py …` and `praeparo module.py …` should be normalised to `python-visual run module.py …` behind the scenes.
3. **Keep existing behaviour backwards compatible**:
   - Older invocations that only use `--output-*` flags and omit `dest` must keep working with identical semantics.
   - No changes to `pack run` behaviour in this phase.

Out of scope:

- Auto‑detecting packs from bare YAML (i.e. `praeparo pack.yaml` → `pack run`). That can be layered in later when pack schemas are fully stabilised.
- Changing default data modes or artefact naming conventions (covered in other epics).

## 3. Desired Behaviour

### 3.1 Shared `[config] [dest]` for `visual run` and `python-visual run`

Both commands SHOULD accept:

```bash
praeparo visual run <type> <config.yaml> [dest] [flags…]
praeparo python-visual run <module.py> [dest] [flags…]
```

where `dest` is optional and interpreted as:

1. **No dest supplied** – current behaviour:
   - HTML:
     - Defaults to `build/<config-stem>.html` via `_default_output_path`.
   - PNG:
     - Only emitted when `--output-png` is supplied.
   - Artefacts:
     - `--artefact-dir` is fully manual; no default is derived.

2. **dest ends with `.png`**:
   - Defaults:
     - `output_png` → `dest`.
     - `artefact_dir` → `<parent>/<stem>/_artifacts`.
   - HTML:
     - Defaults to `<parent>/<stem>/_artifacts/<config-stem>.html` unless `--output-html` is provided.
   - Flags override defaults:
     - `--output-png` wins over `dest`.
     - `--artefact-dir` wins over the derived artefact dir.

3. **dest ends with `.html`**:
   - Defaults:
     - `output_html` → `dest`.
     - `artefact_dir` → `<parent>/<stem>/_artifacts`.
   - PNG:
     - Only emitted when `--output-png` is supplied.

4. **dest is a directory or extension‑less path**:
   - Let `visual_slug = slugify(config.stem)` (reusing the existing slugifier from `praeparo.visuals.dax`).
   - Defaults:
     - `output_png` → `<dest>/<visual_slug>.png`.
     - `output_html` → `<dest>/<visual_slug>.html`.
     - `artefact_dir` → `<dest>/_artifacts`.

5. **Empty or whitespace dest**:
   - Treated as an error:
     - `ValueError: "Destination path cannot be empty."`

In all cases, explicit flags (`--output-html`, `--output-png`, `--artefact-dir`) MUST override any defaults derived from `dest`.

### 3.2 Auto‑detect Python visuals

CLI normalisation SHOULD recognise Python modules and route them to `python-visual` commands automatically:

1. **Bare invocation with a `.py` file**:

   - Input:

     ```bash
     praeparo visuals/documents_sent.py .tmp/amp/documents_sent.png
     ```

   - Normalisation:

     ```text
     ["python-visual", "run", "visuals/documents_sent.py", ".tmp/amp/documents_sent.png"]
     ```

   - Effect:
     - Equivalent to calling `praeparo python-visual run visuals/documents_sent.py .tmp/amp/documents_sent.png`.

2. **`visual run` with a `.py` config**:

   - Input:

     ```bash
     praeparo visual run visuals/documents_sent.py .tmp/amp/documents_sent.png
     ```

   - Normalisation:

     ```text
     ["python-visual", "run", "visuals/documents_sent.py", ".tmp/amp/documents_sent.png"]
     ```

   - This lets users type `visual run` out of habit while still getting Python visual behaviour.

3. **`visual run TYPE config.yaml`**:

   - When the third argument is a visual type (e.g. `governance_matrix`, `powerbi`):
     - Normalisation remains unchanged:

       ```bash
       praeparo visual run governance_matrix visuals/amp_dashboard.yaml out/amp
       ```

     - Continues to route to `visual.run` with the registered type; not treated as Python.

4. **`visual run config.yaml` without type**:

   - Existing normalisation continues to apply:

     ```bash
     praeparo visual run visuals/amp_dashboard.yaml out/amp
     ```

   - Becomes:

     ```text
     ["visual", "run", "auto", "visuals/amp_dashboard.yaml", "out/amp"]
     ```

   - Type is inferred from the YAML’s `type` field via the existing `auto` logic.

Python detection is deliberately **extension‑based** (`.py`), keeping the rule simple and predictable.

## 4. CLI Contract (Praeparo)

Implementation lives in the Praeparo submodule, but the contract is documented here for downstream users.

### 4.1 Parser changes

- `visual run` and `python-visual run` both inherit:
  - `_build_common_parser()`:
    - `config` positional (YAML or Python module).
    - Shared options (`--metrics-root`, `--seed`, `--scenario`, `--data-mode`, etc.).
  - `_build_run_specific_parser()`:
    - NOW also includes the optional positional `dest`.
    - Continues to expose:
      - `--output-html / --out`
      - `--output-png / --png-out`
      - `--build-artifacts-dir`
      - `--png-scale`

- A new helper `_derive_visual_dest_defaults(config_path, dest)`:
  - Returns `(artefact_dir_default, html_default, png_default)` based on the rules in §3.1.
  - Applied by both `_handle_visual_run` and `_handle_python_visual_run` before building `PipelineOptions`.

- `_normalise_argv(...)`:
  - Gains `.py` detection to route:
    - Bare `.py` to `python-visual run`.
    - `visual run <python-file> …` to `python-visual run`.
  - Leaves `pack` and registered visual types untouched.

### 4.2 Examples

**YAML governance visual with directory dest**

```bash
poetry run praeparo visual run governance_matrix \
  visuals/performance_dashboard.yaml \
  .tmp/performance_dashboard
```

Resolves to:

- `output_html` → `.tmp/performance_dashboard/performance_dashboard.html`
- `output_png` → `.tmp/performance_dashboard/performance_dashboard.png`
- `artefact_dir` → `.tmp/performance_dashboard/_artifacts`

**Python visual with PNG dest**

```bash
poetry run praeparo python-visual run \
  visuals/dashboard/documents_sent.py \
  .tmp/documents_sent.png \
  --metrics-root registry/metrics \
  --context context.yaml
```

Resolves to:

- `output_png` → `.tmp/documents_sent.png`
- `artefact_dir` → `.tmp/documents_sent/_artifacts`
- `output_html`:
  - Defaults to `build/documents_sent.html` (unless `--output-html` supplied).

**Shorthand with bare `.py`**

```bash
poetry run praeparo \
  visuals/dashboard/documents_sent.py \
  .tmp/documents_sent.png \
  --metrics-root registry/metrics \
  --context context.yaml
```

Normalised to the previous python‑visual example transparently.

## 5. Implementation Expectations (Praeparo)

The code changes for this phase landed upstream in Praeparo:

- Update `_build_run_specific_parser()` to add the `dest` positional.
- Implement `_derive_visual_dest_defaults()` alongside `_derive_pack_dest_defaults()`.
- In `_handle_visual_run` and `_handle_python_visual_run`:
  - Call `_derive_visual_dest_defaults(args.config, args.dest)` early.
  - Fill `args.artefact_dir`, `args.output_html`, `args.output_png` only when they are currently `None`.
- Extend `_normalise_argv()` to:
  - Route bare `.py` to `python-visual run`.
  - Route `visual run <python-file> …` to `python-visual run` when the third argument ends with `.py`.
- Add CLI tests (in Praeparo):
  - Verify new `[config] [dest]` behaviour for both YAML and Python visuals.
  - Verify that `.py` detection works for:
    - `python-visual run`.
    - `visual run`.
    - Bare `praeparo <file>`.

No changes to `pack run` are part of this epic.

## 6. Usage in Consumer Projects

Once Praeparo implements V‑CLI‑2, consumer project examples can standardise on the new ergonomics. For instance, `visuals/dashboard/documents_sent.py` can advertise:

```bash
poetry run praeparo python-visual run \
  visuals/dashboard/documents_sent.py \
  .tmp/documents_sent.png \
  --metrics-root registry/metrics \
  --context context.yaml
```

And governance or cartesian YAML visuals can use:

```bash
poetry run praeparo visual run governance_matrix \
  visuals/performance_dashboard.yaml \
  .tmp/performance_dashboard
```

This keeps the **pack**, **visual**, and **python‑visual** CLIs aligned around a common pattern:

- Primary inputs as `[config] [dest]`.
- Intelligent defaults for outputs and artefacts, with flags available for overrides.
