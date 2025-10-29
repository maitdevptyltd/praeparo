from __future__ import annotations

from dataclasses import dataclass

import pytest

from praeparo.metrics import MetricCatalog, MetricDaxBuilder, MetricDefinition
from praeparo.visuals.dax import MetricCompilationCache, resolve_metric_reference


@dataclass
class _CatalogBuilder:
    catalog: MetricCatalog
    builder: MetricDaxBuilder


def _catalog_with_metric() -> _CatalogBuilder:
    definition = MetricDefinition.model_validate(
        {
            "key": "documents_sent",
            "display_name": "Documents sent",
            "section": "Documents",
            "define": "SUM('fact_events'[DocumentsSent])",
            "calculate": [],
        }
    )
    catalog = MetricCatalog(metrics={definition.key: definition}, sources={}, files=[])
    builder = MetricDaxBuilder(catalog)
    return _CatalogBuilder(catalog=catalog, builder=builder)


def test_resolve_metric_reference_returns_base_measure() -> None:
    ctx = _catalog_with_metric()
    cache = MetricCompilationCache()
    reference, measure = resolve_metric_reference(
        builder=ctx.builder,
        cache=cache,
        metric_key="documents_sent",
        variant_path=None,
    )
    assert reference == "documents_sent"
    assert "DocumentsSent" in measure.expression


def test_resolve_metric_reference_unknown_variant_raises() -> None:
    ctx = _catalog_with_metric()
    cache = MetricCompilationCache()
    with pytest.raises(KeyError):
        resolve_metric_reference(
            builder=ctx.builder,
            cache=cache,
            metric_key="documents_sent",
            variant_path="manual",
        )
