"""Rendering utilities for Plotly-based matrix visuals."""

from __future__ import annotations

from importlib import util as importlib_util

import plotly.graph_objects as go

from .data import MockResultSet
from .models import MatrixConfig


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


def matrix_figure(config: MatrixConfig, dataset: MockResultSet) -> go.Figure:
    """Render a Plotly table representing the matrix visual."""

    row_headers = [reference.placeholder for reference in dataset.row_fields]
    value_headers = [value.label or value.id for value in config.values]
    headers = row_headers + value_headers

    columns: list[list[object]] = []

    for header in row_headers:
        columns.append([row.get(header) for row in dataset.rows])

    format_lookup = {value.label or value.id: value.format for value in config.values}
    for header in value_headers:
        fmt = format_lookup.get(header)
        formatted = [_format_value(row.get(header), fmt) for row in dataset.rows]
        columns.append(formatted)

    figure = go.Figure(
        data=[
            go.Table(
                header=dict(values=headers, fill_color="#1f77b4", font=dict(color="white", size=12)),
                cells=dict(values=columns, fill_color="white"),
            )
        ]
    )

    if config.title:
        figure.update_layout(title=config.title)

    return figure


def matrix_html(config: MatrixConfig, dataset: MockResultSet, output_path: str) -> None:
    """Write the rendered figure to an HTML file."""

    figure = matrix_figure(config, dataset)
    figure.write_html(output_path, include_plotlyjs="cdn", full_html=True)


def matrix_png(config: MatrixConfig, dataset: MockResultSet, output_path: str, scale: float = 2.0) -> None:
    """Export the rendered figure to a static PNG file."""

    if importlib_util.find_spec("kaleido") is None:
        msg = "PNG export requires the 'kaleido' package. Install it to enable static image output."
        raise RuntimeError(msg)

    figure = matrix_figure(config, dataset)
    figure.write_image(output_path, format="png", scale=scale)


__all__ = ["matrix_figure", "matrix_html", "matrix_png"]
