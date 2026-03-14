from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image

from praeparo.cli import main as cli_main


def test_visual_cli_approve_promotes_png_and_updates_manifest(tmp_path: Path, capsys) -> None:
    artefacts_dir = tmp_path / "artefacts"
    rendered_png = artefacts_dir / "performance_dashboard.png"
    rendered_png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (20, 12), color=(20, 40, 60, 255)).save(rendered_png)

    (artefacts_dir / "render.manifest.json").write_text(
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
                    "approve",
                    str(artefacts_dir),
                    "--baseline-dir",
                    str(baseline_dir),
                    "--note",
                    "Approve current visual baseline.",
                ]
            )
    finally:
        os.chdir(cwd_before)

    assert exc.value.code == 0
    assert (baseline_dir / "performance_dashboard.png").exists()

    payload = json.loads((baseline_dir / "baseline.manifest.json").read_text(encoding="utf-8"))
    assert payload["baseline_key"] == "performance_dashboard"
    assert payload["approval_note"] == "Approve current visual baseline."

    out = capsys.readouterr().out
    assert "[ok] Wrote baseline manifest to baselines/baseline.manifest.json" in out
    assert "[ok] Approved visual baseline performance_dashboard into baselines" in out
