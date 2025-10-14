"""Pydantic models describing metric registry definitions."""

from __future__ import annotations

import re
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SLUG_PATTERN = re.compile(r"^[a-z0-9_]+$")


def _ensure_string_list(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise TypeError("calculate entries must be strings")
        return value
    raise TypeError("calculate must be a string or list of strings")


class MetricVariant(BaseModel):
    """Variant of a base metric (e.g. automated, manual)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(..., description="Human-readable variant name")
    description: str | None = Field(
        default=None, description="Optional explanation for stakeholders"
    )
    calculate: List[str] = Field(
        default_factory=list,
        description="Additional DAX-style predicates applied on top of the base metric",
    )

    _coerce_calculate = field_validator("calculate", mode="before")(_ensure_string_list)


class MetricRatioDefinition(BaseModel):
    """Explicit ratio derived from variants or other metrics."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(..., description="Human-friendly ratio label")
    numerator: str = Field(..., description="Variant key or metric id used as numerator")
    denominator: str = Field(..., description="Variant key or metric id used as denominator")
    format: str | None = Field(
        default=None, description="Display format token (e.g. percent, ratio:0.0)"
    )
    description: str | None = Field(
        default=None, description="Optional notes clarifying the ratio logic"
    )


class MetricRatiosConfig(BaseModel):
    """Configuration for derived ratio metrics."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    auto_percent_of_base: bool = Field(
        default=False,
        description="Automatically publish percent-of-base values for each variant",
    )
    auto_percent_format: str | None = Field(
        default=None,
        alias="format",
        description="Formatting token applied to automatically generated percent ratios",
    )
    definitions: Dict[str, MetricRatioDefinition] = Field(
        default_factory=dict,
        description="Explicitly defined ratio entries keyed by identifier",
    )

    @field_validator("definitions", mode="after")
    @classmethod
    def _validate_ratio_keys(cls, value: Dict[str, MetricRatioDefinition]) -> Dict[str, MetricRatioDefinition]:
        for key in value:
            if not _SLUG_PATTERN.match(key):
                raise ValueError(
                    "ratio identifiers must be snake_case (lowercase letters, digits, underscore)"
                )
        return value


class MetricDefinition(BaseModel):
    """Business-centric definition of an MSA metric."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str | None = Field(
        default=None,
        alias="schema",
        description="Optional schema version identifier for the metric document",
    )
    extends: str | None = Field(
        default=None,
        description="Optional parent metric key to inherit base definitions from",
    )
    key: str = Field(
        ..., description="Stable identifier for referencing the metric", examples=["documents_sent"]
    )
    display_name: str = Field(..., description="Human-friendly metric title")
    section: str = Field(..., description="Grouping or dashboard section the metric belongs to")
    description: str | None = Field(
        default=None,
        description="Narrative summary for business stakeholders",
    )
    notes: str | None = Field(
        default=None, description="Additional implementation or commentary notes"
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Optional free-form taxonomy tags (e.g. timeliness, automation)",
    )
    calculate: List[str] = Field(
        default_factory=list,
        description="Base DAX-style predicates describing the metric scope",
    )
    variants: Dict[str, MetricVariant] = Field(
        default_factory=dict,
        description="Named variants that apply additional predicates or business logic",
    )
    ratios: MetricRatiosConfig | None = Field(
        default=None, description="Automatic or explicit ratios derived from this metric"
    )

    _coerce_calculate = field_validator("calculate", mode="before")(_ensure_string_list)

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if not _SLUG_PATTERN.match(value):
            raise ValueError("metric key must be snake_case (lowercase letters, digits, underscore)")
        return value

    @field_validator("variants", mode="after")
    @classmethod
    def _validate_variant_keys(
        cls, value: Dict[str, MetricVariant]
    ) -> Dict[str, MetricVariant]:
        for key in value:
            if not _SLUG_PATTERN.match(key):
                raise ValueError(
                    "variant identifiers must be snake_case (lowercase letters, digits, underscore)"
                )
        return value

    @field_validator("extends")
    @classmethod
    def _validate_extends(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _SLUG_PATTERN.match(value):
            raise ValueError(
                "extends must reference a snake_case metric key (lowercase letters, digits, underscore)"
            )
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            if not all(isinstance(item, str) for item in value):
                raise TypeError("tags entries must be strings")
            return value
        raise TypeError("tags must be a list of strings")
