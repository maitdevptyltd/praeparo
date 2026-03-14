from __future__ import annotations

from pathlib import Path

from PIL import Image

from praeparo.visuals.render_compare import compare_visual_render_manifest
from praeparo.visuals.render_manifest import VisualRenderManifest


def test_compare_visual_render_manifest_matches_baseline(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"
    output_dir = project_root / "comparisons"

    png_path = render_dir / "performance_dashboard.png"
    baseline_path = baseline_dir / "performance_dashboard.png"
    _write_png(png_path, colour=(10, 20, 30, 255))
    _write_png(baseline_path, colour=(10, 20, 30, 255))

    manifest_path = project_root / "render.manifest.json"
    _write_manifest(manifest_path, png_path="renders/performance_dashboard.png")

    comparison = compare_visual_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        output_dir=output_dir,
        project_root=project_root,
    )

    assert comparison.status == "match"
    assert comparison.metrics is not None
    assert comparison.metrics.changed_pixels == 0
    assert comparison.baseline_path == "baselines/performance_dashboard.png"


def test_compare_visual_render_manifest_writes_diff_for_mismatch(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"
    output_dir = project_root / "comparisons"

    png_path = render_dir / "performance_dashboard.png"
    baseline_path = baseline_dir / "performance_dashboard.png"
    _write_png(png_path, colour=(255, 0, 0, 255))
    _write_png(baseline_path, colour=(0, 0, 255, 255))

    manifest_path = project_root / "render.manifest.json"
    _write_manifest(manifest_path, png_path="renders/performance_dashboard.png")

    comparison = compare_visual_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        output_dir=output_dir,
        project_root=project_root,
    )

    assert comparison.status == "mismatch"
    assert comparison.metrics is not None
    assert comparison.metrics.changed_pixels > 0
    assert comparison.diff_path == "comparisons/performance_dashboard.diff.png"
    assert (output_dir / "performance_dashboard.diff.png").exists()


def test_compare_visual_render_manifest_reports_missing_baseline(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    output_dir = project_root / "comparisons"

    png_path = render_dir / "performance_dashboard.png"
    _write_png(png_path, colour=(10, 20, 30, 255))

    manifest_path = project_root / "render.manifest.json"
    _write_manifest(manifest_path, png_path="renders/performance_dashboard.png")

    comparison = compare_visual_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=project_root / "baselines",
        output_dir=output_dir,
        project_root=project_root,
    )

    assert comparison.status == "missing_baseline"
    assert comparison.baseline_path == "baselines/performance_dashboard.png"


def _write_manifest(path: Path, *, png_path: str) -> None:
    manifest = VisualRenderManifest(
        config_path="registry/customers/test/visuals/performance_dashboard.yaml",
        baseline_key="performance_dashboard",
        visual_type="governance_matrix",
        project_root=".",
        artefact_root="renders/_artifacts",
        png_path=png_path,
        data_mode="mock",
    )
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _write_png(path: Path, *, colour: tuple[int, int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (24, 16), color=colour)
    image.save(path)
