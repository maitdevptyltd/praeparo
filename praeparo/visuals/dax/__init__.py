"""DAX planning utilities shared by Praeparo visuals."""

from .cache import MetricCompilationCache, resolve_metric_reference
from .expressions import MetricReference, ParsedExpression, parse_metric_expression
from .filters import combine_filter_groups, normalise_filter_group, wrap_expression_with_filters
from .planner_core import (
    MeasurePlan,
    VisualPlan,
    VisualDaxPlan,
    NameStrategy,
    default_name_strategy,
    slugify,
)
from .renderer import DEFAULT_MEASURE_TABLE, render_visual_plan

__all__ = [
    "DEFAULT_MEASURE_TABLE",
    "MetricCompilationCache",
    "MeasurePlan",
    "MetricReference",
    "ParsedExpression",
    "NameStrategy",
    "VisualPlan",
    "VisualDaxPlan",
    "combine_filter_groups",
    "default_name_strategy",
    "normalise_filter_group",
    "parse_metric_expression",
    "resolve_metric_reference",
    "render_visual_plan",
    "slugify",
    "wrap_expression_with_filters",
]
