"""Pydantic models describing pack definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FiltersType = str | Sequence[str] | Mapping[str, str] | None


class PackVisualRef(BaseModel):
    """Reference to a visual or an inline visual config plus optional slide-level overrides."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ref: str | None = Field(
        default=None,
        description="Optional path to the visual definition relative to the pack file.",
    )
    type: str | None = Field(
        default=None,
        description="Optional inline visual type or Python module path when embedding a config directly.",
    )
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
    def _normalise_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            msg = "visual.ref cannot be empty"
            raise ValueError(msg)
        return cleaned

    @model_validator(mode="after")
    def _validate_ref_or_type(self) -> "PackVisualRef":
        has_ref = bool(self.ref)
        has_type = bool(self.type)
        if has_ref == has_type:
            raise ValueError("visual must define exactly one of 'ref' or 'type'")
        return self


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
    text: str | list[str] | None = Field(
        default=None,
        description="Plain text (optionally templated) injected into a named text shape.",
    )

    @field_validator("image")
    @classmethod
    def _normalise_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("text")
    @classmethod
    def _normalise_text(cls, value: str | list[str] | None) -> str | list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        cleaned_items = [item.strip() for item in value if item and item.strip()]
        return cleaned_items or None

    @model_validator(mode="after")
    def _validate_exclusive_binding(self) -> "PackPlaceholder":
        has_visual = self.visual is not None
        has_image = bool(self.image)
        has_text = bool(self.text)

        if (has_visual + has_image + has_text) != 1:
            msg = "placeholder must define exactly one of visual, image, or text"
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

    @field_validator("placeholders", mode="before")
    @classmethod
    def _normalise_placeholders(
        cls, value: object
    ) -> dict[str, PackPlaceholder] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            msg = "placeholders must be a mapping"
            raise TypeError(msg)

        normalised: dict[str, PackPlaceholder] = {}
        for placeholder_id, raw in value.items():
            if isinstance(raw, PackPlaceholder):
                normalised[str(placeholder_id)] = raw
                continue

            if isinstance(raw, str):
                placeholder = _placeholder_from_shorthand(raw)
                normalised[str(placeholder_id)] = placeholder
                continue

            if isinstance(raw, Mapping):
                placeholder = PackPlaceholder.model_validate(raw)
                normalised[str(placeholder_id)] = placeholder
                continue

            msg = f"Invalid placeholder value for '{placeholder_id}'"
            raise TypeError(msg)

        return normalised

    @model_validator(mode="after")
    def _validate_image_with_visual_and_template(self) -> "PackSlide":
        if self.image and self.visual is not None:
            msg = "slide cannot define both visual and image"
            raise ValueError(msg)
        if self.image and not self.template:
            msg = "slide-level image requires a template"
            raise ValueError(msg)
        return self


def _placeholder_from_shorthand(value: str) -> PackPlaceholder:
    """Convert string shorthand to a concrete placeholder binding."""

    cleaned = value.strip()
    lower = cleaned.lower()

    is_image = (
        "/" in cleaned
        or "\\" in cleaned
        or lower.endswith(
            (
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".bmp",
                ".svg",
                ".webp",
            )
        )
    )

    if is_image:
        return PackPlaceholder(image=cleaned)

    return PackPlaceholder(text=cleaned)


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
