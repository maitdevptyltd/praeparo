"""Utilities for generating DAX query text from Praeparo models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from .models import MatrixConfig
from .templating import FieldReference

if TYPE_CHECKING:
    from .models import MatrixFilterConfig


@dataclass(frozen=True)
class DaxQueryPlan:
    """Represents the components of a generated DAX query."""

    statement: str
    rows: tuple[FieldReference, ...]
    values: tuple[str, ...]
    define: str | None = None


SHOW_AS_PERCENT_COLUMN_TOTAL = "percent of column total"


def _escape_label(label: str) -> str:
    return label.replace('"', '""')


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


def _split_field_reference(expression: str) -> tuple[str, str]:
    table, column = expression.split(".", 1)
    table = table.strip()
    column = column.strip()
    return table, column


def _format_column_reference(expression: str) -> tuple[str, str, str]:
    table, column = _split_field_reference(expression)
    reference = f"{table}[{column}]"
    return table, column, reference


def _escape_filter_value(value: str) -> str:
    return value.replace('"', '""')


def _format_filter_clause(filter_config: "MatrixFilterConfig") -> str:
    if filter_config.expression:
        return filter_config.expression
    if not filter_config.field or not filter_config.include:
        msg = "Filter configuration must define either an expression or field/include pair."
        raise ValueError(msg)
    _table, _column, column_reference = _format_column_reference(filter_config.field)
    values = ", ".join(f'"{_escape_filter_value(item)}"' for item in filter_config.include)
    return f"{column_reference} IN {{ {values} }}"


def _summarize_columns(row_lines: Sequence[str], value_lines: Sequence[str]) -> str:
    inner_parts: list[str] = []
    inner_parts.extend(row_lines)
    inner_parts.extend(value_lines)

    inner_body = ",\n    ".join(inner_parts) if inner_parts else ""
    return "SUMMARIZECOLUMNS(\n    " + inner_body + "\n)"


def _indent_block(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    return "    " + "\n    ".join(lines)


def _wrap_with_filters(body: str, filter_lines: Sequence[str]) -> str:
    if not filter_lines:
        return body

    indented_body = _indent_block(body)
    filter_block = ",\n".join("    " + line for line in filter_lines)
    return "CALCULATETABLE(\n" + indented_body + ",\n" + filter_block + "\n)"


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
        value_lines.append(f'"{alias}", {expression}')

    filter_lines = [_format_filter_clause(filter_config) for filter_config in config.filters]

    summarize = _summarize_columns(row_lines, value_lines)
    body = summarize if not filter_lines else _wrap_with_filters(summarize, filter_lines)

    define_block: str | None = None
    if config.define:
        candidate = config.define.strip()
        if candidate:
            define_block = candidate

    parts: list[str] = []
    if define_block:
        parts.append("DEFINE\n" + define_block)
    parts.append("EVALUATE\n" + body)
    statement = "\n\n".join(parts)

    return DaxQueryPlan(
        statement=statement,
        rows=ordered_rows,
        values=tuple(measure_names),
        define=define_block,
    )


__all__ = ["DaxQueryPlan", "build_matrix_query"]

