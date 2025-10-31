from __future__ import annotations

from pathlib import Path
import builtins
import sys
from typing import Dict

import pytest

from praeparo.cli import main as cli_main
from praeparo.pipeline import VisualExecutionResult
from praeparo.pipeline.outputs import OutputKind, PipelineOutputArtifact
from praeparo.visuals import (
    VisualCLIArgument,
    VisualCLIOptions,
    register_visual_type,
)


class _DummyConfig:
    type = "cli_example"


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
    )


def test_cli_run_populates_metadata(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "visual.yaml"
    config_path.write_text("type: cli_example\n", encoding="utf-8")

    captured_metadata: Dict[str, object] = {}

    def fake_load_visual_config(path: Path):
        assert path == config_path
        return _DummyConfig()

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

        def execute(self, visual, context):
            captured_metadata.update(context.options.metadata)
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
    assert captured_metadata["sample"] == "example"
    assert captured_metadata["flag"] is True
    context = captured_metadata["context"]
    assert context["calculate"] == ["Metric = 1"]
    assert context["define"] == ["MEASURE Demo[Value] = 1"]
    assert getattr(builtins, "__praeparo_test_plugin_loaded__", False) is True

    sys.path.pop(0)
    if hasattr(builtins, "__praeparo_test_plugin_loaded__"):
        delattr(builtins, "__praeparo_test_plugin_loaded__")


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
