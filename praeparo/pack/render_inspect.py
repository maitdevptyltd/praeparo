"""Structured inspection helpers for one rendered pack target.

Render and compare manifests tell us what happened, but debugging still slows
down when callers have to stitch together related files by hand. These helpers
collapse the relevant render target, slide-scoped sidecars, and optional
comparison results into one inspection payload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from praeparo.pack.render_compare import PackRenderComparison, PackRenderComparisonEntry
from praeparo.pack.render_manifest import (
    PackRenderManifestEntry,
    RenderManifestArtifact,
    load_pack_render_manifest,
    select_pack_render_targets,
)


class RenderArtifactBuckets(BaseModel):
    """Normalized path buckets for a set of manifest artefacts."""

    png_paths: list[str] = Field(default_factory=list)
    dax_paths: list[str] = Field(default_factory=list)
    schema_paths: list[str] = Field(default_factory=list)
    data_paths: list[str] = Field(default_factory=list)
    html_paths: list[str] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    other_paths: list[str] = Field(default_factory=list)


class PackRenderInspection(BaseModel):
    """Inspection view for one rendered slide or placeholder target."""

    kind: Literal["pack_slide_inspection"] = "pack_slide_inspection"
    manifest_path: str
    compare_manifest_path: str | None = None
    pack_path: str
    artefact_root: str
    partial_failure: bool = False
    warnings: list[str] = Field(default_factory=list)
    slide_index: int | None = None
    slide_id: str | None = None
    slide_title: str | None = None
    slide_template: str | None = None
    slide_slug: str
    target_slug: str
    artifact_label: str
    placeholder_id: str | None = None
    visual_path: str | None = None
    visual_type: str | None = None
    png_path: str | None = None
    artefact_dir: str | None = None
    target_artefacts: list[RenderManifestArtifact] = Field(default_factory=list)
    target_artifact_buckets: RenderArtifactBuckets = Field(default_factory=RenderArtifactBuckets)
    metric_context_artefacts: list[RenderManifestArtifact] = Field(default_factory=list)
    evidence_artefacts: list[RenderManifestArtifact] = Field(default_factory=list)
    related_pack_artefacts: list[RenderManifestArtifact] = Field(default_factory=list)
    comparison: PackRenderComparisonEntry | None = None


def inspect_pack_render_target(
    *,
    manifest_path: Path,
    selectors: Sequence[str] = (),
    compare_manifest_path: Path | None = None,
    project_root: Path | None = None,
) -> PackRenderInspection:
    """Build one structured inspection payload for a rendered target.

    Start from the render manifest, resolve exactly one matching target, then
    gather the slide-scoped sidecars that agents typically need for diagnosis:
    the target's own artefacts, matching metric-context files, matching
    evidence outputs, and any existing compare result.
    """

    manifest = load_pack_render_manifest(manifest_path)
    resolution_root = _resolve_project_root(project_root)
    requested = tuple(str(item) for item in selectors)
    selected = select_pack_render_targets(manifest.rendered_targets, selectors=requested)
    entry = _select_exact_target(selected, selectors=requested)

    comparison = None
    resolved_compare_path: Path | None = None

    # If a comparison manifest already exists beside the render artefacts, fold
    # that status into inspection so callers can see the diagnosis and the
    # verdict in one place.
    resolved_compare_path = _resolve_compare_manifest_path(
        manifest_path=manifest_path,
        compare_manifest_path=compare_manifest_path,
    )
    if resolved_compare_path is not None and resolved_compare_path.exists():
        comparison = _find_comparison_entry(
            comparison=_load_pack_render_comparison(resolved_compare_path),
            target_slug=entry.target_slug,
        )

    metric_context_artefacts = _select_metric_context_artefacts(manifest.pack_artefacts, slide_index=entry.slide_index)
    evidence_artefacts = _select_evidence_artefacts(
        manifest.pack_artefacts,
        slide_slug=entry.slide_slug,
        placeholder_id=entry.placeholder_id,
    )
    related_pack_artefacts = sorted(
        [*metric_context_artefacts, *evidence_artefacts],
        key=lambda item: item.path,
    )

    return PackRenderInspection(
        manifest_path=_display_path(manifest_path, root=resolution_root),
        compare_manifest_path=(
            _display_path(resolved_compare_path, root=resolution_root)
            if resolved_compare_path is not None and resolved_compare_path.exists()
            else None
        ),
        pack_path=manifest.pack_path,
        artefact_root=manifest.artefact_root,
        partial_failure=manifest.partial_failure,
        warnings=list(manifest.warnings),
        slide_index=entry.slide_index,
        slide_id=entry.slide_id,
        slide_title=entry.slide_title,
        slide_template=entry.slide_template,
        slide_slug=entry.slide_slug,
        target_slug=entry.target_slug,
        artifact_label=entry.artifact_label,
        placeholder_id=entry.placeholder_id,
        visual_path=entry.visual_path,
        visual_type=entry.visual_type,
        png_path=entry.png_path,
        artefact_dir=entry.artefact_dir,
        target_artefacts=list(entry.artefacts),
        target_artifact_buckets=_bucket_artifacts(entry.artefacts),
        metric_context_artefacts=metric_context_artefacts,
        evidence_artefacts=evidence_artefacts,
        related_pack_artefacts=related_pack_artefacts,
        comparison=comparison,
    )


def write_pack_render_inspection(inspection: PackRenderInspection, path: Path) -> None:
    """Persist an inspection payload using a stable JSON encoding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(inspection.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _select_exact_target(
    entries: Sequence[PackRenderManifestEntry],
    *,
    selectors: Sequence[str],
) -> PackRenderManifestEntry:
    """Require selectors to resolve to exactly one rendered target."""

    if not entries:
        if selectors:
            joined = ", ".join(selectors)
            raise ValueError(f"No rendered targets matched selectors: {joined}")
        raise ValueError("No rendered targets were recorded in render.manifest.json.")

    if len(entries) > 1:
        matches = ", ".join(entry.target_slug for entry in entries)
        raise ValueError(
            "Selectors matched multiple rendered targets. "
            f"Choose a more specific target slug: {matches}"
        )

    return entries[0]


def _load_pack_render_comparison(path: Path) -> PackRenderComparison:
    """Load a comparison manifest from disk."""

    return PackRenderComparison.model_validate_json(path.read_text(encoding="utf-8"))


def _find_comparison_entry(
    *,
    comparison: PackRenderComparison,
    target_slug: str,
) -> PackRenderComparisonEntry | None:
    """Return the comparison row for the selected rendered target, if present."""

    for entry in comparison.comparisons:
        if entry.target_slug == target_slug:
            return entry
    return None


def _select_metric_context_artefacts(
    artefacts: Sequence[RenderManifestArtifact],
    *,
    slide_index: int | None,
) -> list[RenderManifestArtifact]:
    """Pick metric-context sidecars that belong to the selected slide index."""

    if slide_index is None:
        return []

    prefix = f"metric_context.slide_{slide_index}."
    return [item for item in artefacts if Path(item.path).name.startswith(prefix)]


def _select_evidence_artefacts(
    artefacts: Sequence[RenderManifestArtifact],
    *,
    slide_slug: str,
    placeholder_id: str | None,
) -> list[RenderManifestArtifact]:
    """Pick evidence sidecars that belong to the selected slide or placeholder."""

    matched: list[RenderManifestArtifact] = []
    for item in artefacts:
        parts = Path(item.path).parts
        if "_evidence" not in parts:
            continue

        evidence_index = parts.index("_evidence")
        if len(parts) <= evidence_index + 1 or parts[evidence_index + 1] != slide_slug:
            continue

        if placeholder_id is not None:
            if len(parts) <= evidence_index + 2 or parts[evidence_index + 2] != placeholder_id:
                continue
            matched.append(item)
            continue

        matched.append(item)

    return matched


def _bucket_artifacts(artefacts: Sequence[RenderManifestArtifact]) -> RenderArtifactBuckets:
    """Group artefact paths by their broad kind for easier downstream inspection."""

    buckets = RenderArtifactBuckets()
    for item in artefacts:
        if item.kind == "png":
            buckets.png_paths.append(item.path)
        elif item.kind == "dax":
            buckets.dax_paths.append(item.path)
        elif item.kind == "schema":
            buckets.schema_paths.append(item.path)
        elif item.kind == "data":
            buckets.data_paths.append(item.path)
        elif item.kind == "html":
            buckets.html_paths.append(item.path)
        elif item.kind == "file":
            buckets.file_paths.append(item.path)
        else:
            buckets.other_paths.append(item.path)
    return buckets


def _resolve_compare_manifest_path(*, manifest_path: Path, compare_manifest_path: Path | None) -> Path | None:
    """Resolve the optional comparison manifest path for a render artefact set."""

    if compare_manifest_path is not None:
        return compare_manifest_path.expanduser().resolve(strict=False)

    candidate = manifest_path.parent / "_comparisons" / "compare.manifest.json"
    if candidate.exists():
        return candidate.resolve(strict=False)
    return None


def _resolve_project_root(project_root: Path | None) -> Path:
    """Resolve the root used for cwd-relative manifest and compare paths."""

    if project_root is None:
        return Path.cwd().resolve()
    return project_root.expanduser().resolve(strict=False)


def _display_path(path: Path, *, root: Path) -> str:
    """Prefer project-root-relative paths so inspection payloads stay portable."""

    resolved = path.expanduser().resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


__all__ = [
    "PackRenderInspection",
    "RenderArtifactBuckets",
    "inspect_pack_render_target",
    "write_pack_render_inspection",
]
