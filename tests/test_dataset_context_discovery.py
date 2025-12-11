from __future__ import annotations

from pathlib import Path

from praeparo.datasets.context import discover_dataset_context
from praeparo.pipeline import ExecutionContext, PipelineOptions
from praeparo.visuals.context_models import VisualContextModel
from praeparo.visuals.dax_context import DAXContextModel


def test_discover_dataset_context_prefers_visual_context(tmp_path: Path) -> None:
    metrics_root = (tmp_path / "metrics").resolve()
    metrics_root.mkdir()

    visual_context = VisualContextModel(
        metrics_root=metrics_root,
        ignore_placeholders=True,
        dax=DAXContextModel(
            calculate=("CTX_FILTER",),
            define=("DEFINE MEASURE Ctx[Value] = 1",),
        ),
    )

    options = PipelineOptions()
    options.data.provider_case_overrides = {"gov": "mock"}

    execution = ExecutionContext(
        project_root=tmp_path,
        case_key="gov",
        options=options,
        visual_context=visual_context,
    )

    dataset_context = discover_dataset_context(execution)

    assert dataset_context.project_root == tmp_path.resolve()
    assert dataset_context.metrics_root == metrics_root
    assert dataset_context.global_filters == ("CTX_FILTER",)
    assert dataset_context.define_blocks == ("DEFINE MEASURE Ctx[Value] = 1",)
    assert dataset_context.ignore_placeholders is True
    assert dataset_context.use_mock is True


def test_discover_dataset_context_without_visual_context(tmp_path: Path) -> None:
    metrics_root = (tmp_path / "fallback").resolve()
    options = PipelineOptions()

    execution = ExecutionContext(
        project_root=tmp_path,
        options=options,
        visual_context=None,
    )

    dataset_context = discover_dataset_context(execution, default_metrics_root=metrics_root)

    assert dataset_context.metrics_root == metrics_root
    assert dataset_context.ignore_placeholders is False
    assert dataset_context.global_filters == ()
    assert dataset_context.define_blocks == ()
    assert dataset_context.use_mock is False


def test_discover_dataset_context_uses_metadata_ignore_placeholders(tmp_path: Path) -> None:
    metrics_root = (tmp_path / "metrics").resolve()
    metrics_root.mkdir()

    options = PipelineOptions()
    options.metadata["ignore_placeholders"] = True

    execution = ExecutionContext(
        project_root=tmp_path,
        options=options,
        visual_context=None,
    )

    dataset_context = discover_dataset_context(execution, default_metrics_root=metrics_root)

    assert dataset_context.metrics_root == metrics_root
    assert dataset_context.ignore_placeholders is True
