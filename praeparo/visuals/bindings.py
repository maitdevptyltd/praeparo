"""Visual metric binding adapters.

Praeparo visuals can reference catalogue metrics in multiple ways. The explain
workflow needs a consistent way to:

1) List every metric-backed binding in a visual (in a stable, copy/paste order).
2) Resolve a specific binding instance via selector segments.

This module provides a small adapter registry keyed by visual type names so
downstream plugins can register their own binding extractors (for example,
MSANational's governance_matrix visual).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Dict, Protocol

from pydantic import BaseModel, ConfigDict, Field

from praeparo.models import CartesianChartConfig
from praeparo.models.scoped_calculate import ScopedCalculateFilters
from praeparo.models.visual_base import BaseVisualConfig


class VisualMetricBinding(BaseModel):
    """Uniform description of a single metric binding inside a visual."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: str = Field(..., description="Stable identifier for this binding within the visual.")
    selector_segments: tuple[str, ...] = Field(
        ...,
        description="Selector tokens that identify this binding (used after <path>#).",
    )
    label: str | None = Field(default=None, description="Optional display label for this binding.")
    metric_key: str | None = Field(default=None, description="Catalogue metric key powering this binding.")
    expression: str | None = Field(default=None, description="Inline expression powering this binding, when supported.")
    calculate: ScopedCalculateFilters = Field(
        default_factory=ScopedCalculateFilters,
        description="Scoped calculate predicates applied by the binding definition.",
    )
    ratio_to: str | bool | None = Field(default=None, description="Optional ratio semantics for this binding.")
    metadata: Mapping[str, object] = Field(
        default_factory=dict,
        description="Adapter-defined JSON-serialisable metadata used for evidence selection.",
    )

    group_id: str | None = Field(
        default=None,
        description="Optional adapter-defined grouping key (e.g. governance section id).",
    )
    source_path: Path | None = Field(default=None, description="Optional file path used for debugging/errors.")


class VisualMetricBindingsAdapter(Protocol):
    """Adapter interface for extracting and resolving metric bindings from visuals."""

    def list_bindings(self, visual: BaseVisualConfig, *, source_path: Path | None = None) -> Sequence[VisualMetricBinding]:
        """Return bindings in deterministic, copy/paste order."""
        ...

    def resolve_binding(
        self,
        visual: BaseVisualConfig,
        selector_segments: Sequence[str],
        *,
        source_path: Path | None = None,
    ) -> VisualMetricBinding:
        """Resolve a binding from selector segments (tokens after <path>#...)."""
        ...


_BINDINGS_ADAPTERS: Dict[str, VisualMetricBindingsAdapter] = {}


def register_visual_bindings_adapter(
    type_name: str,
    adapter: VisualMetricBindingsAdapter,
    *,
    overwrite: bool = False,
) -> None:
    """Register a bindings adapter for the supplied visual type name."""

    if not isinstance(type_name, str) or not type_name.strip():
        raise ValueError("type_name must be a non-empty string.")
    key = type_name.strip().lower()
    if not overwrite and key in _BINDINGS_ADAPTERS:
        raise ValueError(f"Bindings adapter already registered for visual type '{key}'.")
    _BINDINGS_ADAPTERS[key] = adapter


def get_visual_bindings_adapter(type_name: str) -> VisualMetricBindingsAdapter | None:
    if not isinstance(type_name, str) or not type_name.strip():
        raise ValueError("type_name must be a non-empty string.")
    return _BINDINGS_ADAPTERS.get(type_name.strip().lower())


def require_visual_bindings_adapter(type_name: str) -> VisualMetricBindingsAdapter:
    adapter = get_visual_bindings_adapter(type_name)
    if adapter is None:
        raise ValueError(f"Visual type '{type_name}' does not expose metric bindings.")
    return adapter


class _CartesianBindingsAdapter:
    """Expose each cartesian chart series as a metric binding."""

    def list_bindings(self, visual: BaseVisualConfig, *, source_path: Path | None = None) -> Sequence[VisualMetricBinding]:
        if not isinstance(visual, CartesianChartConfig):
            raise TypeError("Cartesian bindings adapter expects a CartesianChartConfig.")

        bindings: list[VisualMetricBinding] = []
        for series in visual.series:
            label = series.label or series.metric.label
            binding = VisualMetricBinding(
                binding_id=series.id,
                selector_segments=(series.id,),
                label=label,
                metric_key=series.metric.key,
                expression=series.metric.expression,
                calculate=ScopedCalculateFilters(define=list(series.metric.calculate), evaluate=[]),
                ratio_to=series.metric.ratio_to,
                group_id=None,
                source_path=source_path,
            )
            bindings.append(binding)
        return tuple(bindings)

    def resolve_binding(
        self,
        visual: BaseVisualConfig,
        selector_segments: Sequence[str],
        *,
        source_path: Path | None = None,
    ) -> VisualMetricBinding:
        if not selector_segments:
            raise ValueError("Cartesian bindings require a series id selector segment (e.g. <visual>#series_id).")

        series_id = str(selector_segments[0]).strip()
        if not series_id:
            raise ValueError("Series id selector cannot be empty.")

        bindings = self.list_bindings(visual, source_path=source_path)
        matches = [binding for binding in bindings if binding.selector_segments == (series_id,)]
        if matches:
            return matches[0]

        available = ", ".join(binding.binding_id for binding in bindings) if bindings else "<none>"
        raise ValueError(f"Unknown series id '{series_id}'. Available series ids: {available}")


# Built-in adapters
register_visual_bindings_adapter("column", _CartesianBindingsAdapter(), overwrite=True)
register_visual_bindings_adapter("bar", _CartesianBindingsAdapter(), overwrite=True)


__all__ = [
    "VisualMetricBinding",
    "VisualMetricBindingsAdapter",
    "get_visual_bindings_adapter",
    "register_visual_bindings_adapter",
    "require_visual_bindings_adapter",
]
