from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from praeparo.visuals.dax_context import DAXContextModel


class VisualContextModel(BaseModel):
    """Base typed context passed to visual pipelines."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_default=True)

    metrics_root: Path = Field(default=Path("registry/metrics"))
    seed: int = 42
    scenario: str | None = None
    ignore_placeholders: bool = False
    grain: Tuple[str, ...] | None = None
    dax: DAXContextModel = Field(default_factory=DAXContextModel)

    @field_validator("metrics_root", mode="before")
    @classmethod
    def _normalise_metrics_root(cls, value: object) -> Path:
        """Resolve metrics_root to an absolute Path regardless of how callers pass it."""
        if isinstance(value, Path):
            candidate = value
        elif isinstance(value, (str, os.PathLike)):
            candidate = Path(value)
        else:
            candidate = Path("registry/metrics")
        return candidate.expanduser().resolve(strict=False)
