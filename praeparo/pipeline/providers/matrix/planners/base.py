"""Base interfaces for matrix query planners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING, runtime_checkable

from praeparo.data import MatrixResultSet
from praeparo.dax import DaxQueryPlan
from praeparo.models import MatrixConfig

if TYPE_CHECKING:  # pragma: no cover
    from ....core import ExecutionContext


@dataclass(frozen=True)
class MatrixPlannerResult:
    """Represents the outcome of executing a matrix query planner."""

    plan: DaxQueryPlan
    dataset: MatrixResultSet


@runtime_checkable
class MatrixQueryPlanner(Protocol):
    """Planner capable of producing matrix datasets from configuration."""

    def plan(self, config: MatrixConfig, *, context: "ExecutionContext") -> MatrixPlannerResult:
        """Build the DAX plan and execute it to produce a dataset."""
        ...


__all__ = [
    "MatrixPlannerResult",
    "MatrixQueryPlanner",
]
