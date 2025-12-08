"""Pydantic models describing pack definitions."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


__all__ = ["FiltersType", "PackConfig", "PackSlide", "PackVisualRef"]
