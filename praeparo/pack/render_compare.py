"""PNG comparison helpers for pack render manifests.

Focused pack debugging needs more than "the command ran". These helpers compare
rendered PNG targets recorded in `render.manifest.json` against approved
baselines, emit human-inspectable diff images, and summarize the outcome in a
portable manifest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

from PIL import Image, ImageChops
from pydantic import BaseModel, Field

from praeparo.pack.render_manifest import PackRenderManifest, PackRenderManifestEntry
from praeparo.visuals.dax.planner_core import slugify


class RenderComparisonMetrics(BaseModel):
    """Pixel-level summary for one PNG comparison."""

    width: int
    height: int
    compared_pixels: int
    changed_pixels: int
    changed_pixel_ratio: float


class PackRenderComparisonEntry(BaseModel):
    """Comparison result for one rendered target."""

    slide_slug: str
    target_slug: str
    status: Literal["match", "mismatch", "missing_baseline", "missing_png"]
    png_path: str | None = None
    baseline_path: str | None = None
    diff_path: str | None = None
    message: str | None = None
    metrics: RenderComparisonMetrics | None = None


class PackRenderComparison(BaseModel):
    """Summary of comparing a rendered pack output against stored baselines."""

    kind: Literal["pack_slide_comparison"] = "pack_slide_comparison"
    manifest_path: str
    baseline_dir: str
    output_dir: str
    requested_slides: list[str] = Field(default_factory=list)
    compared_targets: int
    matched_targets: int
    failed_targets: int
    comparisons: list[PackRenderComparisonEntry] = Field(default_factory=list)


def load_pack_render_manifest(path: Path) -> PackRenderManifest:
    """Load a previously emitted pack render manifest from disk."""

    return PackRenderManifest.model_validate_json(path.read_text(encoding="utf-8"))


def compare_pack_render_manifest(
    *,
    manifest_path: Path,
    baseline_dir: Path,
    output_dir: Path,
    selectors: Sequence[str] = (),
    project_root: Path | None = None,
) -> PackRenderComparison:
    """Compare rendered PNG targets in a manifest against approved baselines.

    The manifest provides the portable list of rendered targets and their output
    PNG paths. Baselines are resolved as `<baseline_dir>/<target_slug>.png`.
    Diff images are emitted under `<output_dir>/<target_slug>.diff.png`.
    """

    manifest = load_pack_render_manifest(manifest_path)
    resolution_root = _resolve_project_root(project_root)
    requested = tuple(str(item) for item in selectors)
    entries = _select_manifest_entries(manifest.rendered_targets, selectors=requested)
    if requested and not entries:
        joined = ", ".join(requested)
        raise ValueError(f"No rendered targets matched selectors: {joined}")

    output_dir.mkdir(parents=True, exist_ok=True)

    comparisons: list[PackRenderComparisonEntry] = []
    matched = 0
    failed = 0

    for entry in entries:
        comparison = _compare_entry(
            entry=entry,
            baseline_dir=baseline_dir,
            output_dir=output_dir,
            project_root=resolution_root,
        )
        comparisons.append(comparison)
        if comparison.status == "match":
            matched += 1
        else:
            failed += 1

    return PackRenderComparison(
        manifest_path=_display_path(manifest_path, root=resolution_root),
        baseline_dir=_display_path(baseline_dir, root=resolution_root),
        output_dir=_display_path(output_dir, root=resolution_root),
        requested_slides=list(requested),
        compared_targets=len(comparisons),
        matched_targets=matched,
        failed_targets=failed,
        comparisons=comparisons,
    )


def write_pack_render_comparison(comparison: PackRenderComparison, path: Path) -> None:
    """Persist a comparison summary using a stable JSON encoding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(comparison.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _compare_entry(
    *,
    entry: PackRenderManifestEntry,
    baseline_dir: Path,
    output_dir: Path,
    project_root: Path,
) -> PackRenderComparisonEntry:
    """Compare one rendered target against its baseline PNG."""

    if not entry.png_path:
        return PackRenderComparisonEntry(
            slide_slug=entry.slide_slug,
            target_slug=entry.target_slug,
            status="missing_png",
            message="Rendered target did not record a PNG path in render.manifest.json.",
        )

    png_path = _resolve_manifest_path(entry.png_path, root=project_root)
    baseline_path = baseline_dir / f"{entry.target_slug}.png"

    if not png_path.exists():
        return PackRenderComparisonEntry(
            slide_slug=entry.slide_slug,
            target_slug=entry.target_slug,
            status="missing_png",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            message="Rendered PNG path does not exist.",
        )

    if not baseline_path.exists():
        return PackRenderComparisonEntry(
            slide_slug=entry.slide_slug,
            target_slug=entry.target_slug,
            status="missing_baseline",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            message="Baseline PNG is missing.",
        )

    metrics, diff_image = _compare_pngs(png_path=png_path, baseline_path=baseline_path)
    if metrics.changed_pixels == 0:
        return PackRenderComparisonEntry(
            slide_slug=entry.slide_slug,
            target_slug=entry.target_slug,
            status="match",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            metrics=metrics,
        )

    diff_path = output_dir / f"{entry.target_slug}.diff.png"
    diff_image.save(diff_path)
    return PackRenderComparisonEntry(
        slide_slug=entry.slide_slug,
        target_slug=entry.target_slug,
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


def _select_manifest_entries(
    entries: Sequence[PackRenderManifestEntry],
    *,
    selectors: Sequence[str],
) -> list[PackRenderManifestEntry]:
    """Filter manifest targets using slide ids, titles, slugs, or target slugs."""

    if not selectors:
        return list(entries)

    normalized = {slugify(item) for item in selectors}
    selected: list[PackRenderManifestEntry] = []
    for entry in entries:
        title_slug = slugify(entry.slide_title) if entry.slide_title else None
        candidates = {
            slugify(entry.slide_slug),
            slugify(entry.target_slug),
            slugify(entry.artifact_label),
        }
        if entry.slide_id:
            candidates.add(slugify(entry.slide_id))
        if title_slug:
            candidates.add(title_slug)

        if candidates & normalized:
            selected.append(entry)

    return selected


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
    "PackRenderComparison",
    "PackRenderComparisonEntry",
    "RenderComparisonMetrics",
    "compare_pack_render_manifest",
    "load_pack_render_manifest",
    "write_pack_render_comparison",
]
