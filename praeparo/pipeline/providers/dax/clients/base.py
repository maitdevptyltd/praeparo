"""Base protocol for DAX execution clients."""

from __future__ import annotations

from typing import Awaitable, Protocol, Sequence

from praeparo.data import MatrixResultSet
from praeparo.dax import DaxQueryPlan
from praeparo.models import MatrixConfig
from praeparo.templating import FieldReference


class DaxExecutionClient(Protocol):
    """Executes DAX statements and returns raw row data."""

    def execute_matrix(
        self,
        config: MatrixConfig,
        row_fields: Sequence[FieldReference],
        plan: DaxQueryPlan,
        *,
        dataset_id: str,
        workspace_id: str | None = None,
        **kwargs: object,
    ) -> MatrixResultSet | Awaitable[MatrixResultSet]:
        """Execute the supplied DAX plan and return the resulting dataset."""
        ...


__all__ = ["DaxExecutionClient"]
