"""Pydantic models describing metric registry definitions."""

from __future__ import annotations

import re
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from praeparo.models.scoped_calculate import ScopedCalculateFilters


_SLUG_PATTERN = re.compile(r"^[a-z0-9_]+$")
_VALUE_TYPES = {"number", "percent", "currency"}
_FORMAT_PATTERN = re.compile(r"^(number|percent|currency)(:\d+)?$")

MetricDefineEntry = str | Dict[str, str]
MetricDefinePayload = str | Dict[str, str] | List[MetricDefineEntry]


def _normalise_optional_format(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("format must be a string.")
    candidate = value.strip().lower()
    if not candidate:
        return None
    if not _FORMAT_PATTERN.match(candidate):
        raise ValueError(
            "format must start with one of ['currency', 'number', 'percent'] "
            "and may include an optional precision suffix like 'percent:2'."
        )
    return candidate


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


def _normalise_optional_expression(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("expression must be a string.")
    candidate = value.strip()
    if not candidate:
        return None
    return candidate


def _normalise_optional_string(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string.")
    candidate = value.strip()
    return candidate or None


def _ensure_optional_string_list(value: object, *, label: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
        return [candidate] if candidate else None
    if isinstance(value, list):
        cleaned: list[str] = []
        for item in value:
            if item is None:
                continue
            if not isinstance(item, str):
                raise TypeError(f"{label} entries must be strings")
            candidate = item.strip()
            if candidate:
                cleaned.append(candidate)
        return cleaned or None
    raise TypeError(f"{label} must be a string or list of strings")


def _ensure_snake_case_mapping_keys(
    value: Dict[str, str],
    *,
    label: str,
    forbid_prefix: str = "__",
) -> Dict[str, str]:
    for key in value:
        if not _SLUG_PATTERN.match(key):
            raise ValueError(f"{label} keys must be snake_case (lowercase letters, digits, underscore)")
        if forbid_prefix and key.startswith(forbid_prefix):
            raise ValueError(f"{label} keys may not start with '{forbid_prefix}' (reserved for framework fields).")
    return value


def _normalise_define_payload(value: object) -> List[MetricDefineEntry] | None:
    """Normalise a context-style `define` payload into a deterministic sequence.

    Define payloads accept the same shapes as visual context layers:

    - string define fragments
    - mapping of name -> fragment (named blocks)
    - sequences containing strings and/or mappings (mixed named + unlabelled)

    The returned representation mirrors the internal context merge shape: a list
    of one-item mappings (named blocks) plus plain strings (unlabelled blocks).
    """

    if value is None:
        return None

    cleaned: List[MetricDefineEntry] = []

    def _append_named(key: object, raw: object) -> None:
        if raw is None:
            return
        if not isinstance(raw, str):
            raise TypeError("define mapping values must be strings.")
        candidate = raw.strip()
        if not candidate:
            return

        name = str(key)
        if not _SLUG_PATTERN.match(name):
            raise ValueError("define keys must be snake_case (lowercase letters, digits, underscore)")
        cleaned.append({name: candidate})

    if isinstance(value, str):
        candidate = value.strip()
        return [candidate] if candidate else None

    if isinstance(value, dict):
        for key, raw in value.items():
            _append_named(key, raw)
        return cleaned or None

    if isinstance(value, list):
        for entry in value:
            if entry is None:
                continue
            if isinstance(entry, str):
                candidate = entry.strip()
                if candidate:
                    cleaned.append(candidate)
                continue
            if isinstance(entry, dict):
                for key, raw in entry.items():
                    _append_named(key, raw)
                continue
            raise TypeError("define entries must be strings or mappings of strings.")
        return cleaned or None

    raise TypeError("define must be supplied as a string, mapping, or sequence of strings/mappings.")


def _ensure_compose_list(value: object) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("compose must be a YAML list of strings.")
    cleaned: List[str] = []
    for entry in value:
        if entry is None:
            continue
        if not isinstance(entry, str):
            raise TypeError("compose entries must be strings.")
        candidate = entry.strip()
        if candidate:
            cleaned.append(candidate)
    return cleaned


class MetricExplainSpec(BaseModel):
    """Optional configuration for exporting row-level metric evidence."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str | None = Field(
        default=None,
        alias="from",
        description="Optional driving table expression used to build the evidence rowset.",
    )
    where: list[str] | None = Field(
        default=None,
        description="Optional extra rowset predicates appended after compiled calculate filters.",
    )
    grain: str | Dict[str, str] | None = Field(
        default=None,
        description="Evidence grain column reference (string) or a mapping of labels to column references.",
    )
    define: MetricDefinePayload | None = Field(
        default=None,
        description=(
            "Optional DEFINE blocks scoped to explain queries only. "
            "Accepts the same shapes as visual context `define` (string, mapping, or mixed sequences)."
        ),
    )
    select: Dict[str, str] | None = Field(
        default=None,
        description="Mapping of evidence column labels to DAX expressions evaluated per row.",
    )

    _normalise_from = field_validator("from_", mode="before")(
        lambda value: _normalise_optional_string(value, label="from")
    )
    _coerce_where = field_validator("where", mode="before")(
        lambda value: _ensure_optional_string_list(value, label="where")
    )

    @field_validator("grain", mode="before")
    @classmethod
    def _validate_grain(cls, value: object) -> str | Dict[str, str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            candidate = value.strip()
            return candidate or None
        if isinstance(value, dict):
            cleaned: Dict[str, str] = {}
            for key, raw in value.items():
                if raw is None:
                    continue
                if not isinstance(raw, str):
                    raise TypeError("grain mapping values must be strings.")
                candidate = raw.strip()
                if candidate:
                    cleaned[str(key)] = candidate
            return cleaned or None
        raise TypeError("grain must be a string or mapping of strings.")

    @field_validator("select", mode="before")
    @classmethod
    def _validate_select(cls, value: object) -> Dict[str, str] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError("select must be a mapping of label to DAX expression.")
        cleaned: Dict[str, str] = {}
        for key, raw in value.items():
            if raw is None:
                continue
            if not isinstance(raw, str):
                raise TypeError("select mapping values must be strings.")
            candidate = raw.strip()
            if candidate:
                cleaned[str(key)] = candidate
        return cleaned or None

    _validate_define = field_validator("define", mode="before")(_normalise_define_payload)

    @model_validator(mode="after")
    def _validate_keys(self) -> "MetricExplainSpec":
        if isinstance(self.grain, dict):
            _ensure_snake_case_mapping_keys(self.grain, label="grain")
        if isinstance(self.select, dict):
            _ensure_snake_case_mapping_keys(self.select, label="select")
        return self


class MetricVariant(BaseModel):
    """Variant of a base metric (e.g. automated, manual)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(..., description="Human-readable variant name")
    description: str | None = Field(
        default=None, description="Optional explanation for stakeholders"
    )
    calculate: ScopedCalculateFilters = Field(
        default_factory=ScopedCalculateFilters,
        description=(
            "Scoped DAX-style predicates applied on top of the base metric. "
            "DEFINE filters are baked into the compiled measure expression, while "
            "EVALUATE filters are applied when binding the measure in queries."
        ),
    )
    notes: str | None = Field(
        default=None, description="Optional implementation or sourcing notes for the variant"
    )
    explain: MetricExplainSpec | None = Field(
        default=None,
        description="Optional explain configuration used by `praeparo-metrics explain` to export row-level evidence.",
    )
    variants: Dict[str, "MetricVariant"] = Field(
        default_factory=dict,
        description="Optional nested variants that inherit this variant's filters",
    )
    format: str | None = Field(
        default=None,
        description="Optional display format token (percent, number, currency).",
    )
    value_type: str | None = Field(
        default=None,
        description="Override the display value type for this variant (number, percent, currency).",
    )

    _validate_nested_keys = field_validator("variants", mode="after")(_ensure_variant_keys)
    _validate_format = field_validator("format", mode="before")(_normalise_optional_format)

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
    compose: List[str] = Field(
        default_factory=list,
        description=(
            "Optional list of component file references to merge into this metric "
            "before applying the metric's own fields."
        ),
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
    expression: str | None = Field(
        default=None,
        description="Optional arithmetic expression over other metrics.",
    )
    notes: str | None = Field(
        default=None, description="Additional implementation or commentary notes"
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Optional free-form taxonomy tags (e.g. timeliness, automation)",
    )
    calculate: ScopedCalculateFilters = Field(
        default_factory=ScopedCalculateFilters,
        description=(
            "Scoped DAX-style predicates describing the metric scope. "
            "DEFINE filters are baked into the compiled measure expression, while "
            "EVALUATE filters are applied when binding the measure in queries."
        ),
    )
    variants: Dict[str, MetricVariant] = Field(
        default_factory=dict,
        description="Named variants that apply additional predicates or business logic",
    )
    explain: MetricExplainSpec | None = Field(
        default=None,
        description="Optional explain configuration used by `praeparo-metrics explain` to export row-level evidence.",
    )
    ratios: MetricRatiosConfig | None = Field(
        default=None, description="Automatic or explicit ratios derived from this metric"
    )
    format: str | None = Field(
        default=None,
        description="Optional display format token (percent, number, currency).",
    )
    value_type: str = Field(
        default="number",
        description="Display value type for the metric (number, percent, currency).",
    )

    _validate_format = field_validator("format", mode="before")(_normalise_optional_format)
    _normalise_expression = field_validator("expression", mode="before")(
        _normalise_optional_expression
    )
    _validate_compose = field_validator("compose", mode="before")(_ensure_compose_list)

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

    @model_validator(mode="after")
    def _validate_base_expression_exclusive(self) -> "MetricDefinition":
        define = self.define.strip() if isinstance(self.define, str) else ""
        expression = self.expression.strip() if isinstance(self.expression, str) else ""
        if define and expression:
            raise ValueError("metric cannot define both 'define' and 'expression'")
        return self

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


class MetricGroupConfig(BaseModel):
    """Logical grouping of metrics with shared filters."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str | None = Field(
        default=None,
        description="Optional identifier for referencing the group.",
    )
    label: str | None = Field(default=None, description="Optional display label for the group.")
    description: str | None = Field(
        default=None,
        description="Narrative notes describing the group purpose.",
    )
    calculate: List[str] = Field(
        default_factory=list,
        description="Filters applied to every metric within this group.",
    )
    metrics: List[object] = Field(
        default_factory=list,
        description="Metric keys (or nested groups) included in the group.",
    )

    _coerce_calculate = field_validator("calculate", mode="before")(_ensure_string_list)

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _SLUG_PATTERN.match(value):
            raise ValueError("group key must be snake_case (lowercase letters, digits, underscore)")
        return value

    @field_validator("metrics", mode="after")
    @classmethod
    def _validate_metrics(cls, value: List[object]) -> List[object]:
        cleaned: List[object] = []
        for item in value:
            if isinstance(item, str):
                candidate = item.strip()
                if candidate:
                    cleaned.append(candidate)
            elif isinstance(item, MetricGroupConfig):
                cleaned.append(item)
            else:
                raise TypeError("metrics entries must be strings or MetricGroupConfig instances")
        return cleaned

MetricGroupConfig.model_rebuild()
