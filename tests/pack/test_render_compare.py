from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from praeparo.pack.render_compare import compare_pack_render_manifest
from praeparo.pack.render_manifest import PackRenderManifest, PackRenderManifestEntry


def test_compare_pack_render_manifest_matches_baseline(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"
    output_dir = project_root / "comparisons"

    png_path = render_dir / "slide-id-1.png"
    baseline_path = baseline_dir / "slide-id-1.png"
    _write_png(png_path, colour=(10, 20, 30, 255))
    _write_png(baseline_path, colour=(10, 20, 30, 255))

    manifest_path = project_root / "render.manifest.json"
    _write_manifest(
        manifest_path,
        rendered_targets=[
            PackRenderManifestEntry(
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="slide-id-1",
                png_path="renders/slide-id-1.png",
            )
        ],
    )

    comparison = compare_pack_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        output_dir=output_dir,
        project_root=project_root,
    )

    assert comparison.compared_targets == 1
    assert comparison.matched_targets == 1
    assert comparison.failed_targets == 0
    assert comparison.comparisons[0].status == "match"
    assert comparison.comparisons[0].metrics is not None
    assert comparison.comparisons[0].metrics.changed_pixels == 0


def test_compare_pack_render_manifest_writes_diff_for_mismatch(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"
    output_dir = project_root / "comparisons"

    png_path = render_dir / "slide-id-1.png"
    baseline_path = baseline_dir / "slide-id-1.png"
    _write_png(png_path, colour=(255, 0, 0, 255))
    _write_png(baseline_path, colour=(0, 0, 255, 255))

    manifest_path = project_root / "render.manifest.json"
    _write_manifest(
        manifest_path,
        rendered_targets=[
            PackRenderManifestEntry(
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="slide-id-1",
                png_path="renders/slide-id-1.png",
            )
        ],
    )

    comparison = compare_pack_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        output_dir=output_dir,
        project_root=project_root,
    )

    assert comparison.compared_targets == 1
    assert comparison.failed_targets == 1
    assert comparison.comparisons[0].status == "mismatch"
    assert comparison.comparisons[0].metrics is not None
    assert comparison.comparisons[0].metrics.changed_pixels > 0
    assert comparison.comparisons[0].diff_path == "comparisons/slide-id-1.diff.png"
    assert (output_dir / "slide-id-1.diff.png").exists()


def test_compare_pack_render_manifest_rejects_unknown_selector(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"
    output_dir = project_root / "comparisons"

    _write_png(render_dir / "slide-id-1.png", colour=(10, 20, 30, 255))
    _write_png(baseline_dir / "slide-id-1.png", colour=(10, 20, 30, 255))

    manifest_path = project_root / "render.manifest.json"
    _write_manifest(
        manifest_path,
        rendered_targets=[
            PackRenderManifestEntry(
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="slide-id-1",
                png_path="renders/slide-id-1.png",
            )
        ],
    )

    with pytest.raises(ValueError, match="No rendered targets matched selectors"):
        compare_pack_render_manifest(
            manifest_path=manifest_path,
            baseline_dir=baseline_dir,
            output_dir=output_dir,
            selectors=("missing-slide",),
            project_root=project_root,
        )


def _write_manifest(path: Path, *, rendered_targets: list[PackRenderManifestEntry]) -> None:
    manifest = PackRenderManifest(
        kind="pack_render_slide",
        pack_path="registry/customers/test/pack.yaml",
        artefact_root="renders",
        rendered_targets=rendered_targets,
    )
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _write_png(path: Path, *, colour: tuple[int, int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (24, 16), color=colour)
    image.save(path)
