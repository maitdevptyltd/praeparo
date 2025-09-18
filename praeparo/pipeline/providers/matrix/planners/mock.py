"""Test-focused matrix query planners."""

from __future__ import annotations

from typing import Callable, Sequence, TYPE_CHECKING

from praeparo.data import MatrixResultSet
from praeparo.dax import DaxQueryPlan, build_matrix_query
from praeparo.models import MatrixConfig
from praeparo.templating import FieldReference, extract_field_references

from .base import MatrixPlannerResult, MatrixQueryPlanner

if TYPE_CHECKING:  # pragma: no cover
    from ....core import ExecutionContext

MatrixDataProvider = Callable[[MatrixConfig, Sequence[FieldReference], DaxQueryPlan], MatrixResultSet]


class FunctionMatrixPlanner(MatrixQueryPlanner):
    """Adapter that turns a data-provider function into a planner."""

    def __init__(self, provider: MatrixDataProvider) -> None:
        self._provider = provider

    def plan(self, config: MatrixConfig, *, context: "ExecutionContext") -> MatrixPlannerResult:
        row_fields = tuple(extract_field_references([row.template for row in config.rows]))
        plan = build_matrix_query(config, row_fields)
        dataset = self._provider(config, row_fields, plan)
        return MatrixPlannerResult(plan=plan, dataset=dataset)


__all__ = [
    "FunctionMatrixPlanner",
    "MatrixDataProvider",
]
