from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Literal

from .matrix import MatrixConfig


@dataclass(frozen=True)
class FrameChildConfig:
    """Resolved matrix configuration referenced from a frame."""

    source: Path
    config: MatrixConfig
    parameters: Mapping[str, str]


@dataclass(frozen=True)
class FrameConfig:
    """Composition of multiple visuals into a single frame."""

    type: Literal["frame"]
    title: str | None
    layout: Literal["vertical", "horizontal"]
    children: tuple[FrameChildConfig, ...]
    show_titles: bool = False


__all__ = ["FrameChildConfig", "FrameConfig"]

