"""Shared render-profile contracts for review and baseline workflows.

Pack and visual verification now have several cooperating surfaces: render
manifests, baseline approvals, comparisons, audits, and review bundles. They
all need one consistent way to describe how an artefact was produced so humans
and agents can reject profile drift before treating it as an image regression.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

RenderWorkflowKind = Literal["pack_run", "pack_render_slide", "visual_inspect"]
ProfileCheckStatus = Literal["match", "mismatch", "missing"]
ProfileSourceKind = Literal["explicit", "legacy_inferred", "missing"]

_DATA_MODE_PATTERN = re.compile(r"(?:^|/)data_mode=([^/]+)(?:/|$)")


class RenderProfile(BaseModel):
    """Portable provenance for one render or approval workflow."""

    workflow_kind: RenderWorkflowKind
    data_mode: str | None = None


class RenderProfileCheck(BaseModel):
    """Result of comparing a render manifest profile to a baseline profile."""

    status: ProfileCheckStatus
    render_profile: RenderProfile
    baseline_profile: RenderProfile | None = None
    baseline_profile_source: ProfileSourceKind = "missing"
    message: str | None = None


def build_render_profile(*, workflow_kind: RenderWorkflowKind, data_mode: str | None) -> RenderProfile:
    """Build one normalized render profile for manifests and approvals."""

    normalized_data_mode = None if data_mode is None else str(data_mode)
    return RenderProfile(workflow_kind=workflow_kind, data_mode=normalized_data_mode)


def describe_render_profile(profile: RenderProfile | None) -> str:
    """Render one short human-readable label for logs and review bundles."""

    if profile is None:
        return "unknown"

    if profile.data_mode:
        return f"{profile.workflow_kind}[data_mode={profile.data_mode}]"
    return profile.workflow_kind


def compare_render_profiles(
    *,
    render_profile: RenderProfile,
    baseline_profile: RenderProfile | None,
    baseline_profile_source: ProfileSourceKind,
    missing_message: str,
) -> RenderProfileCheck:
    """Compare profiles while distinguishing drift from missing provenance.

    A profile mismatch should fail fast because it means the render was checked
    against a different workflow contract. Missing provenance is also a failure,
    but it should be reported separately so operators can repair the baseline
    metadata instead of chasing a false visual regression.
    """

    if baseline_profile is None:
        return RenderProfileCheck(
            status="missing",
            render_profile=render_profile,
            baseline_profile=None,
            baseline_profile_source=baseline_profile_source,
            message=missing_message,
        )

    if render_profile.model_dump() == baseline_profile.model_dump():
        return RenderProfileCheck(
            status="match",
            render_profile=render_profile,
            baseline_profile=baseline_profile,
            baseline_profile_source=baseline_profile_source,
            message=(
                "Render profile matches baseline profile "
                f"{describe_render_profile(baseline_profile)}."
            ),
        )

    return RenderProfileCheck(
        status="mismatch",
        render_profile=render_profile,
        baseline_profile=baseline_profile,
        baseline_profile_source=baseline_profile_source,
        message=(
            "Render profile "
            f"{describe_render_profile(render_profile)} does not match baseline profile "
            f"{describe_render_profile(baseline_profile)}."
        ),
    )


def infer_data_mode_from_paths(*values: str | None) -> str | None:
    """Infer a legacy data mode from path fragments like `data_mode=mock/`.

    Older baseline manifests only hinted at mock/live provenance through the
    baseline directory or artefact paths. Keep that migration logic in one
    helper so compare and review flows can share it.
    """

    for value in values:
        if not value:
            continue
        match = _DATA_MODE_PATTERN.search(value)
        if match:
            return match.group(1)
    return None


__all__ = [
    "ProfileCheckStatus",
    "ProfileSourceKind",
    "RenderProfile",
    "RenderProfileCheck",
    "RenderWorkflowKind",
    "build_render_profile",
    "compare_render_profiles",
    "describe_render_profile",
    "infer_data_mode_from_paths",
]
