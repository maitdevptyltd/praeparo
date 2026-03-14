from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image

from praeparo.cli import main as cli_main


def test_visual_cli_compare_returns_non_zero_for_missing_baseline(tmp_path: Path, capsys) -> None:
    artefacts_dir = tmp_path / "artefacts"
    rendered_png = artefacts_dir / "performance_dashboard.png"
    rendered_png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (20, 12), color=(20, 40, 60, 255)).save(rendered_png)

    manifest_path = artefacts_dir / "render.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "kind": "visual_inspect",
                "config_path": "registry/customers/test/visuals/performance_dashboard.yaml",
                "baseline_key": "performance_dashboard",
                "visual_type": "governance_matrix",
                "project_root": ".",
                "artefact_root": "artefacts",
                "png_path": "artefacts/performance_dashboard.png",
                "data_mode": "mock",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    baseline_dir = tmp_path / "baselines"

    cwd_before = Path.cwd()
    try:
        os.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc:
            cli_main(
                [
                    "visual",
                    "compare",
                    str(artefacts_dir),
                    "--baseline-dir",
                    str(baseline_dir),
                ]
            )
    finally:
        os.chdir(cwd_before)

    assert exc.value.code == 1
    comparison = json.loads((artefacts_dir / "_comparisons" / "compare.manifest.json").read_text(encoding="utf-8"))
    assert comparison["status"] == "missing_baseline"

    out = capsys.readouterr().out
    assert "[ok] Wrote comparison manifest to" in out
    assert "status=missing_baseline" in out
