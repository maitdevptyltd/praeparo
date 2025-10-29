from __future__ import annotations

import pytest

from praeparo.visuals.dax import MetricReference, ParsedExpression, parse_metric_expression


def test_parse_metric_expression_returns_references() -> None:
    parsed = parse_metric_expression("documents_sent.manual + documents_sent.automated")
    identifiers = [ref.identifier for ref in parsed.references]
    assert identifiers == ["documents_sent.manual", "documents_sent.automated"]


def test_parse_metric_expression_to_dax_substitutes_values() -> None:
    expr = parse_metric_expression("a + b")
    dax = expr.to_dax({"a": "[MeasureA]", "b": "[MeasureB]"})
    assert dax == "(([MeasureA]) + ([MeasureB]))"


def test_parse_metric_expression_missing_substitution_raises() -> None:
    expr = parse_metric_expression("a + b")
    with pytest.raises(KeyError):
        expr.to_dax({"a": "[MeasureA]"})


def test_parse_metric_expression_rejects_unsupported_operator() -> None:
    with pytest.raises(ValueError):
        parse_metric_expression("a % b")


def test_parse_metric_expression_rejects_invalid_constant() -> None:
    with pytest.raises(TypeError):
        parse_metric_expression("a + 'hello'")
