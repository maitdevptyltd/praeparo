"""Shared helper functions for DAX visual planners."""

from __future__ import annotations

from typing import Iterable, Iterator, Sequence

from praeparo.visuals.metrics import VisualGroupConfig, VisualMetricConfig

from .planner_core import NameStrategy, default_name_strategy


def normalise_define_blocks(blocks: str | Sequence[str] | None) -> tuple[str, ...]:
    """Return a tuple of DEFINE blocks stripped of surrounding whitespace."""

    if not blocks:
        return ()
    if isinstance(blocks, str):
        candidates: Iterable[str] = blocks.split("\n\n")
    else:
        candidates = blocks
    cleaned: list[str] = []
    for block in candidates:
        if not block:
            continue
        text = block.strip()
        if text:
            cleaned.append(text)
    return tuple(cleaned)


def split_metric_identifier(identifier: str) -> tuple[str, str | None]:
    """Split a dotted metric identifier into base key and variant path."""

    if not identifier or not identifier.strip():
        raise ValueError("Metric identifier cannot be empty.")
    parts = identifier.split(".")
    base = parts[0]
    if not base:
        raise ValueError(f"Invalid metric identifier '{identifier}'.")
    variant = ".".join(parts[1:]) if len(parts) > 1 else None
    return base, variant or None


def generate_measure_names(
    references: Sequence[str],
    *,
    visual_slug: str,
    name_strategy: NameStrategy = default_name_strategy,
    prefix: str = "",
) -> tuple[str, ...]:
    """Generate unique measure names using the supplied name strategy."""

    counts: dict[str, int] = {}
    results: list[str] = []
    for reference in references:
        base = name_strategy(reference, visual_slug)
        counter = counts.get(base, 0) + 1
        counts[base] = counter
        candidate = base if counter == 1 else f"{base}_{counter}"
        results.append(f"{prefix}{candidate}" if prefix else candidate)
    return tuple(results)


def iter_group_metrics(
    *,
    groups: Iterable[VisualGroupConfig] | None,
    metrics: Iterable[VisualMetricConfig] | None = None,
) -> Iterator[tuple[VisualGroupConfig | None, VisualMetricConfig]]:
    """Yield `(group, metric)` pairs from the provided groups and top-level metrics."""

    if groups:
        for group in groups:
            for entry in group.metrics:
                if isinstance(entry, VisualMetricConfig):
                    yield group, entry  # type: ignore[misc]
                elif isinstance(entry, VisualGroupConfig):
                    yield from iter_group_metrics(groups=[entry], metrics=None)
                else:
                    raise TypeError(
                        "Group metrics must be VisualMetricConfig or nested VisualGroupConfig instances."
                    )
    if metrics:
        for metric in metrics:
            yield None, metric


__all__ = [
    "generate_measure_names",
    "iter_group_metrics",
    "normalise_define_blocks",
    "split_metric_identifier",
]
