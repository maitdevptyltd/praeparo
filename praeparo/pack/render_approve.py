"""Baseline approval helpers for pack render manifests.

Render, compare, and inspect give focused pack workflows the evidence needed to
decide whether a change is acceptable. These helpers close that loop by
promoting selected rendered PNGs into the approved baseline set and recording
the lineage needed to audit that decision later.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field, ValidationError

from praeparo.pack.render_manifest import (
    PackRenderManifest,
    PackRenderManifestEntry,
    load_pack_render_manifest,
    select_pack_render_targets,
)


class PackRenderBaselineEntry(BaseModel):
    """Approval record for one baseline PNG."""

    slide_slug: str
    target_slug: str
    artifact_label: str
    slide_id: str | None = None
    slide_title: str | None = None
    slide_template: str | None = None
    placeholder_id: str | None = None
    visual_path: str | None = None
    visual_type: str | None = None
    baseline_path: str
    source_png_path: str
    approved_at: str
    note: str | None = None


class PackRenderBaselineManifest(BaseModel):
    """Portable summary of approved slide PNG baselines for one pack."""

    kind: Literal["pack_slide_baselines"] = "pack_slide_baselines"
    pack_path: str
    baseline_dir: str
    source_manifest_path: str
    source_artefact_dir: str
    updated_at: str
    approval_note: str | None = None
    targets: list[str] = Field(default_factory=list)
    target_details: list[PackRenderBaselineEntry] = Field(default_factory=list)


class PackRenderBaselineApproval(BaseModel):
    """Result summary for one approval command invocation."""

    kind: Literal["pack_slide_baseline_approval"] = "pack_slide_baseline_approval"
    baseline_dir: str
    baseline_manifest_path: str
    approved_targets: list[PackRenderBaselineEntry] = Field(default_factory=list)
    baseline_manifest: PackRenderBaselineManifest


def approve_pack_render_manifest(
    *,
    manifest_path: Path,
    baseline_dir: Path,
    selectors: Sequence[str],
    project_root: Path | None = None,
    note: str | None = None,
    approved_at: str | None = None,
) -> PackRenderBaselineApproval:
    """Approve selected rendered PNG targets into the baseline directory.

    First resolve each requested selector to exactly one rendered target. Then
    copy the current PNG into `<baseline_dir>/<target_slug>.png` and merge that
    decision into `baseline.manifest.json`, preserving any project-specific
    top-level metadata that already exists there.
    """

    requested = tuple(str(item) for item in selectors)
    if not requested:
        raise ValueError("Provide at least one selector when approving pack slide baselines.")

    render_manifest = load_pack_render_manifest(manifest_path)
    resolution_root = _resolve_project_root(project_root)
    resolved_baseline_dir = baseline_dir.expanduser().resolve(strict=False)
    resolved_baseline_dir.mkdir(parents=True, exist_ok=True)

    approval_time = approved_at or _default_approved_at()

    # Resolve selectors one by one so approval remains explicit. A single broad
    # slide selector should not silently promote multiple placeholder targets.
    selected_entries = _select_targets_for_approval(render_manifest.rendered_targets, selectors=requested)

    # Promote the selected PNGs before we touch the manifest so a failed copy
    # cannot leave the approval ledger claiming files that do not exist.
    approved_targets = [
        _approve_target(
            entry=entry,
            baseline_dir=resolved_baseline_dir,
            project_root=resolution_root,
            approved_at=approval_time,
            note=note,
        )
        for entry in selected_entries
    ]

    baseline_manifest_path = resolved_baseline_dir / "baseline.manifest.json"
    existing_payload = _load_existing_baseline_payload(baseline_manifest_path)
    baseline_manifest = _merge_baseline_manifest(
        render_manifest=render_manifest,
        manifest_path=manifest_path,
        baseline_dir=resolved_baseline_dir,
        approved_targets=approved_targets,
        existing_payload=existing_payload,
        project_root=resolution_root,
        approved_at=approval_time,
        note=note,
    )
    write_pack_render_baseline_manifest(
        baseline_manifest,
        baseline_manifest_path,
        existing_payload=existing_payload,
    )

    return PackRenderBaselineApproval(
        baseline_dir=_display_path(resolved_baseline_dir, root=resolution_root),
        baseline_manifest_path=_display_path(baseline_manifest_path, root=resolution_root),
        approved_targets=approved_targets,
        baseline_manifest=baseline_manifest,
    )


def write_pack_render_baseline_manifest(
    manifest: PackRenderBaselineManifest,
    path: Path,
    *,
    existing_payload: dict[str, Any] | None = None,
) -> None:
    """Persist a baseline manifest while preserving unrelated project metadata."""

    payload = dict(existing_payload or {})

    # Keep project-specific metadata like customer keys or reference months, but
    # overwrite the fields that Praeparo now manages for approvals.
    for key in {
        "kind",
        "pack_path",
        "baseline_dir",
        "source_manifest_path",
        "source_artefact_dir",
        "updated_at",
        "approval_note",
        "targets",
        "target_details",
    }:
        payload.pop(key, None)

    payload.update(manifest.model_dump(mode="json"))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _select_targets_for_approval(
    entries: Sequence[PackRenderManifestEntry],
    *,
    selectors: Sequence[str],
) -> list[PackRenderManifestEntry]:
    """Resolve each selector to exactly one target while preserving selector order."""

    selected_by_slug: dict[str, PackRenderManifestEntry] = {}

    for selector in selectors:
        matches = select_pack_render_targets(entries, selectors=(selector,))
        if not matches:
            raise ValueError(f"No rendered targets matched selector: {selector}")

        if len(matches) > 1:
            joined = ", ".join(item.target_slug for item in matches)
            raise ValueError(
                "Selector matched multiple rendered targets. "
                f"Choose a more specific target slug for '{selector}': {joined}"
            )

        entry = matches[0]
        selected_by_slug.setdefault(entry.target_slug, entry)

    return list(selected_by_slug.values())


def _approve_target(
    *,
    entry: PackRenderManifestEntry,
    baseline_dir: Path,
    project_root: Path,
    approved_at: str,
    note: str | None,
) -> PackRenderBaselineEntry:
    """Copy one rendered PNG into the baseline set and record its lineage."""

    if not entry.png_path:
        raise ValueError(
            f"Rendered target '{entry.target_slug}' does not record a PNG path in render.manifest.json."
        )

    source_png_path = _resolve_manifest_path(entry.png_path, root=project_root)
    if not source_png_path.exists():
        raise ValueError(
            "Rendered PNG path does not exist for target "
            f"'{entry.target_slug}': {_display_path(source_png_path, root=project_root)}"
        )

    baseline_path = baseline_dir / f"{entry.target_slug}.png"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_png_path, baseline_path)

    return PackRenderBaselineEntry(
        slide_slug=entry.slide_slug,
        target_slug=entry.target_slug,
        artifact_label=entry.artifact_label,
        slide_id=entry.slide_id,
        slide_title=entry.slide_title,
        slide_template=entry.slide_template,
        placeholder_id=entry.placeholder_id,
        visual_path=entry.visual_path,
        visual_type=entry.visual_type,
        baseline_path=_display_path(baseline_path, root=project_root),
        source_png_path=_display_path(source_png_path, root=project_root),
        approved_at=approved_at,
        note=note,
    )


def _merge_baseline_manifest(
    *,
    render_manifest: PackRenderManifest,
    manifest_path: Path,
    baseline_dir: Path,
    approved_targets: Sequence[PackRenderBaselineEntry],
    existing_payload: dict[str, Any],
    project_root: Path,
    approved_at: str,
    note: str | None,
) -> PackRenderBaselineManifest:
    """Combine new approvals with any existing baseline ledger entries."""

    existing_targets = _parse_existing_targets(existing_payload.get("targets"))
    existing_details = _parse_existing_target_details(existing_payload.get("target_details"))

    target_slugs = _merge_target_slugs(existing_targets, [item.target_slug for item in approved_targets])
    target_details = _merge_target_details(existing_details, approved_targets)

    return PackRenderBaselineManifest(
        pack_path=render_manifest.pack_path,
        baseline_dir=_display_path(baseline_dir, root=project_root),
        source_manifest_path=_display_path(manifest_path, root=project_root),
        source_artefact_dir=render_manifest.artefact_root,
        updated_at=approved_at,
        approval_note=note if note is not None else _coerce_optional_string(existing_payload.get("approval_note")),
        targets=target_slugs,
        target_details=target_details,
    )


def _parse_existing_targets(raw: Any) -> list[str]:
    """Validate the legacy `targets` list when one already exists."""

    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError("Existing baseline.manifest.json field 'targets' must be a list of strings.")
    return list(raw)


def _parse_existing_target_details(raw: Any) -> list[PackRenderBaselineEntry]:
    """Validate previously recorded per-target approval details."""

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Existing baseline.manifest.json field 'target_details' must be a list.")

    details: list[PackRenderBaselineEntry] = []
    for item in raw:
        try:
            details.append(PackRenderBaselineEntry.model_validate(item))
        except ValidationError as exc:
            raise ValueError("Existing baseline.manifest.json contains an invalid target_details entry.") from exc
    return details


def _merge_target_slugs(existing: Sequence[str], approved: Sequence[str]) -> list[str]:
    """Preserve the existing target order and append newly approved slugs."""

    merged = list(existing)
    known = set(existing)
    for target_slug in approved:
        if target_slug in known:
            continue
        merged.append(target_slug)
        known.add(target_slug)
    return merged


def _merge_target_details(
    existing: Sequence[PackRenderBaselineEntry],
    approved: Sequence[PackRenderBaselineEntry],
) -> list[PackRenderBaselineEntry]:
    """Replace approved target details in-place while preserving unrelated entries."""

    merged = list(existing)
    indices = {item.target_slug: index for index, item in enumerate(existing)}

    for item in approved:
        existing_index = indices.get(item.target_slug)
        if existing_index is None:
            merged.append(item)
            indices[item.target_slug] = len(merged) - 1
            continue
        merged[existing_index] = item

    return merged


def _load_existing_baseline_payload(path: Path) -> dict[str, Any]:
    """Load the existing baseline manifest payload, if present."""

    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Baseline manifest is not valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Existing baseline.manifest.json must contain a top-level object.")

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
    "PackRenderBaselineApproval",
    "PackRenderBaselineEntry",
    "PackRenderBaselineManifest",
    "approve_pack_render_manifest",
    "write_pack_render_baseline_manifest",
]
