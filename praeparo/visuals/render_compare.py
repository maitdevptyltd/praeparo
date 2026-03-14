"""PNG comparison helpers for standalone visual render manifests.

Visual inspection manifests capture the files emitted by one focused render.
These helpers compare the primary PNG against an approved baseline and emit one
portable summary plus an optional diff image for agent and human review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image, ImageChops
from pydantic import BaseModel

from praeparo.visuals.render_manifest import VisualRenderManifest, load_visual_render_manifest


class RenderComparisonMetrics(BaseModel):
    """Pixel-level summary for one PNG comparison."""

    width: int
    height: int
    compared_pixels: int
    changed_pixels: int
    changed_pixel_ratio: float


class VisualRenderComparison(BaseModel):
    """Summary of comparing one rendered visual against its approved baseline."""

    kind: Literal["visual_comparison"] = "visual_comparison"
    manifest_path: str
    baseline_dir: str
    output_dir: str
    baseline_key: str
    config_path: str
    visual_type: str
    status: Literal["match", "mismatch", "missing_baseline", "missing_png"]
    png_path: str | None = None
    baseline_path: str | None = None
    diff_path: str | None = None
    message: str | None = None
    metrics: RenderComparisonMetrics | None = None


def compare_visual_render_manifest(
    *,
    manifest_path: Path,
    baseline_dir: Path,
    output_dir: Path,
    project_root: Path | None = None,
) -> VisualRenderComparison:
    """Compare a visual render manifest's primary PNG against its baseline."""

    manifest = load_visual_render_manifest(manifest_path)
    resolution_root = _resolve_project_root(project_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    return _compare_manifest(
        manifest=manifest,
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        output_dir=output_dir,
        project_root=resolution_root,
    )


def write_visual_render_comparison(comparison: VisualRenderComparison, path: Path) -> None:
    """Persist a comparison summary using a stable JSON encoding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(comparison.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _compare_manifest(
    *,
    manifest: VisualRenderManifest,
    manifest_path: Path,
    baseline_dir: Path,
    output_dir: Path,
    project_root: Path,
) -> VisualRenderComparison:
    """Resolve the manifest PNG and compare it against the expected baseline file."""

    baseline_path = baseline_dir / f"{manifest.baseline_key}.png"

    if not manifest.png_path:
        return VisualRenderComparison(
            manifest_path=_display_path(manifest_path, root=project_root),
            baseline_dir=_display_path(baseline_dir, root=project_root),
            output_dir=_display_path(output_dir, root=project_root),
            baseline_key=manifest.baseline_key,
            config_path=manifest.config_path,
            visual_type=manifest.visual_type,
            status="missing_png",
            baseline_path=_display_path(baseline_path, root=project_root),
            message="Visual render manifest did not record a PNG path.",
        )

    png_path = _resolve_manifest_path(manifest.png_path, root=project_root)
    if not png_path.exists():
        return VisualRenderComparison(
            manifest_path=_display_path(manifest_path, root=project_root),
            baseline_dir=_display_path(baseline_dir, root=project_root),
            output_dir=_display_path(output_dir, root=project_root),
            baseline_key=manifest.baseline_key,
            config_path=manifest.config_path,
            visual_type=manifest.visual_type,
            status="missing_png",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            message="Rendered PNG path does not exist.",
        )

    if not baseline_path.exists():
        return VisualRenderComparison(
            manifest_path=_display_path(manifest_path, root=project_root),
            baseline_dir=_display_path(baseline_dir, root=project_root),
            output_dir=_display_path(output_dir, root=project_root),
            baseline_key=manifest.baseline_key,
            config_path=manifest.config_path,
            visual_type=manifest.visual_type,
            status="missing_baseline",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            message="Baseline PNG is missing.",
        )

    metrics, diff_image = _compare_pngs(png_path=png_path, baseline_path=baseline_path)
    if metrics.changed_pixels == 0:
        return VisualRenderComparison(
            manifest_path=_display_path(manifest_path, root=project_root),
            baseline_dir=_display_path(baseline_dir, root=project_root),
            output_dir=_display_path(output_dir, root=project_root),
            baseline_key=manifest.baseline_key,
            config_path=manifest.config_path,
            visual_type=manifest.visual_type,
            status="match",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            metrics=metrics,
        )

    diff_path = output_dir / f"{manifest.baseline_key}.diff.png"
    diff_image.save(diff_path)
    return VisualRenderComparison(
        manifest_path=_display_path(manifest_path, root=project_root),
        baseline_dir=_display_path(baseline_dir, root=project_root),
        output_dir=_display_path(output_dir, root=project_root),
        baseline_key=manifest.baseline_key,
        config_path=manifest.config_path,
        visual_type=manifest.visual_type,
        status="mismatch",
        png_path=_display_path(png_path, root=project_root),
        baseline_path=_display_path(baseline_path, root=project_root),
        diff_path=_display_path(diff_path, root=project_root),
        metrics=metrics,
        message="Rendered PNG differs from baseline.",
    )


def _compare_pngs(*, png_path: Path, baseline_path: Path) -> tuple[RenderComparisonMetrics, Image.Image]:
    """Compare two PNGs on a common RGBA canvas and build a diff image."""

    with Image.open(png_path) as rendered_image:
        rendered = rendered_image.convert("RGBA")
    with Image.open(baseline_path) as baseline_image:
        baseline = baseline_image.convert("RGBA")

    width = max(rendered.width, baseline.width)
    height = max(rendered.height, baseline.height)

    rendered_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    rendered_canvas.paste(rendered, (0, 0))

    baseline_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    baseline_canvas.paste(baseline, (0, 0))

    diff = ImageChops.difference(rendered_canvas, baseline_canvas)

    diff_mask = diff.convert("L").point(lambda value: 255 if value else 0)
    histogram = diff_mask.histogram()
    changed_pixels = sum(histogram[1:])
    compared_pixels = width * height
    ratio = 0.0 if compared_pixels == 0 else changed_pixels / compared_pixels

    return (
        RenderComparisonMetrics(
            width=width,
            height=height,
            compared_pixels=compared_pixels,
            changed_pixels=changed_pixels,
            changed_pixel_ratio=ratio,
        ),
        diff,
    )


def _resolve_project_root(project_root: Path | None) -> Path:
    """Resolve the root used for cwd-relative render manifest paths."""

    if project_root is None:
        return Path.cwd().resolve()
    return project_root.expanduser().resolve(strict=False)


def _resolve_manifest_path(path: str, *, root: Path) -> Path:
    """Resolve a manifest path relative to the chosen project root."""

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.expanduser().resolve(strict=False)
    return (root / candidate).expanduser().resolve(strict=False)


def _display_path(path: Path, *, root: Path) -> str:
    """Prefer project-root-relative paths so manifests stay portable across machines."""

    resolved = path.expanduser().resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


__all__ = [
    "RenderComparisonMetrics",
    "VisualRenderComparison",
    "compare_visual_render_manifest",
    "write_visual_render_comparison",
]
