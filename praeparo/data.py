"""Data providers for Praeparo visuals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .dax import DaxQueryPlan
from .models import MatrixConfig
from .powerbi import PowerBIClient, PowerBISettings
from .templating import FieldReference


@dataclass
class MatrixResultSet:
    """Tabular data representing the outcome of a matrix query."""

    rows: list[dict[str, object]]
    row_fields: tuple[FieldReference, ...]


def _seed_value(base: int, multiplier: int) -> float:
    return round(base * multiplier / 100.0, 4)


def mock_matrix_data(config: MatrixConfig, row_fields: Iterable[FieldReference]) -> MatrixResultSet:
    """Generate deterministic sample data for a matrix visual."""

    ordered_fields = tuple(row_fields)
    generated_rows: list[dict[str, object]] = []

    for index in range(1, 4):
        row: dict[str, object] = {}
        for field in ordered_fields:
            seed = f"{field.column.replace('_', ' ').title()} {index}"
            row[field.placeholder] = seed
        for value_position, value in enumerate(config.values, start=1):
            multiplier = index * value_position
            if value.format and value.format.startswith("percent"):
                row[value.label or value.id] = _seed_value(multiplier, 5)
            elif value.format and value.format.startswith("duration"):
                row[value.label or value.id] = multiplier * 900
            else:
                row[value.label or value.id] = multiplier * 100
        generated_rows.append(row)

    return MatrixResultSet(rows=generated_rows, row_fields=ordered_fields)


async def powerbi_matrix_data(
    config: MatrixConfig,
    row_fields: Sequence[FieldReference],
    query_plan: DaxQueryPlan,
    dataset_id: str,
    *,
    group_id: str | None = None,
    settings: PowerBISettings | None = None,
) -> MatrixResultSet:
    """Execute the matrix DAX query against a live Power BI dataset."""

    ordered_fields = tuple(row_fields)
    settings = settings or PowerBISettings.from_env()

    async with PowerBIClient(settings) as client:
        rows = await client.execute_dax(dataset_id, query_plan.statement, group_id=group_id)

    materialized: list[dict[str, object]] = []
    for raw in rows:
        record: dict[str, object] = {}
        for field in ordered_fields:
            for candidate in (field.placeholder, field.dax_reference, field.column):
                if candidate in raw:
                    record[field.placeholder] = raw[candidate]
                    break
            else:
                record[field.placeholder] = None
        for value_config in config.values:
            alias = value_config.label or value_config.id
            record[alias] = raw.get(alias)
        materialized.append(record)

    return MatrixResultSet(rows=materialized, row_fields=ordered_fields)


__all__ = ["MatrixResultSet", "mock_matrix_data", "powerbi_matrix_data"]
