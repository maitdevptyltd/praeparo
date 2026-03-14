from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image

from praeparo.cli import main as cli_main


def test_pack_cli_compare_slide_returns_non_zero_for_missing_baseline(tmp_path: Path, capsys) -> None:
    artefacts_dir = tmp_path / "artefacts"
    rendered_png = artefacts_dir / "slide-id-1.png"
    rendered_png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (20, 12), color=(20, 40, 60, 255)).save(rendered_png)

    manifest_path = artefacts_dir / "render.manifest.json"
    manifest_path.write_text(
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
                        "png_path": str(rendered_png.relative_to(tmp_path)),
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
                    "compare-slide",
                    str(artefacts_dir),
                    "--baseline-dir",
                    str(baseline_dir),
                ]
            )
    finally:
        os.chdir(cwd_before)

    assert exc.value.code == 1
    comparison = json.loads((artefacts_dir / "_comparisons" / "compare.manifest.json").read_text(encoding="utf-8"))
    assert comparison["failed_targets"] == 1
    assert comparison["comparisons"][0]["status"] == "missing_baseline"

    out = capsys.readouterr().out
    assert "[ok] Wrote comparison manifest to" in out
    assert "1 missing baseline" in out
