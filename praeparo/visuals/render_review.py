"""Human-reviewable summaries for standalone visual verification flows."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from praeparo.review_profiles import RenderProfile, describe_render_profile
from praeparo.visuals.render_approve import (
    VisualRenderBaselineApprovalRun,
    VisualRenderBaselineManifest,
    load_visual_render_baseline_payload,
)
from praeparo.visuals.render_compare import (
    VisualRenderComparison,
    compare_visual_render_manifest,
    write_visual_render_comparison,
)

ReviewStatus = Literal[
    "approved",
    "exempt",
    "mismatch",
    "missing_baseline",
    "missing_png",
    "profile_mismatch",
    "missing_profile",
]


class VisualRenderReview(BaseModel):
    """Portable review surface for one focused visual verification pass."""

    kind: Literal["visual_render_review"] = "visual_render_review"
    manifest_path: str
    compare_manifest_path: str | None = None
    baseline_dir: str
    baseline_manifest_path: str | None = None
    baseline_key: str
    config_path: str
    visual_type: str
    render_profile: RenderProfile | None = None
    render_profile_label: str
    review_status: ReviewStatus
    status_reason: str | None = None
    approval_history: list[VisualRenderBaselineApprovalRun] = Field(default_factory=list)
    exemption_reason: str | None = None
    comparison: VisualRenderComparison


def review_visual_render_manifest(
    *,
    manifest_path: Path,
    baseline_dir: Path,
    output_dir: Path,
    project_root: Path | None = None,
) -> VisualRenderReview:
    """Build one review bundle for a standalone visual verification pass."""

    comparison = compare_visual_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        output_dir=output_dir,
        project_root=project_root,
    )
    resolution_root = _resolve_project_root(project_root)
    compare_manifest_path = output_dir / "compare.manifest.json"
    write_visual_render_comparison(comparison, compare_manifest_path)
    baseline_manifest_path = baseline_dir.expanduser().resolve(strict=False) / "baseline.manifest.json"
    baseline_manifest = _load_baseline_manifest(baseline_manifest_path)
    review_status, reason = _classify_review_status(
        comparison.status,
        baseline_manifest.exemption_reason if baseline_manifest is not None else None,
    )

    return VisualRenderReview(
        manifest_path=comparison.manifest_path,
        compare_manifest_path=_display_path(compare_manifest_path, root=resolution_root),
        baseline_dir=comparison.baseline_dir,
        baseline_manifest_path=(
            _display_path(baseline_manifest_path, root=resolution_root)
            if baseline_manifest_path.exists()
            else None
        ),
        baseline_key=comparison.baseline_key,
        config_path=comparison.config_path,
        visual_type=comparison.visual_type,
        render_profile=comparison.render_profile,
        render_profile_label=describe_render_profile(comparison.render_profile),
        review_status=review_status,
        status_reason=reason or comparison.message,
        approval_history=(baseline_manifest.approval_runs if baseline_manifest is not None else []),
        exemption_reason=(baseline_manifest.exemption_reason if baseline_manifest is not None else None),
        comparison=comparison,
    )


def write_visual_render_review(review: VisualRenderReview, path: Path) -> None:
    """Persist a visual review bundle using a stable JSON encoding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(review.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _load_baseline_manifest(path: Path) -> VisualRenderBaselineManifest | None:
    """Load the typed visual baseline manifest when one exists."""

    payload = load_visual_render_baseline_payload(path)
    if not payload:
        return None
    return VisualRenderBaselineManifest.model_validate(payload)


def _classify_review_status(status: str, exemption_reason: str | None) -> tuple[ReviewStatus, str | None]:
    """Map compare statuses into the final review vocabulary."""

    if status == "match":
        return "approved", None
    if status == "missing_baseline" and exemption_reason:
        return "exempt", exemption_reason
    if status == "mismatch":
        return "mismatch", None
    if status == "missing_baseline":
        return "missing_baseline", None
    if status == "missing_png":
        return "missing_png", None
    if status == "profile_mismatch":
        return "profile_mismatch", None
    return "missing_profile", None


def _resolve_project_root(project_root: Path | None) -> Path:
    """Resolve the root used for cwd-relative review paths."""

    if project_root is None:
        return Path.cwd().resolve()
    return project_root.expanduser().resolve(strict=False)


def _display_path(path: Path, *, root: Path) -> str:
    """Prefer project-root-relative paths so review bundles stay portable."""

    resolved = path.expanduser().resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


__all__ = [
    "VisualRenderReview",
    "review_visual_render_manifest",
    "write_visual_render_review",
]
