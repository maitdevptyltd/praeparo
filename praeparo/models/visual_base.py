"""Common visual configuration base models."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field

LoadVisualFn = Callable[[Path, Mapping[str, Any] | None, Mapping[str, Any] | None, tuple[Path, ...]], "BaseVisualConfig"]


class BaseVisualConfig(BaseModel):
    """Shared fields and behaviour for all visual configurations."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: str = Field(..., description="Visual type discriminator.")
    title: str | None = Field(default=None, description="Human-friendly title for the visual.")
    description: str | None = Field(default=None, description="Optional authoring help text.")

    def resolve(self, *, load_visual: LoadVisualFn, path: Path, stack: tuple[Path, ...]) -> "BaseVisualConfig":
        """Resolve nested references; default implementation is a no-op."""

        return self


__all__ = ["BaseVisualConfig", "LoadVisualFn"]
