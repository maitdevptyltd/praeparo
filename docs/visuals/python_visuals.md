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

## Notes

- The base class auto-registers a transient `python` pipeline definition per run; existing YAML visuals are unaffected.
- `schema_artifact.value` is `None` by default—override `build_schema` only if your visual needs it.
- Context models stay strongly typed; re-use `VisualContextModel` fields (metrics root, grain, DAX filters) to stay aligned with YAML execution.
