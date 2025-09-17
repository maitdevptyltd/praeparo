"""Mocked data providers for proof-of-concept pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import MatrixConfig
from .templating import FieldReference


@dataclass
class MockResultSet:
    """Synthetic dataset representing the outcome of a faux DAX execution."""

    rows: list[dict[str, object]]
    row_fields: tuple[FieldReference, ...]


def _seed_value(base: int, multiplier: int) -> float:
    return round(base * multiplier / 100.0, 4)


def mock_matrix_data(config: MatrixConfig, row_fields: Iterable[FieldReference]) -> MockResultSet:
    """Generate deterministic sample data for a matrix visual."""

    ordered_fields = tuple(row_fields)
    generated_rows: list[dict[str, object]] = []

    for index in range(1, 4):
        row: dict[str, object] = {}
        for position, field in enumerate(ordered_fields, start=1):
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

    return MockResultSet(rows=generated_rows, row_fields=ordered_fields)


__all__ = ["MockResultSet", "mock_matrix_data"]
