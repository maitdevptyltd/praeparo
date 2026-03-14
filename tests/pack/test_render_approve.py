from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from praeparo.pack.render_approve import approve_pack_render_manifest
from praeparo.pack.render_manifest import PackRenderManifest, PackRenderManifestEntry
from praeparo.review_profiles import build_render_profile


def test_approve_pack_render_manifest_promotes_png_and_records_lineage(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"

    png_path = render_dir / "slide-id-1.png"
    _write_png(png_path, colour=(10, 20, 30, 255))

    manifest_path = project_root / "render.manifest.json"
    _write_manifest(
        manifest_path,
        rendered_targets=[
            PackRenderManifestEntry(
                slide_index=1,
                slide_id="slide_id_1",
                slide_title="Slide Id 1",
                slide_template="full_page_image",
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="[01]_slide-id-1",
                visual_path="registry/customers/test/visuals/slide_id_1.yaml",
                visual_type="governance_matrix",
                png_path="renders/slide-id-1.png",
            )
        ],
    )

    approval = approve_pack_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        selectors=("slide-id-1",),
        project_root=project_root,
        note="Accept baseline drift after legend tweak.",
        approved_at="2026-03-15T14:00:00+10:00",
    )

    baseline_png = baseline_dir / "slide-id-1.png"
    baseline_manifest_path = baseline_dir / "baseline.manifest.json"
    assert baseline_png.exists()
    assert baseline_manifest_path.exists()

    assert approval.baseline_manifest_path == "baselines/baseline.manifest.json"
    assert approval.approved_targets[0].baseline_path == "baselines/slide-id-1.png"
    assert approval.approved_targets[0].source_png_path == "renders/slide-id-1.png"
    assert approval.baseline_manifest.targets == ["slide-id-1"]
    assert approval.baseline_manifest.target_details[0].note == "Accept baseline drift after legend tweak."
    assert approval.baseline_manifest.target_details[0].render_profile is not None
    assert approval.baseline_manifest.target_details[0].render_profile.workflow_kind == "pack_render_slide"
    assert approval.baseline_manifest.approval_runs[0].source_manifest_path == "render.manifest.json"
    assert approval.baseline_manifest.approval_runs[0].source_artefact_dir == "renders"
    assert approval.baseline_manifest.approval_runs[0].approved_targets == ["slide-id-1"]
    assert approval.baseline_manifest.approval_runs[0].render_profile is not None
    assert approval.baseline_manifest.approval_runs[0].render_profile.data_mode == "mock"

    payload = json.loads(baseline_manifest_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "pack_slide_baselines"
    assert payload["pack_path"] == "registry/customers/test/pack.yaml"
    assert payload["source_manifest_path"] == "render.manifest.json"
    assert payload["source_artefact_dir"] == "renders"
    assert payload["targets"] == ["slide-id-1"]
    assert payload["latest_render_profile"]["workflow_kind"] == "pack_render_slide"
    assert payload["approval_runs"][0]["source_manifest_path"] == "render.manifest.json"
    assert payload["approval_runs"][0]["approved_targets"] == ["slide-id-1"]
    assert payload["approval_runs"][0]["render_profile"]["data_mode"] == "mock"


def test_approve_pack_render_manifest_preserves_existing_metadata(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"

    png_path = render_dir / "slide-id-1.png"
    _write_png(png_path, colour=(100, 120, 140, 255))

    manifest_path = project_root / "render.manifest.json"
    _write_manifest(
        manifest_path,
        rendered_targets=[
            PackRenderManifestEntry(
                slide_index=1,
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="[01]_slide-id-1",
                png_path="renders/slide-id-1.png",
            )
        ],
    )

    baseline_dir.mkdir(parents=True, exist_ok=True)
    (baseline_dir / "baseline.manifest.json").write_text(
        json.dumps(
            {
                "customer": "test_customer",
                "reference_month": "2026-02-01",
                "source_artefact_dir": ".tmp/vscode/month=2026-02-01/police_and_nurses_governance_pack",
                "updated_at": "2026-02-01T12:00:00+10:00",
                "notes": ["Existing metadata should survive approval."],
                "targets": ["other-slide", "slide-id-1"],
                "target_details": [
                    {
                        "slide_slug": "other-slide",
                        "target_slug": "other-slide",
                        "artifact_label": "other-slide",
                        "baseline_path": "baselines/other-slide.png",
                        "source_png_path": ".tmp/other-slide.png",
                        "approved_at": "2026-02-01T12:00:00+10:00",
                    },
                    {
                        "slide_slug": "slide-id-1",
                        "target_slug": "slide-id-1",
                        "artifact_label": "[01]_slide-id-1",
                        "baseline_path": "baselines/slide-id-1.png",
                        "source_png_path": ".tmp/old-slide-id-1.png",
                        "approved_at": "2026-02-01T12:00:00+10:00",
                        "note": "Old approval",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    approve_pack_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        selectors=("slide-id-1",),
        project_root=project_root,
        approved_at="2026-03-15T14:05:00+10:00",
    )

    payload = json.loads((baseline_dir / "baseline.manifest.json").read_text(encoding="utf-8"))
    assert payload["customer"] == "test_customer"
    assert payload["reference_month"] == "2026-02-01"
    assert payload["notes"] == ["Existing metadata should survive approval."]
    assert payload["targets"] == ["other-slide", "slide-id-1"]

    other_detail, updated_detail = payload["target_details"]
    assert other_detail["target_slug"] == "other-slide"
    assert updated_detail["target_slug"] == "slide-id-1"
    assert updated_detail["source_png_path"] == "renders/slide-id-1.png"
    assert updated_detail["approved_at"] == "2026-03-15T14:05:00+10:00"
    assert updated_detail["note"] is None
    assert payload["approval_runs"][0]["source_artefact_dir"] == ".tmp/vscode/month=2026-02-01/police_and_nurses_governance_pack"
    assert payload["approval_runs"][0]["approved_at"] == "2026-02-01T12:00:00+10:00"
    assert payload["approval_runs"][0]["approved_targets"] == ["other-slide", "slide-id-1"]
    assert payload["approval_runs"][1]["source_manifest_path"] == "render.manifest.json"
    assert payload["approval_runs"][1]["source_artefact_dir"] == "renders"
    assert payload["approval_runs"][1]["approved_targets"] == ["slide-id-1"]


def test_approve_pack_render_manifest_rejects_ambiguous_selector(tmp_path: Path) -> None:
    manifest_path = tmp_path / "render.manifest.json"
    _write_manifest(
        manifest_path,
        rendered_targets=[
            PackRenderManifestEntry(
                slide_index=3,
                slide_slug="quarterly_performance_all_brands",
                target_slug="quarterly_performance_all_brands__top_left",
                artifact_label="[03]_quarterly_performance_all_brands__top_left",
            ),
            PackRenderManifestEntry(
                slide_index=3,
                slide_slug="quarterly_performance_all_brands",
                target_slug="quarterly_performance_all_brands__top_right",
                artifact_label="[03]_quarterly_performance_all_brands__top_right",
            ),
        ],
    )

    with pytest.raises(ValueError, match="Selector matched multiple rendered targets"):
        approve_pack_render_manifest(
            manifest_path=manifest_path,
            baseline_dir=tmp_path / "baselines",
            selectors=("quarterly_performance_all_brands",),
            project_root=tmp_path,
            approved_at="2026-03-15T14:10:00+10:00",
        )


def _write_manifest(path: Path, *, rendered_targets: list[PackRenderManifestEntry]) -> None:
    manifest = PackRenderManifest(
        kind="pack_render_slide",
        pack_path="registry/customers/test/pack.yaml",
        artefact_root="renders",
        render_profile=build_render_profile(workflow_kind="pack_render_slide", data_mode="mock"),
        rendered_targets=rendered_targets,
    )
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _write_png(path: Path, *, colour: tuple[int, int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (24, 16), color=colour)
    image.save(path)
