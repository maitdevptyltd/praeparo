"""Backwards-compatible imports for metric expressions.

`praeparo.expressions.metrics` holds the neutral implementation so both registry
metrics and visuals can compile arithmetic expressions without circular imports.
This module re-exports the public surface for legacy import paths.
"""

from praeparo.expressions.metrics import (  # noqa: F401
    MetricReference,
    ParsedExpression,
    parse_metric_expression,
    resolve_expression_metric,
)

__all__ = [
    "MetricReference",
    "ParsedExpression",
    "parse_metric_expression",
    "resolve_expression_metric",
]
