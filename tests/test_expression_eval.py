from __future__ import annotations

import pytest

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


def test_expression_eval_ratio_to_infers_parent_denominator() -> None:
    parsed = parse_metric_expression("ratio_to(a.b)")
    value = evaluate_expression(parsed, {"a.b": 5, "a": 10})
    assert value == 0.5


def test_expression_eval_ratio_to_handles_missing_or_zero_denominator() -> None:
    parsed = parse_metric_expression("ratio_to(a.b)")
    assert evaluate_expression(parsed, {"a.b": 5, "a": 0}) is None
    assert evaluate_expression(parsed, {"a.b": 5}) is None


def test_expression_eval_ratio_to_uses_fallback_for_missing_or_zero_denominator() -> None:
    parsed = parse_metric_expression("ratio_to(a.b, 1)")
    assert evaluate_expression(parsed, {"a.b": 5, "a": 0}) == 1
    assert evaluate_expression(parsed, {"a.b": 5}) == 1


def test_expression_eval_ratio_to_uses_explicit_denominator_with_fallback() -> None:
    parsed = parse_metric_expression('ratio_to(a.b, "c", 0.25)')
    assert evaluate_expression(parsed, {"a.b": 5, "c": 0}) == pytest.approx(0.25)
    assert evaluate_expression(parsed, {"a.b": 5}) == pytest.approx(0.25)


def test_expression_eval_ratio_to_with_fallback_keeps_real_ratio_when_denominator_present() -> None:
    parsed = parse_metric_expression("ratio_to(a.b, 1)")
    assert evaluate_expression(parsed, {"a.b": 5, "a": 10}) == pytest.approx(0.5)


def test_expression_eval_ratio_to_with_fallback_still_propagates_missing_numerator() -> None:
    parsed = parse_metric_expression("ratio_to(a.b, 1)")
    assert evaluate_expression(parsed, {"a": 10}) is None


def test_expression_eval_ratio_to_with_fallback_returns_fallback_when_numerator_and_denominator_missing() -> None:
    parsed = parse_metric_expression("ratio_to(a.b, 1)")
    assert evaluate_expression(parsed, {}) == 1


def test_expression_eval_ratio_to_weighted_expression() -> None:
    parsed = parse_metric_expression("ratio_to(a.b) * 0.85 + ratio_to(a.c) * 1.0")
    value = evaluate_expression(parsed, {"a.b": 5, "a.c": 2, "a": 10})
    assert value == pytest.approx(0.625)


def test_expression_eval_min_max_functions() -> None:
    parsed = parse_metric_expression("min(a, b) + max(a, b)")
    value = evaluate_expression(parsed, {"a": 2, "b": 5})
    assert value == 7


def test_expression_eval_min_propagates_ratio_to_missing_value() -> None:
    parsed = parse_metric_expression("min(ratio_to(a.b) / 0.85, 1)")
    assert evaluate_expression(parsed, {"a.b": 5, "a": 0}) is None


def test_expression_eval_min_with_ratio_to_fallback_does_not_propagate_blank() -> None:
    parsed = parse_metric_expression("min(ratio_to(a.b, 1) / 0.85, 1)")
    assert evaluate_expression(parsed, {"a.b": 5, "a": 0}) == pytest.approx(1.0)
