"""Rendering utilities for matrix visuals."""

from __future__ import annotations

from importlib import util as importlib_util
from pathlib import Path

import plotly.graph_objects as go

from ..data import MatrixResultSet
from ..models import MatrixConfig
from ._shared import estimate_table_height, table_trace


MATRIX_TITLE_MARGIN = 48


def matrix_figure(config: MatrixConfig, dataset: MatrixResultSet) -> go.Figure:
    """Render a Plotly table representing the matrix visual."""

    table = table_trace(config, dataset)
    figure = go.Figure(data=[table])

    title_margin = MATRIX_TITLE_MARGIN if config.title else 0
    margin = dict(l=0, r=0, t=title_margin, b=0)

    layout_kwargs = dict(
        title=config.title,
        margin=margin,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )

    if config.auto_height:
        content_height = estimate_table_height(len(dataset.rows))
        total_height = content_height + margin["t"] + margin["b"]
        layout_kwargs["height"] = total_height
        layout_kwargs["autosize"] = False

    figure.update_layout(**layout_kwargs)

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


def matrix_png(config: MatrixConfig, dataset: MatrixResultSet, output_path: str, scale: float = 2.0) -> None:
    """Export the rendered figure to a static PNG file."""

    if importlib_util.find_spec("kaleido") is None:
        msg = "PNG export requires the 'kaleido' package. Install it to enable static image output."
        raise RuntimeError(msg)

    figure = matrix_figure(config, dataset)
    write_kwargs: dict[str, object] = {"format": "png", "scale": scale}
    if figure.layout.height:
        write_kwargs["height"] = figure.layout.height
    figure.write_image(output_path, **write_kwargs)


__all__ = ["matrix_figure", "matrix_html", "matrix_png", "table_trace"]
