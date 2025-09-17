"""Rendering utilities for frame visuals."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..data import MatrixResultSet
from ..models import FrameConfig, MatrixConfig
from .matrix import table_trace


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

    figure = make_subplots(
        rows=len(children),
        cols=1,
        specs=specs,
        vertical_spacing=0.08,
        **subplot_kwargs,
    )

    for index, (child_config, dataset) in enumerate(children, start=1):
        table = table_trace(child_config, dataset)
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


def frame_png(
    frame: FrameConfig,
    children: Sequence[tuple[MatrixConfig, MatrixResultSet]],
    output_path: str,
    scale: float = 2.0,
) -> None:
    """Export a frame visualization to a static PNG file."""

    from importlib import util as importlib_util  # local import to avoid cycles

    if importlib_util.find_spec("kaleido") is None:
        msg = "PNG export requires the 'kaleido' package. Install it to enable static image output."
        raise RuntimeError(msg)

    figure = frame_figure(frame, children)
    figure.write_image(output_path, format="png", scale=scale)


__all__ = ["frame_figure", "frame_html", "frame_png"]

