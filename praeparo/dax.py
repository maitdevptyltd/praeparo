"""Utilities for generating DAX query text from Praeparo models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .models import MatrixConfig
from .templating import FieldReference


@dataclass(frozen=True)
class DaxQueryPlan:
    """Represents the components of a generated DAX query."""

    statement: str
    rows: tuple[FieldReference, ...]
    values: tuple[str, ...]


SHOW_AS_PERCENT_COLUMN_TOTAL = "percent of column total"


def _escape_label(label: str) -> str:
    return label.replace('\"', '\"\"')


def _format_measure(identifier: str) -> str:
    trimmed = identifier.strip()
    if trimmed.startswith("[") and trimmed.endswith("]"):
        return trimmed
    return f"[{trimmed}]"


def _apply_show_as(show_as: str | None, measure: str, row_fields: Sequence[FieldReference]) -> str:
    if not show_as:
        return measure

    normalized = show_as.strip().lower()
    if normalized == SHOW_AS_PERCENT_COLUMN_TOTAL and row_fields:
        clauses = []
        primary = row_fields[-1]
        clauses.append(f"REMOVEFILTERS({primary.dax_reference})")
        for field in row_fields[:-1]:
            target = field.table or field.dax_reference
            clauses.append(f"REMOVEFILTERS({target})")
        arguments = ", ".join(clauses)
        return f"DIVIDE({measure}, CALCULATE({measure}, {arguments}))"

    return measure


def build_matrix_query(config: MatrixConfig, row_fields: Sequence[FieldReference]) -> DaxQueryPlan:
    """Construct a simple SUMMARIZECOLUMNS query for the given matrix configuration."""

    ordered_rows = tuple(row_fields)
    row_lines: list[str] = [reference.dax_reference for reference in ordered_rows]

    value_lines: list[str] = []
    measure_names: list[str] = []
    for value in config.values:
        alias = _escape_label(value.label or value.id)
        measure = _format_measure(value.id)
        expression = _apply_show_as(value.show_as, measure, ordered_rows)
        measure_names.append(measure)
        value_lines.append(f'\"{alias}\", {expression}')

    inner_parts: list[str] = []
    inner_parts.extend(row_lines)
    inner_parts.extend(value_lines)

    inner_body = ",\n    ".join(inner_parts) if inner_parts else ""
    statement = "EVALUATE\nSUMMARIZECOLUMNS(\n    " + inner_body + "\n)"

    return DaxQueryPlan(statement=statement, rows=ordered_rows, values=tuple(measure_names))


__all__ = ["DaxQueryPlan", "build_matrix_query"]
