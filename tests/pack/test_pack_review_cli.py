from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

from praeparo.cli import main as cli_main


def test_pack_cli_review_writes_human_review_bundle(tmp_path: Path, capsys) -> None:
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
                "render_profile": {"workflow_kind": "pack_render_slide", "data_mode": "mock"},
                "rendered_targets": [
                    {
                        "slide_index": 1,
                        "slide_slug": "slide-id-1",
                        "target_slug": "slide-id-1",
                        "artifact_label": "[01]_slide-id-1",
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
    baseline_dir.mkdir(parents=True, exist_ok=True)
    (baseline_dir / "baseline.manifest.json").write_text(
        json.dumps(
            {
                "kind": "pack_slide_baselines",
                "pack_path": "registry/customers/test/test_pack.yaml",
                "baseline_dir": "baselines",
                "source_manifest_path": "artefacts/render.manifest.json",
                "source_artefact_dir": "artefacts",
                "updated_at": "2026-03-15T16:10:00+10:00",
                "approval_note": "Synthetic test baseline.",
                "latest_render_profile": {"workflow_kind": "pack_render_slide", "data_mode": "mock"},
                "targets": [],
                "target_details": [],
                "approval_runs": [],
                "exemptions": [{"target_slug": "slide-id-1", "reason": "Intentional exemption."}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    cwd_before = Path.cwd()
    try:
        os.chdir(tmp_path)
        try:
            cli_main(
                [
                    "pack",
                    "review",
                    str(artefacts_dir),
                    "--baseline-dir",
                    str(baseline_dir),
                ]
            )
        except SystemExit as exc:
            assert exc.code == 0
    finally:
        os.chdir(cwd_before)

    review = json.loads((artefacts_dir / "_review" / "review.manifest.json").read_text(encoding="utf-8"))
    assert review["approved_targets"] == 0
    assert review["exempt_targets"] == 1
    assert review["targets"][0]["review_status"] == "exempt"

    out = capsys.readouterr().out
    assert "[ok] Wrote review manifest to artefacts/_review/review.manifest.json" in out
