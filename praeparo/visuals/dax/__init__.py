"""DAX planning utilities shared by Praeparo visuals."""

from .cache import MetricCompilationCache, resolve_metric_reference
from .expressions import (
    MetricReference,
    ParsedExpression,
    parse_metric_expression,
    resolve_expression_metric,
)
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
from .utils import (
    generate_measure_names,
    iter_group_metrics,
    normalise_define_blocks,
    split_metric_identifier,
)

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
    "generate_measure_names",
    "iter_group_metrics",
    "normalise_filter_group",
    "normalise_define_blocks",
    "parse_metric_expression",
    "resolve_expression_metric",
    "resolve_metric_reference",
    "render_visual_plan",
    "slugify",
    "split_metric_identifier",
    "wrap_expression_with_filters",
]
