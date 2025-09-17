"""Rendering utilities for Plotly-based matrix visuals."""

from __future__ import annotations

from importlib import util as importlib_util
from pathlib import Path
from typing import Iterable, Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .data import MatrixResultSet
from .models import FrameConfig, MatrixConfig
from .templating import FieldReference, label_from_template, render_template


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


def _table_trace(config: MatrixConfig, dataset: MatrixResultSet) -> go.Table:
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


def matrix_figure(config: MatrixConfig, dataset: MatrixResultSet) -> go.Figure:
    """Render a Plotly table representing the matrix visual."""

    table = _table_trace(config, dataset)
    figure = go.Figure(data=[table])

    figure.update_layout(
        title=config.title,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )

    return figure


def frame_figure(
    frame: FrameConfig,
    children: Sequence[tuple[MatrixConfig, MatrixResultSet]],
) -> go.Figure:
    """Render a frame by stacking child matrix visuals vertically."""

    if not children:
        raise ValueError("Frame requires at least one child visual to render")

    specs = [[{"type": "table"}] for _ in children]
    titles = [child_config.title or f"Section {index}" for index, (child_config, _) in enumerate(children, start=1)]
    subplot_kwargs: dict[str, object] = {}
    if frame.show_titles:
        subplot_kwargs["subplot_titles"] = titles
    figure = make_subplots(rows=len(children), cols=1, specs=specs, vertical_spacing=0.08, **subplot_kwargs)

    for index, (child_config, dataset) in enumerate(children, start=1):
        table = _table_trace(child_config, dataset)
        figure.add_trace(table, row=index, col=1)

    figure.update_layout(
        title=frame.title,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="white",
        plot_bgcolor="white",
        height=350 * len(children),
        showlegend=False,
    )

    return figure


def matrix_html(config: MatrixConfig, dataset: MatrixResultSet, output_path: str) -> None:
    """Write the rendered figure to an HTML file."""

    figure = matrix_figure(config, dataset)
    div_id = Path(output_path).stem.replace(" ", "_") or "matrix"
    fragment = figure.to_html(full_html=False, include_plotlyjs="cdn", div_id=div_id)
    html = (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\"><head><meta charset=\"utf-8\" />"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
        "<style>body{margin:0;padding:0;}</style></head><body>"
        f"{fragment}"
        "</body></html>"
    )
    Path(output_path).write_text(html, encoding="utf-8")


def frame_html(
    frame: FrameConfig,
    children: Sequence[tuple[MatrixConfig, MatrixResultSet]],
    output_path: str,
) -> None:
    """Write a composed frame to an HTML file."""

    figure = frame_figure(frame, children)
    div_id = Path(output_path).stem.replace(" ", "_") or "frame"
    fragment = figure.to_html(full_html=False, include_plotlyjs="cdn", div_id=div_id)
    html = (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\"><head><meta charset=\"utf-8\" />"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
        "<style>body{margin:0;padding:0;}</style></head><body>"
        f"{fragment}"
        "</body></html>"
    )
    Path(output_path).write_text(html, encoding="utf-8")


def matrix_png(config: MatrixConfig, dataset: MatrixResultSet, output_path: str, scale: float = 2.0) -> None:
    """Export the rendered figure to a static PNG file."""

    if importlib_util.find_spec("kaleido") is None:
        msg = "PNG export requires the 'kaleido' package. Install it to enable static image output."
        raise RuntimeError(msg)

    figure = matrix_figure(config, dataset)
    figure.write_image(output_path, format="png", scale=scale)


def frame_png(
    frame: FrameConfig,
    children: Sequence[tuple[MatrixConfig, MatrixResultSet]],
    output_path: str,
    scale: float = 2.0,
) -> None:
    """Export a frame visualization to a static PNG file."""

    if importlib_util.find_spec("kaleido") is None:
        msg = "PNG export requires the 'kaleido' package. Install it to enable static image output."
        raise RuntimeError(msg)

    figure = frame_figure(frame, children)
    figure.write_image(output_path, format="png", scale=scale)


__all__ = [
    "frame_figure",
    "frame_html",
    "frame_png",
    "matrix_figure",
    "matrix_html",
    "matrix_png",
]


