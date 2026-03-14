"""PNG comparison helpers for standalone visual render manifests.

Visual inspection manifests capture the files emitted by one focused render.
These helpers compare the primary PNG against an approved baseline and emit one
portable summary plus an optional diff image for agent and human review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageChops
from pydantic import BaseModel

from praeparo.review_profiles import (
    ProfileSourceKind,
    RenderProfile,
    RenderProfileCheck,
    build_render_profile,
    compare_render_profiles,
    infer_data_mode_from_paths,
)
from praeparo.visuals.render_approve import load_visual_render_baseline_payload
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
    baseline_manifest_path: str | None = None
    output_dir: str
    baseline_key: str
    config_path: str
    visual_type: str
    render_profile: RenderProfile | None = None
    status: Literal["match", "mismatch", "missing_baseline", "missing_png", "profile_mismatch", "missing_profile"]
    png_path: str | None = None
    baseline_path: str | None = None
    diff_path: str | None = None
    message: str | None = None
    metrics: RenderComparisonMetrics | None = None
    profile_check: RenderProfileCheck | None = None


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
    baseline_manifest_path = baseline_dir / "baseline.manifest.json"
    baseline_payload = load_visual_render_baseline_payload(baseline_manifest_path)

    return _compare_manifest(
        manifest=manifest,
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        baseline_manifest_path=baseline_manifest_path,
        baseline_payload=baseline_payload,
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
    baseline_manifest_path: Path,
    baseline_payload: dict[str, Any],
    output_dir: Path,
    project_root: Path,
) -> VisualRenderComparison:
    """Resolve the manifest PNG and compare it against the expected baseline file."""

    baseline_path = baseline_dir / f"{manifest.baseline_key}.png"

    render_profile = _resolve_render_profile(manifest.render_profile)

    if not manifest.png_path:
        return VisualRenderComparison(
            manifest_path=_display_path(manifest_path, root=project_root),
            baseline_dir=_display_path(baseline_dir, root=project_root),
            baseline_manifest_path=(
                _display_path(baseline_manifest_path, root=project_root)
                if baseline_manifest_path.exists()
                else None
            ),
            output_dir=_display_path(output_dir, root=project_root),
            baseline_key=manifest.baseline_key,
            config_path=manifest.config_path,
            visual_type=manifest.visual_type,
            render_profile=render_profile,
            status="missing_png",
            baseline_path=_display_path(baseline_path, root=project_root),
            message="Visual render manifest did not record a PNG path.",
        )

    png_path = _resolve_manifest_path(manifest.png_path, root=project_root)
    if not png_path.exists():
        return VisualRenderComparison(
            manifest_path=_display_path(manifest_path, root=project_root),
            baseline_dir=_display_path(baseline_dir, root=project_root),
            baseline_manifest_path=(
                _display_path(baseline_manifest_path, root=project_root)
                if baseline_manifest_path.exists()
                else None
            ),
            output_dir=_display_path(output_dir, root=project_root),
            baseline_key=manifest.baseline_key,
            config_path=manifest.config_path,
            visual_type=manifest.visual_type,
            render_profile=render_profile,
            status="missing_png",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            message="Rendered PNG path does not exist.",
        )

    if not baseline_path.exists():
        return VisualRenderComparison(
            manifest_path=_display_path(manifest_path, root=project_root),
            baseline_dir=_display_path(baseline_dir, root=project_root),
            baseline_manifest_path=(
                _display_path(baseline_manifest_path, root=project_root)
                if baseline_manifest_path.exists()
                else None
            ),
            output_dir=_display_path(output_dir, root=project_root),
            baseline_key=manifest.baseline_key,
            config_path=manifest.config_path,
            visual_type=manifest.visual_type,
            render_profile=render_profile,
            status="missing_baseline",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            message="Baseline PNG is missing.",
        )

    profile_check = _build_profile_check(
        render_profile=render_profile,
        baseline_dir=baseline_dir,
        baseline_payload=baseline_payload,
        project_root=project_root,
    )
    if profile_check.status != "match":
        return VisualRenderComparison(
            manifest_path=_display_path(manifest_path, root=project_root),
            baseline_dir=_display_path(baseline_dir, root=project_root),
            baseline_manifest_path=(
                _display_path(baseline_manifest_path, root=project_root)
                if baseline_manifest_path.exists()
                else None
            ),
            output_dir=_display_path(output_dir, root=project_root),
            baseline_key=manifest.baseline_key,
            config_path=manifest.config_path,
            visual_type=manifest.visual_type,
            render_profile=render_profile,
            status="profile_mismatch" if profile_check.status == "mismatch" else "missing_profile",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            message=profile_check.message,
            profile_check=profile_check,
        )

    metrics, diff_image = _compare_pngs(png_path=png_path, baseline_path=baseline_path)
    if metrics.changed_pixels == 0:
        return VisualRenderComparison(
            manifest_path=_display_path(manifest_path, root=project_root),
            baseline_dir=_display_path(baseline_dir, root=project_root),
            baseline_manifest_path=(
                _display_path(baseline_manifest_path, root=project_root)
                if baseline_manifest_path.exists()
                else None
            ),
            output_dir=_display_path(output_dir, root=project_root),
            baseline_key=manifest.baseline_key,
            config_path=manifest.config_path,
            visual_type=manifest.visual_type,
            render_profile=render_profile,
            status="match",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            metrics=metrics,
            profile_check=profile_check,
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
        render_profile=render_profile,
        status="mismatch",
        png_path=_display_path(png_path, root=project_root),
        baseline_path=_display_path(baseline_path, root=project_root),
        diff_path=_display_path(diff_path, root=project_root),
        metrics=metrics,
        message="Rendered PNG differs from baseline.",
        profile_check=profile_check,
    )


def _build_profile_check(
    *,
    render_profile: RenderProfile,
    baseline_dir: Path,
    baseline_payload: dict[str, Any],
    project_root: Path,
) -> RenderProfileCheck:
    """Resolve the baseline profile before comparing the visual PNG."""

    if not baseline_payload:
        return compare_render_profiles(
            render_profile=render_profile,
            baseline_profile=render_profile,
            baseline_profile_source="legacy_inferred",
            missing_message=(
                "Baseline render profile is missing for this visual. "
                "Re-approve the baseline or add explicit profile metadata."
            ),
        )

    baseline_profile, profile_source = _resolve_visual_baseline_profile(
        baseline_dir=baseline_dir,
        baseline_payload=baseline_payload,
        project_root=project_root,
    )
    return compare_render_profiles(
        render_profile=render_profile,
        baseline_profile=baseline_profile,
        baseline_profile_source=profile_source,
        missing_message=(
            "Baseline render profile is missing for this visual. "
            "Re-approve the baseline or add explicit profile metadata."
        ),
    )


def _resolve_visual_baseline_profile(
    *,
    baseline_dir: Path,
    baseline_payload: dict[str, Any],
    project_root: Path,
) -> tuple[RenderProfile | None, ProfileSourceKind]:
    """Resolve the baseline profile that applies to the visual."""

    explicit_profile = _coerce_render_profile(baseline_payload.get("render_profile"))
    if explicit_profile is not None:
        return explicit_profile, "explicit"

    raw_runs = baseline_payload.get("approval_runs")
    if isinstance(raw_runs, list):
        for item in reversed(raw_runs):
            if not isinstance(item, dict):
                continue
            run_profile = _coerce_render_profile(item.get("render_profile"))
            if run_profile is not None:
                return run_profile, "explicit"

            source_manifest_path = _coerce_optional_string(item.get("source_manifest_path"))
            source_artefact_dir = _coerce_optional_string(item.get("source_artefact_dir"))
            inferred = _infer_legacy_visual_profile(
                baseline_dir=baseline_dir,
                project_root=project_root,
                source_manifest_path=source_manifest_path,
                source_artefact_dir=source_artefact_dir,
            )
            if inferred is not None:
                return inferred, "legacy_inferred"

    inferred_profile = _infer_legacy_visual_profile(
        baseline_dir=baseline_dir,
        project_root=project_root,
        source_manifest_path=_coerce_optional_string(baseline_payload.get("source_manifest_path")),
        source_artefact_dir=_coerce_optional_string(baseline_payload.get("source_artefact_dir")),
    )
    if inferred_profile is not None:
        return inferred_profile, "legacy_inferred"

    return None, "missing"


def _infer_legacy_visual_profile(
    *,
    baseline_dir: Path,
    project_root: Path,
    source_manifest_path: str | None,
    source_artefact_dir: str | None,
) -> RenderProfile | None:
    """Infer a conservative profile for older visual baseline manifests."""

    if source_manifest_path:
        resolved_manifest_path = _resolve_manifest_path(source_manifest_path, root=project_root)
        if resolved_manifest_path.exists():
            try:
                manifest = load_visual_render_manifest(resolved_manifest_path)
            except Exception:
                manifest = None
            if manifest is not None:
                return _resolve_render_profile(manifest.render_profile)

    data_mode = infer_data_mode_from_paths(
        baseline_dir.as_posix(),
        source_manifest_path,
        source_artefact_dir,
    )
    if data_mode is None:
        return None

    return build_render_profile(workflow_kind="visual_inspect", data_mode=data_mode)


def _resolve_render_profile(profile: RenderProfile | None) -> RenderProfile:
    """Return the manifest profile, or a partial legacy fallback when absent."""

    if profile is not None:
        return profile
    return build_render_profile(workflow_kind="visual_inspect", data_mode=None)


def _coerce_render_profile(raw: object) -> RenderProfile | None:
    """Validate optional render-profile payloads from legacy JSON manifests."""

    if raw is None:
        return None
    try:
        return RenderProfile.model_validate(raw)
    except Exception:
        return None


def _coerce_optional_string(raw: object) -> str | None:
    """Keep optional string metadata only when the legacy JSON shape matches."""

    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    return None


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
