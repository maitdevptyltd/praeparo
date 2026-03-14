"""Structured manifests for pack render outputs.

The pack runner already emits useful artefacts on disk, but agents and humans
still need one stable summary they can inspect without traversing the
filesystem by hand. These helpers collect per-slide outputs into a portable
manifest that points back to the rendered files.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, Sequence

from pydantic import BaseModel, Field

from praeparo.visuals.dax.planner_core import slugify

if TYPE_CHECKING:
    from praeparo.pack.runner import PackSlideResult


class RenderManifestArtifact(BaseModel):
    """One file emitted while rendering a slide target."""

    kind: str
    path: str


class PackRenderManifestEntry(BaseModel):
    """Manifest row for one rendered slide or placeholder target."""

    slide_index: int | None = None
    slide_id: str | None = None
    slide_title: str | None = None
    slide_slug: str
    target_slug: str
    artifact_label: str
    placeholder_id: str | None = None
    visual_path: str | None = None
    visual_type: str | None = None
    png_path: str | None = None
    artefact_dir: str | None = None
    artefacts: list[RenderManifestArtifact] = Field(default_factory=list)


class PackRenderManifest(BaseModel):
    """Portable summary of a pack render command."""

    kind: Literal["pack_run", "pack_render_slide"]
    pack_path: str
    artefact_root: str
    result_file: str | None = None
    requested_slides: list[str] = Field(default_factory=list)
    partial_failure: bool = False
    warnings: list[str] = Field(default_factory=list)
    pack_artefacts: list[RenderManifestArtifact] = Field(default_factory=list)
    rendered_targets: list[PackRenderManifestEntry] = Field(default_factory=list)


def build_pack_render_manifest(
    *,
    kind: Literal["pack_run", "pack_render_slide"],
    pack_path: Path,
    artefact_root: Path,
    results: Sequence["PackSlideResult"],
    requested_slides: Sequence[str] = (),
    result_file: Path | None = None,
    partial_failure: bool = False,
    warnings: Sequence[str] = (),
) -> PackRenderManifest:
    """Collect one manifest for the rendered slide targets in a pack run."""

    entries: list[PackRenderManifestEntry] = []
    claimed_paths: set[Path] = set()
    for fallback_index, item in enumerate(results, start=1):
        slide = item.slide
        slide_slug = item.slide_slug or _default_slide_slug(slide_title=slide.title, slide_id=slide.id, index=fallback_index)
        target_slug = item.target_slug or slide_slug
        artifact_label = item.artifact_label or target_slug
        artefacts = _collect_result_artefacts(item)
        claimed_paths.update(_resolved_manifest_paths(artefacts))

        entries.append(
            PackRenderManifestEntry(
                slide_index=item.slide_index or fallback_index,
                slide_id=slide.id,
                slide_title=slide.title,
                slide_slug=slide_slug,
                target_slug=target_slug,
                artifact_label=artifact_label,
                placeholder_id=item.placeholder_id,
                visual_path=_display_path(item.visual_path) if item.visual_path else None,
                visual_type=item.visual_type or getattr(item.result.config, "type", None),
                png_path=_display_path(item.png_path) if item.png_path else None,
                artefact_dir=_display_path(item.artefact_dir) if item.artefact_dir else None,
                artefacts=artefacts,
            )
        )

    return PackRenderManifest(
        kind=kind,
        pack_path=_display_path(pack_path),
        artefact_root=_display_path(artefact_root),
        result_file=_display_path(result_file) if result_file else None,
        requested_slides=[str(item) for item in requested_slides],
        partial_failure=partial_failure,
        warnings=[str(item) for item in warnings],
        pack_artefacts=_collect_root_artefacts(artefact_root=artefact_root, claimed_paths=claimed_paths),
        rendered_targets=entries,
    )


def write_pack_render_manifest(manifest: PackRenderManifest, path: Path) -> None:
    """Persist a pack render manifest using a stable JSON encoding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _collect_result_artefacts(result: "PackSlideResult") -> list[RenderManifestArtifact]:
    """Collect explicit pipeline outputs plus any extra sidecars in artefact_dir."""

    artefacts_by_path: dict[Path, RenderManifestArtifact] = {}

    for output in result.result.outputs:
        resolved = output.path.expanduser().resolve(strict=False)
        artefacts_by_path[resolved] = RenderManifestArtifact(
            kind=str(output.kind.value),
            path=_display_path(output.path),
        )

    if result.artefact_dir and result.artefact_dir.exists():
        for path in sorted(candidate for candidate in result.artefact_dir.rglob("*") if candidate.is_file()):
            resolved = path.expanduser().resolve(strict=False)
            artefacts_by_path.setdefault(
                resolved,
                RenderManifestArtifact(kind=_guess_artifact_kind(path), path=_display_path(path)),
            )

    if result.png_path:
        resolved_png = result.png_path.expanduser().resolve(strict=False)
        artefacts_by_path.setdefault(
            resolved_png,
            RenderManifestArtifact(kind="png", path=_display_path(result.png_path)),
        )

    return sorted(artefacts_by_path.values(), key=lambda item: item.path)


def _guess_artifact_kind(path: Path) -> str:
    """Infer a broad artefact kind for sidecars not reported by the pipeline."""

    name = path.name.lower()
    suffix = path.suffix.lower()

    if suffix == ".png":
        return "png"
    if suffix == ".html":
        return "html"
    if suffix == ".dax":
        return "dax"
    if suffix == ".json" and "schema" in name:
        return "schema"
    if suffix == ".json":
        return "data"
    return "file"


def _display_path(path: Path) -> str:
    """Prefer cwd-relative paths so manifests stay portable across machines."""

    resolved = path.expanduser().resolve(strict=False)
    cwd = Path.cwd().resolve()
    try:
        return resolved.relative_to(cwd).as_posix()
    except ValueError:
        return resolved.as_posix()


def _default_slide_slug(*, slide_title: str | None, slide_id: str | None, index: int) -> str:
    """Derive a stable slug when tests or callers omit runner metadata."""

    if slide_id:
        return slugify(slide_id)
    if slide_title:
        return slugify(slide_title)
    return f"slide_{index}"


def _collect_root_artefacts(*, artefact_root: Path, claimed_paths: set[Path]) -> list[RenderManifestArtifact]:
    """Capture pack-level sidecars that are not owned by one rendered target."""

    if not artefact_root.exists():
        return []

    root_artefacts: list[RenderManifestArtifact] = []
    for path in sorted(candidate for candidate in artefact_root.rglob("*") if candidate.is_file()):
        if path.name == "render.manifest.json":
            continue
        resolved = path.expanduser().resolve(strict=False)
        if resolved in claimed_paths:
            continue
        root_artefacts.append(
            RenderManifestArtifact(kind=_guess_artifact_kind(path), path=_display_path(path))
        )
    return root_artefacts


def _resolved_manifest_paths(artefacts: Sequence[RenderManifestArtifact]) -> set[Path]:
    """Convert manifest artefact paths back into resolved paths for de-duplication."""

    resolved: set[Path] = set()
    cwd = Path.cwd().resolve()
    for item in artefacts:
        candidate = Path(item.path)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        resolved.add(candidate.expanduser().resolve(strict=False))
    return resolved


__all__ = [
    "PackRenderManifest",
    "PackRenderManifestEntry",
    "RenderManifestArtifact",
    "build_pack_render_manifest",
    "write_pack_render_manifest",
]
