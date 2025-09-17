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
    hidden: bool = Field(
        default=False,
        description="If true, the row participates in queries but is omitted from rendered outputs.",
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


class MatrixFilterConfig(BaseModel):
    """Declarative global filter applied to a matrix query."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    field: str | None = Field(
        default=None,
        description="Target column expressed as 'table.column'.",
    )
    include: list[str] | None = Field(
        default=None,
        description="Allowed values that remain after the filter is applied.",
    )
    expression: str | None = Field(
        default=None,
        description="Raw DAX filter expression inserted into the evaluation context.",
    )

    @field_validator("field")
    @classmethod
    def _normalize_field(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            msg = "Filter field cannot be empty."
            raise ValueError(msg)
        if "." not in normalized:
            msg = "Filter field must be expressed as 'table.column'."
            raise ValueError(msg)
        left, right = normalized.split(".", 1)
        if not left or not right:
            msg = "Filter field must include both table and column."
            raise ValueError(msg)
        return normalized

    @field_validator("include", mode="before")
    @classmethod
    def _ensure_list(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("include")
    @classmethod
    def _normalize_include(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if not text:
                continue
            cleaned.append(text)
        if not cleaned:
            msg = "Filter include list must contain at least one value."
            raise ValueError(msg)
        deduplicated = list(dict.fromkeys(cleaned))
        return deduplicated

    @field_validator("expression")
    @classmethod
    def _normalize_expression(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            msg = "Filter expression cannot be empty."
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def _validate_filter_mode(self) -> "MatrixFilterConfig":
        if self.expression:
            if self.field or self.include:
                msg = "Expression filters cannot include field/include properties."
                raise ValueError(msg)
            return self
        if not self.field or not self.include:
            msg = "Field filters must provide both 'field' and 'include'."
            raise ValueError(msg)
        return self



class MatrixConfig(BaseModel):
    """Top-level configuration for a matrix visual."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["matrix"] = Field(description="Visual type identifier; must be 'matrix'.")
    title: str | None = Field(default=None, description="Matrix title used in decks or charts.")
    description: str | None = Field(default=None, description="Optional helper text for authors.")
    define: str | None = Field(
        default=None,
        description="Optional DAX DEFINE statements prefixed to generated queries.",
    )
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
    filters: list[MatrixFilterConfig] = Field(
        default_factory=list,
        description="Global filters applied to every generated query before evaluation.",
    )

    auto_height: bool = Field(
        default=True,
        alias="autoHeight",
        description="Automatically size the rendered matrix height based on row count.",
    )

    @field_validator("define")
    @classmethod
    def _normalize_define(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        return normalized or None

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


__all__ = [
    "MatrixConfig",
    "MatrixFilterConfig",
    "MatrixTotals",
    "MatrixValueConfig",
    "RowTemplate",
]
