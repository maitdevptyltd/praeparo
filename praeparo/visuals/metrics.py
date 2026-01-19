"""Shared Pydantic models for declarative visual definitions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


CalculateInput = str | Sequence[str] | Mapping[str, str] | Sequence[str | Mapping[str, str]]


def normalise_str_sequence(value: CalculateInput | Iterable[str] | None) -> List[str]:
    """Coerce calculate-style inputs into a clean list of strings.

    Visuals frequently use the same shorthands as packs and context layers:

    - String: single predicate.
    - Sequence of strings: ordered predicates.
    - Mapping: named predicates (values are used; keys are labels).
    - Mixed sequences containing one-item mappings.
    """

    if value is None:
        return []

    def _coerce_item(item: object) -> list[str]:
        if item is None:
            return []
        if isinstance(item, str):
            trimmed = item.strip()
            return [trimmed] if trimmed else []
        if isinstance(item, Mapping):
            flattened: list[str] = []
            for candidate in item.values():
                if candidate is None:
                    continue
                if not isinstance(candidate, str):
                    raise TypeError("entries must be strings")
                trimmed = candidate.strip()
                if trimmed:
                    flattened.append(trimmed)
            return flattened
        raise TypeError("entries must be strings")

    raw_items: list[object]
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, Mapping):
        raw_items = list(value.values())
    else:
        if not isinstance(value, Iterable):
            raise TypeError("entries must be strings")
        raw_items = list(value)

    normalised: List[str] = []
    for item in raw_items:
        if isinstance(item, Mapping):
            normalised.extend(_coerce_item(item))
        else:
            normalised.extend(_coerce_item(item))
    return normalised


class VisualMetricMockScenario(BaseModel):
    """Baseline characteristics for a visual mock scenario."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    label: Optional[str] = Field(default=None, description="Optional display label for the scenario.")
    multiplier: float = Field(default=1.0, description="Scale factor applied to base mock values.")
    offset: float = Field(default=0.0, description="Absolute offset applied to base mock values.")
    jitter: float = Field(default=0.0, description="Random jitter range for generated mock values.")


class VisualMetricMockScenarioOverride(BaseModel):
    """Overrides applied to a specific mock scenario for a metric."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    multiplier: float | None = Field(default=None, description="Scenario-specific multiplier override.")
    offset: float | None = Field(default=None, description="Scenario-specific offset override.")
    jitter: float | None = Field(default=None, description="Scenario-specific jitter override.")


class VisualMetricMock(BaseModel):
    """Mock configuration for a metric when live data is unavailable."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    factory: str = Field(
        default="count",
        description="Mock factory type (e.g. count, currency, ratio, duration).",
    )
    mean: float | None = Field(default=None, description="Expected mean value for generated samples.")
    trend: float | None = Field(default=None, description="Linear trend applied across samples.")
    trend_range: tuple[float, float] | None = Field(
        default=None,
        description="Optional min/max bounds for the trend component.",
    )
    jitter: float | None = Field(default=None, description="Random jitter applied per sample.")
    minimum: float | None = Field(default=None, alias="min", description="Lower bound for generated values.")
    maximum: float | None = Field(default=None, alias="max", description="Upper bound for generated values.")
    scenario_overrides: dict[str, VisualMetricMockScenarioOverride] = Field(
        default_factory=dict,
        description="Per-scenario overrides applied on top of the base mock configuration.",
    )

    @field_validator("trend_range", mode="before")
    @classmethod
    def _normalise_trend_range(cls, value: object) -> tuple[float, float] | None:
        if value is None:
            return None
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return float(value[0]), float(value[1])
        raise TypeError("trend_range must be a two-value list or tuple")

    @field_validator("factory", mode="before")
    @classmethod
    def _normalise_factory(cls, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError("factory must be a string")
        candidate = value.strip().lower()
        allowed = {"count", "currency", "ratio", "duration"}
        if candidate not in allowed:
            raise ValueError(f"factory must be one of {sorted(allowed)}")
        return candidate


class VisualMockConfig(BaseModel):
    """Container for mock scenarios referenced by a visual."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    scenarios: dict[str, VisualMetricMockScenario] = Field(
        default_factory=dict,
        description="Named mock scenarios available to metrics within the visual.",
    )


class VisualMetricConfig(BaseModel):
    """Reference to a metric or expression used in a visual."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str = Field(..., description="Metric key or virtual identifier consumed by the visual.")
    label: str | None = Field(default=None, description="Optional display label override for the metric.")
    expression: str | None = Field(
        default=None,
        description="Inline expression that replaces the metric lookup when provided.",
    )
    calculate: List[str] = Field(
        default_factory=list,
        description="Additional predicates applied when resolving this metric for the visual.",
    )
    ratio_to: str | bool | None = Field(
        default=None,
        description=(
            "Optional ratio hint for this metric. "
            "Use true to ratio against the inferred base metric (trimmed variant), "
            "or provide an explicit metric key."
        ),
    )
    mock: VisualMetricMock | None = Field(
        default=None,
        description="Optional mock configuration specific to this metric.",
    )

    _normalise_calculate = field_validator("calculate", mode="before")(normalise_str_sequence)
    @field_validator("ratio_to", mode="before")
    @classmethod
    def _normalise_ratio_to(cls, value: object) -> str | bool | None:
        if value is None or value is False:
            return None
        if value is True:
            return True
        if isinstance(value, str):
            candidate = value.strip()
            return candidate or None
        raise TypeError("ratio_to must be true, false, or a string metric key.")


class VisualGroupConfig(BaseModel):
    """Logical grouping of visual metrics with shared filters."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str | None = Field(
        default=None,
        description="Optional identifier for referencing this group elsewhere in the visual definition.",
    )
    label: str | None = Field(default=None, description="Optional display label for the group.")
    description: str | None = Field(default=None, description="Narrative notes describing the group.")
    calculate: List[str] = Field(
        default_factory=list,
        description="Filters applied to every metric nested within this group.",
    )
    metrics: List[object] = Field(
        default_factory=list,
        description="Metric keys or nested groups inheriting this group's filters.",
    )

    _normalise_calculate = field_validator("calculate", mode="before")(normalise_str_sequence)
    @field_validator("metrics", mode="after")
    @classmethod
    def _validate_metrics(cls, value: List[object]) -> List[object]:
        cleaned: List[object] = []
        for item in value:
            if isinstance(item, str):
                candidate = item.strip()
                if candidate:
                    cleaned.append(candidate)
            elif isinstance(item, (VisualMetricConfig, VisualGroupConfig)):
                cleaned.append(item)
            else:
                raise TypeError("metrics entries must be strings, VisualMetricConfig, or VisualGroupConfig")
        return cleaned


VisualGroupConfig.model_rebuild()


__all__ = [
    "CalculateInput",
    "VisualMetricConfig",
    "VisualMetricMock",
    "VisualMetricMockScenario",
    "VisualMetricMockScenarioOverride",
    "VisualMockConfig",
    "normalise_str_sequence",
]
