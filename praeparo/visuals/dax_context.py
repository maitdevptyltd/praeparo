"""Typed model for global DAX context fragments."""

from __future__ import annotations

from typing import Tuple

from pydantic import BaseModel, Field


class DAXContextModel(BaseModel):
    """Global DAX context (calculate/define) for a visual execution."""

    calculate: Tuple[str, ...] = Field(default_factory=tuple)
    define: Tuple[str, ...] = Field(default_factory=tuple)


__all__ = ["DAXContextModel"]
