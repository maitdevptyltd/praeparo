from __future__ import annotations

from pathlib import Path

import pytest

from praeparo.cli import main as cli_main


FIXTURE_VISUAL = Path(__file__).parent / "fixtures" / "python_visuals" / "simple_visual.py"


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
