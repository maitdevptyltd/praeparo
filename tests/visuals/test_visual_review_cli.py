from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

from praeparo.cli import main as cli_main


def test_visual_cli_review_writes_human_review_bundle(tmp_path: Path, capsys) -> None:
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
                "render_profile": {"workflow_kind": "visual_inspect", "data_mode": "mock"},
                "png_path": "artefacts/performance_dashboard.png",
                "data_mode": "mock",
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
                "kind": "visual_baseline",
                "config_path": "registry/customers/test/visuals/performance_dashboard.yaml",
                "baseline_key": "performance_dashboard",
                "visual_type": "governance_matrix",
                "baseline_dir": "baselines",
                "baseline_path": "baselines/performance_dashboard.png",
                "source_manifest_path": "artefacts/render.manifest.json",
                "source_artefact_dir": "artefacts",
                "source_png_path": "artefacts/performance_dashboard.png",
                "updated_at": "2026-03-15T16:12:00+10:00",
                "approval_note": "Synthetic test baseline.",
                "render_profile": {"workflow_kind": "visual_inspect", "data_mode": "mock"},
                "approval_runs": [],
                "exemption_reason": "Intentional exemption.",
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
                    "visual",
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
    assert review["review_status"] == "exempt"
    assert review["status_reason"] == "Intentional exemption."

    out = capsys.readouterr().out
    assert "[ok] Wrote review manifest to artefacts/_review/review.manifest.json" in out
