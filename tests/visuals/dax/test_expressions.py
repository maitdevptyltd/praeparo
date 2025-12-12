from __future__ import annotations

import pytest

from praeparo.metrics import MetricCatalog, MetricDaxBuilder, MetricDefinition
from praeparo.visuals.dax import (
    MetricCompilationCache,
    MetricReference,
    ParsedExpression,
    parse_metric_expression,
    resolve_expression_metric,
)


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


def test_parse_metric_expression_ratio_to_infers_parent_denominator() -> None:
    parsed = parse_metric_expression("ratio_to(documents_sent.manual)")
    identifiers = [ref.identifier for ref in parsed.references]
    assert identifiers == ["documents_sent", "documents_sent.manual"]
    numerator_ref = next(ref for ref in parsed.references if ref.identifier == "documents_sent.manual")
    assert numerator_ref.ratio_to_ref == "documents_sent"


def test_parse_metric_expression_ratio_to_accepts_explicit_denominator() -> None:
    parsed = parse_metric_expression('ratio_to(documents_sent.manual, "lodgements.total")')
    identifiers = [ref.identifier for ref in parsed.references]
    assert identifiers == ["lodgements.total", "documents_sent.manual"]
    numerator_ref = next(ref for ref in parsed.references if ref.identifier == "documents_sent.manual")
    assert numerator_ref.ratio_to_ref == "lodgements.total"


def test_parse_metric_expression_ratio_to_emits_divide_dax() -> None:
    expr = parse_metric_expression("ratio_to(a.b)")
    dax = expr.to_dax({"a": "[Denominator]", "a.b": "[Numerator]"})
    assert dax == "DIVIDE(([Numerator]), ([Denominator]))"


def test_parse_metric_expression_ratio_to_invalid_usage_raises() -> None:
    with pytest.raises(ValueError, match="requires a dotted metric key"):
        parse_metric_expression("ratio_to(a)")
    with pytest.raises(ValueError, match="non-empty string"):
        parse_metric_expression('ratio_to(a.b, "")')
    with pytest.raises(TypeError, match="string metric key"):
        parse_metric_expression("ratio_to(a.b, 123)")


def _sample_catalog() -> tuple[MetricCatalog, MetricDaxBuilder]:
    definition = MetricDefinition.model_validate(
        {
            "key": "documents_sent",
            "display_name": "Documents sent",
            "section": "Documents",
            "define": "SUM('fact_events'[DocumentsSent])",
            "variants": {
                "manual": {
                    "display_name": "Manual",
                    "calculate": ["'fact_events'[IsManual] = TRUE()"],
                }
            },
        }
    )
    catalog = MetricCatalog(metrics={definition.key: definition}, sources={}, files=[])
    builder = MetricDaxBuilder(catalog)
    return catalog, builder


def test_resolve_expression_metric_compiles_definition() -> None:
    _, builder = _sample_catalog()
    cache = MetricCompilationCache()

    measure = resolve_expression_metric(
        metric_key="documents_sent.manual_ratio",
        expression="documents_sent.manual / documents_sent",
        builder=builder,
        cache=cache,
        label="Manual ratio",
    )

    assert measure.key == "documents_sent.manual_ratio"
    assert measure.label == "Manual ratio"
    assert "CALCULATE" in measure.expression
    assert "/" in measure.expression


def test_resolve_expression_metric_ratio_to_compiles_safe_divide() -> None:
    _, builder = _sample_catalog()
    cache = MetricCompilationCache()

    measure = resolve_expression_metric(
        metric_key="documents_sent.manual_ratio_safe",
        expression="ratio_to(documents_sent.manual)",
        builder=builder,
        cache=cache,
        label="Manual ratio safe",
    )

    assert "DIVIDE" in measure.expression


def test_resolve_expression_metric_self_reference_raises() -> None:
    _, builder = _sample_catalog()
    cache = MetricCompilationCache()

    with pytest.raises(ValueError):
        resolve_expression_metric(
            metric_key="documents_sent.manual_ratio",
            expression="documents_sent.manual_ratio + documents_sent",
            builder=builder,
            cache=cache,
        )
