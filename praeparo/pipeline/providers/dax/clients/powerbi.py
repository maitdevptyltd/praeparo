"""Power BI implementation of the DAX execution client."""

from __future__ import annotations

from typing import Awaitable, Sequence, cast

from praeparo.data import MatrixResultSet
from praeparo.dax import DaxQueryPlan
from praeparo.models import MatrixConfig
from praeparo.powerbi import PowerBISettings
from praeparo.templating import FieldReference

from .base import DaxExecutionClient
from praeparo.data import powerbi_matrix_data


class PowerBIDaxClient(DaxExecutionClient):
    """Executes DAX queries against the Power BI service."""

    def __init__(self, settings: PowerBISettings | None = None) -> None:
        self._settings = settings

    @classmethod
    def from_env(cls) -> "PowerBIDaxClient":
        return cls(settings=PowerBISettings.from_env())

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
        raw_settings = kwargs.pop("settings", None) if "settings" in kwargs else None
        settings = cast(PowerBISettings | None, raw_settings)
        effective_settings = settings or self._settings or PowerBISettings.from_env()
        return powerbi_matrix_data(
            config,
            row_fields,
            plan,
            dataset_id=dataset_id,
            group_id=workspace_id,
            settings=effective_settings,
        )


__all__ = ["PowerBIDaxClient"]
