"""Rendering utilities for cartesian (column/bar) visuals."""

from __future__ import annotations

from importlib import util as importlib_util
from pathlib import Path
from typing import Iterable, cast

import plotly.graph_objects as go
from plotly.graph_objs.layout import Legend, Margin

from praeparo.data import ChartResultSet
from praeparo.models import (
    CartesianChartConfig,
    SeriesStackingMode,
)


def _apply_dimensions(figure: go.Figure, width: int | None, height: int | None) -> None:
    updates: dict[str, object] = {}
    if width is not None:
        updates["width"] = int(width)
    if height is not None:
        updates["height"] = int(height)
    if updates:
        updates.setdefault("autosize", False)
        figure.update_layout(**updates)


def cartesian_figure(config: CartesianChartConfig, dataset: ChartResultSet) -> go.Figure:
    """Render a Plotly figure representing the cartesian chart visual."""

    categories = [category.label for category in dataset.categories]
    orientation = "h" if config.type == "bar" else "v"
    figure = go.Figure()

    stack_modes = {
        series.id: (series.stacking.mode if series.stacking else SeriesStackingMode.NONE)
        for series in config.series
        if series.type == "column"
    }
    active_stack_modes = {mode for mode in stack_modes.values() if mode is not SeriesStackingMode.NONE}
    is_stacked = bool(active_stack_modes)

    for series_config in config.series:
        data = _series_values(dataset, series_config.id)
        axis = "y2" if series_config.axis == "secondary" and orientation == "v" else None
        if orientation == "h" and series_config.axis == "secondary":
            axis = "x2"

        if series_config.type == "line":
            trace = go.Scatter(
                x=categories if orientation == "v" else data,
                y=data if orientation == "v" else categories,
                mode="lines+markers" if series_config.marker and series_config.marker.show else "lines",
                name=series_config.label or series_config.metric.label or series_config.metric.key,
            )
        else:
            trace = go.Bar(
                x=categories if orientation == "v" else data,
                y=data if orientation == "v" else categories,
                name=series_config.label or series_config.metric.label or series_config.metric.key,
                orientation=orientation,
            )
            if series_config.stacking and series_config.stacking.key:
                trace.offsetgroup = series_config.stacking.key
                trace.legendgroup = series_config.stacking.key

        if axis:
            if orientation == "v":
                trace.yaxis = axis
            else:
                trace.xaxis = axis

        if series_config.data_labels:
            label_position = _resolve_label_position(series_config.data_labels.position, orientation)
            if series_config.type == "line" and label_position in {"outside", "inside"}:
                label_position = "top center" if label_position == "outside" else "middle center"
            trace.text = data
            trace.textposition = label_position
            if series_config.data_labels.format:
                trace.texttemplate = _format_template(series_config.data_labels.format)

        figure.add_trace(trace)

    _configure_layout(figure, config, categories, is_stacked, orientation)

    return figure


def cartesian_html(
    config: CartesianChartConfig,
    dataset: ChartResultSet,
    output_path: str,
    *,
    width: int | None = None,
    height: int | None = None,
) -> None:
    """Write the rendered cartesian chart to an HTML file."""

    figure = cartesian_figure(config, dataset)
    _apply_dimensions(figure, width, height)
    div_id = Path(output_path).stem.replace(" ", "_") or "chart"
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


def cartesian_png(
    config: CartesianChartConfig,
    dataset: ChartResultSet,
    output_path: str,
    *,
    scale: float = 2.0,
    width: int | None = None,
    height: int | None = None,
) -> None:
    """Export the rendered cartesian chart to a static PNG."""

    if importlib_util.find_spec("kaleido") is None:
        msg = "PNG export requires the 'kaleido' package. Install it to enable static image output."
        raise RuntimeError(msg)

    figure = cartesian_figure(config, dataset)
    _apply_dimensions(figure, width, height)
    write_kwargs: dict[str, object] = {"format": "png", "scale": scale}
    if width is not None:
        write_kwargs["width"] = int(width)
    if height is not None:
        write_kwargs["height"] = int(height)
    figure.write_image(output_path, **write_kwargs)


def _series_values(dataset: ChartResultSet, series_id: str) -> list[object]:
    for series in dataset.series:
        if series.id == series_id:
            return series.values
    return [0 for _ in dataset.categories]


def _resolve_label_position(position: str | None, orientation: str) -> str:
    if not position:
        return "auto"
    mapping = {
        "above": "outside",
        "outside_end": "outside",
        "inside": "inside",
        "center": "inside",
    }
    resolved = mapping.get(position.lower(), "auto")
    if orientation == "h" and resolved == "outside":
        return "outside"
    return resolved


def _precision_from_token(token: str, default: int = 0) -> int:
    if ":" not in token:
        return default
    candidate = token.split(":", 1)[1].strip()
    if not candidate:
        return default
    try:
        return max(0, int(float(candidate)))
    except ValueError:
        return default


def _format_template(format_token: str | None) -> str:
    token = (format_token or "").strip().lower()
    if not token:
        return "%{text}"
    if token.startswith("percent"):
        precision = _precision_from_token(token, default=0)
        return f"%{{text:.{precision}%}}"
    if token.startswith("number"):
        precision = _precision_from_token(token, default=0)
        return f"%{{text:.{precision}f}}"
    return "%{text}"


def _derive_tickformat(format_token: str | None) -> str | None:
    if not format_token:
        return None

    token = format_token.strip().lower()
    if not token:
        return None

    def _precision(spec: str) -> int:
        try:
            value = float(spec)
        except (TypeError, ValueError):
            return 0
        return max(0, int(value))

    if token.startswith("percent"):
        precision = "0"
        if ":" in token:
            precision = token.split(":", 1)[1]
        return f".{_precision(precision)}%"

    if token.startswith("number"):
        precision = "0"
        if ":" in token:
            precision = token.split(":", 1)[1]
        return f",.{_precision(precision)}f"

    return None


def _configure_layout(
    figure: go.Figure,
    config: CartesianChartConfig,
    categories: Iterable[str],
    is_stacked: bool,
    orientation: str,
) -> None:
    legend_position = (config.layout.legend.position if config.layout and config.layout.legend else "top").lower()
    legend_obj: Legend | None = None
    if legend_position == "none":
        legend_obj = Legend(orientation="h", y=-0.3, x=0.5, xanchor="center", visible=False)
    elif legend_position in {"top", "bottom"}:
        legend_obj = Legend(orientation="h",
            y=1.2 if legend_position == "top" else -0.2,              # was 1.1 / -0.2
            yanchor="top" if legend_position == "top" else "bottom",
            x=0.5, xanchor="center",)
    elif legend_position in {"left", "right"}:
        legend_obj = Legend(
            orientation="v",
            x=0.0 if legend_position == "left" else 1.0,
            xanchor="left" if legend_position == "left" else "right",
            y=1.0,
            yanchor="top",
        )

    barmode = "stack" if is_stacked and orientation == "v" else "group"
    if orientation == "h" and is_stacked:
        barmode = "stack"

    figure.update_layout(
        # Remove the default outer padding, so exports are trimmed exactly the visual's bounds
        margin_b=0,
        margin_l=0,
        margin_r=0,
        margin_t=0,
        
        title=config.title,
        # Let the title adjust the margin, otherwise the 0 margins above will cut off the title
        title_automargin=True,
        
        paper_bgcolor="white",
        plot_bgcolor="white",
        barmode=barmode if any(series.type == "column" for series in config.series) else None,
        xaxis=_axis_options(config, axis="primary_x", orientation=orientation),
        yaxis=_axis_options(config, axis="primary_y", orientation=orientation),
        legend=legend_obj,
    )

    if any(series.axis == "secondary" for series in config.series):
        if orientation == "v":
            figure.update_layout(yaxis2=_secondary_axis_options(config, orientation))
        else:
            figure.update_layout(xaxis2=_secondary_axis_options(config, orientation))


def _axis_options(config: CartesianChartConfig, *, axis: str, orientation: str) -> dict[str, object]:
    primary = config.value_axes.primary
    options: dict[str, object] = {}
    if axis == "primary_x":
        if orientation == "v":
            options["title"] = config.category.label or ""
        else:
            options["title"] = primary.label or ""
    else:
        if orientation == "v":
            options["title"] = primary.label or ""
        else:
            options["title"] = config.category.label or ""

    is_value_axis = (axis == "primary_y" and orientation == "v") or (axis == "primary_x" and orientation == "h")
    if is_value_axis:
        range_values: list[float | None] | None = None
        if primary.minimum is not None or primary.maximum is not None:
            range_values = cast(list[float | None], [None, None])
            if primary.minimum is not None:
                range_values[0] = primary.minimum
            if primary.maximum is not None:
                range_values[1] = primary.maximum
            options["range"] = range_values

        tick_format = primary.tick_format or _derive_tickformat(primary.format)
        if tick_format:
            options["tickformat"] = tick_format
    return options


def _secondary_axis_options(config: CartesianChartConfig, orientation: str) -> dict[str, object]:
    secondary = config.value_axes.secondary
    if not secondary:
        return {}
    options: dict[str, object] = {
        "title": secondary.label or "",
        "overlaying": "y" if orientation == "v" else "x",
        "side": "right" if orientation == "v" else "top",
        "showgrid": False,
    }
    if secondary.minimum is not None or secondary.maximum is not None:
        range_values = cast(list[float | None], [None, None])
        if secondary.minimum is not None:
            range_values[0] = secondary.minimum
        if secondary.maximum is not None:
            range_values[1] = secondary.maximum
        options["range"] = range_values

    tick_format = secondary.tick_format or _derive_tickformat(secondary.format)
    if tick_format:
        options["tickformat"] = tick_format
    return options


__all__ = ["cartesian_figure", "cartesian_html", "cartesian_png"]
