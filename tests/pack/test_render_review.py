from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from praeparo.pack.render_manifest import PackRenderManifest, PackRenderManifestEntry
from praeparo.pack.render_review import review_pack_render_manifest
from praeparo.review_profiles import build_render_profile


def test_review_pack_render_manifest_marks_missing_baseline_as_exempt(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"

    _write_png(render_dir / "slide-id-1.png", colour=(10, 20, 30, 255))

    manifest = PackRenderManifest(
        kind="pack_render_slide",
        pack_path="registry/customers/test/pack.yaml",
        artefact_root="renders",
        render_profile=build_render_profile(workflow_kind="pack_render_slide", data_mode="mock"),
        rendered_targets=[
            PackRenderManifestEntry(
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="[01]_slide-id-1",
                png_path="renders/slide-id-1.png",
            )
        ],
    )
    manifest_path = project_root / "render.manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    baseline_dir.mkdir(parents=True, exist_ok=True)
    (baseline_dir / "baseline.manifest.json").write_text(
        json.dumps(
            {
                "kind": "pack_slide_baselines",
                "pack_path": "registry/customers/test/pack.yaml",
                "baseline_dir": "baselines",
                "source_manifest_path": "render.manifest.json",
                "source_artefact_dir": "renders",
                "updated_at": "2026-03-15T16:00:00+10:00",
                "approval_note": "Synthetic test baseline.",
                "latest_render_profile": {
                    "workflow_kind": "pack_render_slide",
                    "data_mode": "mock",
                },
                "targets": [],
                "target_details": [],
                "approval_runs": [],
                "exemptions": [
                    {
                        "target_slug": "slide-id-1",
                        "reason": "This slide is intentionally excluded from baseline coverage.",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    review = review_pack_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        project_root=project_root,
    )

    assert review.reviewed_targets == 1
    assert review.exempt_targets == 1
    assert review.attention_targets == 0
    assert review.targets[0].review_status == "exempt"
    assert review.targets[0].status_reason == "This slide is intentionally excluded from baseline coverage."


def _write_png(path: Path, *, colour: tuple[int, int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (24, 16), color=colour)
    image.save(path)
