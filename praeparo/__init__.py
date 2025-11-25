"""Praeparo package public interface."""

from .metrics import (
    MetricDaxBuilder,
    MetricDaxPlan,
    MetricCatalog,
    MetricDiscoveryError,
    MetricDefinition,
    MetricGroupConfig,
    MetricMeasureDefinition,
    MetricRatioDefinition,
    MetricRatiosConfig,
    MetricVariant,
    discover_metric_files,
    load_metric_catalog,
)
from .models.matrix import (
    MatrixConfig,
    MatrixFilterConfig,
    MatrixTotals,
    MatrixValueConfig,
    RowTemplate,
)
from .utils import normalize_dax_expression
from .visuals import cartesian as _visuals_cartesian  # noqa: F401
from .visuals import powerbi as _visuals_powerbi  # noqa: F401

__all__ = [
    "MetricDaxBuilder",
    "MetricDaxPlan",
    "MetricCatalog",
    "MetricDiscoveryError",
    "MetricDefinition",
    "MetricGroupConfig",
    "MetricMeasureDefinition",
    "MetricRatioDefinition",
    "MetricRatiosConfig",
    "MetricVariant",
    "MatrixConfig",
    "MatrixFilterConfig",
    "MatrixTotals",
    "MatrixValueConfig",
    "RowTemplate",
    "normalize_dax_expression",
    "discover_metric_files",
    "load_metric_catalog",
]
