from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from praeparo.review_profiles import build_render_profile
from praeparo.visuals.render_approve import approve_visual_render_manifest
from praeparo.visuals.render_manifest import VisualRenderManifest


def test_approve_visual_render_manifest_promotes_png_and_records_lineage(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"

    png_path = render_dir / "performance_dashboard.png"
    _write_png(png_path, colour=(10, 20, 30, 255))

    manifest_path = project_root / "render.manifest.json"
    _write_manifest(manifest_path, png_path="renders/performance_dashboard.png")

    approval = approve_visual_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        project_root=project_root,
        note="Approve current customer preview.",
        approved_at="2026-03-15T15:00:00+10:00",
    )

    baseline_png = baseline_dir / "performance_dashboard.png"
    baseline_manifest_path = baseline_dir / "baseline.manifest.json"
    assert baseline_png.exists()
    assert baseline_manifest_path.exists()

    assert approval.baseline_manifest_path == "baselines/baseline.manifest.json"
    assert approval.baseline_manifest.baseline_path == "baselines/performance_dashboard.png"
    assert approval.baseline_manifest.source_png_path == "renders/performance_dashboard.png"
    assert approval.baseline_manifest.render_profile is not None
    assert approval.baseline_manifest.render_profile.data_mode == "mock"
    assert approval.baseline_manifest.approval_runs[0].render_profile is not None

    payload = json.loads(baseline_manifest_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "visual_baseline"
    assert payload["baseline_key"] == "performance_dashboard"
    assert payload["source_manifest_path"] == "render.manifest.json"
    assert payload["approval_note"] == "Approve current customer preview."
    assert payload["render_profile"]["workflow_kind"] == "visual_inspect"
    assert payload["approval_runs"][0]["render_profile"]["data_mode"] == "mock"


def test_approve_visual_render_manifest_preserves_existing_metadata(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"

    png_path = render_dir / "performance_dashboard.png"
    _write_png(png_path, colour=(100, 120, 140, 255))

    manifest_path = project_root / "render.manifest.json"
    _write_manifest(manifest_path, png_path="renders/performance_dashboard.png")

    baseline_dir.mkdir(parents=True, exist_ok=True)
    (baseline_dir / "baseline.manifest.json").write_text(
        json.dumps(
            {
                "customer": "test_customer",
                "reference_month": "2026-02-01",
                "approval_note": "Keep existing note if no new note is supplied.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    approve_visual_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        project_root=project_root,
        approved_at="2026-03-15T15:05:00+10:00",
    )

    payload = json.loads((baseline_dir / "baseline.manifest.json").read_text(encoding="utf-8"))
    assert payload["customer"] == "test_customer"
    assert payload["reference_month"] == "2026-02-01"
    assert payload["approval_note"] == "Keep existing note if no new note is supplied."


def test_approve_visual_render_manifest_rejects_missing_png(tmp_path: Path) -> None:
    manifest_path = tmp_path / "render.manifest.json"
    _write_manifest(manifest_path, png_path="renders/missing.png")

    with pytest.raises(ValueError, match="Rendered PNG path does not exist"):
        approve_visual_render_manifest(
            manifest_path=manifest_path,
            baseline_dir=tmp_path / "baselines",
            project_root=tmp_path,
            approved_at="2026-03-15T15:10:00+10:00",
        )


def _write_manifest(path: Path, *, png_path: str) -> None:
    manifest = VisualRenderManifest(
        config_path="registry/customers/test/visuals/performance_dashboard.yaml",
        baseline_key="performance_dashboard",
        visual_type="governance_matrix",
        project_root=".",
        artefact_root="renders/_artifacts",
        render_profile=build_render_profile(workflow_kind="visual_inspect", data_mode="mock"),
        png_path=png_path,
        data_mode="mock",
    )
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _write_png(path: Path, *, colour: tuple[int, int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (24, 16), color=colour)
    image.save(path)
