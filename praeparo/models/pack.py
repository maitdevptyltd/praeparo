"""Pydantic models describing pack definitions."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FiltersType = str | Sequence[str] | Mapping[str, str] | None


class PackVisualRef(BaseModel):
    """Reference to a visual plus optional slide-level overrides."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ref: str = Field(..., description="Path to the visual definition relative to the pack file.")
    filters: FiltersType = Field(
        default=None,
        description="Optional OData filters applied on top of pack-level defaults.",
    )
    calculate: FiltersType = Field(
        default=None,
        description="Optional DAX filters applied on top of pack-level defaults.",
    )

    @field_validator("ref")
    @classmethod
    def _normalise_ref(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "visual.ref cannot be empty"
            raise ValueError(msg)
        return cleaned


class PackPlaceholder(BaseModel):
    """Placeholder binding used by PPTX assembly."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    visual: PackVisualRef | None = Field(
        default=None,
        description="Visual rendered for this placeholder.",
    )
    image: str | None = Field(
        default=None,
        description="Optional static image path for this placeholder, relative to the pack file.",
    )

    @field_validator("image")
    @classmethod
    def _normalise_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_image_or_visual(self) -> "PackPlaceholder":
        if self.visual is None and not self.image:
            msg = "placeholder must define either visual or image"
            raise ValueError(msg)
        if self.visual is not None and self.image:
            msg = "placeholder cannot define both visual and image"
            raise ValueError(msg)
        return self


class PackSlide(BaseModel):
    """Single slide within a pack."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str = Field(..., description="Human-friendly slide title.")
    id: str | None = Field(default=None, description="Optional stable identifier for the slide.")
    notes: str | None = Field(default=None, description="Free-form notes for authors/reviewers.")
    visual: PackVisualRef | None = Field(
        default=None,
        description="Optional visual reference; absent for non-visual slides.",
    )
    template: str | None = Field(
        default=None,
        description="Optional PPTX template identifier (TEMPLATE_TAG) used during deck assembly.",
    )
    placeholders: dict[str, PackPlaceholder] | None = Field(
        default=None,
        description="Optional placeholder map when a slide template contains multiple picture placeholders.",
    )
    image: str | None = Field(
        default=None,
        description="Optional static image path when using a PPTX template without a visual.",
    )

    @field_validator("title")
    @classmethod
    def _normalise_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "title cannot be empty"
            raise ValueError(msg)
        return cleaned

    @field_validator("id")
    @classmethod
    def _normalise_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("image")
    @classmethod
    def _normalise_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_image_with_visual_and_template(self) -> "PackSlide":
        if self.image and self.visual is not None:
            msg = "slide cannot define both visual and image"
            raise ValueError(msg)
        if self.image and not self.template:
            msg = "slide-level image requires a template"
            raise ValueError(msg)
        return self


class PackConfig(BaseModel):
    """Root configuration for a pack composed of slides."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, protected_namespaces=())

    schema: str = Field(..., description="Schema or contract identifier for the pack.")
    context: dict[str, Any] = Field(default_factory=dict, description="Template context shared by slides.")
    define: str | None = Field(
        default=None,
        description="Optional DAX DEFINE block applied to DAX-backed visuals.",
    )
    calculate: FiltersType = Field(
        default=None,
        description="Pack-level DAX filters applied to DAX-backed visuals.",
    )
    filters: FiltersType = Field(
        default=None,
        description="Pack-level OData filters applied to Power BI visuals.",
    )
    slides: list[PackSlide] = Field(default_factory=list, description="Ordered slide definitions.")

    @field_validator("schema")
    @classmethod
    def _normalise_schema(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "schema cannot be empty"
            raise ValueError(msg)
        return cleaned


__all__ = ["FiltersType", "PackConfig", "PackPlaceholder", "PackSlide", "PackVisualRef"]
