from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from praeparo.cli import main as cli_main
from praeparo import cli


FIXTURE_VISUAL = Path(__file__).parent / "fixtures" / "python_visuals" / "simple_visual.py"


def _copy_fixture(module_path: Path) -> Path:
    target = module_path
    target.write_text(FIXTURE_VISUAL.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_python_visual_cli_run_writes_outputs(tmp_path) -> None:
    png_path = tmp_path / "out.png"
    html_path = tmp_path / "out.html"

    argv = [
        "python-visual",
        "run",
        str(FIXTURE_VISUAL),
        "--output-png",
        str(png_path),
        "--output-html",
        str(html_path),
        "--meta",
        "report_title=Demo",
    ]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert png_path.exists()
    assert html_path.exists()
    assert "<h1>Demo</h1>" in html_path.read_text(encoding="utf-8")


def test_python_visual_cli_errors_when_no_visual_found(tmp_path, capsys) -> None:
    module_path = tmp_path / "no_visual.py"
    module_path.write_text("from __future__ import annotations\n\nVALUE = 1\n", encoding="utf-8")

    argv = ["python-visual", "run", str(module_path)]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 2
    assert "No PythonVisualBase subclasses" in capsys.readouterr().err


def test_python_visual_cli_surfaces_import_errors(tmp_path, capsys) -> None:
    module_path = tmp_path / "broken_visual.py"
    module_path.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    argv = ["python-visual", "run", str(module_path)]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 2
    assert "Failed to import Python visual module" in capsys.readouterr().err


def test_python_visual_cli_dest_png_sets_defaults(tmp_path, monkeypatch) -> None:
    module_path = _copy_fixture(tmp_path / "simple_visual.py")
    dest = tmp_path / "render.png"
    expected_artefacts = dest.parent / dest.stem / "_artifacts"
    expected_html = expected_artefacts / f"{module_path.stem}.html"

    captured = {}

    original_build_options: Callable = cli._build_pipeline_options

    def _spy_build_options(args, metadata, include_outputs):
        options = original_build_options(args, metadata, include_outputs=include_outputs)
        captured["options"] = options
        return options

    monkeypatch.setattr(cli, "_build_pipeline_options", _spy_build_options)

    argv = ["python-visual", "run", str(module_path), str(dest), "--meta", "report_title=Demo"]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert dest.exists()
    assert expected_html.exists()
    options = captured["options"]
    assert options.artefact_dir == expected_artefacts
    assert any(target.path == dest for target in options.outputs)
    assert any(target.path == expected_html for target in options.outputs)


def test_python_visual_cli_dest_directory_defaults(tmp_path, monkeypatch) -> None:
    module_path = _copy_fixture(tmp_path / "simple_visual.py")
    dest_dir = tmp_path / "outputs"
    slug = "simple_visual"
    expected_png = dest_dir / f"{slug}.png"
    expected_html = dest_dir / f"{slug}.html"
    expected_artefacts = dest_dir / "_artifacts"

    captured = {}

    original_build_options: Callable = cli._build_pipeline_options

    def _spy_build_options(args, metadata, include_outputs):
        options = original_build_options(args, metadata, include_outputs=include_outputs)
        captured["options"] = options
        return options

    monkeypatch.setattr(cli, "_build_pipeline_options", _spy_build_options)

    argv = ["python-visual", "run", str(module_path), str(dest_dir), "--meta", "report_title=Snapshot"]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert expected_png.exists()
    assert expected_html.exists()
    options = captured["options"]
    assert options.artefact_dir == expected_artefacts
    assert any(target.path == expected_png for target in options.outputs)
    assert any(target.path == expected_html for target in options.outputs)


def test_bare_py_invocation_auto_detects_python_visual(tmp_path) -> None:
    module_path = _copy_fixture(tmp_path / "simple_visual.py")
    dest = tmp_path / "auto.png"
    artefact_dir = dest.parent / dest.stem / "_artifacts"
    expected_html = artefact_dir / f"{module_path.stem}.html"

    argv = [str(module_path), str(dest)]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert dest.exists()
    assert expected_html.exists()


def test_visual_run_py_invocation_redirects(tmp_path) -> None:
    module_path = _copy_fixture(tmp_path / "simple_visual.py")
    dest = tmp_path / "redirect.png"
    artefact_dir = dest.parent / dest.stem / "_artifacts"
    expected_html = artefact_dir / f"{module_path.stem}.html"

    argv = ["visual", "run", str(module_path), str(dest)]

    with pytest.raises(SystemExit) as exc:
        cli_main(argv)

    assert exc.value.code == 0
    assert dest.exists()
    assert expected_html.exists()
