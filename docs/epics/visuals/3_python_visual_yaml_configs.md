# Epic: Python Visual YAML Configs via `type` Paths (Phase PV‑3)

> Status: **Implemented** – YAML visuals can now point `type` at a `.py` module; the discovered Python visual declares a `config_model` that validates the YAML (with meta keys stripped), and cartesian configs have a Python-friendly base for reuse.

Implementation notes:

- Reserved YAML meta (`type`, `schema`/`schema_version`) are filtered before `config_model` validation.
- `CartesianChartConfigBase` (no discriminator) and `PythonCartesianChartConfig` let Python visuals reuse cartesian settings without clashing with `type: ./visual.py`.
- YAML loaders auto-register the Python visual’s pipeline under `type: python` so packs/CLI reuse the instance’s `build_dataset`/`render` hooks.

## 1. Problem

After PV‑1 (`python-visual` base class) and V‑CLI‑2 (CLI ergonomics and auto‑detection), Python visuals work well when invoked directly as modules:

- `praeparo python-visual run ./visuals/dashboard/documents_sent.py …`

However, the **YAML story for Python visuals is still awkward**:

- YAML visuals today always use `type` as a _registered visual kind_ (`governance_matrix`, `column`, `bar`, etc.).
- To wire a Python visual into packs, our earlier design proposed an extra key such as `python_visual: ./visuals/dashboard/documents_sent.py`, keeping `type: column` for cartesian configs.
- This adds a new top‑level field to the visual schema and creates a split mental model:
  - Sometimes `type` is a symbolic visual kind.
  - Sometimes the real “type” is hidden in `python_visual`, while `type` is really “chart shape”.

For code-backed dashboard tiles we specifically want:

- To keep **YAML front‑matter simple** and avoid extra keys where possible.
- To let a Python visual such as `documents_sent.py`:
  - Declare **its own config model** (e.g. `CartesianChartConfig` or a close cousin).
  - Accept that config **directly from YAML** with no extra nesting (`config:` blocks).
- To be able to reuse the cartesian configuration model (category/value axes, series, formatting) for these dashboard tiles, even though they are ultimately rendered by a Python visual.

We need a contract that lets `type` point directly at a Python visual file while still giving that visual a rich, typed config surface in YAML.

## 2. Goals

Phase PV‑3 should:

1. **Let YAML visuals point at Python files via `type`**
   - When `type` looks like a path to a `.py` file, treat it as a Python visual module, not a registered visual kind.
2. **Let Python visuals declare their own config models**
   - Each `PythonVisualBase` subclass can expose a `config_model` (a Pydantic model).
   - YAML fields (other than a small set of reserved meta keys) are validated against that `config_model`.
3. **Reuse existing config models where appropriate**
   - For dashboard tiles, allow `documents_sent.py` (eventually `DashboardVisual`) to use a cartesian‑shaped config:
     - Category field, value axes, series, formats, stacking, etc.
     - Either by reusing `CartesianChartConfig` directly or by composing a closely‑aligned model.
4. **Keep YAML shape flat and familiar**
   - Avoid nested `config:` blocks.
   - Keep fields like `title`, `category`, `value_axes`, `series` at the top level, as in existing cartesian visuals.
5. **Stay backwards compatible**
   - Existing visuals that use `type: governance_matrix`, `type: column`, `type: bar`, etc. must continue to work unchanged.
   - The new behaviour only kicks in when `type` clearly looks like a Python path.

Out of scope for PV‑3:

- Changing the schema of existing cartesian visuals.
- Auto‑registering Python visuals as named types in the global visual registry.
- Pack CLI ergonomics (already covered in V‑CLI‑2 and pack epics).

## 3. Proposed Design

### 3.1 `type` as Python visual path

We extend the meaning of `type` in YAML visual configs:

- If `type` is a **simple identifier** (e.g. `governance_matrix`, `column`, `bar`, `powerbi`), behaviour is unchanged: Praeparo looks up a registered visual type and uses its loader.
- If `type` **looks like a Python path**, for example:
  - Starts with `./` or `../`.
  - Contains a path separator (`/` or `\`) and ends with `.py`.
  - Or is an absolute path ending with `.py`.
  then Praeparo treats this as a **Python visual module**.

Example for a dashboard tile:

```yaml
# visuals/dashboard/documents_sent.yaml
schema: draft-1
type: ./documents_sent.py         # Python visual module path

title: Documents Sent
category:
  field: "'dim_calendar'[month]"
  label: Month
  data_type: date
  format: MMM-yy
  order: asc
value_axes:
  primary:
    label: Documents sent
    format: number:0
  secondary:
    label: SLA %
    format: percent:0
layout:
  legend:
    position: bottom
series:
  - id: documents_sent
    label: Documents sent
    type: column
    metric:
      key: documents_sent
  - id: pct_in_4h
    label: "% Sent in 4 hours"
    type: line
    axis: secondary
    metric:
      key: documents_sent.within_4_hours
    data_labels:
      position: above
      format: percent:0
```

Here:

- `type` no longer names a registered visual kind; it is the path to `documents_sent.py`.
- The remainder of the YAML mirrors the cartesian chart config used in `automation_90_second_documents_performance.yaml` and other cartesian visuals.

### 3.2 Config model declaration on Python visuals

In PV‑1 we introduced `PythonVisualBase`, which already supports a `context_model`. PV‑3 extends this pattern with an explicit `config_model`:

```python
# visuals/dashboard/documents_sent.py
from __future__ import annotations

from praeparo.models import CartesianChartConfig  # existing cartesian model
from praeparo.pipeline import ExecutionContext
from praeparo.pipeline.python_visual import PythonVisualBase
from praeparo.pipeline.outputs import OutputKind, OutputTarget, PipelineOutputArtifact
from praeparo.visuals.context_models import VisualContextModel


class DashboardContext(VisualContextModel):
    # Placeholder for any project-specific context fields; can start empty.
    pass


class DashboardVisual(PythonVisualBase[CartesianChartConfig, DashboardContext]):
    """Base visual for dashboard tiles backed by cartesian config."""

    config_model = CartesianChartConfig
    context_model = DashboardContext
    name = "Dashboard Tile"

    def build_dataset(self, pipeline, config, schema_artifact, context: ExecutionContext[DashboardContext]):
        # Use the cartesian config (category, series, value_axes) to plan a dataset,
        # typically via MetricDatasetBuilder and the standard query planners.
        ...

    def render(
        self,
        pipeline,
        config,
        schema_artifact,
        dataset_artifact,
        context: ExecutionContext[DashboardContext],
        outputs: list[OutputTarget],
    ) -> list[PipelineOutputArtifact]:
        # Option A: delegate to cartesian_figure(cartesian_config, dataset) then adjust styling.
        # Option B: build a Plotly figure manually, using config.series and axis metadata.
        ...
```

Key points:

- `config_model` tells Praeparo how to interpret the YAML for this Python visual.
  - For `DashboardVisual` we reuse `CartesianChartConfig` so the YAML shape remains familiar.
  - Other Python visuals can choose their own config model (including small, bespoke models).
- `context_model` continues to drive typed visual context, just as in PV‑1.

### 3.3 YAML → config model mapping

When loading a YAML visual whose `type` resolves to a Python module:

1. Praeparo imports the module and discovers the target `PythonVisualBase` subclass (e.g. `DashboardVisual`).
2. It reads `config_model` from the class. If not set, a default `BaseModel` or `dict[str, object]` model can be assumed.
3. It constructs the config payload by:
   - Taking the full YAML mapping.
   - Removing a small set of reserved meta keys:
     - `schema` (used by visual registry/schema tooling).
     - `type` (module path).
     - Potentially `name`/`description` if those are treated as top‑level metadata rather than config.
   - Passing the remaining mapping into `config_model.model_validate`.
4. The resulting instance becomes the `config` argument for `build_dataset` and `render`.

This keeps the YAML **flat** while giving each Python visual complete control over its config model.

### 3.4 Interaction with existing visual registry

The visual registry semantics remain:

- If `type` is a **known registered type** (e.g. `governance_matrix`, `column`, `bar`), the existing loaders are used and PV‑3 is not involved.
- If `type` looks like a Python path, the loader bypasses the registry and treats the file as a Python visual module.

This means:

- There is **no conflict** with the built‑in cartesian visuals:
  - Existing `type: column` / `type: bar` YAMLs continue to use the cartesian loader.
  - Dashboard YAMLs will use `type: ./documents_sent.py`, and the Python visual itself will opt into a cartesian‑shaped config via `config_model = CartesianChartConfig`.
- In future, we can still choose to register certain Python visuals under friendly names if desired, but PV‑3 does not require that.

### 3.5 Packs and dashboard tiles

Once PV‑3 is in place, packs can refer to dashboard tiles via YAML refs that point at the Python visual:

```yaml
slides:
  - id: documents_sent
    title: Documents Sent
    template: dashboard_tile
    visual:
      ref: ./visuals/dashboard/documents_sent.yaml

  - id: settlements
    title: Settlements
    template: dashboard_tile
    visual:
      ref: ./visuals/dashboard/settlements.yaml
```

Each of those YAML visuals:

- Uses `type: ./documents_sent.py` (or a renamed `visual.py`) to point at the shared `DashboardVisual`.
- Supplies its own cartesian‑shaped config (category, axes, series) so the same Python visual can render different tiles with consistent styling.

Pack behaviour around PPTX templates, placeholder geometry, and Python visual sizing is covered separately in the pack epics (notably [Pack Template Geometry And Visual Sizing](../pack_runner/12_pack_template_geometry_and_visual_sizing.md)).

## 4. Implementation Plan (Praeparo)

> Implementation lives upstream in Praeparo. This epic captures the design and migration intent.

### 4.1 Loader and registry changes

- Extend the visual loader (likely in `praeparo/visuals/registry.py`) to:
  - Detect when `config["type"]` is a Python path (`.py` with a path separator).
  - Route those configs to a new helper, e.g. `load_python_visual_from_yaml`.
- Implement `load_python_visual_from_yaml(path: Path, payload: Mapping[str, object])`:
  - Import the module via `python_visual_loader`.
  - Discover the primary `PythonVisualBase` subclass.
  - Read `config_model` from the class.
  - Build the config payload by removing reserved keys from `payload` and validating the remainder with `config_model`.
  - Return `(visual_instance, config_instance)` or an appropriate wrapper for the existing `VisualPipeline` infrastructure.

### 4.2 PythonVisualBase enhancements

- Add an optional `config_model` attribute to `PythonVisualBase`:

  - Default to a simple `BaseModel` with no fields, so visuals that don’t need structured config can ignore it.
  - For visuals like `DashboardVisual`, set `config_model = CartesianChartConfig` to opt into the cartesian config surface.

- Ensure `PythonVisualBase.to_definition()`:
  - Uses the provided `config_model` type when constructing the visual pipeline’s config parameter.
  - Continues to support CLI‑only Python visuals that don’t come from YAML (PV‑1 behaviour).

### 4.3 Tests

Add upstream tests in Praeparo to cover:

1. **Basic path‑based Python visual**
   - YAML visual with `type: ./tests/fixtures/python_visuals/simple_visual.py` and a couple of extra fields.
   - The Python visual exposes a small `config_model` that matches those fields.
   - Assert that:
     - YAML loads without using the registered visual types.
     - `build_dataset` and `render` receive a validated config instance.
2. **Cartesian‑backed Python visual**
   - A fixture `cartesian_python_visual.py` that sets `config_model = CartesianChartConfig`.
   - YAML mirroring an existing column/bar chart but with `type: ./cartesian_python_visual.py`.
   - Assert that the config validates and the visual can render a chart using `cartesian_figure` or similar.
3. **Regression on existing types**
   - Existing governance and cartesian YAMLs with `type: governance_matrix`, `type: column`, `type: bar` still load and execute via the registered visual loaders.

## 5. Validation & downstream adoption

Once PV‑3 lands upstream:

- Add one or more dashboard YAML visuals under a consumer project's `visuals/dashboard/` folder that:
  - Use `type: ./documents_sent.py` (or `./visual.py` after refactor).
  - Supply cartesian‑shaped config fields as per the example in §3.1.
- Refactor `documents_sent.py` into `DashboardVisual`:
  - Set `config_model = CartesianChartConfig`.
  - Implement `build_dataset`/`render` using the new ratio and trailing‑month helpers.
- Update the relevant pack definitions to reference these YAML visuals.
- Refresh project docs to show:
  - How a YAML visual can point at a Python visual via `type`.
  - How the project is reusing cartesian config shapes for metric dashboards.

## 6. Open Questions

- **Config vs meta separation**
  - Which top‑level keys should always be treated as meta (never part of the config_model)?
    - Today we assume `schema` and `type`; we may also choose to reserve `name` / `description`.
- **Exact reuse of `CartesianChartConfig`**
  - Do we reuse `CartesianChartConfig` directly, or define a small dashboard-specific wrapper that embeds it?
  - Direct reuse keeps the API identical to other cartesian visuals but may require us to treat its own `type` field carefully.
- **Multiple Python visuals per module**
  - For now we assume a single primary `PythonVisualBase` subclass per module; if modules grow multiple visuals, we may need an explicit selector mechanism.

These can be resolved during implementation; the epic’s aim is to fix the overall direction so Python visuals can be first‑class YAML citizens without additional top‑level keys.
