from __future__ import annotations

import builtins
from pathlib import Path
import sys
from typing import Any, Dict, Mapping, cast

import pytest

from praeparo.cli import main as cli_main
from praeparo.dax import DaxQueryPlan
from praeparo.models import BaseVisualConfig, PackConfig, PackSlide, PackVisualRef
from praeparo.pack import PackSlideResult
from praeparo.visuals.dax_compilers import DaxCompileArtifact, register_dax_compiler
from praeparo.pipeline import VisualExecutionResult
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
    assert ctx.metrics_root == Path("registry/metrics")
    assert ctx.seed == 42
    assert ctx.dax.calculate == ("Metric = 1",)
    assert ctx.dax.define == ("MEASURE Demo[Value] = 1",)
    context_payload = cast(Mapping[str, Any], captured_metadata.get("context"))
    assert context_payload.get("calculate") == ["Metric = 1"]
    assert context_payload.get("define") == ["MEASURE Demo[Value] = 1"]
    if hasattr(builtins, "__praeparo_test_plugin_loaded__"):
        delattr(builtins, "__praeparo_test_plugin_loaded__")


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
        output_root,
        max_powerbi_concurrency=None,
        base_options,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
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
    assert artefacts_dir.as_posix() in out
    assert captured["path"] == pack_path
    assert captured["output_root"] == artefacts_dir
    assert captured["only_slides"] == ("slide-id-1",)


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
