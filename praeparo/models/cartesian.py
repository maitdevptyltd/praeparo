"""Pydantic models describing cartesian (column/bar) chart visuals."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from praeparo.visuals.metrics import VisualMetricConfig, VisualMockConfig, normalise_str_sequence

from .visual_base import BaseVisualConfig


class CategoryDataType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    DATE = "date"


class CategoryOrder(str, Enum):
    ASCENDING = "asc"
    DESCENDING = "desc"


class CategorySortMode(str, Enum):
    SERIES = "series"
    VALUE = "value"
    CATEGORY = "category"


class CategorySortConfig(BaseModel):
    """Declarative sorting instructions for a category axis."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    by: CategorySortMode = Field(
        default=CategorySortMode.CATEGORY,
        description="Sorting strategy applied to categories.",
    )
    direction: CategoryOrder = Field(
        default=CategoryOrder.ASCENDING,
        description="Sort direction applied to the category axis.",
    )
    series_id: str | None = Field(
        default=None,
        description="Optional series identifier used when sorting by series values.",
    )

    @field_validator("series_id")
    @classmethod
    def _validate_series_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        candidate = value.strip()
        if not candidate:
            return None
        return candidate


class CategoryConfig(BaseModel):
    """Configuration for the category axis of a column/bar chart."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    field: str = Field(
        ...,
        description="Semantic model column referenced by the category axis (e.g. `'dim_calendar'[month]`).",
    )
    label: str | None = Field(
        default=None,
        description="Optional display label for the axis.",
    )
    data_type: CategoryDataType | None = Field(
        default=None,
        description="Optional hint describing the category data type.",
    )
    format: str | None = Field(
        default=None,
        description="Formatting token applied to rendered category labels.",
    )
    order: CategoryOrder | None = Field(
        default=None,
        description="Explicit chronological ordering applied after query execution.",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        description="Maximum number of categories to surface after sorting.",
    )
    mock_values: Sequence[str] | None = Field(
        default=None,
        description="Optional ordered mock category labels used when seeding sample data.",
    )
    sort: CategorySortConfig | None = Field(
        default=None,
        description="Advanced sorting instructions applied to resolved categories.",
    )

    @field_validator("field")
    @classmethod
    def _normalise_field(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            msg = "category.field cannot be empty."
            raise ValueError(msg)
        return candidate

    @field_validator("label", "format", mode="before")
    @classmethod
    def _normalise_optional(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            candidate = value.strip()
            return candidate or None
        return value

    @field_validator("mock_values", mode="before")
    @classmethod
    def _normalise_mock_values(cls, value):
        if value is None:
            return None
        values = normalise_str_sequence(value)
        return tuple(values) if values else None


class AxisConfig(BaseModel):
    """Metadata describing a value axis."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    label: str | None = Field(default=None, description="Axis title displayed alongside ticks.")
    format: str | None = Field(default=None, description="Formatting directive (e.g. percent:0).")
    minimum: float | None = Field(default=None, alias="min", description="Optional lower bound override.")
    maximum: float | None = Field(default=None, alias="max", description="Optional upper bound override.")
    tick_format: str | None = Field(default=None, alias="ticks", description="Custom tick formatting rule.")

    @field_validator("label", "format", "tick_format", mode="before")
    @classmethod
    def _normalise_optional(cls, value):  # noqa: ANN001
        if value is None:
            return value
        if isinstance(value, str):
            candidate = value.strip()
            return candidate or None
        return value


class ValueAxesConfig(BaseModel):
    """Primary/secondary axis configuration."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    primary: AxisConfig = Field(..., description="Primary value axis configuration.")
    secondary: AxisConfig | None = Field(default=None, description="Optional secondary axis.")


class LegendPosition(str, Enum):
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    NONE = "none"


class LegendConfig(BaseModel):
    """Legend placement metadata."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    position: LegendPosition = Field(
        default=LegendPosition.TOP,
        description="Where the legend is rendered relative to the plot.",
    )


class LayoutConfig(BaseModel):
    """Container for presentation-only layout toggles."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    legend: LegendConfig | None = Field(default=None, description="Legend placement options.")


class SeriesStackingMode(str, Enum):
    NORMAL = "normal"
    PERCENT = "percent"
    NONE = "none"


class SeriesStackingConfig(BaseModel):
    """Series-level stacking instructions."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str | None = Field(
        default=None,
        description="Grouping key used to stack related series together.",
    )
    mode: SeriesStackingMode = Field(
        default=SeriesStackingMode.NORMAL,
        description="Stacking behaviour applied to the series.",
    )

    @field_validator("key")
    @classmethod
    def _normalise_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        return candidate or None


class SeriesMarkerConfig(BaseModel):
    """Marker styling for line series."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    show: bool = Field(default=False, description="When true, render markers on the line trace.")
    size: int | None = Field(default=None, description="Optional marker size override.")


class DataLabelConfig(BaseModel):
    """Data label styling per series."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    position: str | None = Field(default=None, description="Label position token (e.g. above, outside_end).")
    format: str | None = Field(default=None, description="Formatting directive applied to label text.")

    @field_validator("position", "format", mode="before")
    @classmethod
    def _normalise_text(cls, value):  # noqa: ANN001
        if value is None:
            return value
        if isinstance(value, str):
            candidate = value.strip()
            return candidate or None
        return value


class SeriesTransformMode(str, Enum):
    PERCENT_OF_TOTAL = "percent_of_total"


class SeriesTransformConfig(BaseModel):
    """Declarative post-processing applied to series data."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    mode: SeriesTransformMode = Field(..., description="Transformation applied to the resolved series values.")
    scope: Literal["category", "visual"] = Field(
        default="visual",
        description="Scope applied when calculating the transform.",
    )
    source_series: str | None = Field(
        default=None,
        description="Optional series identifier used as the value source.",
    )

    @field_validator("source_series")
    @classmethod
    def _normalise_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        return candidate or None


class CartesianSeriesConfig(BaseModel):
    """Series rendered within a cartesian chart."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(..., description="Stable identifier for the series.")
    label: str | None = Field(default=None, description="Display label for the series.")
    type: Literal["column", "line"] = Field(
        default="column",
        description="Trace type rendered for this series.",
    )
    axis: Literal["primary", "secondary"] = Field(
        default="primary",
        description="Axis used to scale this series.",
    )
    format: str | None = Field(default=None, description="Formatting directive for rendered values.")
    stacking: SeriesStackingConfig | None = Field(
        default=None,
        description="Optional stacking behaviour applied to this series.",
    )
    marker: SeriesMarkerConfig | None = Field(
        default=None,
        description="Marker styling used for line traces.",
    )
    data_labels: DataLabelConfig | None = Field(
        default=None,
        description="Display options for per-point data labels.",
    )
    show_as: str | None = Field(
        default=None,
        description="Optional semantic for derived displays (e.g. percent of total).",
    )
    transform: SeriesTransformConfig | None = Field(
        default=None,
        description="Optional derived value instruction executed after retrieval.",
    )
    metric: VisualMetricConfig = Field(
        ...,
        description="Metric binding powering this series.",
    )

    @field_validator("id")
    @classmethod
    def _normalise_id(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            msg = "series.id cannot be empty."
            raise ValueError(msg)
        return candidate

    @field_validator("label", "format", "show_as", mode="before")
    @classmethod
    def _normalise_optional(cls, value):  # noqa: ANN001
        if value is None:
            return value
        if isinstance(value, str):
            candidate = value.strip()
            return candidate or None
        return value

    @model_validator(mode="after")
    def _validate_transform(self) -> "CartesianSeriesConfig":
        if self.transform and self.metric.expression:
            raise ValueError("series.transform is not supported for inline expression metrics.")
        return self


class CartesianChartConfigBase(BaseVisualConfig):
    """Shared cartesian chart configuration without a visual type discriminator."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # The base config intentionally omits the visual type discriminator so Python-backed
    # visuals can reuse this model without conflicting with the YAML `type` meta field.
    type: str | None = Field(default=None, description="Visual type discriminator.", exclude=True)
    title: str | None = Field(default=None, description="Optional chart title.")
    description: str | None = Field(default=None, description="Helper copy for editors.")
    datasource: str | None = Field(
        default=None,
        alias="dataSource",
        description="Optional datasource reference used for live execution.",
    )
    define: str | Sequence[str] | None = Field(
        default=None,
        description="DEFINE blocks prepended to generated DAX statements.",
    )
    calculate: Sequence[str] | None = Field(
        default=None,
        description="CALCULATE filters applied globally to every measure in the visual.",
    )
    category: CategoryConfig = Field(
        ...,
        description="Configuration for the category axis.",
    )
    value_axes: ValueAxesConfig = Field(
        ...,
        description="Primary (and optional secondary) axes.",
    )
    layout: LayoutConfig | None = Field(
        default=None,
        description="Presentation-focused layout overrides.",
    )
    series: list[CartesianSeriesConfig] = Field(
        ...,
        description="Series rendered in the chart.",
    )
    mock: VisualMockConfig | None = Field(
        default=None,
        description="Mock data scenarios used for previews.",
    )

    @field_validator("datasource")
    @classmethod
    def _normalise_datasource(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        return candidate or None

    @field_validator("define", mode="before")
    @classmethod
    def _normalise_define(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return tuple(normalise_str_sequence(value))

    @field_validator("calculate", mode="before")
    @classmethod
    def _normalise_calculate(cls, value):
        if value is None:
            return tuple()
        return tuple(normalise_str_sequence(value))

    @model_validator(mode="after")
    def _ensure_unique_series(self) -> "CartesianChartConfigBase":
        if not self.series:
            raise ValueError("At least one series must be defined for a cartesian chart.")

        identifiers = [entry.id for entry in self.series]
        if len(identifiers) != len(set(identifiers)):
            msg = "Series identifiers must be unique within a visual."
            raise ValueError(msg)
        return self


class CartesianChartConfig(CartesianChartConfigBase):
    """Top-level configuration for registered column/bar visuals."""

    type: Literal["column", "bar"] = Field(
        description="Visual type discriminator.",
    )
    schema_version: str | None = Field(
        default=None,
        alias="schema",
        description="Optional schema version identifier for the visual document.",
    )


class PythonCartesianChartConfig(CartesianChartConfigBase):
    """Config model for Python-backed cartesian visuals referenced via type: ./visual.py."""

    # Reserved for potential Python-only extensions in future.
    pass


__all__ = [
    "AxisConfig",
    "CartesianChartConfig",
    "CartesianChartConfigBase",
    "CartesianSeriesConfig",
    "CategoryConfig",
    "CategoryDataType",
    "CategoryOrder",
    "CategorySortConfig",
    "CategorySortMode",
    "DataLabelConfig",
    "LayoutConfig",
    "LegendConfig",
    "LegendPosition",
    "SeriesMarkerConfig",
    "SeriesStackingConfig",
    "SeriesStackingMode",
    "SeriesTransformConfig",
    "SeriesTransformMode",
    "ValueAxesConfig",
    "PythonCartesianChartConfig",
]
