# Epic: Python‑Backed Custom Visuals (Phase PV‑1)

> Status: **Complete** – shipped upstream in Praeparo as PV‑1 (`praeparo python-visual run ...`), including `.py` auto-routing, pack integration, docs, and tests.

## 0. Implementation Notes

This epic is implemented upstream in Praeparo and is now the canonical contract used by this repo.

- **Core contract:** `praeparo/pipeline/python_visual.py` (`PythonVisualBase`)
- **CLI integration:** `praeparo/cli/__init__.py` (`python-visual` commands + `.py` auto-routing)
- **Developer docs:** `docs/visuals/python_visuals.md`
- **Test coverage:** `tests/test_python_visual_cli.py`, `tests/visuals/test_python_visual_yaml_configs.py`

## 1. Problem

Praeparo’s current extensibility story for visuals is powerful but relatively heavy:

- Visuals are defined as YAML configs (`type: governance_matrix`, Power BI, cartesian, etc.).
- Each visual type is backed by:
  - A Pydantic config model (`BaseVisualConfig` subclass).
  - A registered loader in `praeparo.visuals.registry.register_visual_type`.
  - A full visual pipeline (`VisualPipelineDefinition` / `VisualPipelineDefinitionBase`) that wires schema, dataset, and render stages.
- The CLI (`praeparo visual run|artifacts|dax`) expects a **YAML file** and uses its `type` to:
  - Look up the visual registration.
  - Construct an `ExecutionContext[VisualContextModel]`.
  - Route into the pipeline for schema/dataset/render.

For production dashboard types (governance_matrix, Power BI exports, cartesian plots), this is the right level of ceremony. But for **ad hoc, Python‑native visuals**, the bar feels too high:

- A user who just wants to:
  - Define a dataset using `MetricDatasetBuilder` or arbitrary Python.
  - Render it to a PNG/HTML using their own plotting library.
  - Run it via `praeparo visual ...`
  currently has to:
  - Create a YAML config with a synthetic `type`.
  - Ship a plugin module that:
    - Registers a new visual type and config model.
    - Registers a pipeline definition with schema/dataset/render builders.
- There is **no built‑in way to point the CLI at a single Python file** that declares “here is my dataset + render function” and get artefacts out.

This makes quick experiments (e.g. operational one‑offs, SRE dashboards, small internal tools) more complex than they need to be, and encourages hand‑rolled scripts instead of reusing Praeparo’s context, datasources, and pipeline outputs.

## 2. Goals

Phase PV‑1 should introduce a **“Python visual module”** concept with:

1. **Simple class-based contract**
   - A small, explicit base class that Python files can subclass:
     - Override a `build_dataset` hook (optionally using Praeparo’s dataset builders).
     - Override a `render` hook that receives the dataset plus `ExecutionContext` and `OutputTarget`s.
2. **CLI integration without YAML**
   - New CLI entry that lets users run:
     - `praeparo python-visual run path/to/visual.py ...`
     - Or an extended `visual` subcommand that understands a `python` type and module path.
   - The CLI should:
     - Load and validate the module.
     - Construct an `ExecutionContext` (including metrics_root, scenario, context, DAX filters) in the same way as for other visuals where relevant.
3. **Re‑use of existing pipeline primitives**
   - Use `ExecutionContext`, `VisualPipeline`, `OutputTarget`, and `PipelineOptions`:
     - Python visuals should feel like thin adapters over the existing pipeline, not an entirely separate execution path.
   - For DAX‑backed Python visuals, re‑use:
     - `MetricDatasetBuilder`, `MetricDatasetPlan`, `DefaultQueryPlannerProvider`, etc.
4. **Low ceremony & discoverability**
   - A new user should be able to:
     - Copy a minimal template Python file.
     - Implement `build_dataset` and `render` functions.
     - Run it through the CLI without touching YAML or plugin registration.
5. **Clear separation of concerns**
   - PV‑1 designs and implements this in Praeparo upstream.
   - This repo documents requirements and local examples, but does not own the core feature.

Out of scope for PV‑1:

- IDE generators, cookiecutters, or project scaffolding beyond a minimal template.
- Multi‑slide “packs” of Python visuals (those can come later by composing these modules in pack configs).

## 3. Proposed Architecture

### 3.1 Visual base class contract

Instead of asking developers to remember free function names, PV‑1 introduces a small **class-based contract** built on top of Praeparo’s `VisualPipelineDefinitionBase`. Upstream in Praeparo, we define something like:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Iterable, Sequence, Type, TypeVar

from praeparo.models import BaseVisualConfig
from praeparo.pipeline import ExecutionContext, VisualPipelineDefinitionBase
from praeparo.pipeline.outputs import OutputTarget, PipelineOutputArtifact
from praeparo.visuals.context_models import VisualContextModel


DatasetT = TypeVar("DatasetT")
ContextT = TypeVar("ContextT", bound=VisualContextModel)


@dataclass
class PythonVisualBase(
    VisualPipelineDefinitionBase[None, DatasetT, BaseVisualConfig, ContextT],
    Generic[DatasetT, ContextT],
):
    """Base class for Python-backed visuals.

    Subclasses only implement build_dataset + render; schema is a no-op.
    """

    context_model: Type[ContextT]
    name: str | None = None

    def build_schema(self, pipeline, config, context: ExecutionContext[ContextT]):
        from praeparo.pipeline.registry import SchemaArtifact
        return SchemaArtifact(schema=None)

    def build_dataset(
        self,
        pipeline,
        config,
        schema_artifact,
        context: ExecutionContext[ContextT],
    ) -> DatasetT:
        raise NotImplementedError

    def render(
        self,
        pipeline,
        config,
        schema_artifact,
        dataset_artifact,
        context: ExecutionContext[ContextT],
        outputs: Sequence[OutputTarget],
    ) -> list[PipelineOutputArtifact]:
        raise NotImplementedError
```

Key points:

- Developers import `PythonVisualBase` and **subclass it** rather than memorising free function names.
- The base class hides schema plumbing by default (`schema=None`), so Python visuals focus on dataset + render.
- `context_model` expresses the typed context for the visual; Praeparo can use this when building `ExecutionContext.visual_context`.

#### 3.1.1 Minimal developer example

With `PythonVisualBase` in place, a developer’s file can look like:

```python
# my_python_visual.py
from __future__ import annotations

from typing import Iterable, List, Sequence

import matplotlib.pyplot as plt

from praeparo.pipeline import ExecutionContext, PipelineOutputArtifact
from praeparo.pipeline.outputs import OutputKind, OutputTarget
from praeparo.visuals.context_models import VisualContextModel
from praeparo.pipeline.python_visual import PythonVisualBase


class MyContext(VisualContextModel):
    report_title: str | None = None


class MyVisual(PythonVisualBase[List[int], MyContext]):
    context_model = MyContext
    name = "My Simple Python Visual"

    def build_dataset(
        self,
        pipeline,
        config,
        schema_artifact,
        context: ExecutionContext[MyContext],
    ) -> List[int]:
        # Real code would query metrics or another datasource.
        return [10, 20, 15, 30]

    def render(
        self,
        pipeline,
        config,
        schema_artifact,
        dataset_artifact,
        context: ExecutionContext[MyContext],
        outputs: Sequence[OutputTarget],
    ) -> list[PipelineOutputArtifact]:
        png_targets = [o for o in outputs if o.kind == OutputKind.PNG]
        if not png_targets:
            return []

        target = png_targets[0]
        target.path.parent.mkdir(parents=True, exist_ok=True)

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(range(len(dataset_artifact.dataset)), dataset_artifact.dataset)
        ax.set_title(context.visual_context.report_title or self.name or "Python Visual")

        dpi = int(96 * (target.scale or 2.0))
        fig.tight_layout()
        fig.savefig(target.path, dpi=dpi)
        plt.close(fig)

        return [PipelineOutputArtifact(kind=OutputKind.PNG, path=target.path)]
```

The PV‑1 CLI can then discover `MyVisual`, turn it into a `VisualPipelineDefinition` via `to_definition()`, and execute it like any other visual.

#### 3.1.2 Metrics-aware example using metrics_root

A slightly richer example can lean on `metrics_root` and Praeparo’s metric catalogue to build a dataset before rendering:

```python
# metrics_aware_visual.py
from __future__ import annotations

from typing import Dict, Sequence

import matplotlib.pyplot as plt

from praeparo.metrics import load_metric_catalog
from praeparo.pipeline import ExecutionContext, PipelineOutputArtifact
from praeparo.pipeline.outputs import OutputKind, OutputTarget
from praeparo.visuals.context_models import VisualContextModel
from praeparo.pipeline.python_visual import PythonVisualBase


class MetricsContext(VisualContextModel):
    """Context with access to metrics_root and a list of metric keys."""

    metric_keys: Sequence[str] | None = None
    report_title: str | None = None


class MetricsVisual(PythonVisualBase[Dict[str, float], MetricsContext]):
    context_model = MetricsContext
    name = "Metric Snapshot Visual"

    def build_dataset(self, pipeline, config, schema_artifact, context: ExecutionContext[MetricsContext]) -> Dict[str, float]:
        """Resolve a small set of metrics from the catalogue and attach dummy values."""

        metrics_root = context.visual_context.metrics_root
        catalog = load_metric_catalog([str(metrics_root)])

        keys = list(context.visual_context.metric_keys or [])
        if not keys:
            keys = ["settlements.total", "settlements.within_3d"]

        data: Dict[str, float] = {}
        for key in keys:
            if key in catalog.metrics:
                # Real code would use MetricDaxBuilder + dataset builders here.
                data[key] = 100.0
        return data

    def render(self, pipeline, config, schema_artifact, dataset_artifact, context: ExecutionContext[MetricsContext], outputs: Sequence[OutputTarget]) -> list[PipelineOutputArtifact]:
        """Render a simple bar chart of metric values."""

        png_targets = [o for o in outputs if o.kind == OutputKind.PNG]
        if not png_targets:
            return []

        target = png_targets[0]
        target.path.parent.mkdir(parents=True, exist_ok=True)

        labels = list(dataset_artifact.dataset.keys())
        values = list(dataset_artifact.dataset.values())

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(labels, values)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_title(context.visual_context.report_title or self.name or "Metrics Visual")

        dpi = int(96 * (target.scale or 2.0))
        fig.tight_layout()
        fig.savefig(target.path, dpi=dpi)
        plt.close(fig)

        return [PipelineOutputArtifact(kind=OutputKind.PNG, path=target.path)]
```

This pattern shows how Python visuals can:

- Read `metrics_root` from the typed context model.
- Use Praeparo’s metric catalogue (and later dataset builders) to drive the dataset.
- Still render via any Python charting library while benefiting from Praeparo’s CLI, context, and output handling.

### 3.2 CLI entrypoint and command shape

Introduce a new top‑level command family in Praeparo’s CLI dedicated to Python visuals. For example:

```bash
praeparo python-visual run path/to/visual.py \
  --metrics-root registry/metrics \
  --artefact-dir .tmp/python_visuals/example \
  --output-png .tmp/python_visuals/example/example.png \
  --seed 42 \
  --scenario baseline \
  --context path/to/context.yaml
```

Design choices:

- **Separate command namespace** (PV‑1):
  - Command: `python-visual run` (and optionally `python-visual artifacts` later).
  - This avoids overloading the existing `visual` registry, which assumes YAML + `type`.
  - Implementation can still use `VisualPipeline` internally, but without requiring a visual registration.
- Optional PV‑2 extension:
  - Allow `praeparo visual run python path/to/visual.py` by:
    - Treating `python` as a special “type” that bypasses YAML loading.
    - Resolving the Python module from the path and using the same module contract.

CLI responsibilities:

- Resolve the module from the given path:
  - Support both `path/to/visual.py` and `package.module:attr` forms later.
- Import it in a controlled way (e.g. using `importlib`):
  - Discover the first subclass of `PythonVisualBase[...]` in the module (or a named one if the CLI grows a `--visual-class` selector).
  - Fail with clear errors if no suitable subclass is found.
- Build a `VisualContextModel`:
  - Read `visual_class.context_model` from the subclass and use that as the context model.
  - Fall back to `VisualContextModel` only if the subclass explicitly opts into that.
- Construct `ExecutionContext` and `PipelineOptions` similarly to existing `visual` commands:
  - Honour `--metrics-root`, `--seed`, `--scenario`, `--data-mode`, `--context`, `--calculate`, `--define`, `--grain`, etc., where meaningful.
- Construct `OutputTarget` instances from CLI flags:
  - For PV‑1, support at least:
    - `--output-png PATH`
    - `--output-html PATH`
    - `--artefact-dir PATH` (for any extra artefacts the visual may write).

### 3.3 Execution flow

PV‑1 can model the flow closely on the existing visual pipeline but with a simplified orchestration:

1. **Load module**:
   - Import the module.
   - Discover a `PythonVisualBase[...]` subclass (e.g. `MyVisual`) and instantiate it.
2. **Build context**:
   - Collect metadata from CLI (`_prepare_context_payload`, etc.).
   - Instantiate the selected `VisualContextModel`.
   - Construct `ExecutionContext[ContextT]` with:
     - `options: PipelineOptions` (data_mode, artefact paths, build_artifacts_dir, etc.).
     - `visual_context: ContextT`.
3. **Plan and build dataset**:
   - Use `visual.to_definition()` to obtain a `VisualPipelineDefinition`.
   - Build a `VisualPipeline` just as for YAML-based visuals and call its dataset builder stage (which forwards into `PythonVisualBase.build_dataset`).
   - Optionally support a helper in Praeparo that the visual can call to:
     - Use `MetricDatasetBuilder` and DAX planners.
     - Or skip DAX entirely for non‑Power BI data sources.
4. **Render outputs**:
   - Build the `outputs: Sequence[OutputTarget]` from CLI arguments.
   - Invoke the pipeline’s render stage, which forwards into `PythonVisualBase.render`.
   - Collect and summarise `PipelineOutputArtifact` for the CLI (print what was written).

### 3.4 Relationship to VisualPipelineDefinition

In PV‑1, we avoid forcing Python modules to implement the full `VisualPipelineDefinitionBase` (schema + dataset + render). Instead:

- Python modules **only define dataset + render**, not schema:
  - This keeps the contract small and focused on “produce data” and “produce artefacts”.
  - If schema is needed (e.g. to describe metadata), the visual can treat it as part of the dataset or write it directly to artefacts.

Internally, Praeparo could offer an adapter for future reuse:

- A small helper that wraps a Python visual module into a synthetic `VisualPipelineDefinition` when needed (for packs or more advanced integration), but PV‑1 does not require that.

### 3.5 Metrics, datasources, and DAX

Python visuals should be able to **opt‑in** to existing Praeparo capabilities:

- Provide helpers (in Praeparo) that can be imported from the module:
  - For example:

    ```python
    from praeparo.visuals.python import build_metric_dataset

    def build_dataset(context: ExecutionContext[PythonVisualContext]) -> MetricDataset:
      return build_metric_dataset(
        metrics_root=context.visual_context.metrics_root,
        # e.g. supply a list of metric keys + filters
        metrics=["settlements.total", "settlements.within_3d"],
        context=context,
      )
    ```

- PV‑1 should:
  - Define the module contract and CLI wiring.
  - Expose minimal, generic helpers for DAX‑backed datasets.
  - Leave richer helpers (e.g. governance/matrix higher‑level adapters) for future work.

## 4. Phased Implementation

### Phase PV‑1 – Core Python visual CLI

- Add a new `python-visual` command group to Praeparo’s CLI:
  - `python-visual run` with flags:
    - `PATH` to the Python module file.
    - `--artefact-dir`, `--output-png`, `--output-html`, plus selected context flags.
  - Reuse `_prepare_context_payload`, `_instantiate_visual_context`, and `_build_pipeline_options` where sensible.
-- Implement module loading and validation:
  - Use `importlib` to import from a file path.
  - Discover a `PythonVisualBase[...]` subclass, validate that it implements `build_dataset` and `render`, and inspect its `context_model`.
-- Implement execution:
  - Build `ExecutionContext`, `OutputTarget` list, and a `VisualPipelineDefinition` via `visual_instance.to_definition()`.
  - Execute the pipeline as usual and print a summary of outputs (mirroring the existing `_summarise_outputs` behaviour).
- Documentation:
  - Add a dedicated section to Praeparo’s docs (upstream) explaining:
    - The Python visual module contract.
    - CLI usage.
    - A minimal example that uses a simple in‑memory dataset and Matplotlib/Plotly.

### Phase PV‑2 – Integration with visual/pack ecosystem

- Allow Python visuals to participate in:
  - Packs, via a new `type: python_visual` slide descriptor that references the module path.
  - Potentially, the existing `visual` CLI surface as a “type”:
    - For example: `praeparo visual run python path/to/visual.py`.
- Provide a lightweight adapter to wrap a Python visual module as a `VisualPipelineDefinition`:
  - So packs can treat Python visuals like any other type in their pipelines.

### Phase PV‑3 – Ergonomics & templates

- Add project templates for Python visuals:
  - Cookiecutter or `praeparo python-visual init` to scaffold a starter file.
- Provide richer helper functions:
  - For example:
    - Helpers that mirror governance matrix planning but for custom dataset/visual shapes.
- Expand docs with additional recipes:
  - Simple metric table visual.
  - Combined Power BI + custom overlay visual.

## 5. Validation

Once PV‑1 is implemented upstream in Praeparo:

- Add unit/integration tests in Praeparo:
  - Test a minimal Python visual module that:
    - Returns a simple dataset (e.g. list of rows).
    - Writes a PNG/HTML to the requested paths.
  - Validate that:
    - CLI flags (`--metrics-root`, `--seed`, `--scenario`, `--context`) reach the `ExecutionContext`.
    - Errors in the module (missing functions, exceptions) surface as clear CLI messages.
- Add at least one **downstream usage example**:
  - A tiny Python visual under a consumer project `examples/` folder or docs snippet that:
    - Uses Praeparo’s metric catalogue to build a small dataset.
    - Renders a PNG with a small chart or scorecard view.
  - Capture the run command in the consumer project docs.

## 6. Out of Scope & Follow‑Ups

Out of scope for PV‑1:

- Auto‑registration of Python modules as named visual “types” in `praeparo.visuals.registry`.
- Rich schema contracts or auto‑documentation for Python visuals.
- Multi‑visual packs built entirely from Python modules (beyond PV‑2 integration hooks).

Potential follow‑ups:

- **Typed dataset contracts** – e.g. a small `PythonVisualDataset` protocol that encourages consistent use of schemas.
- **Tighter pack integration** – letting packs reference Python visuals alongside YAML ones, with shared context/filters.
- **Studio/editor support** – generating or editing Python visual modules from a UI, backed by this contract.
