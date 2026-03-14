"""Human-reviewable summaries for focused pack verification flows.

Compare and audit already tell agents whether a rendered target matched its
baseline and which artefacts to inspect next. These helpers package that same
information into one review bundle so a human can confirm the agent's decision
without replaying shell history or reading raw logs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from praeparo.pack.render_approve import (
    PackRenderBaselineApprovalRun,
    PackRenderBaselineExemption,
    PackRenderBaselineManifest,
    load_pack_render_baseline_payload,
)
from praeparo.pack.render_audit import audit_pack_render_manifest
from praeparo.review_profiles import RenderProfile, describe_render_profile

ReviewStatus = Literal[
    "approved",
    "exempt",
    "mismatch",
    "missing_baseline",
    "missing_png",
    "profile_mismatch",
    "missing_profile",
    "unchecked",
]


class PackRenderReviewEntry(BaseModel):
    """One target row in a human-reviewable pack verification bundle."""

    slide_slug: str
    target_slug: str
    review_status: ReviewStatus
    status_reason: str | None = None
    inspection_path: str | None = None


class PackRenderReview(BaseModel):
    """Portable review surface for one focused pack verification pass."""

    kind: Literal["pack_render_review"] = "pack_render_review"
    manifest_path: str
    audit_manifest_path: str | None = None
    compare_manifest_path: str | None = None
    baseline_dir: str
    baseline_manifest_path: str | None = None
    pack_path: str
    artefact_root: str
    render_profile: RenderProfile | None = None
    render_profile_label: str
    reviewed_targets: int
    approved_targets: int
    exempt_targets: int
    attention_targets: int
    unchecked_targets: int
    warnings: list[str] = Field(default_factory=list)
    approval_history: list[PackRenderBaselineApprovalRun] = Field(default_factory=list)
    exemptions: list[PackRenderBaselineExemption] = Field(default_factory=list)
    targets: list[PackRenderReviewEntry] = Field(default_factory=list)


def review_pack_render_manifest(
    *,
    manifest_path: Path,
    baseline_dir: Path,
    selectors: Sequence[str] = (),
    compare_output_dir: Path | None = None,
    inspection_output_dir: Path | None = None,
    project_root: Path | None = None,
    emit_inspections: bool = True,
) -> PackRenderReview:
    """Build one review bundle for a focused pack verification pass.

    Start from the audit flow because it already knows how to refresh compare
    results and emit inspections for targets that need attention. Then fold in
    the baseline approval ledger and any explicit exemptions so the final JSON
    answers both "did it match?" and "is this target required or exempt?"
    """

    audit = audit_pack_render_manifest(
        manifest_path=manifest_path,
        selectors=selectors,
        baseline_dir=baseline_dir,
        compare_output_dir=compare_output_dir,
        inspection_output_dir=inspection_output_dir,
        project_root=project_root,
        emit_inspections=emit_inspections,
    )
    resolution_root = _resolve_project_root(project_root)
    baseline_manifest_path = baseline_dir.expanduser().resolve(strict=False) / "baseline.manifest.json"
    baseline_manifest = _load_baseline_manifest(baseline_manifest_path)
    exemptions_by_target = {
        item.target_slug: item for item in (baseline_manifest.exemptions if baseline_manifest is not None else [])
    }

    approved = 0
    exempt = 0
    attention = 0
    unchecked = 0
    targets: list[PackRenderReviewEntry] = []

    # Classify each target once so humans can see the same contract the agent
    # relied on: approved, exempt, or still needing work.
    for target in audit.targets:
        review_status, reason = _classify_target(target.status, exemptions_by_target.get(target.target_slug))
        if review_status == "approved":
            approved += 1
        elif review_status == "exempt":
            exempt += 1
        elif review_status == "unchecked":
            unchecked += 1
        else:
            attention += 1

        targets.append(
            PackRenderReviewEntry(
                slide_slug=target.slide_slug,
                target_slug=target.target_slug,
                review_status=review_status,
                status_reason=reason or (target.comparison.message if target.comparison is not None else None),
                inspection_path=target.inspection_path,
            )
        )

    return PackRenderReview(
        manifest_path=audit.manifest_path,
        audit_manifest_path=None,
        compare_manifest_path=audit.compare_manifest_path,
        baseline_dir=_display_path(baseline_dir, root=resolution_root),
        baseline_manifest_path=(
            _display_path(baseline_manifest_path, root=resolution_root)
            if baseline_manifest_path.exists()
            else None
        ),
        pack_path=audit.pack_path,
        artefact_root=audit.artefact_root,
        render_profile=audit.render_profile,
        render_profile_label=describe_render_profile(audit.render_profile),
        reviewed_targets=len(targets),
        approved_targets=approved,
        exempt_targets=exempt,
        attention_targets=attention,
        unchecked_targets=unchecked,
        warnings=audit.warnings,
        approval_history=(baseline_manifest.approval_runs if baseline_manifest is not None else []),
        exemptions=(baseline_manifest.exemptions if baseline_manifest is not None else []),
        targets=targets,
    )


def write_pack_render_review(review: PackRenderReview, path: Path) -> None:
    """Persist a pack review bundle using a stable JSON encoding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(review.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _load_baseline_manifest(path: Path) -> PackRenderBaselineManifest | None:
    """Load the typed baseline manifest when one exists beside the PNGs."""

    payload = load_pack_render_baseline_payload(path)
    if not payload:
        return None
    return PackRenderBaselineManifest.model_validate(payload)


def _classify_target(
    status: str,
    exemption: PackRenderBaselineExemption | None,
) -> tuple[ReviewStatus, str | None]:
    """Map audit statuses into the final review vocabulary."""

    if status == "match":
        return "approved", None
    if status == "missing_baseline" and exemption is not None:
        return "exempt", exemption.reason
    if status == "unchecked":
        return "unchecked", None
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
    "PackRenderReview",
    "PackRenderReviewEntry",
    "review_pack_render_manifest",
    "write_pack_render_review",
]
