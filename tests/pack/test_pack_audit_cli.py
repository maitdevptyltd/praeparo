from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image

from praeparo.cli import main as cli_main


def test_pack_cli_audit_writes_summary_and_inspections(tmp_path: Path, capsys) -> None:
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
                        "slide_index": 1,
                        "slide_id": "slide-id-1",
                        "slide_title": "Slide One",
                        "slide_template": "full_page_image",
                        "slide_slug": "slide-id-1",
                        "target_slug": "slide-id-1",
                        "artifact_label": "[01]_slide-id-1",
                        "visual_path": "registry/customers/test/visuals/slide_id_1.yaml",
                        "visual_type": "governance_matrix",
                        "png_path": "artefacts/slide-id-1.png",
                        "artefacts": []
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
                    "audit",
                    str(artefacts_dir),
                    "--baseline-dir",
                    str(baseline_dir),
                ]
            )
    finally:
        os.chdir(cwd_before)

    assert exc.value.code == 1

    audit_path = artefacts_dir / "_audit" / "audit.manifest.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["attention_targets"] == 1
    assert audit["missing_baseline_targets"] == 1
    assert audit["targets"][0]["inspection_path"] == "artefacts/_inspections/slide-id-1.inspect.json"

    comparison_path = artefacts_dir / "_comparisons" / "compare.manifest.json"
    assert comparison_path.exists()
    inspection_path = artefacts_dir / "_inspections" / "slide-id-1.inspect.json"
    assert inspection_path.exists()

    out = capsys.readouterr().out
    assert "[ok] Wrote audit manifest to artefacts/_audit/audit.manifest.json" in out
    assert "1 need attention" in out
    assert "[ok] Wrote 1 inspection manifest(s)." in out
