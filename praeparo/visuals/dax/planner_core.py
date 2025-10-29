"""Core primitives for assembling visual DAX plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Sequence, Tuple

from praeparo.metrics import MetricMeasureDefinition


NameStrategy = Callable[[str, str], str]


@dataclass(frozen=True)
class MeasurePlan:
    """Resolved measure configuration used by visual planners."""

    reference: str
    measure_name: str
    expression: str
    display_name: str
    metric_filters: tuple[str, ...] = field(default_factory=tuple)
    section_filters: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VisualPlan:
    """Collection of measures and metadata for a visual output."""

    slug: str
    measures: tuple[MeasurePlan, ...] = field(default_factory=tuple)
    grain_columns: tuple[str, ...] = field(default_factory=tuple)
    define_blocks: tuple[str, ...] = field(default_factory=tuple)
    global_filters: tuple[str, ...] = field(default_factory=tuple)
    placeholders: tuple[str, ...] = field(default_factory=tuple)


def slugify(value: str) -> str:
    lowered = value.lower()
    cleaned: List[str] = []
    previous_underscore = False
    for char in lowered:
        if char.isalnum():
            cleaned.append(char)
            previous_underscore = False
        elif not previous_underscore:
            cleaned.append("_")
            previous_underscore = True
    text = "".join(cleaned).strip("_")
    return text or "measure"


def default_name_strategy(reference: str, visual_slug: str) -> str:
    reference_slug = reference.replace(".", "_")
    base_slug = f"{visual_slug}_{reference_slug}"
    return slugify(base_slug)


__all__ = ["MeasurePlan", "VisualPlan", "NameStrategy", "slugify", "default_name_strategy"]
