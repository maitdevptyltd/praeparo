"""Shared Pydantic models for declarative visual definitions."""

from __future__ import annotations

from typing import Iterable, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


CalculateInput = str | List[str]


def normalise_str_sequence(value: CalculateInput | Iterable[str] | None) -> List[str]:
    """Coerce a string or iterable of strings into a clean list."""

    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    else:
        items = list(value)
    normalised: List[str] = []
    for item in items:
        if not isinstance(item, str):
            raise TypeError("entries must be strings")
        trimmed = item.strip()
        if trimmed:
            normalised.append(trimmed)
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
    mock: VisualMetricMock | None = Field(
        default=None,
        description="Optional mock configuration specific to this metric.",
    )

    _normalise_calculate = field_validator("calculate", mode="before")(normalise_str_sequence)


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
