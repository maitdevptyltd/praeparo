"""Helpers for compiling metric definitions used by visuals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from praeparo.metrics import MetricDaxBuilder, MetricDaxPlan, MetricMeasureDefinition


@dataclass
class MetricCompilationCache:
    """Cache compiled metric plans to avoid redundant builder invocations."""

    _plans: Dict[str, MetricDaxPlan]
    _in_progress: set[str]

    def __init__(self) -> None:
        self._plans = {}
        self._in_progress = set()

    def get_plan(self, builder: MetricDaxBuilder, metric_key: str) -> MetricDaxPlan:
        plan = self._plans.get(metric_key)
        if plan is None:
            if metric_key in self._in_progress:
                raise ValueError(
                    f"Circular metric dependency detected while compiling '{metric_key}'."
                )

            self._in_progress.add(metric_key)
            try:
                plan = builder.compile_metric(metric_key, cache=self)
                self._plans[metric_key] = plan
            finally:
                self._in_progress.discard(metric_key)
        return plan


def resolve_metric_reference(
    *,
    builder: MetricDaxBuilder,
    cache: MetricCompilationCache,
    metric_key: str,
    variant_path: str | None,
) -> Tuple[str, MetricMeasureDefinition]:
    """Resolve a metric key (optionally with variant path) to a measure definition."""

    plan = cache.get_plan(builder, metric_key)

    if not variant_path:
        return metric_key, plan.base

    variants = plan.variants
    if variant_path not in variants:
        raise KeyError(f"Metric '{metric_key}' does not define variant '{variant_path}'.")
    definition = variants[variant_path]
    return definition.key, definition


__all__ = ["MetricCompilationCache", "resolve_metric_reference"]
