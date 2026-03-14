"""Audit helpers for pack render manifests.

Focused pack verification has good low-level primitives now: render, compare,
inspect, and approve. These helpers add the missing triage layer by summarizing
which rendered targets are clean, which need attention, and which inspections
were emitted to help diagnose those failures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from praeparo.pack.render_compare import (
    PackRenderComparison,
    PackRenderComparisonEntry,
    compare_pack_render_manifest,
    write_pack_render_comparison,
)
from praeparo.pack.render_inspect import (
    PackRenderInspection,
    inspect_pack_render_target,
    write_pack_render_inspection,
)
from praeparo.pack.render_manifest import (
    PackRenderManifestEntry,
    load_pack_render_manifest,
    select_pack_render_targets,
)


class PackRenderAuditEntry(BaseModel):
    """Audit summary for one rendered slide or placeholder target."""

    slide_slug: str
    target_slug: str
    status: Literal["match", "mismatch", "missing_baseline", "missing_png", "unchecked"]
    needs_attention: bool = False
    slide_id: str | None = None
    slide_title: str | None = None
    slide_template: str | None = None
    artifact_label: str
    placeholder_id: str | None = None
    visual_path: str | None = None
    visual_type: str | None = None
    png_path: str | None = None
    inspection_path: str | None = None
    comparison: PackRenderComparisonEntry | None = None


class PackRenderAudit(BaseModel):
    """Portable summary of a pack verification pass."""

    kind: Literal["pack_render_audit"] = "pack_render_audit"
    manifest_path: str
    compare_manifest_path: str | None = None
    baseline_dir: str | None = None
    pack_path: str
    artefact_root: str
    partial_failure: bool = False
    warnings: list[str] = Field(default_factory=list)
    requested_slides: list[str] = Field(default_factory=list)
    audited_targets: int
    matched_targets: int
    attention_targets: int
    unchecked_targets: int
    mismatched_targets: int
    missing_baseline_targets: int
    missing_png_targets: int
    inspections_generated: int
    targets: list[PackRenderAuditEntry] = Field(default_factory=list)


def audit_pack_render_manifest(
    *,
    manifest_path: Path,
    selectors: Sequence[str] = (),
    baseline_dir: Path | None = None,
    compare_manifest_path: Path | None = None,
    compare_output_dir: Path | None = None,
    inspection_output_dir: Path | None = None,
    project_root: Path | None = None,
    emit_inspections: bool = True,
) -> PackRenderAudit:
    """Audit a rendered pack and summarize which targets need attention.

    Start from the render manifest and the optional baseline configuration. If a
    baseline directory is supplied, refresh the compare manifest first so the
    audit reflects the latest PNG diff results. Then walk the selected targets,
    generate inspection payloads for anything that failed comparison, and emit a
    stable audit summary for humans, CI, or future MCP surfaces.
    """

    render_manifest = load_pack_render_manifest(manifest_path)
    resolution_root = _resolve_project_root(project_root)
    requested = tuple(str(item) for item in selectors)
    entries = select_pack_render_targets(render_manifest.rendered_targets, selectors=requested)
    if requested and not entries:
        joined = ", ".join(requested)
        raise ValueError(f"No rendered targets matched selectors: {joined}")

    resolved_compare_manifest_path: Path | None = None
    comparison: PackRenderComparison | None = None
    resolved_baseline_dir: Path | None = None

    # Refresh compare outputs when a baseline directory is supplied. Otherwise,
    # fold in any existing compare manifest so audit stays useful after a prior
    # verification run.
    if baseline_dir is not None:
        resolved_baseline_dir = baseline_dir.expanduser().resolve(strict=False)
        compare_dir = compare_output_dir or manifest_path.parent / "_comparisons"
        comparison = compare_pack_render_manifest(
            manifest_path=manifest_path,
            baseline_dir=resolved_baseline_dir,
            output_dir=compare_dir,
            selectors=requested,
            project_root=resolution_root,
        )
        resolved_compare_manifest_path = compare_dir / "compare.manifest.json"
        write_pack_render_comparison(comparison, resolved_compare_manifest_path)
    else:
        resolved_compare_manifest_path = _resolve_compare_manifest_path(
            manifest_path=manifest_path,
            compare_manifest_path=compare_manifest_path,
        )
        if resolved_compare_manifest_path is not None:
            comparison = _load_pack_render_comparison(resolved_compare_manifest_path)

    comparison_by_target = _comparison_index(comparison)
    inspection_dir = inspection_output_dir or (manifest_path.parent / "_inspections")

    matched = 0
    attention = 0
    unchecked = 0
    mismatched = 0
    missing_baseline = 0
    missing_png = 0
    inspections_generated = 0
    audit_entries: list[PackRenderAuditEntry] = []

    for entry in entries:
        comparison_entry = comparison_by_target.get(entry.target_slug)
        status = comparison_entry.status if comparison_entry is not None else "unchecked"
        needs_attention = status in {"mismatch", "missing_baseline", "missing_png"}

        if status == "match":
            matched += 1
        elif status == "unchecked":
            unchecked += 1
        else:
            attention += 1
            if status == "mismatch":
                mismatched += 1
            elif status == "missing_baseline":
                missing_baseline += 1
            elif status == "missing_png":
                missing_png += 1

        inspection_path: str | None = None

        # When a target needs attention, emit a focused inspection payload so
        # callers can immediately see the resolved visual path, sidecars, and
        # compare verdict without running another command.
        if emit_inspections and needs_attention:
            inspection = inspect_pack_render_target(
                manifest_path=manifest_path,
                selectors=(entry.target_slug,),
                compare_manifest_path=resolved_compare_manifest_path,
                project_root=resolution_root,
            )
            target_inspection_path = inspection_dir / f"{entry.target_slug}.inspect.json"
            write_pack_render_inspection(inspection, target_inspection_path)
            inspection_path = _display_path(target_inspection_path, root=resolution_root)
            inspections_generated += 1

        audit_entries.append(
            PackRenderAuditEntry(
                slide_slug=entry.slide_slug,
                target_slug=entry.target_slug,
                status=status,
                needs_attention=needs_attention,
                slide_id=entry.slide_id,
                slide_title=entry.slide_title,
                slide_template=entry.slide_template,
                artifact_label=entry.artifact_label,
                placeholder_id=entry.placeholder_id,
                visual_path=entry.visual_path,
                visual_type=entry.visual_type,
                png_path=entry.png_path,
                inspection_path=inspection_path,
                comparison=comparison_entry,
            )
        )

    return PackRenderAudit(
        manifest_path=_display_path(manifest_path, root=resolution_root),
        compare_manifest_path=(
            _display_path(resolved_compare_manifest_path, root=resolution_root)
            if resolved_compare_manifest_path is not None and resolved_compare_manifest_path.exists()
            else None
        ),
        baseline_dir=(
            _display_path(resolved_baseline_dir, root=resolution_root)
            if resolved_baseline_dir is not None
            else None
        ),
        pack_path=render_manifest.pack_path,
        artefact_root=render_manifest.artefact_root,
        partial_failure=render_manifest.partial_failure,
        warnings=list(render_manifest.warnings),
        requested_slides=list(requested),
        audited_targets=len(audit_entries),
        matched_targets=matched,
        attention_targets=attention,
        unchecked_targets=unchecked,
        mismatched_targets=mismatched,
        missing_baseline_targets=missing_baseline,
        missing_png_targets=missing_png,
        inspections_generated=inspections_generated,
        targets=audit_entries,
    )


def write_pack_render_audit(audit: PackRenderAudit, path: Path) -> None:
    """Persist a pack audit summary using a stable JSON encoding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(audit.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _comparison_index(comparison: PackRenderComparison | None) -> dict[str, PackRenderComparisonEntry]:
    """Index comparison rows by target slug for quick audit lookups."""

    if comparison is None:
        return {}
    return {item.target_slug: item for item in comparison.comparisons}


def _load_pack_render_comparison(path: Path) -> PackRenderComparison:
    """Load a comparison manifest from disk."""

    return PackRenderComparison.model_validate_json(path.read_text(encoding="utf-8"))


def _resolve_compare_manifest_path(*, manifest_path: Path, compare_manifest_path: Path | None) -> Path | None:
    """Resolve an explicit or adjacent compare manifest path."""

    if compare_manifest_path is not None:
        resolved = compare_manifest_path.expanduser().resolve(strict=False)
        if not resolved.exists():
            raise ValueError(f"Compare manifest does not exist: {compare_manifest_path}")
        return resolved

    candidate = manifest_path.parent / "_comparisons" / "compare.manifest.json"
    if candidate.exists():
        return candidate.resolve(strict=False)
    return None


def _resolve_project_root(project_root: Path | None) -> Path:
    """Resolve the root used for cwd-relative audit paths."""

    if project_root is None:
        return Path.cwd().resolve()
    return project_root.expanduser().resolve(strict=False)


def _display_path(path: Path, *, root: Path) -> str:
    """Prefer project-root-relative paths so audit payloads stay portable."""

    resolved = path.expanduser().resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


__all__ = [
    "PackRenderAudit",
    "PackRenderAuditEntry",
    "audit_pack_render_manifest",
    "write_pack_render_audit",
]
