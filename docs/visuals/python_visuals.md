# Python-Backed Visuals

> **Status:** Available (PV‑1). Ship quick visuals without writing YAML.

## Overview

`PythonVisualBase` offers a small class-based API for visuals that prefer code
over YAML. Implementers override only two hooks:

- `build_dataset(...)` — assemble any dataset payload (lists, DataFrames, Plotly-ready rows, etc.).
- `render(...)` — emit outputs (HTML/PNG/other files) using the requested `OutputTarget` list.

The base class handles the rest:

- Schema is optional (`None` by default).
- A `context_model: Type[VisualContextModel]` attribute declares the typed context you want.
- `to_config()` returns a stub `BaseVisualConfig` so visuals run through the standard `VisualPipeline`.

## Quickstart

Create a module like `visuals/my_visual.py`:

```python
from __future__ import annotations
from typing import Sequence

from praeparo.pipeline import OutputTarget, PythonVisualBase
from praeparo.pipeline.outputs import OutputKind, PipelineOutputArtifact
from praeparo.pipeline.registry import DatasetArtifact, RenderOutcome
from praeparo.visuals.context_models import VisualContextModel


class ReportContext(VisualContextModel):
    report_title: str | None = None


class MyVisual(PythonVisualBase[list[int], ReportContext]):
    context_model = ReportContext
    name = "My Python Visual"

    def build_dataset(self, pipeline, config, schema_artifact, context):
        # Build whatever dataset shape this visual needs.
        return DatasetArtifact(value=[1, 2, 3], filename="numbers.json")

    def render(self, pipeline, config, schema_artifact, dataset_artifact, context, outputs: Sequence[OutputTarget]):
        emitted: list[PipelineOutputArtifact] = []
        for target in outputs:
            target.path.parent.mkdir(parents=True, exist_ok=True)
            if target.kind is OutputKind.HTML:
                target.path.write_text(f\"<h1>{context.visual_context.report_title}</h1>\", encoding=\"utf-8\")
            elif target.kind is OutputKind.PNG:
                target.path.write_bytes(b\"PNG\")  # Swap in Plotly, Altair, or Matplotlib here.
            emitted.append(PipelineOutputArtifact(kind=target.kind, path=target.path))
        return RenderOutcome(outputs=emitted)
```

Run it through the CLI:

```bash
praeparo python-visual run visuals/my_visual.py \
  --output-html ./build/my_visual.html \
  --output-png ./build/my_visual.png \
  --meta report_title="Quarterly Snapshot" \
  --metrics-root ./registry/metrics
```

CLI behaviour matches YAML visuals:

- Context flags (`--context`, `--calculate`, `--define`, `--metrics-root`,
  `--grain`, `--seed`, `--scenario`) populate the typed `ReportContext`.
- `--project-root` changes the fallback project root when you run from outside
  a project. Typed context models still prefer their own `metrics_root`
  (defaulting to `<cwd>/registry/metrics`) unless you pass `--metrics-root`.
- Outputs are driven by `--output-html` / `--output-png` (HTML defaults to
  `build/<module>.html` if omitted).
- The pipeline still discovers datasources and metrics roots, then fills in
  `ExecutionContext.dataset_context`, so you can plug in
  `MetricDatasetBuilder` if desired.
- When a module exports multiple visuals, pick one with `--visual-class MyVisual`.

## Destination shorthand

The `run` command accepts an optional positional `dest` so you can skip a few
flags:

- `praeparo python-visual run visuals/my_visual.py report.png`  
  Sets `--output-png report.png`, defaults HTML to `build/my_visual.html`, and uses `report/_artifacts` for artefacts unless overridden.
- `praeparo python-visual run visuals/my_visual.py ./exports/`  
  Slugifies the module name (`my_visual`) and writes `./exports/my_visual.html`, `./exports/my_visual.png`, and artefacts under `./exports/_artifacts` by default.

Flagged outputs (`--output-html`, `--output-png`, `--artefact-dir`) still win
over anything derived from `dest`.

You can also skip the explicit subcommand - `.py` files are auto-detected:

```bash
praeparo visuals/my_visual.py ./exports/
# or
praeparo visual run visuals/my_visual.py ./exports/report.png
```

## YAML wrappers (`type: ./module.py`)

Python visuals can also be referenced from YAML by pointing `type` at a module
path instead of a registered visual kind:

```yaml
schema: draft-1
type: ./documents_sent.py

title: Documents Sent
category:
  field: "'dim_calendar'[month]"
  label: Month
  data_type: date
value_axes:
  primary:
    label: Documents sent
    format: number:0
series:
  - id: documents_sent
    label: Documents sent
    type: column
    metric:
      key: documents_sent
```

When `type` resolves to a `.py` module, Praeparo:

- imports the module and discovers the `PythonVisualBase` subclass,
- reads that class's `config_model`,
- strips reserved YAML meta keys such as `type`, `schema`, and
  `schema_version`,
- validates the remaining payload with `config_model`, and
- executes the visual through the standard visual pipeline.

This keeps the YAML flat while still giving the Python visual a strongly typed
config surface.

If the wrapped config model includes DAX-backed chart fields such as
`category.field`, keep using canonical DAX column syntax in that YAML today.
Praeparo has some partial support for dotted shorthand field references, but
that behaviour is not yet a universal contract across all DAX-backed visual
and dataset-builder paths.

Example:

```python
from praeparo.models import CartesianChartConfig
from praeparo.pipeline import PythonVisualBase
from praeparo.visuals.context_models import VisualContextModel


class DashboardContext(VisualContextModel):
    pass


class DashboardVisual(PythonVisualBase[CartesianChartConfig, DashboardContext]):
    config_model = CartesianChartConfig
    context_model = DashboardContext
```

Use this pattern when you want pack refs, shared YAML front matter, or project
review workflows to stay YAML-first while the implementation remains code-first.

## Responsive tiers and breakpoints

Python visuals often need a few layout modes instead of one fixed figure. The
best pattern is to keep the data model stable and change only the presentation
when the available canvas changes.

Use a small set of tiers that map to the space you actually have, for example:

- `compact` for narrow embeds or mobile-sized canvases,
- `standard` for the default pack or report layout,
- `wide` for large desktop exports or full-page figures.

The runtime can supply width and height hints through the visual context or
output metadata. Read those hints once, choose a tier, and branch on that tier
inside `render(...)` rather than scattering size checks through the figure
code.

```python
def resolve_layout_tier(width: int | None, height: int | None) -> str:
    if width is not None and width < 640:
        return "compact"
    if width is not None and width < 1024:
        return "standard"
    if height is not None and height < 720:
        return "standard"
    return "wide"
```

Inside `render(...)`, keep the tier-specific changes limited to presentation:

```python
metadata = context.options.metadata or {}
tier = resolve_layout_tier(metadata.get("width"), metadata.get("height"))

if tier == "compact":
    fig.update_layout(legend=dict(orientation="h"), margin=dict(l=12, r=12))
elif tier == "standard":
    fig.update_layout(legend=dict(orientation="v"))
else:
    fig.update_layout(legend=dict(orientation="v"), height=900)
```

That keeps the chart readable across outputs without changing the underlying
dataset or logic.

## Using Python visuals in packs

Pack slides can point `visual.ref` directly at a Python module:

```yaml
slides:
  - title: "Requests Processed"
    template: "full_page_image"
    visual:
      ref: ./visuals/dashboard/requests_processed.py
```

When a `visual.ref` ends with `.py`, Praeparo:

- Imports the module and locates the first (or specified) `PythonVisualBase` subclass.
- Registers its `python` pipeline definition via `visual.to_definition()`.
- Builds a `BaseVisualConfig` with `visual.to_config()` and executes it through the standard `VisualPipeline`.
- Instantiates the visual’s `context_model` from the pack metadata (including merged `context`/`calculate`/`define` payloads) so size hints and DAX filters flow through unchanged.

Refs ending in `.yaml` / `.yml` keep the existing YAML visual behaviour. Packs can mix YAML and Python visuals freely on different slides and placeholders.

## Notes

- The base class auto-registers a temporary `python` pipeline definition for
  each run; existing YAML visuals are unaffected.
- YAML wrappers that point `type` at a `.py` module apply the Python visual’s
  declared `context_model` during `praeparo visual run`, so `--context`,
  `--calculate`, and `--define` filters flow into generated DAX the same way as
  native YAML visuals.
- When the wrapped config model is DAX-backed, prefer canonical DAX column
  references in YAML fields such as `category.field` until field-reference
  normalisation is centralised across Praeparo.
- `schema_artifact.value` is `None` by default. Override `build_schema` only if
  your visual needs it.
- Context models stay strongly typed. Re-use `VisualContextModel` fields
  (metrics root, grain, DAX filters) to stay aligned with YAML execution.

## Metric dataset builder shortcuts

Python visuals can return a `MetricDatasetBuilder` directly. The pipeline will
execute it, persist the dataset JSON, and emit any DAX plans declared by the
builder.

```python
from praeparo.datasets import MetricDatasetBuilder

class RequestsProcessedVisual(PythonVisualBase[list[dict[str, object]], ReportContext]):
    context_model = ReportContext

    def build_dataset(self, pipeline, config, schema_artifact, context):
        builder = MetricDatasetBuilder(context.dataset_context, slug="requests_processed")
        builder.metric("requests_processed", alias="requests_processed")
        builder.metric("requests_processed.within_target", alias="pct_within_target", value_type="ratio")
        return builder  # pipeline executes and emits JSON + .dax under artefact_dir
```

The explicit form still works when you need full control:

```python
from praeparo.pipeline.registry import DatasetArtifact

def build_dataset(self, pipeline, config, schema_artifact, context):
    rows = [
        {"Month": "Jan-25", "requests_processed": 120, "pct_within_target": 0.92},
    ]
    return DatasetArtifact(value=rows, filename="requests_processed.data.json")
```

When `artefact_dir` is set (CLI `dest` or pack run), the pipeline writes:

- `*.data.json` based on `DatasetArtifact.filename` (builder default: `<slug>.data.json`).
- `*.dax` for each plan in `DatasetArtifact.plans`, including those produced by `MetricDatasetBuilder`.

## Render shorthand (return a Figure)

Renderers can return a Plotly `go.Figure` directly; the pipeline will emit
HTML/PNG for every requested `OutputTarget` and wrap it in a `RenderOutcome`.

```python
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from praeparo.datasets import MetricDatasetBuilder
from praeparo.pipeline import PythonVisualBase

class RequestsProcessedVisual(PythonVisualBase[..., ReportContext]):
    context_model = ReportContext

    def build_dataset(self, pipeline, config, schema_artifact, context):
        builder = MetricDatasetBuilder(context.dataset_context, slug="requests_processed")
        builder.metric("requests_processed", alias="requests_processed")
        builder.metric("requests_processed.within_target", alias="pct_within_target", value_type="ratio")
        return builder  # shorthand: MetricDatasetBuilder

    def render(self, pipeline, config, schema_artifact, dataset_artifact, context, outputs):
        fig = make_subplots()
        fig.add_bar(x=["processed"], y=[dataset_artifact.value[0]["requests_processed"]])

        width = context.options.metadata.get("width")
        height = context.options.metadata.get("height")
        if width or height:
            fig.update_layout(width=width, height=height)  # optional size hints from the pack

        return fig  # shorthand: Figure → pipeline writes HTML/PNG
```

Accepted return types:

- `build_dataset`: `DatasetArtifact` (explicit) or `MetricDatasetBuilder` (shorthand).
- `render`: `RenderOutcome` (explicit), `go.Figure` (HTML/PNG auto-written), or
  `None` (no outputs).
