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


def test_parse_metric_expression_ratio_to_accepts_inferred_denominator_with_fallback() -> None:
    parsed = parse_metric_expression("ratio_to(documents_sent.manual, 1)")
    identifiers = [ref.identifier for ref in parsed.references]
    assert identifiers == ["documents_sent", "documents_sent.manual"]
    numerator_ref = next(ref for ref in parsed.references if ref.identifier == "documents_sent.manual")
    assert numerator_ref.ratio_to_ref == "documents_sent"


def test_parse_metric_expression_ratio_to_emits_divide_dax() -> None:
    expr = parse_metric_expression("ratio_to(a.b)")
    dax = expr.to_dax({"a": "[Denominator]", "a.b": "[Numerator]"})
    assert dax == "DIVIDE(([Numerator]), ([Denominator]))"


def test_parse_metric_expression_ratio_to_emits_divide_with_fallback_dax() -> None:
    expr = parse_metric_expression("ratio_to(a.b, 1)")
    dax = expr.to_dax({"a": "[Denominator]", "a.b": "[Numerator]"})
    assert dax == (
        "(VAR __ratio_den_1 = ([Denominator]) "
        "RETURN IF(ISBLANK(__ratio_den_1) || __ratio_den_1 = 0, 1, DIVIDE(([Numerator]), __ratio_den_1)))"
    )


def test_parse_metric_expression_ratio_to_emits_divide_with_explicit_denominator_and_fallback_dax() -> None:
    expr = parse_metric_expression('ratio_to(a.b, "c", 0.5)')
    dax = expr.to_dax({"a.b": "[Numerator]", "c": "[Denominator]"})
    assert dax == (
        "(VAR __ratio_den_1 = ([Denominator]) "
        "RETURN IF(ISBLANK(__ratio_den_1) || __ratio_den_1 = 0, 0.5, DIVIDE(([Numerator]), __ratio_den_1)))"
    )


def test_parse_metric_expression_min_collects_references_in_order() -> None:
    parsed = parse_metric_expression("min(documents_sent.manual, documents_sent.automated)")
    identifiers = [ref.identifier for ref in parsed.references]
    assert identifiers == ["documents_sent.manual", "documents_sent.automated"]


def test_parse_metric_expression_max_collects_references_in_order() -> None:
    parsed = parse_metric_expression("max(a, b)")
    identifiers = [ref.identifier for ref in parsed.references]
    assert identifiers == ["a", "b"]


def test_parse_metric_expression_min_emits_blank_safe_minx() -> None:
    expr = parse_metric_expression("min(ratio_to(a.b) / 0.85, 1)")
    dax = expr.to_dax({"a": "[Denominator]", "a.b": "[Numerator]"})
    assert "DIVIDE" in dax
    assert "VAR __values_" in dax
    assert "FILTER" in dax
    assert "ISBLANK([Value])" in dax
    assert "BLANK()" in dax
    assert "MINX" in dax


def test_parse_metric_expression_max_emits_blank_safe_maxx() -> None:
    expr = parse_metric_expression("MAX(ratio_to(a.b) / 0.85, 1)")
    dax = expr.to_dax({"a": "[Denominator]", "a.b": "[Numerator]"})
    assert "DIVIDE" in dax
    assert "VAR __values_" in dax
    assert "FILTER" in dax
    assert "ISBLANK([Value])" in dax
    assert "BLANK()" in dax
    assert "MAXX" in dax


def test_parse_metric_expression_ratio_to_invalid_usage_raises() -> None:
    with pytest.raises(ValueError, match="requires a dotted metric key"):
        parse_metric_expression("ratio_to(a)")
    with pytest.raises(ValueError, match="non-empty string"):
        parse_metric_expression('ratio_to(a.b, "")')
    with pytest.raises(TypeError, match="string metric key when a fallback is provided"):
        parse_metric_expression("ratio_to(a.b, 0, 1)")
    with pytest.raises(TypeError, match="numeric literal"):
        parse_metric_expression('ratio_to(a.b, "c", "x")')
    with pytest.raises(TypeError, match="numeric literal"):
        parse_metric_expression("ratio_to(a.b, test)")


def test_parse_metric_expression_min_invalid_usage_raises() -> None:
    with pytest.raises(ValueError, match="requires at least two arguments"):
        parse_metric_expression("min(a)")
    with pytest.raises(TypeError, match="does not accept keyword arguments"):
        parse_metric_expression("min(a, b=1)")


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
