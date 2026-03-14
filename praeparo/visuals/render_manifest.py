"""Structured manifests for standalone visual inspection runs.

Focused visual debugging needs the same kind of portable summary that pack
rendering now emits. These helpers capture the files emitted by one visual
execution so compare, approval, and MCP layers can build on one stable
contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, Field

from praeparo.pipeline import PipelineOptions, VisualExecutionResult
from praeparo.visuals.dax.planner_core import slugify


class VisualRenderArtifact(BaseModel):
    """One file emitted while inspecting a visual."""

    kind: str
    path: str


class VisualRenderManifest(BaseModel):
    """Portable summary of one standalone visual inspection run."""

    kind: Literal["visual_inspect"] = "visual_inspect"
    config_path: str
    baseline_key: str
    visual_type: str
    project_root: str
    artefact_root: str
    html_path: str | None = None
    png_path: str | None = None
    schema_path: str | None = None
    dataset_path: str | None = None
    requested_outputs: list[VisualRenderArtifact] = Field(default_factory=list)
    outputs: list[VisualRenderArtifact] = Field(default_factory=list)
    data_mode: str
    datasource_override: str | None = None
    provider_key: str | None = None
    dataset_id: str | None = None
    workspace_id: str | None = None
    metrics_root: str | None = None
    warnings: list[str] = Field(default_factory=list)


def build_visual_render_manifest(
    *,
    config_path: Path,
    project_root: Path,
    result: VisualExecutionResult,
    options: PipelineOptions,
    warnings: Sequence[str] = (),
) -> VisualRenderManifest:
    """Collect one manifest for the files emitted by a visual inspection run.

    Start from the explicit pipeline outputs, then sweep the artefact directory
    for any extra sidecars the renderer emitted outside the standard output
    list. That keeps the manifest useful across built-in visuals and more
    specialized downstream renderers.
    """

    artefact_root = options.artefact_dir
    if artefact_root is None:
        raise ValueError("Visual inspection requires an artefact directory.")

    outputs = _collect_result_outputs(result=result, artefact_dir=artefact_root, project_root=project_root)
    requested_outputs = _collect_requested_outputs(options=options, project_root=project_root)
    metrics_root = _coerce_metadata_path(options.metadata, key="metrics_root", project_root=project_root)

    return VisualRenderManifest(
        config_path=_display_path(config_path, root=project_root),
        baseline_key=slugify(config_path.stem),
        visual_type=result.config.type,
        project_root=_display_path(project_root, root=project_root),
        artefact_root=_display_path(artefact_root, root=project_root),
        html_path=_primary_output_path(outputs=outputs, requested_outputs=requested_outputs, kind="html"),
        png_path=_primary_output_path(outputs=outputs, requested_outputs=requested_outputs, kind="png"),
        schema_path=_display_optional_path(result.schema_path, root=project_root),
        dataset_path=_display_optional_path(result.dataset_path, root=project_root),
        requested_outputs=requested_outputs,
        outputs=outputs,
        data_mode=str(options.metadata.get("data_mode", "mock")),
        datasource_override=options.data.datasource_override,
        provider_key=options.data.provider_key,
        dataset_id=options.data.dataset_id,
        workspace_id=options.data.workspace_id,
        metrics_root=metrics_root,
        warnings=[str(item) for item in warnings],
    )


def write_visual_render_manifest(manifest: VisualRenderManifest, path: Path) -> None:
    """Persist a visual render manifest using a stable JSON encoding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_visual_render_manifest(path: Path) -> VisualRenderManifest:
    """Load a previously emitted visual render manifest from disk."""

    return VisualRenderManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _collect_result_outputs(
    *,
    result: VisualExecutionResult,
    artefact_dir: Path,
    project_root: Path,
) -> list[VisualRenderArtifact]:
    """Merge pipeline-declared outputs with any extra artefact-directory sidecars."""

    artefacts_by_path: dict[Path, VisualRenderArtifact] = {}

    for output in result.outputs:
        resolved = output.path.expanduser().resolve(strict=False)
        artefacts_by_path[resolved] = VisualRenderArtifact(
            kind=str(output.kind.value),
            path=_display_path(output.path, root=project_root),
        )

    if artefact_dir.exists():
        for path in sorted(candidate for candidate in artefact_dir.rglob("*") if candidate.is_file()):
            if path.name == "render.manifest.json":
                continue
            resolved = path.expanduser().resolve(strict=False)
            artefacts_by_path.setdefault(
                resolved,
                VisualRenderArtifact(kind=_guess_artifact_kind(path), path=_display_path(path, root=project_root)),
            )

    return sorted(artefacts_by_path.values(), key=lambda item: item.path)


def _collect_requested_outputs(
    *,
    options: PipelineOptions,
    project_root: Path,
) -> list[VisualRenderArtifact]:
    """Record the HTML/PNG outputs the caller asked the pipeline to emit."""

    requested: list[VisualRenderArtifact] = []
    for target in options.outputs:
        requested.append(
            VisualRenderArtifact(
                kind=str(target.kind.value),
                path=_display_path(target.path, root=project_root),
            )
        )
    return requested


def _primary_output_path(
    *,
    outputs: Sequence[VisualRenderArtifact],
    requested_outputs: Sequence[VisualRenderArtifact],
    kind: str,
) -> str | None:
    """Prefer the caller-requested HTML/PNG output, then fall back to any emitted file.

    Some renderers emit internal HTML sidecars in addition to the explicit HTML
    output target the caller asked for. Inspection flows care most about the
    primary target path, so prefer a requested output when it is present in the
    emitted output set.
    """

    emitted_paths = {item.path for item in outputs if item.kind == kind}
    for item in requested_outputs:
        if item.kind == kind and item.path in emitted_paths:
            return item.path

    for item in outputs:
        if item.kind == kind:
            return item.path
    return None


def _coerce_metadata_path(
    metadata: Mapping[str, object],
    *,
    key: str,
    project_root: Path,
) -> str | None:
    """Render well-known Path-like metadata fields portably in the manifest."""

    raw = metadata.get(key)
    if isinstance(raw, Path):
        return _display_path(raw, root=project_root)
    if isinstance(raw, str):
        return _display_path(Path(raw), root=project_root)
    return None


def _display_optional_path(path: Path | None, *, root: Path) -> str | None:
    """Render optional paths consistently with the other manifest entries."""

    if path is None:
        return None
    return _display_path(path, root=root)


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


def _display_path(path: Path, *, root: Path) -> str:
    """Prefer project-root-relative paths so manifests stay portable."""

    resolved = path.expanduser().resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


__all__ = [
    "VisualRenderArtifact",
    "VisualRenderManifest",
    "build_visual_render_manifest",
    "load_visual_render_manifest",
    "write_visual_render_manifest",
]
