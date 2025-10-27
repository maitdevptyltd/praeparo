"""Pydantic models describing metric registry definitions."""

from __future__ import annotations

import re
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SLUG_PATTERN = re.compile(r"^[a-z0-9_]+$")
_VALUE_TYPES = {"number", "percent", "currency"}


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


def _ensure_variant_keys(
    value: Dict[str, "MetricVariant"]
) -> Dict[str, "MetricVariant"]:
    for key in value:
        if not _SLUG_PATTERN.match(key):
            raise ValueError(
                "variant identifiers must be snake_case (lowercase letters, digits, underscore)"
            )
    return value


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
    notes: str | None = Field(
        default=None, description="Optional implementation or sourcing notes for the variant"
    )
    variants: Dict[str, "MetricVariant"] = Field(
        default_factory=dict,
        description="Optional nested variants that inherit this variant's filters",
    )
    value_type: str | None = Field(
        default=None,
        description="Override the display value type for this variant (number, percent, currency).",
    )

    _coerce_calculate = field_validator("calculate", mode="before")(_ensure_string_list)
    _validate_nested_keys = field_validator("variants", mode="after")(_ensure_variant_keys)

    @field_validator("value_type", mode="before")
    @classmethod
    def _validate_value_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip().lower()
        if candidate not in _VALUE_TYPES:
            raise ValueError(f"value_type must be one of {sorted(_VALUE_TYPES)}")
        return candidate


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
    define: str | None = Field(
        default=None,
        description="Optional base expression (e.g., DAX) describing how the metric is calculated",
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
    value_type: str = Field(
        default="number",
        description="Display value type for the metric (number, percent, currency).",
    )

    _coerce_calculate = field_validator("calculate", mode="before")(_ensure_string_list)

    @field_validator("value_type", mode="before")
    @classmethod
    def _validate_value_type(cls, value: str | None) -> str:
        if value is None:
            return "number"
        candidate = str(value).strip().lower()
        if candidate not in _VALUE_TYPES:
            raise ValueError(f"value_type must be one of {sorted(_VALUE_TYPES)}")
        return candidate

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
        return _ensure_variant_keys(value)

    def flattened_variants(self) -> Dict[str, MetricVariant]:
        """Return a mapping of fully-qualified variant keys (dot notation) to variants."""

        flattened: Dict[str, MetricVariant] = {}

        def _walk(prefix: str, variants: Dict[str, MetricVariant]) -> None:
            for key, variant in variants.items():
                fq_key = f"{prefix}.{key}" if prefix else key
                flattened[fq_key] = variant
                if variant.variants:
                    _walk(fq_key, variant.variants)

        _walk("", self.variants)
        return flattened

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
