"""Planner provider abstractions for the visual pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Protocol, TYPE_CHECKING

from praeparo.models import BaseVisualConfig

if TYPE_CHECKING:  # pragma: no cover
    from ..core import ExecutionContext
    from .matrix.planners.base import MatrixQueryPlanner


class QueryPlannerProvider(Protocol):
    """Resolves a planner capable of handling the supplied visual."""

    def resolve(self, visual: BaseVisualConfig, context: "ExecutionContext") -> Any:
        """Return a planner object that can execute the supplied visual."""


@dataclass
class DefaultQueryPlannerProvider(QueryPlannerProvider):
    """Simple mapping-based provider for query planners."""

    planners: Mapping[str, Any]

    def __post_init__(self) -> None:
        self._planners: Dict[str, Any] = dict(self.planners)

    def resolve(self, visual: BaseVisualConfig, context: "ExecutionContext") -> Any:
        planner = self._planners.get(visual.type)
        if planner is None:
            message = f"No query planner registered for visual type '{visual.type}'."
            raise ValueError(message)
        return planner


def build_default_query_planner_provider() -> QueryPlannerProvider:
    """Construct the default planner provider used by the CLI and tests."""

    from .dax.clients.powerbi import PowerBIDaxClient
    from .matrix.planners.dax import DaxBackedMatrixPlanner

    matrix_planner = DaxBackedMatrixPlanner(dax_client=PowerBIDaxClient.from_env())
    return DefaultQueryPlannerProvider(planners={"matrix": matrix_planner})


__all__ = [
    "DefaultQueryPlannerProvider",
    "QueryPlannerProvider",
    "build_default_query_planner_provider",
]
