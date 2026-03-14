from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from praeparo.review_profiles import build_render_profile
from praeparo.visuals.render_manifest import VisualRenderManifest
from praeparo.visuals.render_review import review_visual_render_manifest


def test_review_visual_render_manifest_marks_missing_baseline_as_exempt(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"
    output_dir = project_root / "comparisons"

    _write_png(render_dir / "performance_dashboard.png", colour=(10, 20, 30, 255))

    manifest = VisualRenderManifest(
        config_path="registry/customers/test/visuals/performance_dashboard.yaml",
        baseline_key="performance_dashboard",
        visual_type="governance_matrix",
        project_root=".",
        artefact_root="renders/_artifacts",
        render_profile=build_render_profile(workflow_kind="visual_inspect", data_mode="mock"),
        png_path="renders/performance_dashboard.png",
        data_mode="mock",
    )
    manifest_path = project_root / "render.manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

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
                "source_manifest_path": "render.manifest.json",
                "source_artefact_dir": "renders/_artifacts",
                "source_png_path": "renders/performance_dashboard.png",
                "updated_at": "2026-03-15T16:05:00+10:00",
                "approval_note": "Synthetic test baseline.",
                "render_profile": {
                    "workflow_kind": "visual_inspect",
                    "data_mode": "mock",
                },
                "approval_runs": [],
                "exemption_reason": "This visual is intentionally exempt from baseline coverage.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    review = review_visual_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        output_dir=output_dir,
        project_root=project_root,
    )

    assert review.review_status == "exempt"
    assert review.status_reason == "This visual is intentionally exempt from baseline coverage."
    assert (output_dir / "compare.manifest.json").exists()


def _write_png(path: Path, *, colour: tuple[int, int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (24, 16), color=colour)
    image.save(path)
