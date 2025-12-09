from __future__ import annotations

from pathlib import Path
from typing import Tuple

from pydantic import BaseModel, ConfigDict, Field

from praeparo.visuals.dax_context import DAXContextModel


class VisualContextModel(BaseModel):
    """Base typed context passed to visual pipelines."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    metrics_root: Path = Field(default=Path("registry/metrics"))
    seed: int = 42
    scenario: str | None = None
    ignore_placeholders: bool = False
    grain: Tuple[str, ...] | None = None
    dax: DAXContextModel = Field(default_factory=DAXContextModel)
