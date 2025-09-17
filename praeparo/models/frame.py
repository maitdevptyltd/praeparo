from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .visual_base import BaseVisualConfig, LoadVisualFn


class FrameChildDefinition(BaseModel):
    """Raw child reference encountered in a frame YAML document."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ref: str = Field(..., description="Relative path to the child visual configuration.")
    parameters: Mapping[str, Any] = Field(
        default_factory=dict,
        description="Parameter overrides injected into the child visual context.",
    )
    overrides: Mapping[str, Any] = Field(
        default_factory=dict,
        description="Inline overrides applied to the child visual before validation.",
    )

    @model_validator(mode="before")
    @classmethod
    def _collect_overrides(cls, value: Any) -> Mapping[str, Any]:
        if isinstance(value, FrameChildDefinition):
            return value.model_dump()
        if not isinstance(value, Mapping):
            msg = "Frame child definitions must be mappings."
            raise TypeError(msg)

        ref = value.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            msg = "Frame child definition requires a non-empty 'ref' field."
            raise ValueError(msg)

        raw_parameters = value.get("parameters") or {}
        if not isinstance(raw_parameters, Mapping):
            msg = "Frame child parameters must be provided as a mapping."
            raise TypeError(msg)

        overrides = {
            key: item
            for key, item in value.items()
            if key not in {"ref", "parameters"}
        }

        return {
            "ref": ref.strip(),
            "parameters": dict(raw_parameters),
            "overrides": dict(overrides),
        }


class FrameChildConfig(BaseModel):
    """Resolved child visual that participates in a frame visual."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Path
    visual: BaseVisualConfig
    parameters: Mapping[str, str]
    overrides: Mapping[str, Any] = Field(
        default_factory=dict,
        description="Overrides applied when the child visual was loaded.",
    )

    @property
    def config(self) -> BaseVisualConfig:
        """Backward-compatible accessor for the resolved child visual."""

        return self.visual


class FrameConfig(BaseVisualConfig):
    """Composition of multiple visuals into a single frame."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, arbitrary_types_allowed=True)

    type: Literal["frame"] = Field(default="frame", description="Visual type identifier; must be 'frame'.")
    layout: Literal["vertical", "horizontal"] = Field(
        default="vertical",
        description="Controls the stacking direction for child visuals.",
    )
    auto_height: bool = Field(
        default=True,
        alias="autoHeight",
        description="Automatically size the rendered frame height based on child content.",
    )
    show_titles: bool = Field(
        default=False,
        alias="showTitles",
        description="When true, render subplot titles for each child visual.",
    )
    children: tuple[FrameChildDefinition | FrameChildConfig, ...] = Field(
        ...,
        min_length=1,
        description="Child visuals or references that compose the frame.",
    )

    def resolve(
        self,
        *,
        load_visual: LoadVisualFn,
        path: Path,
        stack: tuple[Path, ...],
    ) -> "FrameConfig":
        resolved_children: list[FrameChildConfig] = []

        for entry in self.children:
            if isinstance(entry, FrameChildConfig):
                resolved_children.append(entry)
                continue

            if not isinstance(entry, FrameChildDefinition):
                msg = "Unexpected child payload encountered while resolving frame children."
                raise ValueError(msg)

            child_path = (path.parent / entry.ref).resolve()
            parameters_override = entry.parameters or None
            overrides = entry.overrides or None

            child_visual = load_visual(
                child_path,
                overrides,
                parameters_override,
                stack + (path,),
            )

            resolved_children.append(
                FrameChildConfig(
                    source=child_path,
                    visual=child_visual,
                    parameters={
                        str(key): str(value) if not isinstance(value, str) else value
                        for key, value in (entry.parameters or {}).items()
                    },
                    overrides=dict(entry.overrides),
                )
            )

        return self.model_copy(update={"children": tuple(resolved_children)})


__all__ = [
    "FrameChildConfig",
    "FrameChildDefinition",
    "FrameConfig",
]
