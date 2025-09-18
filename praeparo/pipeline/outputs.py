"""Output configuration primitives for the visual pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class OutputKind(str, Enum):
    """Supported artifact formats emitted by the pipeline."""

    HTML = "html"
    PNG = "png"


@dataclass(frozen=True)
class OutputTarget:
    """Describes a requested artifact emitted after execution."""

    kind: OutputKind
    path: Path
    scale: float | None = None

    @classmethod
    def html(cls, path: Path) -> "OutputTarget":
        return cls(kind=OutputKind.HTML, path=Path(path))

    @classmethod
    def png(cls, path: Path, *, scale: float = 2.0) -> "OutputTarget":
        return cls(kind=OutputKind.PNG, path=Path(path), scale=scale)


@dataclass(frozen=True)
class PipelineOutputArtifact:
    """Represents a file emitted by the pipeline."""

    kind: OutputKind
    path: Path


__all__ = ["OutputKind", "OutputTarget", "PipelineOutputArtifact"]
