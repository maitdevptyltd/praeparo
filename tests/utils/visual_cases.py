from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Tuple

from praeparo.dax import DaxQueryPlan, build_matrix_query
from praeparo.io.yaml_loader import load_visual_config
from praeparo.models import FrameConfig, MatrixConfig
from praeparo.templating import FieldReference, extract_field_references


def discover_yaml_files(root: Path) -> list[Path]:
    return sorted(root.glob("**/*.yaml"))


def case_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    parts = list(relative.parts)
    parts[-1] = Path(parts[-1]).stem
    return "_".join(parts)


def case_snapshot_path(path: Path, root: Path) -> Path:
    relative = path.relative_to(root)
    parts = list(relative.parts)
    parts[-1] = Path(parts[-1]).stem
    return Path(*parts)


@dataclass(frozen=True)
class MatrixArtifacts:
    kind: Literal["matrix"]
    config: MatrixConfig
    row_fields: tuple[FieldReference, ...]
    plan: DaxQueryPlan


@dataclass(frozen=True)
class FrameChildArtifacts:
    config: MatrixConfig
    row_fields: tuple[FieldReference, ...]
    plan: DaxQueryPlan


@dataclass(frozen=True)
class FrameArtifacts:
    kind: Literal["frame"]
    config: FrameConfig
    children: tuple[FrameChildArtifacts, ...]


VisualArtifacts = MatrixArtifacts | FrameArtifacts


def _matrix_artifacts(config: MatrixConfig) -> MatrixArtifacts:
    row_fields = tuple(extract_field_references([row.template for row in config.rows]))
    plan = build_matrix_query(config, row_fields)
    return MatrixArtifacts(kind="matrix", config=config, row_fields=row_fields, plan=plan)


def load_visual_artifacts(path: Path) -> VisualArtifacts:
    visual = load_visual_config(path)
    if isinstance(visual, MatrixConfig):
        return _matrix_artifacts(visual)

    if isinstance(visual, FrameConfig):
        children = tuple(_matrix_artifacts(child.config) for child in visual.children)
        return FrameArtifacts(kind="frame", config=visual, children=children)

    raise TypeError(f"Unsupported visual configuration returned for {path}")
