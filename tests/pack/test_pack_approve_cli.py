from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image

from praeparo.cli import main as cli_main


def test_pack_cli_approve_slide_promotes_png_and_updates_manifest(tmp_path: Path, capsys) -> None:
    artefacts_dir = tmp_path / "artefacts"
    rendered_png = artefacts_dir / "slide-id-1.png"
    rendered_png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (20, 12), color=(20, 40, 60, 255)).save(rendered_png)

    (artefacts_dir / "render.manifest.json").write_text(
        json.dumps(
            {
                "kind": "pack_render_slide",
                "pack_path": "registry/customers/test/test_pack.yaml",
                "artefact_root": "artefacts",
                "rendered_targets": [
                    {
                        "slide_slug": "slide-id-1",
                        "target_slug": "slide-id-1",
                        "artifact_label": "slide-id-1",
                        "png_path": "artefacts/slide-id-1.png",
                        "artefacts": [],
                    }
                ],
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
                    "pack",
                    "approve-slide",
                    str(artefacts_dir),
                    "--baseline-dir",
                    str(baseline_dir),
                    "--slide",
                    "slide-id-1",
                    "--note",
                    "Approve latest focused render.",
                    "--project-root",
                    str(tmp_path),
                ]
            )
    finally:
        os.chdir(cwd_before)

    assert exc.value.code == 0
    assert (baseline_dir / "slide-id-1.png").exists()

    payload = json.loads((baseline_dir / "baseline.manifest.json").read_text(encoding="utf-8"))
    assert payload["targets"] == ["slide-id-1"]
    assert payload["target_details"][0]["note"] == "Approve latest focused render."

    out = capsys.readouterr().out
    assert "[ok] Wrote baseline manifest to baselines/baseline.manifest.json" in out
    assert "[ok] Approved 1 target(s) into baselines: slide-id-1" in out
