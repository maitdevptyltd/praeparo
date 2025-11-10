from __future__ import annotations

from praeparo.datasets.expression_eval import evaluate_expression
from praeparo.visuals.dax.expressions import parse_metric_expression


def test_expression_eval_basic_arithmetic() -> None:
    parsed = parse_metric_expression("documents_sent + documents_sent.manual")
    value = evaluate_expression(parsed, {"documents_sent": 200, "documents_sent.manual": 50})
    assert value == 250


def test_expression_eval_handles_division_by_zero() -> None:
    parsed = parse_metric_expression("documents_sent / documents_sent.manual")
    value = evaluate_expression(parsed, {"documents_sent": 100, "documents_sent.manual": 0})
    assert value == 0


def test_expression_eval_with_constants() -> None:
    parsed = parse_metric_expression("documents_sent.manual + 5")
    value = evaluate_expression(parsed, {"documents_sent.manual": 10})
    assert value == 15
