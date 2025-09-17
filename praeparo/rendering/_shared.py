"""Shared helpers for Praeparo rendering modules."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import plotly.graph_objects as go

from ..data import MatrixResultSet
from ..models import MatrixConfig
from ..templating import FieldReference, label_from_template, render_template


def _format_value(value: object, fmt: str | None) -> object:
    if value is None or fmt is None:
        return value
    if fmt.startswith("percent") and isinstance(value, (int, float)):
        precision = 2
        parts = fmt.split(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            precision = int(parts[1])
        return f"{value:.{precision}%}"
    if fmt.startswith("duration") and isinstance(value, (int, float)):
        total_seconds = int(value)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return value


def _row_headers(config: MatrixConfig, references: Iterable[FieldReference]) -> list[str]:
    headers: list[str] = []
    for row in config.rows:
        if row.hidden:
            continue
        if row.label:
            headers.append(row.label)
        else:
            headers.append(label_from_template(row.template, references))
    return headers


def _row_columns(config: MatrixConfig, dataset: MatrixResultSet) -> list[list[object]]:
    columns: list[list[object]] = []
    for row_config in config.rows:
        if row_config.hidden:
            continue
        column_values = [render_template(row_config.template, record) for record in dataset.rows]
        columns.append(column_values)
    return columns


def table_trace(config: MatrixConfig, dataset: MatrixResultSet) -> go.Table:
    row_headers = _row_headers(config, dataset.row_fields)
    value_headers = [value.label or value.id for value in config.values]
    headers = row_headers + value_headers

    columns: list[list[object]] = []
    columns.extend(_row_columns(config, dataset))

    format_lookup = {value.label or value.id: value.format for value in config.values}
    for header in value_headers:
        fmt = format_lookup.get(header)
        formatted = [_format_value(record.get(header), fmt) for record in dataset.rows]
        columns.append(formatted)

    return go.Table(
        header=dict(values=headers, fill_color="#1f77b4", font=dict(color="white", size=12), align="left"),
        cells=dict(values=columns, fill_color="white", align="left"),
    )


__all__ = ["table_trace"]
