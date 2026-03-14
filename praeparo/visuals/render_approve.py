"""Baseline approval helpers for standalone visual render manifests.

Visual inspection and comparison establish whether a render changed and whether
the new output matches the current approved reference. These helpers close that
loop by promoting the inspected PNG into the baseline set and recording the
lineage needed to audit that decision later.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from praeparo.review_profiles import RenderProfile
from praeparo.visuals.render_manifest import VisualRenderManifest, load_visual_render_manifest


class VisualRenderBaselineApprovalRun(BaseModel):
    """Approval record for one update to the visual baseline."""

    approved_at: str | None = None
    source_manifest_path: str | None = None
    source_artefact_dir: str | None = None
    source_png_path: str | None = None
    approval_note: str | None = None
    render_profile: RenderProfile | None = None


class VisualRenderBaselineManifest(BaseModel):
    """Portable summary of the approved baseline for one visual config."""

    kind: Literal["visual_baseline"] = "visual_baseline"
    config_path: str
    baseline_key: str
    visual_type: str
    baseline_dir: str
    baseline_path: str
    source_manifest_path: str
    source_artefact_dir: str
    source_png_path: str
    updated_at: str
    approval_note: str | None = None
    render_profile: RenderProfile | None = None
    approval_runs: list[VisualRenderBaselineApprovalRun] = Field(default_factory=list)
    exemption_reason: str | None = None


class VisualRenderBaselineApproval(BaseModel):
    """Result summary for one visual baseline approval invocation."""

    kind: Literal["visual_baseline_approval"] = "visual_baseline_approval"
    baseline_dir: str
    baseline_manifest_path: str
    baseline_manifest: VisualRenderBaselineManifest


def approve_visual_render_manifest(
    *,
    manifest_path: Path,
    baseline_dir: Path,
    project_root: Path | None = None,
    note: str | None = None,
    approved_at: str | None = None,
) -> VisualRenderBaselineApproval:
    """Approve a visual render manifest's primary PNG into the baseline set."""

    manifest = load_visual_render_manifest(manifest_path)
    resolution_root = _resolve_project_root(project_root)
    resolved_baseline_dir = baseline_dir.expanduser().resolve(strict=False)
    resolved_baseline_dir.mkdir(parents=True, exist_ok=True)
    approval_time = approved_at or _default_approved_at()
    baseline_manifest_path = resolved_baseline_dir / "baseline.manifest.json"
    existing_payload = load_visual_render_baseline_payload(baseline_manifest_path)

    baseline_manifest = _approve_manifest(
        manifest=manifest,
        manifest_path=manifest_path,
        baseline_dir=resolved_baseline_dir,
        existing_payload=existing_payload,
        project_root=resolution_root,
        approved_at=approval_time,
        note=note if note is not None else _coerce_optional_string(existing_payload.get("approval_note")),
    )

    write_visual_render_baseline_manifest(
        baseline_manifest,
        baseline_manifest_path,
        existing_payload=existing_payload,
    )

    return VisualRenderBaselineApproval(
        baseline_dir=_display_path(resolved_baseline_dir, root=resolution_root),
        baseline_manifest_path=_display_path(baseline_manifest_path, root=resolution_root),
        baseline_manifest=baseline_manifest,
    )


def write_visual_render_baseline_manifest(
    manifest: VisualRenderBaselineManifest,
    path: Path,
    *,
    existing_payload: dict[str, Any] | None = None,
) -> None:
    """Persist a visual baseline manifest while preserving unrelated metadata."""

    payload = dict(existing_payload or {})
    for key in {
        "kind",
        "config_path",
        "baseline_key",
        "visual_type",
        "baseline_dir",
        "baseline_path",
        "source_manifest_path",
        "source_artefact_dir",
        "source_png_path",
        "updated_at",
        "approval_note",
        "render_profile",
        "approval_runs",
        "exemption_reason",
    }:
        payload.pop(key, None)

    payload.update(manifest.model_dump(mode="json"))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _approve_manifest(
    *,
    manifest: VisualRenderManifest,
    manifest_path: Path,
    baseline_dir: Path,
    existing_payload: dict[str, Any],
    project_root: Path,
    approved_at: str,
    note: str | None,
) -> VisualRenderBaselineManifest:
    """Copy the current PNG into the baseline directory and record its lineage."""

    if not manifest.png_path:
        raise ValueError("Visual render manifest did not record a PNG path.")

    source_png_path = _resolve_manifest_path(manifest.png_path, root=project_root)
    if not source_png_path.exists():
        raise ValueError(
            "Rendered PNG path does not exist: "
            f"{_display_path(source_png_path, root=project_root)}"
        )

    baseline_path = baseline_dir / f"{manifest.baseline_key}.png"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_png_path, baseline_path)

    return VisualRenderBaselineManifest(
        config_path=manifest.config_path,
        baseline_key=manifest.baseline_key,
        visual_type=manifest.visual_type,
        baseline_dir=_display_path(baseline_dir, root=project_root),
        baseline_path=_display_path(baseline_path, root=project_root),
        source_manifest_path=_display_path(manifest_path, root=project_root),
        source_artefact_dir=manifest.artefact_root,
        source_png_path=_display_path(source_png_path, root=project_root),
        updated_at=approved_at,
        approval_note=note,
        render_profile=manifest.render_profile,
        approval_runs=_merge_approval_runs(
            existing_payload=existing_payload,
            approved_at=approved_at,
            manifest_path=manifest_path,
            artefact_root=manifest.artefact_root,
            source_png_path=_display_path(source_png_path, root=project_root),
            note=note,
            render_profile=manifest.render_profile,
            project_root=project_root,
        ),
        exemption_reason=_coerce_optional_string(existing_payload.get("exemption_reason")),
    )


def _merge_approval_runs(
    *,
    existing_payload: dict[str, Any],
    approved_at: str,
    manifest_path: Path,
    artefact_root: str,
    source_png_path: str,
    note: str | None,
    render_profile: RenderProfile | None,
    project_root: Path,
) -> list[VisualRenderBaselineApprovalRun]:
    """Append the latest approval while preserving any earlier review history."""

    merged = _parse_existing_approval_runs(existing_payload.get("approval_runs"))
    merged.append(
        VisualRenderBaselineApprovalRun(
            approved_at=approved_at,
            source_manifest_path=_display_path(manifest_path, root=project_root),
            source_artefact_dir=artefact_root,
            source_png_path=source_png_path,
            approval_note=note,
            render_profile=render_profile,
        )
    )
    return merged


def _parse_existing_approval_runs(raw: Any) -> list[VisualRenderBaselineApprovalRun]:
    """Validate any pre-existing approval ledger entries."""

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Existing baseline.manifest.json field 'approval_runs' must be a list.")

    runs: list[VisualRenderBaselineApprovalRun] = []
    for item in raw:
        runs.append(VisualRenderBaselineApprovalRun.model_validate(item))
    return runs


def load_visual_render_baseline_payload(path: Path) -> dict[str, Any]:
    """Load the existing baseline manifest payload, if present."""

    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Baseline manifest is not valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Existing baseline.manifest.json must contain a top-level object.")

    if "approval_note" in payload:
        _coerce_optional_string(payload["approval_note"])

    return payload


def _coerce_optional_string(raw: Any) -> str | None:
    """Keep optional string metadata only when it already has the right shape."""

    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("Existing baseline.manifest.json field 'approval_note' must be a string.")
    return raw


def _default_approved_at() -> str:
    """Capture a human-readable local approval timestamp for audit trails."""

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _resolve_project_root(project_root: Path | None) -> Path:
    """Resolve the root used for cwd-relative manifest and baseline paths."""

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
    """Prefer project-root-relative paths so approval manifests stay portable."""

    resolved = path.expanduser().resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


__all__ = [
    "VisualRenderBaselineApproval",
    "VisualRenderBaselineApprovalRun",
    "VisualRenderBaselineManifest",
    "approve_visual_render_manifest",
    "load_visual_render_baseline_payload",
    "write_visual_render_baseline_manifest",
]
