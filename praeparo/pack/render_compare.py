"""PNG comparison helpers for pack render manifests.

Focused pack debugging needs more than "the command ran". These helpers compare
rendered PNG targets recorded in `render.manifest.json` against approved
baselines, emit human-inspectable diff images, and summarize the outcome in a
portable manifest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Sequence

from PIL import Image, ImageChops
from pydantic import BaseModel, Field

from praeparo.pack.render_approve import load_pack_render_baseline_payload
from praeparo.pack.render_manifest import (
    PackRenderManifestEntry,
    load_pack_render_manifest,
    select_pack_render_targets,
)
from praeparo.review_profiles import (
    ProfileSourceKind,
    RenderProfile,
    RenderProfileCheck,
    build_render_profile,
    compare_render_profiles,
    infer_data_mode_from_paths,
)


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
    status: Literal["match", "mismatch", "missing_baseline", "missing_png", "profile_mismatch", "missing_profile"]
    png_path: str | None = None
    baseline_path: str | None = None
    diff_path: str | None = None
    message: str | None = None
    metrics: RenderComparisonMetrics | None = None
    profile_check: RenderProfileCheck | None = None


class PackRenderComparison(BaseModel):
    """Summary of comparing a rendered pack output against stored baselines."""

    kind: Literal["pack_slide_comparison"] = "pack_slide_comparison"
    manifest_path: str
    baseline_dir: str
    baseline_manifest_path: str | None = None
    output_dir: str
    render_profile: RenderProfile | None = None
    requested_slides: list[str] = Field(default_factory=list)
    compared_targets: int
    matched_targets: int
    failed_targets: int
    comparisons: list[PackRenderComparisonEntry] = Field(default_factory=list)

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
    render_profile = _resolve_render_profile(manifest.kind, manifest.render_profile)
    requested = tuple(str(item) for item in selectors)
    entries = select_pack_render_targets(manifest.rendered_targets, selectors=requested)
    if requested and not entries:
        joined = ", ".join(requested)
        raise ValueError(f"No rendered targets matched selectors: {joined}")

    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_manifest_path = baseline_dir / "baseline.manifest.json"
    baseline_payload = load_pack_render_baseline_payload(baseline_manifest_path)

    comparisons: list[PackRenderComparisonEntry] = []
    matched = 0
    failed = 0

    for entry in entries:
        comparison = _compare_entry(
            entry=entry,
            baseline_dir=baseline_dir,
            output_dir=output_dir,
            render_profile=render_profile,
            baseline_payload=baseline_payload,
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
        baseline_manifest_path=(
            _display_path(baseline_manifest_path, root=resolution_root)
            if baseline_manifest_path.exists()
            else None
        ),
        output_dir=_display_path(output_dir, root=resolution_root),
        render_profile=render_profile,
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
    render_profile: RenderProfile,
    baseline_payload: dict[str, Any],
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

    profile_check = _build_profile_check(
        target_slug=entry.target_slug,
        render_profile=render_profile,
        baseline_dir=baseline_dir,
        baseline_payload=baseline_payload,
        project_root=project_root,
    )
    if profile_check.status != "match":
        return PackRenderComparisonEntry(
            slide_slug=entry.slide_slug,
            target_slug=entry.target_slug,
            status="profile_mismatch" if profile_check.status == "mismatch" else "missing_profile",
            png_path=_display_path(png_path, root=project_root),
            baseline_path=_display_path(baseline_path, root=project_root),
            message=profile_check.message,
            profile_check=profile_check,
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
            profile_check=profile_check,
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
        profile_check=profile_check,
    )


def _build_profile_check(
    *,
    target_slug: str,
    render_profile: RenderProfile,
    baseline_dir: Path,
    baseline_payload: dict[str, Any],
    project_root: Path,
) -> RenderProfileCheck:
    """Resolve one baseline profile for the target before comparing PNGs.

    Prefer explicit per-target or per-approval-run profiles from newer baseline
    manifests. If those do not exist yet, fall back to conservative legacy
    inference so older baseline sets still load, but surface missing metadata
    separately from a true render-profile mismatch.
    """

    if not baseline_payload:
        return compare_render_profiles(
            render_profile=render_profile,
            baseline_profile=render_profile,
            baseline_profile_source="legacy_inferred",
            missing_message=(
                "Baseline render profile is missing for "
                f"'{target_slug}'. Re-approve the baseline or add explicit profile metadata."
            ),
        )

    baseline_profile, profile_source = _resolve_target_baseline_profile(
        target_slug=target_slug,
        baseline_dir=baseline_dir,
        baseline_payload=baseline_payload,
        project_root=project_root,
    )
    return compare_render_profiles(
        render_profile=render_profile,
        baseline_profile=baseline_profile,
        baseline_profile_source=profile_source,
        missing_message=(
            "Baseline render profile is missing for "
            f"'{target_slug}'. Re-approve the baseline or add explicit profile metadata."
        ),
    )


def _resolve_target_baseline_profile(
    *,
    target_slug: str,
    baseline_dir: Path,
    baseline_payload: dict[str, Any],
    project_root: Path,
) -> tuple[RenderProfile | None, ProfileSourceKind]:
    """Resolve the baseline profile that applies to one target slug."""

    detail_profile = _coerce_render_profile(_matching_target_detail(baseline_payload, target_slug).get("render_profile"))
    if detail_profile is not None:
        return detail_profile, "explicit"

    run = _matching_approval_run(baseline_payload, target_slug)
    if run is not None:
        run_profile = _coerce_render_profile(run.get("render_profile"))
        if run_profile is not None:
            return run_profile, "explicit"

    latest_profile = _coerce_render_profile(baseline_payload.get("latest_render_profile"))
    if latest_profile is not None:
        return latest_profile, "explicit"

    inferred_profile = _infer_legacy_pack_profile(
        baseline_dir=baseline_dir,
        project_root=project_root,
        source_manifest_path=_coerce_optional_string((run or {}).get("source_manifest_path")),
        source_artefact_dir=_coerce_optional_string((run or {}).get("source_artefact_dir")),
    )
    if inferred_profile is not None:
        return inferred_profile, "legacy_inferred"

    return None, "missing"


def _matching_target_detail(payload: dict[str, Any], target_slug: str) -> dict[str, Any]:
    """Return the raw target detail payload for the requested target, if any."""

    raw = payload.get("target_details")
    if not isinstance(raw, list):
        return {}

    for item in raw:
        if isinstance(item, dict) and item.get("target_slug") == target_slug:
            return item
    return {}


def _matching_approval_run(payload: dict[str, Any], target_slug: str) -> dict[str, Any] | None:
    """Return the newest approval run that explicitly touched the target slug."""

    raw = payload.get("approval_runs")
    if not isinstance(raw, list):
        return None

    for item in reversed(raw):
        if not isinstance(item, dict):
            continue
        approved_targets = item.get("approved_targets")
        if isinstance(approved_targets, list) and target_slug in approved_targets:
            return item
    return None


def _coerce_render_profile(raw: object) -> RenderProfile | None:
    """Validate optional render-profile payloads from legacy JSON manifests."""

    if raw is None:
        return None
    try:
        return RenderProfile.model_validate(raw)
    except Exception:
        return None


def _infer_legacy_pack_profile(
    *,
    baseline_dir: Path,
    project_root: Path,
    source_manifest_path: str | None,
    source_artefact_dir: str | None,
) -> RenderProfile | None:
    """Infer a conservative profile for older pack baseline manifests."""

    if source_manifest_path:
        resolved_manifest_path = _resolve_manifest_path(source_manifest_path, root=project_root)
        if resolved_manifest_path.exists():
            try:
                manifest = load_pack_render_manifest(resolved_manifest_path)
            except Exception:
                manifest = None
            if manifest is not None:
                return _resolve_render_profile(manifest.kind, manifest.render_profile)

    data_mode = infer_data_mode_from_paths(
        baseline_dir.as_posix(),
        source_manifest_path,
        source_artefact_dir,
    ) or "live"
    workflow_kind = "pack_render_slide" if source_manifest_path else "pack_run"
    return build_render_profile(workflow_kind=workflow_kind, data_mode=data_mode)


def _resolve_render_profile(
    workflow_kind: Literal["pack_run", "pack_render_slide"],
    profile: RenderProfile | None,
) -> RenderProfile:
    """Return the manifest profile, or a partial legacy fallback when absent."""

    if profile is not None:
        return profile
    return build_render_profile(workflow_kind=workflow_kind, data_mode=None)


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
    "PackRenderComparison",
    "PackRenderComparisonEntry",
    "RenderComparisonMetrics",
    "compare_pack_render_manifest",
    "load_pack_render_manifest",
    "write_pack_render_comparison",
]
