from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MatrixTotals(str, Enum):
    """Supported total display options for a matrix visual."""

    OFF = "off"
    ROW = "row"
    COLUMN = "column"
    BOTH = "both"


class MatrixValueConfig(BaseModel):
    """Declarative configuration for a matrix value column."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(..., description="Unique identifier or measure name for the value column.")
    show_as: str | None = Field(
        default=None,
        title="Display rule",
        description="Optional calculation hint such as 'Percent of column total'.",
    )
    label: str | None = Field(
        default=None,
        description="Friendly label used in rendered visuals; defaults to the value id.",
    )
    format: str | None = Field(
        default=None,
        description="Formatting directive, e.g. 'percent:0' or 'duration:hms'.",
    )

    @field_validator("id")
    @classmethod
    def _normalize_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Value id cannot be empty."
            raise ValueError(msg)
        return normalized

    @field_validator("label", "show_as", "format")
    @classmethod
    def _normalize_optional(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        return normalized or None


class RowTemplate(BaseModel):
    """Template configuration for a matrix row dimension column."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    template: str = Field(..., description="Row template expressed using Jinja-style placeholders.")
    label: str | None = Field(
        default=None,
        description="Optional override for the rendered column header.",
    )

    @field_validator("template")
    @classmethod
    def _normalize_template(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Row template cannot be empty."
            raise ValueError(msg)
        return normalized

    @field_validator("label")
    @classmethod
    def _normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        return normalized or None


class MatrixConfig(BaseModel):
    """Top-level configuration for a matrix visual."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["matrix"] = Field(description="Visual type identifier; must be 'matrix'.")
    title: str | None = Field(default=None, description="Matrix title used in decks or charts.")
    description: str | None = Field(default=None, description="Optional helper text for authors.")
    rows: list[RowTemplate] = Field(
        ...,
        description="Row templates expressed using Jinja-style placeholders.",
        min_length=1,
    )
    values: list[MatrixValueConfig] = Field(
        ...,
        description="Collection of value columns that populate the matrix body.",
        min_length=1,
    )
    totals: MatrixTotals = Field(
        default=MatrixTotals.OFF,
        description="Controls whether grand totals are displayed for rows, columns, or both.",
    )

    @field_validator("rows", mode="before")
    @classmethod
    def _normalize_rows(cls, value):
        if value is None:
            msg = "Matrix requires at least one row template."
            raise ValueError(msg)
        if isinstance(value, list):
            normalized = []
            for item in value:
                if isinstance(item, str):
                    normalized.append({"template": item})
                elif isinstance(item, dict):
                    normalized.append(item)
                else:
                    msg = "Row definitions must be strings or mappings with 'template'."
                    raise TypeError(msg)
            if not normalized:
                msg = "Matrix requires at least one row template."
                raise ValueError(msg)
            return normalized
        msg = "rows must be provided as a list"
        raise TypeError(msg)

    @model_validator(mode="after")
    def _check_value_ids(self) -> "MatrixConfig":
        identifiers = [value.id for value in self.values]
        if len(identifiers) != len(set(identifiers)):
            msg = "Matrix values must use unique ids."
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _default_labels(self) -> "MatrixConfig":
        for value in self.values:
            if value.label is None:
                value.label = value.id
        return self
