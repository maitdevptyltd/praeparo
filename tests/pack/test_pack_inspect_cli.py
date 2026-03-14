from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from praeparo.cli import main as cli_main


def test_pack_cli_inspect_slide_writes_inspection_manifest(tmp_path: Path, capsys) -> None:
    artefacts_dir = tmp_path / "artefacts"
    artefacts_dir.mkdir(parents=True, exist_ok=True)

    (artefacts_dir / "render.manifest.json").write_text(
        json.dumps(
            {
                "kind": "pack_render_slide",
                "pack_path": "registry/customers/test/test_pack.yaml",
                "artefact_root": "artefacts",
                "rendered_targets": [
                    {
                        "slide_index": 2,
                        "slide_id": "performance_dashboard",
                        "slide_title": "Performance Dashboard",
                        "slide_template": "full_page_image",
                        "slide_slug": "performance_dashboard_all_brands",
                        "target_slug": "performance_dashboard_all_brands",
                        "artifact_label": "[02]_performance_dashboard_all_brands",
                        "visual_path": "registry/customers/test/visuals/performance_dashboard.yaml",
                        "visual_type": "governance_matrix",
                        "png_path": "artefacts/[02]_performance_dashboard_all_brands.png",
                        "artefact_dir": "artefacts/[02]_performance_dashboard_all_brands",
                        "artefacts": []
                    }
                ],
                "pack_artefacts": [
                    {
                        "kind": "dax",
                        "path": "artefacts/metric_context.slide_2.dax"
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    comparisons_dir = artefacts_dir / "_comparisons"
    comparisons_dir.mkdir(parents=True, exist_ok=True)
    (comparisons_dir / "compare.manifest.json").write_text(
        json.dumps(
            {
                "kind": "pack_slide_comparison",
                "manifest_path": "artefacts/render.manifest.json",
                "baseline_dir": "registry/customers/test/baselines",
                "output_dir": "artefacts/_comparisons",
                "compared_targets": 1,
                "matched_targets": 1,
                "failed_targets": 0,
                "comparisons": [
                    {
                        "slide_slug": "performance_dashboard_all_brands",
                        "target_slug": "performance_dashboard_all_brands",
                        "status": "match",
                        "png_path": "artefacts/[02]_performance_dashboard_all_brands.png",
                        "baseline_path": "registry/customers/test/baselines/performance_dashboard_all_brands.png",
                        "metrics": {
                            "width": 100,
                            "height": 50,
                            "compared_pixels": 5000,
                            "changed_pixels": 0,
                            "changed_pixel_ratio": 0.0
                        }
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    cwd_before = Path.cwd()
    try:
        os.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc:
            cli_main(
                [
                    "pack",
                    "inspect-slide",
                    str(artefacts_dir),
                    "--slide",
                    "performance_dashboard_all_brands",
                    "--project-root",
                    str(tmp_path),
                ]
            )
    finally:
        os.chdir(cwd_before)

    assert exc.value.code == 0

    inspection_path = artefacts_dir / "_inspections" / "performance_dashboard_all_brands.inspect.json"
    inspection = json.loads(inspection_path.read_text(encoding="utf-8"))
    assert inspection["target_slug"] == "performance_dashboard_all_brands"
    assert inspection["slide_template"] == "full_page_image"
    assert inspection["comparison"]["status"] == "match"
    assert inspection["metric_context_artefacts"] == [
        {"kind": "dax", "path": "artefacts/metric_context.slide_2.dax"}
    ]

    out = capsys.readouterr().out
    assert "[ok] Wrote inspection manifest to artefacts/_inspections/performance_dashboard_all_brands.inspect.json" in out
