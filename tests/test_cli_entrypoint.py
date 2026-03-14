from __future__ import annotations

import builtins
import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Mapping, cast

import plotly.graph_objects as go
import pytest

import praeparo.cli as cli
from praeparo.cli import main as cli_main
from praeparo.dax import DaxQueryPlan
from praeparo.models import BaseVisualConfig, PackConfig, PackSlide, PackVisualRef
from praeparo.pack import PackPowerBIFailure, PackSlideResult
from praeparo.visuals.dax_compilers import DaxCompileArtifact, register_dax_compiler
from praeparo.visuals.dax import slugify
from praeparo.pipeline import PipelineOptions, VisualExecutionResult
from praeparo.pipeline.outputs import OutputKind, PipelineOutputArtifact
from praeparo.visuals import (
    VisualCLIArgument,
    VisualCLIOptions,
    register_visual_type,
)
from praeparo.visuals import VisualContextModel


class _DummyConfig(BaseVisualConfig):
    type: str = "cli_example"

class _DummyContext(VisualContextModel):
    sample: str | None = None


def _dummy_loader(path: Path, payload, stack):  # pragma: no cover - loader patched in tests
    return _DummyConfig()


@pytest.fixture(scope="module", autouse=True)
def _register_cli_example() -> None:
    register_visual_type(
        "cli_example",
        _dummy_loader,
        overwrite=True,
        cli=VisualCLIOptions(
            arguments=(
                VisualCLIArgument("--sample", help="Sample metadata input.", metadata_key="sample"),
            ),
        ),
        context_model=_DummyContext,
    )
    register_dax_compiler(
        "cli_example",
        lambda visual, context, args: [
            DaxCompileArtifact(
                path=(
                    context.options.artefact_dir
                    or (context.config_path or Path("visual.yaml")).parent
                )
                / f"{(context.config_path or Path('visual.yaml')).stem}.dax",
                plan=DaxQueryPlan(statement="EVALUATE {}", rows=(), values=()),
                statement="EVALUATE {}",
            )
        ],
        overwrite=True,
    )


def test_cli_run_populates_metadata(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "visual.yaml"
    config_path.write_text("type: cli_example\n", encoding="utf-8")

    captured_metadata: Dict[str, object] = {}
    captured_options: list = []
    captured_contexts: list = []

    def fake_load_visual_config(path: Path):
        assert path == config_path
        return _DummyConfig()

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

        def execute(self, visual, context):
            captured_metadata.update(context.options.metadata)
            captured_options.append(context.options)
            captured_contexts.append(context.visual_context)
            result = VisualExecutionResult(
                config=visual,
                outputs=[
                    PipelineOutputArtifact(kind=OutputKind.HTML, path=tmp_path / "result.html"),
                ],
            )
            result.schema_path = tmp_path / "schema.json"
            result.dataset_path = tmp_path / "data.json"
            return result

    monkeypatch.setattr("praeparo.cli.load_visual_config", fake_load_visual_config)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_module_name = "cli_test_plugin"
    (plugin_dir / f"{plugin_module_name}.py").write_text(
        "import builtins\n"
        "builtins.__praeparo_test_plugin_loaded__ = True\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(plugin_dir))

    argv = [
        "visual",
        "run",
        "cli_example",
        str(config_path),
        "--plugin",
        plugin_module_name,
        "--sample",
        "example",
        "--meta",
        "flag=true",
        "--calculate",
        "Metric = 1",
        "--define",
        "MEASURE Demo[Value] = 1",
        "--output-html",
        str(tmp_path / "custom.html"),
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    sys.path.pop(0)
    assert captured_metadata["sample"] == "example"
    assert captured_metadata["flag"] is True
    assert captured_metadata["data_mode"] == "mock"
    assert "context" in captured_metadata
    assert captured_options
    options = captured_options[0]
    assert options.data.datasource_override is None
    assert options.data.provider_key == "mock"
    assert options.metadata["data_mode"] == "mock"
    assert captured_contexts
    ctx = captured_contexts[0]
    assert isinstance(ctx, _DummyContext)
    assert ctx.sample == "example"
    assert ctx.metrics_root == Path("registry/metrics").expanduser().resolve(strict=False)
    assert ctx.seed == 42
    assert ctx.dax.calculate == ("Metric = 1",)
    assert ctx.dax.define == ("MEASURE Demo[Value] = 1",)
    context_payload = cast(Mapping[str, Any], captured_metadata.get("context"))
    assert context_payload.get("calculate") == ["Metric = 1"]
    assert context_payload.get("define") == ["MEASURE Demo[Value] = 1"]
    if hasattr(builtins, "__praeparo_test_plugin_loaded__"):
        delattr(builtins, "__praeparo_test_plugin_loaded__")


def test_yaml_visual_without_typed_context_defaults_metrics_root_to_cwd(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "registry" / "metrics").mkdir(parents=True)

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "visual.yaml"
    config_path.write_text("type: dummy_noctx\n", encoding="utf-8")

    captured: Dict[str, object] = {}

    def dummy_loader(path: Path, payload, stack):
        return BaseVisualConfig(type="dummy_noctx")

    from praeparo.pipeline.registry import (
        SchemaArtifact,
        DatasetArtifact,
        RenderOutcome,
        VisualPipelineDefinition,
        register_visual_pipeline,
    )

    def schema_builder(pipeline, config, context):
        assert context.dataset_context is not None
        captured["project_root"] = context.project_root
        captured["metrics_root"] = context.dataset_context.metrics_root
        return SchemaArtifact(value={})

    def dataset_builder(pipeline, config, schema_artifact, context):
        return DatasetArtifact(value={}, filename="data.json")

    def renderer(pipeline, config, schema_artifact, dataset_artifact, context, outputs):
        return RenderOutcome(outputs=[])

    register_visual_type("dummy_noctx", dummy_loader, overwrite=True, context_model=None)
    register_visual_pipeline(
        "dummy_noctx",
        VisualPipelineDefinition(
            schema_builder=schema_builder,
            dataset_builder=dataset_builder,
            renderer=renderer,
        ),
        overwrite=True,
    )

    dest_png = tmp_path / "out.png"
    argv = [
        "visual",
        "run",
        "dummy_noctx",
        str(config_path),
        str(dest_png),
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert captured["project_root"] == tmp_path.resolve()
    assert captured["metrics_root"] == (tmp_path / "registry" / "metrics").resolve()


def test_cli_run_accepts_pack_context(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "visual.yaml"
    config_path.write_text("type: cli_example\n", encoding="utf-8")

    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text(
        "\n".join(
            [
                "schema: ing-pack",
                "context:",
                "  lender_id: 201",
                "  month: 2025-10-01",
                "  customer: ING",
                "calculate:",
                "  lender: \"'dim_lender'[LenderId] = {{ lender_id }}\"",
                "slides: []",
            ]
        ),
        encoding="utf-8",
    )

    captured_metadata: Dict[str, object] = {}
    captured_contexts: list = []

    def fake_load_visual_config(path: Path):
        assert path == config_path
        return _DummyConfig()

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

        def execute(self, visual, context):
            captured_metadata.update(context.options.metadata)
            captured_contexts.append(context.visual_context)
            return VisualExecutionResult(
                config=visual,
                outputs=[PipelineOutputArtifact(kind=OutputKind.HTML, path=tmp_path / "out.html")],
            )

    monkeypatch.setattr("praeparo.cli.load_visual_config", fake_load_visual_config)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    argv = [
        "visual",
        "run",
        "cli_example",
        str(config_path),
        "--context",
        str(pack_path),
        "--artefact-dir",
        str(tmp_path / "artefacts"),
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert captured_contexts
    ctx = captured_contexts[0]
    assert ctx.dax.calculate == ("'dim_lender'[LenderId] = 201",)
    assert ctx.dax.define == ()

    context_payload = cast(Mapping[str, Any], captured_metadata.get("context"))
    assert context_payload["lender_id"] == 201
    assert str(context_payload["month"]) == "2025-10-01"
    assert context_payload["customer"] == "ING"
    assert context_payload["calculate"] == [{"lender": "'dim_lender'[LenderId] = 201"}]
    assert all("{{" not in item for item in ctx.dax.calculate)


def test_cli_run_prefers_last_named_calculate(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "visual.yaml"
    config_path.write_text("type: cli_example\n", encoding="utf-8")

    context_path = tmp_path / "context.yaml"
    context_path.write_text(
        "\n".join(
            [
                "calculate:",
                "  - lender: \"'dim_lender'[LenderId] = 201\"",
                "  - lender: \"'dim_lender'[LenderId] = 301\"",
            ]
        ),
        encoding="utf-8",
    )

    captured_metadata: Dict[str, object] = {}
    captured_contexts: list = []

    def fake_load_visual_config(path: Path):
        assert path == config_path
        return _DummyConfig()

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

        def execute(self, visual, context):
            captured_metadata.update(context.options.metadata)
            captured_contexts.append(context.visual_context)
            return VisualExecutionResult(
                config=visual,
                outputs=[PipelineOutputArtifact(kind=OutputKind.HTML, path=tmp_path / "out.html")],
            )

    monkeypatch.setattr("praeparo.cli.load_visual_config", fake_load_visual_config)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    argv = [
        "visual",
        "run",
        "cli_example",
        str(config_path),
        "--context",
        str(context_path),
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert captured_contexts
    ctx = captured_contexts[0]
    assert ctx.dax.calculate == ("'dim_lender'[LenderId] = 301",)
    context_payload = cast(Mapping[str, Any], captured_metadata.get("context"))
    assert context_payload["calculate"] == [{"lender": "'dim_lender'[LenderId] = 301"}]


def test_cli_run_prefers_last_context_file_for_named_calculate(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "visual.yaml"
    config_path.write_text("type: cli_example\n", encoding="utf-8")

    first_path = tmp_path / "first.yaml"
    first_path.write_text(
        "\n".join(["calculate:", "  lender: \"'dim_lender'[LenderId] = 201\""]) + "\n",
        encoding="utf-8",
    )
    second_path = tmp_path / "second.yaml"
    second_path.write_text(
        "\n".join(["calculate:", "  lender: \"'dim_lender'[LenderId] = 301\""]) + "\n",
        encoding="utf-8",
    )

    captured_contexts: list = []

    def fake_load_visual_config(path: Path):
        assert path == config_path
        return _DummyConfig()

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

        def execute(self, visual, context):
            captured_contexts.append(context.visual_context)
            return VisualExecutionResult(
                config=visual,
                outputs=[PipelineOutputArtifact(kind=OutputKind.HTML, path=tmp_path / "out.html")],
            )

    monkeypatch.setattr("praeparo.cli.load_visual_config", fake_load_visual_config)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    argv = [
        "visual",
        "run",
        "cli_example",
        str(config_path),
        "--context",
        str(first_path),
        "--context",
        str(second_path),
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert captured_contexts
    ctx = captured_contexts[0]
    assert ctx.dax.calculate == ("'dim_lender'[LenderId] = 301",)


def test_visual_defaults_to_mock_when_data_mode_unspecified() -> None:
    args = argparse.Namespace(
        data_mode=None,
        datasource=None,
        dataset_id=None,
        workspace_id=None,
        artefact_dir=None,
        print_dax=False,
        validate_define=False,
        sort_rows=False,
    )

    metadata = {"data_mode": "mock"}
    options = cli._build_pipeline_options(args, metadata, include_outputs=False)

    assert options.data.provider_key == "mock"
    assert options.data.datasource_override is None
    assert options.metadata["data_mode"] == "mock"


def test_cli_live_mode_defaults_datasource(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "visual.yaml"
    config_path.write_text("type: cli_example\n", encoding="utf-8")

    monkeypatch.setattr("praeparo.cli.load_visual_config", lambda path: _DummyConfig())

    captured_options: list = []

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

        def execute(self, visual, context):
            captured_options.append(context.options)
            return VisualExecutionResult(
                config=visual,
                outputs=[PipelineOutputArtifact(kind=OutputKind.HTML, path=tmp_path / "out.html")],
            )

    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    argv = [
        "visual",
        "run",
        "cli_example",
        str(config_path),
        "--data-mode",
        "live",
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert captured_options
    options = captured_options[0]
    assert options.data.datasource_override == "default"
    assert options.data.provider_key is None
    assert options.metadata["data_mode"] == "live"


def test_cli_dax_writes_output(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "visual.yaml"
    config_path.write_text("type: cli_example\n", encoding="utf-8")

    monkeypatch.setattr("praeparo.cli.load_visual_config", lambda path: _DummyConfig())

    artefact_dir = tmp_path / "out"
    argv = [
        "visual",
        "dax",
        "cli_example",
        str(config_path),
        "--artefact-dir",
        str(artefact_dir),
        "--grain",
        "'dim_calendar'[Month]",
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    output_path = artefact_dir / "visual.dax"
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == "EVALUATE {}"


def test_cli_normalises_legacy_invocation(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "legacy.yaml"
    config_path.write_text("type: cli_example\n", encoding="utf-8")

    monkeypatch.setattr("praeparo.cli.load_visual_config", lambda path: _DummyConfig())

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

        def execute(self, visual, context):
            return VisualExecutionResult(
                config=visual,
                outputs=[
                    PipelineOutputArtifact(kind=OutputKind.HTML, path=tmp_path / "legacy.html"),
                ],
            )

    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli_main([str(config_path)])

    assert exc.value.code == 0


def test_pack_cli_loads_plugin_module(monkeypatch, tmp_path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_module_name = "cli_pack_test_plugin"
    (plugin_dir / f"{plugin_module_name}.py").write_text(
        "import builtins\nbuiltins.__praeparo_pack_test_plugin_loaded__ = True\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(plugin_dir))

    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    def fake_load_pack_config(path: Path) -> PackConfig:
        assert path == pack_path
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    artefacts_dir = tmp_path / "artefacts"
    argv = [
        "pack",
        "run",
        str(pack_path),
        "--plugin",
        plugin_module_name,
        "--artefact-dir",
        str(artefacts_dir),
    ]

    try:
        with pytest.raises(SystemExit) as exc:
            cli_main(argv)
        assert exc.value.code == 0
        assert hasattr(builtins, "__praeparo_pack_test_plugin_loaded__")
    finally:
        if str(plugin_dir) in sys.path:
            sys.path.remove(str(plugin_dir))
        if hasattr(builtins, "__praeparo_pack_test_plugin_loaded__"):
            delattr(builtins, "__praeparo_pack_test_plugin_loaded__")


def test_pack_cli_run_invokes_runner(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        captured["path"] = path
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["output_root"] = output_root
        captured["only_slides"] = only_slides
        slide = pack.slides[0]
        result = VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[])
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=result,
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    artefacts_dir = tmp_path / "artefacts"
    argv = [
        "pack",
        "run",
        str(pack_path),
        "--artefact-dir",
        str(artefacts_dir),
        "--slides",
        "slide-id-1",
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "[ok] Wrote 1 PNG" in out
    assert "[ok] Pack run completed in" in out
    assert artefacts_dir.as_posix() in out
    assert captured["path"] == pack_path
    assert captured["output_root"] == artefacts_dir
    assert captured["only_slides"] == ("slide-id-1",)


def test_pack_cli_run_writes_render_manifest(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    def fake_load_pack_config(path: Path) -> PackConfig:
        assert path == pack_path
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        slide = pack.slides[0]
        slide_dir = output_root / "[01]_slide-id-1"
        slide_dir.mkdir(parents=True, exist_ok=True)
        schema_path = slide_dir / "schema.json"
        schema_path.write_text("{}", encoding="utf-8")
        extra_path = slide_dir / "extra.data.json"
        extra_path.write_text("{}", encoding="utf-8")

        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")

        result = VisualExecutionResult(
            config=BaseVisualConfig(type="powerbi"),
            outputs=[PipelineOutputArtifact(kind=OutputKind.SCHEMA, path=schema_path)],
        )
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=result,
                png_path=png_path,
                slide_index=1,
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="[01]_slide-id-1",
                artefact_dir=slide_dir,
                visual_type="powerbi",
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    artefacts_dir = tmp_path / "artefacts"
    with pytest.raises(SystemExit) as exc:
        cli_main(["pack", "run", str(pack_path), "--artefact-dir", str(artefacts_dir)])

    assert exc.value.code == 0
    manifest_path = artefacts_dir / "render.manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["kind"] == "pack_run"
    assert manifest["requested_slides"] == []
    assert manifest["rendered_targets"][0]["artifact_label"] == "[01]_slide-id-1"
    artefact_paths = {item["path"] for item in manifest["rendered_targets"][0]["artefacts"]}
    assert str(artefacts_dir / "[01]_slide-id-1" / "schema.json") in artefact_paths
    assert str(artefacts_dir / "[01]_slide-id-1" / "extra.data.json") in artefact_paths

    out = capsys.readouterr().out
    assert "[ok] Wrote render manifest to" in out


def test_pack_cli_render_slide_targets_requested_slides(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        assert path == pack_path
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["only_slides"] = only_slides
        captured["metadata"] = dict(base_options.metadata)

        slide = pack.slides[0]
        slide_dir = output_root / "[01]_slide-id-1"
        slide_dir.mkdir(parents=True, exist_ok=True)
        png_path = output_root / "slide-id-1.png"
        png_path.write_text("png", encoding="utf-8")
        result = VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[])
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=result,
                png_path=png_path,
                slide_index=1,
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="[01]_slide-id-1",
                artefact_dir=slide_dir,
                visual_type="powerbi",
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    artefacts_dir = tmp_path / "artefacts"
    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "render-slide",
                str(pack_path),
                "--artefact-dir",
                str(artefacts_dir),
                "--slide",
                "slide-id-1",
            ]
        )

    assert exc.value.code == 0
    assert captured["only_slides"] == ("slide-id-1",)
    assert "result_file" not in cast(dict[str, object], captured["metadata"])

    manifest = json.loads((artefacts_dir / "render.manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "pack_render_slide"
    assert manifest["requested_slides"] == ["slide-id-1"]

    out = capsys.readouterr().out
    assert "[ok] Wrote render manifest to" in out
    assert "[ok] Slide render completed in" in out


def test_pack_cli_run_accepts_context_file(monkeypatch, tmp_path, capsys) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    pack_path = tmp_path / "registry" / "packs" / "pack.yaml"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text("contents", encoding="utf-8")

    override_path = tmp_path / "overrides" / "orde.yaml"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(
        "\n".join(
            [
                "schema: orde-pack",
                "context:",
                "  lender_id: 178",
                "  customer: ORDE",
                "calculate:",
                "  lender: \"'dim_lender'[LenderId] = {{ lender_id }}\"",
                "slides: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        assert path == pack_path
        return PackConfig(
            schema="test-pack",
            context={"lender_id": 166, "customer": "Standard Lender"},
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["output_root"] = output_root
        captured["base_options"] = base_options
        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    artefacts_dir = tmp_path / "artefacts"
    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "run",
                str(pack_path),
                "--metrics-root",
                str(metrics_root),
                "--context",
                str(override_path),
                "--artefact-dir",
                str(artefacts_dir),
            ]
        )

    assert exc.value.code == 0
    assert captured["output_root"] == artefacts_dir
    base_options = cast(PipelineOptions, captured["base_options"])
    metadata = cast(Mapping[str, object], base_options.metadata)
    context_payload = cast(Mapping[str, Any], metadata["context"])
    assert context_payload["customer"] == "ORDE"
    assert context_payload["lender_id"] == 178
    assert context_payload["calculate"] == [{"lender": "'dim_lender'[LenderId] = 178"}]
    out = capsys.readouterr().out
    assert "[ok] Wrote 1 PNG" in out


def test_pack_cli_dest_templates_render_with_context_override(monkeypatch, tmp_path, capsys) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    pack_path = tmp_path / "registry" / "packs" / "pack.yaml"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text("contents", encoding="utf-8")
    dest = tmp_path / "out" / "customer={{ customer }}" / "governance"

    override_path = tmp_path / "overrides" / "orde.yaml"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(
        "\n".join(
            [
                "schema: orde-pack",
                "context:",
                "  customer: ORDE",
                "slides: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            context={"customer": "Standard Lender"},
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["output_root"] = output_root
        captured["base_options"] = base_options

        result_file = None
        if base_options and isinstance(base_options.metadata, Mapping):
            raw = base_options.metadata.get("result_file")
            if isinstance(raw, Path):
                result_file = raw
        if result_file is not None:
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text("pptx", encoding="utf-8")

        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "run",
                str(pack_path),
                str(dest),
                "--metrics-root",
                str(metrics_root),
                "--context",
                str(override_path),
            ]
        )

    assert exc.value.code == 0
    expected_dest = tmp_path / "out" / "customer=ORDE" / "governance"
    expected_artefacts = expected_dest / "_artifacts"
    assert captured["output_root"] == expected_artefacts
    base_options = cast(PipelineOptions, captured["base_options"])
    expected_result = expected_dest / f"{slugify(pack_path.stem)}_r01.pptx"
    assert base_options.metadata.get("result_file") == expected_result
    out = capsys.readouterr().out
    assert f"[ok] Wrote PPTX to {expected_result}" in out


def test_pack_cli_dest_directory_sets_defaults(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "ing governance pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")
    dest = tmp_path / "out" / "ing"

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["output_root"] = output_root
        captured["base_options"] = base_options

        result_file = None
        if base_options and isinstance(base_options.metadata, Mapping):
            raw = base_options.metadata.get("result_file")
            if isinstance(raw, Path):
                result_file = raw
        if result_file is not None:
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text("pptx", encoding="utf-8")

        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "run",
                str(pack_path),
                str(dest),
            ]
        )

    assert exc.value.code == 0
    artefact_dir = dest / "_artifacts"
    assert captured["output_root"] == artefact_dir
    base_options = cast(PipelineOptions, captured["base_options"])
    assert base_options is not None
    assert base_options.artefact_dir == artefact_dir
    expected_result = dest / f"{slugify(pack_path.stem)}_r01.pptx"
    assert base_options.metadata.get("result_file") == expected_result
    out = capsys.readouterr().out
    assert f"[ok] Wrote PPTX to {expected_result}" in out
    assert "[ok] Pack run completed in" in out
    assert artefact_dir.as_posix() in out


def test_pack_cli_dest_pptx_sets_result_and_artifacts(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "ing pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")
    dest = tmp_path / "out" / "ing_governance_2025-12.pptx"

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["output_root"] = output_root
        captured["base_options"] = base_options

        result_file = None
        if base_options and isinstance(base_options.metadata, Mapping):
            raw = base_options.metadata.get("result_file")
            if isinstance(raw, Path):
                result_file = raw
        if result_file is not None:
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text("pptx", encoding="utf-8")

        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "run",
                str(pack_path),
                str(dest),
            ]
        )

    assert exc.value.code == 0
    artefact_dir = dest.parent / dest.stem / "_artifacts"
    assert captured["output_root"] == artefact_dir
    base_options = cast(PipelineOptions, captured["base_options"])
    assert base_options is not None
    assert base_options.artefact_dir == artefact_dir
    expected_result = dest.parent / f"{slugify(pack_path.stem)}_r01.pptx"
    assert base_options.metadata.get("result_file") == expected_result
    out = capsys.readouterr().out
    assert f"[ok] Wrote PPTX to {expected_result}" in out
    assert "[ok] Pack run completed in" in out
    assert artefact_dir.as_posix() in out


def test_pack_cli_dest_allows_flag_overrides(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "ing pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")
    dest = tmp_path / "out" / "ing_governance_2025-12.pptx"
    explicit_artefact_dir = tmp_path / "custom" / "artefacts"
    explicit_result = tmp_path / "custom" / "ing.pptx"

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["output_root"] = output_root
        captured["base_options"] = base_options

        result_file = None
        if base_options and isinstance(base_options.metadata, Mapping):
            raw = base_options.metadata.get("result_file")
            if isinstance(raw, Path):
                result_file = raw
        if result_file is not None:
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text("pptx", encoding="utf-8")

        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "run",
                str(pack_path),
                str(dest),
                "--artefact-dir",
                str(explicit_artefact_dir),
                "--result-file",
                str(explicit_result),
            ]
        )

    assert exc.value.code == 0
    assert captured["output_root"] == explicit_artefact_dir
    base_options = cast(PipelineOptions, captured["base_options"])
    assert base_options is not None
    assert base_options.artefact_dir == explicit_artefact_dir
    assert base_options.metadata.get("result_file") == explicit_result
    out = capsys.readouterr().out
    assert f"[ok] Wrote PPTX to {explicit_result}" in out
    assert "[ok] Pack run completed in" in out
    assert explicit_artefact_dir.as_posix() in out


def test_pack_cli_dest_templates_render_with_registry_context(monkeypatch, tmp_path, capsys) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)
    context_root = tmp_path / "registry" / "context"
    context_root.mkdir(parents=True)
    (context_root / "month.yaml").write_text(
        'context:\n  month: "2025-11-01"\n',
        encoding="utf-8",
    )

    pack_path = tmp_path / "registry" / "customers" / "pack.yaml"
    pack_path.parent.mkdir(parents=True)
    pack_path.write_text("contents", encoding="utf-8")
    dest = tmp_path / "out" / "month={{ month }}" / "ing"

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["output_root"] = output_root
        captured["base_options"] = base_options

        result_file = None
        if base_options and isinstance(base_options.metadata, Mapping):
            raw = base_options.metadata.get("result_file")
            if isinstance(raw, Path):
                result_file = raw
        if result_file is not None:
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text("pptx", encoding="utf-8")

        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "run",
                str(pack_path),
                str(dest),
            ]
        )

    assert exc.value.code == 0
    rendered_dest = tmp_path / "out" / "month=2025-11-01" / "ing"
    artefact_dir = rendered_dest / "_artifacts"
    assert captured["output_root"] == artefact_dir
    base_options = cast(PipelineOptions, captured["base_options"])
    assert base_options is not None
    assert base_options.artefact_dir == artefact_dir
    expected_result = rendered_dest / f"{slugify(pack_path.stem)}_r01.pptx"
    assert base_options.metadata.get("result_file") == expected_result
    out = capsys.readouterr().out
    assert f"[ok] Wrote PPTX to {expected_result}" in out
    assert "[ok] Pack run completed in" in out


def test_pack_cli_revision_updates_default_result(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "ing governance pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")
    dest = tmp_path / "out" / "ing_governance_pack"

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            context={"month": "2025-12-01"},
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["output_root"] = output_root
        captured["base_options"] = base_options

        result_file = None
        if base_options and isinstance(base_options.metadata, Mapping):
            raw = base_options.metadata.get("result_file")
            if isinstance(raw, Path):
                result_file = raw
        if result_file is not None:
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text("pptx", encoding="utf-8")

        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "run",
                str(pack_path),
                str(dest),
                "--revision-strategy",
                "full",
            ]
        )

    assert exc.value.code == 0
    artefact_dir = dest / "_artifacts"
    assert captured["output_root"] == artefact_dir
    base_options = cast(PipelineOptions, captured["base_options"])
    assert base_options is not None
    expected_result = dest / f"{slugify(pack_path.stem)}_2025-12.pptx"
    assert base_options.metadata.get("result_file") == expected_result
    assert base_options.metadata.get("revision") == "2025-12"
    assert base_options.metadata.get("revision_minor") == 1
    out = capsys.readouterr().out
    assert f"[ok] Wrote PPTX to {expected_result}" in out
    assert "[ok] Pack run completed in" in out


def test_pack_cli_result_file_infers_artefact_dir(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")
    result_path = tmp_path / "out" / "ing_governance.pptx"

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["output_root"] = output_root
        captured["base_options"] = base_options

        result_file = None
        if base_options and isinstance(base_options.metadata, Mapping):
            raw = base_options.metadata.get("result_file")
            if isinstance(raw, Path):
                result_file = raw
        if result_file is not None:
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text("pptx", encoding="utf-8")

        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "run",
                str(pack_path),
                "--result-file",
                str(result_path),
            ]
        )

    assert exc.value.code == 0
    inferred_artefact = result_path.parent / result_path.stem / "_artifacts"
    assert captured["output_root"] == inferred_artefact
    base_options = cast(PipelineOptions, captured["base_options"])
    assert base_options is not None
    assert base_options.artefact_dir == inferred_artefact
    assert base_options.metadata.get("result_file") == result_path
    out = capsys.readouterr().out
    assert f"[ok] Wrote PPTX to {result_path}" in out
    assert "[ok] Pack run completed in" in out


def test_pack_run_defaults_to_live_data_mode(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["base_options"] = base_options
        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    artefacts_dir = tmp_path / "artefacts"
    argv = [
        "pack",
        "run",
        str(pack_path),
        "--artefact-dir",
        str(artefacts_dir),
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    base_options = cast(PipelineOptions, captured["base_options"])
    assert base_options.metadata["data_mode"] == "live"
    assert base_options.data.provider_key is None
    assert base_options.data.datasource_override == "default"
    out = capsys.readouterr().out
    assert "[ok] Wrote 1 PNG" in out


def test_pack_run_respects_mock_data_mode_override(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg,
        pack,
        *,
        project_root=None,
        output_root,
        max_powerbi_concurrency=None,
        base_options=None,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        evidence_only=False,
    ):
        captured["base_options"] = base_options
        slide = pack.slides[0]
        png_path = output_root / "slide-id-1.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_text("png", encoding="utf-8")
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=png_path,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    artefacts_dir = tmp_path / "artefacts"
    argv = [
        "pack",
        "run",
        str(pack_path),
        "--artefact-dir",
        str(artefacts_dir),
        "--data-mode",
        "mock",
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    base_options = cast(PipelineOptions, captured["base_options"])
    assert base_options.metadata["data_mode"] == "mock"
    assert base_options.data.provider_key == "mock"
    assert base_options.data.datasource_override is None
    out = capsys.readouterr().out
    assert "[ok] Wrote 1 PNG" in out


def test_pack_cli_run_warns_when_no_pngs(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide Zero", visual=PackVisualRef(ref="zero.yaml"))],
        )

    def fake_run_pack(*_, **__):
        slide = PackSlide(title="Slide Zero", visual=PackVisualRef(ref="zero.yaml"))
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path,
                result=VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[]),
                png_path=None,
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "run",
                str(pack_path),
                "--artefact-dir",
                str(tmp_path / "artefacts"),
            ]
        )

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "[warn] No PNG outputs were produced." in out


def test_pack_cli_pptx_only_restitch(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    captured: Dict[str, object] = {"run_pack_called": False, "restitch_called": False}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(*_, **__):
        captured["run_pack_called"] = True
        raise AssertionError("run_pack should not be invoked for --pptx-only")

    def fake_restitch(pack_path_arg, pack, *, output_root, result_file, base_options):
        captured["restitch_called"] = True
        captured["output_root"] = output_root
        captured["result_file"] = result_file
        captured["metadata"] = base_options.metadata

    def fake_allocate_revision(*args, **kwargs):
        captured["revision_strategy"] = kwargs.get("strategy")
        return None

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.restitch_pack_pptx", fake_restitch)
    monkeypatch.setattr("praeparo.cli.allocate_revision", fake_allocate_revision)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", lambda *_, **__: None)

    artefacts_dir = tmp_path / "artefacts"
    result_path = tmp_path / "deck" / "out.pptx"
    argv = [
        "pack",
        "run",
        str(pack_path),
        "--artefact-dir",
        str(artefacts_dir),
        "--result-file",
        str(result_path),
        "--pptx-only",
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert captured["restitch_called"] is True
    assert captured["run_pack_called"] is False
    assert captured["output_root"] == artefacts_dir
    assert captured["result_file"] == result_path
    metadata = cast(Mapping[str, object], captured["metadata"])
    assert metadata.get("result_file") == result_path
    assert captured["revision_strategy"] == "minor"
    out = capsys.readouterr().out
    assert "Restitched PPTX" in out


@pytest.mark.parametrize(
    "extra_args,expected_strategy",
    [
        ([], "full"),
        (["--slides", "one"], "minor"),
        (["--pptx-only", "--result-file", "out.pptx", "--artefact-dir", "artifacts"], "minor"),
    ],
)
def test_pack_cli_infers_revision_strategy(monkeypatch, tmp_path, extra_args, expected_strategy) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(*_, **__):
        return []

    def fake_restitch(*_, **__):
        return None

    def fake_allocate_revision(*args, **kwargs):
        captured["strategy"] = kwargs.get("strategy")
        return None

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.restitch_pack_pptx", fake_restitch)
    monkeypatch.setattr("praeparo.cli.allocate_revision", fake_allocate_revision)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", lambda *_, **__: None)

    argv = [
        "pack",
        "run",
        str(pack_path),
        "--artefact-dir",
        str(tmp_path / "artefacts"),
    ]

    for token in extra_args:
        if token == "out.pptx":
            argv.append(str(tmp_path / "out.pptx"))
            continue
        if token == "artifacts":
            argv.append(str(tmp_path / "pptx_artifacts"))
            continue
        argv.append(token)

    with pytest.raises(SystemExit):
        cli_main(argv)

    assert captured["strategy"] == expected_strategy


def test_pack_cli_allow_partial_prints_summary(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(schema="test-pack", slides=[])

    failure = PackPowerBIFailure(
        "1 Power BI slide(s) failed:\n  - slide_a (Slide A): RuntimeError: boom\nHint: re-run with --slides \"Slide A\" --max-pbi-concurrency 1 for focused debugging.",
        successful_results=[],
        failed_exports=[],
    )

    def fake_run_pack(*_, **__):
        raise failure

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", lambda *_, **__: None)

    argv = [
        "pack",
        "run",
        str(pack_path),
        "--artefact-dir",
        str(tmp_path / "artefacts"),
        "--allow-partial",
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Power BI slide(s) failed" in out
    assert "Slide A" in out
    assert "RuntimeError" in out


def test_pack_cli_without_partial_re_raises(monkeypatch, tmp_path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    def fake_load_pack_config(path: Path) -> PackConfig:
        return PackConfig(schema="test-pack", slides=[])

    failure = PackPowerBIFailure(
        "1 Power BI slide(s) failed:\n  - slide_a (Slide A): RuntimeError: boom\nHint: re-run with --slides \"Slide A\" --max-pbi-concurrency 1 for focused debugging.",
        successful_results=[],
        failed_exports=[],
    )

    def fake_run_pack(*_, **__):
        raise failure

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", lambda *_, **__: None)

    argv = [
        "pack",
        "run",
        str(pack_path),
        "--artefact-dir",
        str(tmp_path / "artefacts"),
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    # argparse surfaces RuntimeError via parser.error with exit code 2
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Power BI slide(s) failed" in err


def test_pack_cli_runs_python_visual(tmp_path: Path, monkeypatch) -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "python_visuals" / "pack_python_visual.py"
    visual_path = tmp_path / "visuals" / "pack_python_visual.py"
    visual_path.parent.mkdir(parents=True, exist_ok=True)
    visual_path.write_text(fixture_path.read_text(encoding="utf-8"), encoding="utf-8")

    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text(
        "\n".join(
            [
                "schema: test-pack",
                "context:",
                "  title: Demo",
                "slides:",
                "  - title: Python Visual Slide",
                "    template: full_page_image",
                f"    visual:",
                f"      ref: visuals/pack_python_visual.py",
            ]
        ),
        encoding="utf-8",
    )

    def fake_write_image(self, output_path, *, scale=2.0, **_: object) -> None:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"PNG")

    monkeypatch.setattr(go.Figure, "write_image", fake_write_image, raising=False)

    dest = tmp_path / "outputs"
    argv = ["pack", "run", str(pack_path), str(dest), "--data-mode", "mock"]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    artefact_dir = dest / "_artifacts"
    expected_png = artefact_dir / "[01]_python_visual_slide.png"
    assert expected_png.exists()
