from __future__ import annotations

from pathlib import Path

from praeparo.datasets.context import MetricDatasetBuilderContext, discover_dataset_context
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


def test_builder_context_discovers_registry_datasources_root(tmp_path: Path) -> None:
    registry_datasources = tmp_path / "registry" / "datasources"
    registry_datasources.mkdir(parents=True)
    registry_datasources.joinpath("default.yaml").write_text("type: powerbi\n", encoding="utf-8")

    context = MetricDatasetBuilderContext.discover(project_root=tmp_path)

    assert context.datasources_root == registry_datasources.resolve()
    assert context.datasource_file == (registry_datasources / "default.yaml").resolve()
    assert context.default_datasource == str((registry_datasources / "default.yaml").resolve())


def test_builder_context_prefers_legacy_datasources_root_when_both_exist(tmp_path: Path) -> None:
    legacy_datasources = tmp_path / "datasources"
    registry_datasources = tmp_path / "registry" / "datasources"
    legacy_datasources.mkdir(parents=True)
    registry_datasources.mkdir(parents=True)
    legacy_datasources.joinpath("default.yaml").write_text("type: powerbi\n", encoding="utf-8")
    registry_datasources.joinpath("default.yaml").write_text("type: powerbi\n", encoding="utf-8")

    context = MetricDatasetBuilderContext.discover(project_root=tmp_path)

    assert context.datasources_root == legacy_datasources.resolve()
    assert context.datasource_file == (legacy_datasources / "default.yaml").resolve()
