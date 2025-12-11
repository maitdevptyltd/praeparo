# Python-Backed Visuals

> **Status:** Available (PV‑1). Ship quick visuals without writing YAML.

## Overview

`PythonVisualBase` offers a minimal class-based API for visuals that prefer code over YAML. Implementers override only two hooks:

- `build_dataset(...)` — assemble any dataset payload (lists, DataFrames, Plotly-ready rows, etc.).
- `render(...)` — emit outputs (HTML/PNG/other files) using the requested `OutputTarget` list.

The base class wires everything else:

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
        # Produce any dataset shape you need (could call MetricDatasetBuilder here).
        return DatasetArtifact(value=[1, 2, 3], filename="numbers.json")

    def render(self, pipeline, config, schema_artifact, dataset_artifact, context, outputs: Sequence[OutputTarget]):
        emitted: list[PipelineOutputArtifact] = []
        for target in outputs:
            target.path.parent.mkdir(parents=True, exist_ok=True)
            if target.kind is OutputKind.HTML:
                target.path.write_text(f\"<h1>{context.visual_context.report_title}</h1>\", encoding=\"utf-8\")
            elif target.kind is OutputKind.PNG:
                target.path.write_bytes(b\"PNG\")  # Swap in plotly/altair/matplotlib as needed.
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

- Context flags (`--context`, `--calculate`, `--define`, `--metrics-root`, `--grain`, `--seed`, `--scenario`) populate the typed `ReportContext`.
- `--project-root` overrides the project root used for fallback discovery and default build paths when running from outside a project. Typed context models still prefer their own `metrics_root` (defaulting to `<cwd>/registry/metrics`) unless you pass `--metrics-root`.
- Outputs are driven by `--output-html` / `--output-png` (HTML defaults to `build/<module>.html` if omitted).
- The pipeline still discovers datasources/metrics roots and populates `ExecutionContext.dataset_context`, so you can plug in `MetricDatasetBuilder` if desired.
- When a module exports multiple visuals, pick one with `--visual-class MyVisual`.

## Destination shorthand

The `run` command now accepts an optional positional `dest` to cut down on flags:

- `praeparo python-visual run visuals/my_visual.py report.png`  
  Sets `--output-png report.png`, defaults HTML to `build/my_visual.html`, and uses `report/_artifacts` for artefacts unless overridden.
- `praeparo python-visual run visuals/my_visual.py ./exports/`  
  Slugifies the module name (`my_visual`) and writes `./exports/my_visual.html`, `./exports/my_visual.png`, and artefacts under `./exports/_artifacts` by default.

Flagged outputs (`--output-html`, `--output-png`, `--artefact-dir`) still win over anything derived from `dest`.

You can also skip the explicit subcommand—`.py` files are auto-detected:

```bash
praeparo visuals/my_visual.py ./exports/
# or
praeparo visual run visuals/my_visual.py ./exports/report.png
```

## Using Python visuals in packs

Pack slides can point `visual.ref` directly at a Python module:

```yaml
slides:
  - title: "Documents Sent"
    template: "full_page_image"
    visual:
      ref: ./visuals/dashboard/documents_sent.py
```

When a `visual.ref` ends with `.py`, Praeparo:

- Imports the module and locates the first (or specified) `PythonVisualBase` subclass.
- Registers its `python` pipeline definition via `visual.to_definition()`.
- Builds a `BaseVisualConfig` with `visual.to_config()` and executes it through the standard `VisualPipeline`.
- Instantiates the visual’s `context_model` from the pack metadata (including merged `context`/`calculate`/`define` payloads) so size hints and DAX filters flow through unchanged.

Refs ending in `.yaml` / `.yml` keep the existing YAML visual behaviour. Packs can mix YAML and Python visuals freely on different slides and placeholders.

## Notes

- The base class auto-registers a transient `python` pipeline definition per run; existing YAML visuals are unaffected.
- YAML wrappers that point `type` at a `.py` module now apply the Python visual’s declared `context_model` during `praeparo visual run`, so `--context`, `--calculate`, and `--define` filters flow into generated DAX the same way as native YAML visuals.
- `schema_artifact.value` is `None` by default—override `build_schema` only if your visual needs it.
- Context models stay strongly typed; re-use `VisualContextModel` fields (metrics root, grain, DAX filters) to stay aligned with YAML execution.

## Metric dataset builder shortcuts

Python visuals can now return a `MetricDatasetBuilder` directly. The pipeline will execute it, persist the dataset JSON, and emit any DAX plans declared by the builder.

```python
from praeparo.datasets import MetricDatasetBuilder

class DocumentsSentVisual(PythonVisualBase[list[dict[str, object]], ReportContext]):
    context_model = ReportContext

    def build_dataset(self, pipeline, config, schema_artifact, context):
        builder = MetricDatasetBuilder(context.dataset_context, slug="documents_sent")
        builder.metric("documents_sent", alias="documents_sent")
        builder.metric("documents_sent.within_4_hours", alias="pct_in_4h", value_type="ratio")
        return builder  # pipeline executes and emits JSON + .dax under artefact_dir
```

The explicit form still works when you need full control:

```python
from praeparo.pipeline.registry import DatasetArtifact

def build_dataset(self, pipeline, config, schema_artifact, context):
    rows = [
        {"Month": "Jan-25", "documents_sent": 120, "pct_in_4h": 0.92},
    ]
    return DatasetArtifact(value=rows, filename="documents_sent.data.json")
```

When `artefact_dir` is set (CLI dest or pack run), the pipeline writes:

- `*.data.json` based on `DatasetArtifact.filename` (builder default: `<slug>.data.json`).
- `*.dax` for each plan in `DatasetArtifact.plans`, including those produced by `MetricDatasetBuilder`.

## Render shorthand (return a Figure)

Renderers can now return a Plotly `go.Figure` directly; the pipeline will emit HTML/PNG for every requested `OutputTarget` and wrap it in a `RenderOutcome`.

```python
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from praeparo.datasets import MetricDatasetBuilder
from praeparo.pipeline import PythonVisualBase

class DocumentsSentVisual(PythonVisualBase[..., ReportContext]):
    context_model = ReportContext

    def build_dataset(self, pipeline, config, schema_artifact, context):
        builder = MetricDatasetBuilder(context.dataset_context, slug="documents_sent")
        builder.metric("documents_sent", alias="documents_sent")
        builder.metric("documents_sent.within_4_hours", alias="pct_in_4h", value_type="ratio")
        return builder  # shorthand: MetricDatasetBuilder

    def render(self, pipeline, config, schema_artifact, dataset_artifact, context, outputs):
        fig = make_subplots()
        fig.add_bar(x=["sent"], y=[dataset_artifact.value[0]["documents_sent"]])

        width = context.options.metadata.get("width")
        height = context.options.metadata.get("height")
        if width or height:
            fig.update_layout(width=width, height=height)  # optional size hints from pack template

        return fig  # shorthand: Figure → pipeline writes HTML/PNG
```

Accepted return types:

- `build_dataset`: `DatasetArtifact` (explicit) or `MetricDatasetBuilder` (shorthand).
- `render`: `RenderOutcome` (explicit), `go.Figure` (shorthand; HTML/PNG auto-written), or `None` (no outputs).
