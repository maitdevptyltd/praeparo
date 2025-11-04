"""Base interfaces for cartesian chart planners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, TYPE_CHECKING, runtime_checkable

from praeparo.data import ChartResultSet
from praeparo.dax import DaxQueryPlan
from praeparo.models import CartesianChartConfig

if TYPE_CHECKING:  # pragma: no cover
    from ....core import ExecutionContext


@dataclass(frozen=True)
class ChartPlannerResult:
    """Represents the outcome of executing a cartesian chart planner."""

    plan: DaxQueryPlan
    dataset: ChartResultSet
    measure_map: Mapping[str, str]
    placeholders: tuple[str, ...] = ()


@runtime_checkable
class ChartQueryPlanner(Protocol):
    """Planner capable of producing chart datasets from configuration."""

    def plan(self, config: CartesianChartConfig, *, context: "ExecutionContext") -> ChartPlannerResult:
        """Build the DAX plan and execute it to produce a dataset."""
        ...


__all__ = ["ChartPlannerResult", "ChartQueryPlanner"]
