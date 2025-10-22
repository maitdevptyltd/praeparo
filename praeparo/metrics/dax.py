"""Compile metric definitions into reusable DAX expressions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .catalog import MetricCatalog
from .models import MetricDefinition, MetricVariant
from ..utils import normalize_dax_expression


@dataclass(frozen=True)
class MetricMeasureDefinition:
    """Resolved DAX expression for a metric or variant."""

    key: str
    """Fully-qualified identifier (e.g. metric key or metric.variant)."""

    label: str
    """Display-friendly name sourced from the metric or variant."""

    expression: str
    """DAX expression representing the measure."""

    filters: tuple[str, ...]
    """Ordered list of filters applied while composing the expression."""

    description: str | None = None
    """Optional narrative or notes for the measure."""

    variant_path: str | None = None
    """Variant path relative to the metric (None for the base metric)."""


@dataclass(frozen=True)
class MetricDaxPlan:
    """Collection of DAX expressions for a metric and its variants."""

    metric_key: str
    base: MetricMeasureDefinition
    variants: dict[str, MetricMeasureDefinition]


class MetricDaxBuilder:
    """Convert metric definitions (and variants) into DAX expressions."""

    def __init__(self, catalog: MetricCatalog) -> None:
        self._catalog = catalog

    def compile_metric(self, metric_key: str) -> MetricDaxPlan:
        """Return the DAX plan for the supplied metric key."""

        metric = self._catalog.get_metric(metric_key)
        if metric is None:
            raise KeyError(f"Metric '{metric_key}' not found in catalog.")

        chain = _resolve_metric_chain(self._catalog, metric)
        define = _resolve_define(chain)
        base_filters = _collect_metric_filters(chain)

        base_expression = normalize_dax_expression(_compose_calculate(define, base_filters))
        base_measure = MetricMeasureDefinition(
            key=metric_key,
            label=metric.display_name,
            expression=base_expression,
            filters=tuple(base_filters),
            description=metric.description,
            variant_path=None,
        )

        variant_definitions: dict[str, MetricMeasureDefinition] = {}
        flattened_variants = metric.flattened_variants()
        if flattened_variants:
            for path, variant in flattened_variants.items():
                variant_filters = _collect_variant_filters(metric, path)
                combined_filters = tuple(base_filters + variant_filters)
                variant_expression = normalize_dax_expression(_compose_calculate(define, combined_filters))
                variant_key = f"{metric_key}.{path}"
                variant_definitions[path] = MetricMeasureDefinition(
                    key=variant_key,
                    label=variant.display_name,
                    expression=variant_expression,
                    filters=combined_filters,
                    description=variant.description,
                    variant_path=path,
                )

        return MetricDaxPlan(metric_key=metric_key, base=base_measure, variants=variant_definitions)


def _resolve_metric_chain(catalog: MetricCatalog, metric: MetricDefinition) -> list[MetricDefinition]:
    """Return the inheritance chain for the metric (root → leaf)."""

    chain: list[MetricDefinition] = []
    current: MetricDefinition | None = metric
    seen: set[str] = set()
    while current is not None:
        chain.append(current)
        parent_key = current.extends
        if parent_key is None:
            break
        if parent_key in seen:
            raise ValueError(f"Circular extends detected while resolving metric '{metric.key}'.")
        seen.add(parent_key)
        parent = catalog.get_metric(parent_key)
        if parent is None:
            raise KeyError(f"Metric '{metric.key}' extends unknown parent '{parent_key}'.")
        current = parent
    return list(reversed(chain))


def _resolve_define(chain: Iterable[MetricDefinition]) -> str:
    """Return the effective define block for the metric chain."""

    define: str | None = None
    for metric in chain:
        if metric.define:
            candidate = metric.define.strip()
            if candidate:
                define = candidate
    if not define:
        keys = " → ".join(item.key for item in chain)
        raise ValueError(f"Metric chain '{keys}' does not define a base expression.")
    return define


def _collect_metric_filters(chain: Iterable[MetricDefinition]) -> list[str]:
    """Collect filters from the inheritance chain in declaration order."""

    filters: list[str] = []
    for metric in chain:
        filters.extend(_normalise_filters(metric.calculate))
    return filters


def _collect_variant_filters(metric: MetricDefinition, path: str) -> list[str]:
    """Collect filters for the variant path (including ancestor variants)."""

    if not path:
        return []

    segments = path.split(".")
    filters: list[str] = []
    node: dict[str, MetricVariant] = dict(metric.variants)

    for segment in segments:
        if segment not in node:
            raise KeyError(f"Variant path '{path}' not found for metric '{metric.key}'.")
        variant = node[segment]
        filters.extend(_normalise_filters(variant.calculate))
        node = dict(variant.variants)

    return filters


def _normalise_filters(filters: Iterable[str]) -> list[str]:
    """Return a clean list of filter expressions."""

    cleaned: list[str] = []
    for value in filters or []:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        cleaned.append(text)
    return cleaned


def _format_block(text: str) -> str:
    lines = text.strip().splitlines()
    return "\n".join("    " + line.rstrip() for line in lines) if lines else ""


def _compose_calculate(base_expression: str, filters: Iterable[str]) -> str:
    """Wrap the base expression in CALCULATE when filters are supplied."""

    filter_list = _normalise_filters(filters)
    if not filter_list:
        return base_expression.strip()

    formatted_blocks = [_format_block(base_expression)]
    formatted_blocks.extend(_format_block(item) for item in filter_list)
    body = ",\n".join(block for block in formatted_blocks if block)
    return f"CALCULATE(\n{body}\n)"


__all__ = ["MetricDaxBuilder", "MetricDaxPlan", "MetricMeasureDefinition"]
