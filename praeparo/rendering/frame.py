"""Rendering utilities for frame visuals."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..data import MatrixResultSet
from ..models import FrameConfig, MatrixConfig
from ._shared import estimate_table_height
from .matrix import table_trace


DEFAULT_CHILD_HEIGHT = 350
AUTO_FRAME_VERTICAL_SPACING = 0.015
FRAME_TITLE_MARGIN = 48
SUBPLOT_TITLE_MARGIN = 16


def frame_figure(
    frame: FrameConfig,
    children: Sequence[tuple[MatrixConfig, MatrixResultSet]],
) -> go.Figure:
    """Render a frame by stacking child matrix visuals vertically."""

    if not children:
        raise ValueError("Frame requires at least one child visual to render")

    row_count = len(children)
    specs = [[{"type": "table"}] for _ in children]
    titles = [child_config.title or f"Section {index}" for index, (child_config, _) in enumerate(children, start=1)]
    vertical_spacing = AUTO_FRAME_VERTICAL_SPACING if frame.auto_height else 0.08

    subplot_kwargs: dict[str, object] = {}
    if frame.show_titles:
        subplot_kwargs["subplot_titles"] = titles

    computed_heights: list[float] | None = None
    if frame.auto_height:
        computed_heights = []
        for child_config, dataset in children:
            if child_config.auto_height:
                height = estimate_table_height(len(dataset.rows))
            else:
                height = DEFAULT_CHILD_HEIGHT
            computed_heights.append(height)
        subplot_kwargs["row_heights"] = computed_heights

    figure = make_subplots(
        rows=row_count,
        cols=1,
        specs=specs,
        vertical_spacing=vertical_spacing,
        **subplot_kwargs,
    )

    for index, (child_config, dataset) in enumerate(children, start=1):
        table = table_trace(child_config, dataset)
        figure.add_trace(table, row=index, col=1)

    top_margin = FRAME_TITLE_MARGIN if frame.title else 0
    if frame.show_titles:
        top_margin += SUBPLOT_TITLE_MARGIN
    margin = dict(l=0, r=0, t=top_margin, b=0)

    layout_kwargs = dict(
        title=frame.title,
        margin=margin,
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
    )

    if frame.auto_height and computed_heights:
        content_height = sum(computed_heights)
        spacing_fraction = vertical_spacing if row_count > 1 else 0.0
        domain_fraction = 1 - spacing_fraction * (row_count - 1)
        if domain_fraction <= 0:
            domain_fraction = 1.0
        base_height = content_height / domain_fraction
        layout_kwargs["height"] = int(round(base_height + margin["t"] + margin["b"]))
    else:
        fallback_height = DEFAULT_CHILD_HEIGHT * row_count
        layout_kwargs["height"] = fallback_height + margin["t"] + margin["b"]

    layout_kwargs["autosize"] = False
    figure.update_layout(**layout_kwargs)

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
    write_kwargs: dict[str, object] = {"format": "png", "scale": scale}
    if figure.layout.height:
        write_kwargs["height"] = figure.layout.height
    figure.write_image(output_path, **write_kwargs)


__all__ = ["frame_figure", "frame_html", "frame_png"]

