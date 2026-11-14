"""Adjustable paper-style look for scatter / error-bar figures. No Streamlit import."""

from __future__ import annotations

import re
from dataclasses import dataclass

import plotly.graph_objects as go

from labkit.plot_theme import FONT_FAMILY, INK, SURFACE, paper_template

LEGEND_POSITIONS = ("Inside top-right", "Inside top-left", "Right", "Below", "Hidden")
TICK_DIRECTIONS = ("inside", "outside")
GRID_COLOR = "#e3e3e3"

_SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
_LEGENDS = {
    "Right": {"orientation": "v", "x": 1.02, "xanchor": "left", "y": 1.0, "yanchor": "top"},
    "Inside top-left": {"orientation": "v", "x": 0.02, "xanchor": "left", "y": 0.98, "yanchor": "top"},
    "Inside top-right": {"orientation": "v", "x": 0.98, "xanchor": "right", "y": 0.98, "yanchor": "top"},
    "Below": {"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.18, "yanchor": "top"},
}


@dataclass
class ScatterStyle:
    font_size: int = 15
    height_px: int = 520
    point_size: int = 7
    point_opacity: float = 0.6
    point_outline: bool = False
    center_size: int = 12
    errorbar_width: float = 1.4
    show_grid: bool = False
    tick_direction: str = "inside"
    legend_position: str = "Inside top-right"
    pretty_labels: bool = True


def pretty_label(text: str | None) -> str:
    """``cm^-1`` -> ``cm⁻¹``, ``10^13`` -> ``10¹³``, ``eps`` -> ``ε``."""
    if not text:
        return ""
    out = re.sub(r"\^(-?\d+)", lambda m: m.group(1).translate(_SUPERSCRIPT), str(text))
    return re.sub(r"\beps\b", "ε", out)


def _is_center_trace(trace: go.Scatter) -> bool:
    return trace.error_x.array is not None or trace.error_y.array is not None


def apply_scatter_style(fig: go.Figure, style: ScatterStyle) -> go.Figure:
    """Restyle a figure in place: raw points, center markers with error bars, axes, legend."""
    for trace in fig.data:
        if trace.type != "scatter" or "markers" not in (trace.mode or ""):
            continue
        if _is_center_trace(trace):
            trace.marker.size = style.center_size
            trace.marker.line = {"width": 1.4, "color": INK}
            trace.error_x.thickness = style.errorbar_width
            trace.error_y.thickness = style.errorbar_width
            trace.error_x.width = style.center_size * 0.4
            trace.error_y.width = style.center_size * 0.4
        else:
            trace.marker.size = style.point_size
            trace.marker.opacity = style.point_opacity
            trace.marker.line = {"width": 0.8 if style.point_outline else 0, "color": SURFACE}

    axis = {
        "showline": True,
        "mirror": True,
        "linecolor": INK,
        "linewidth": 1.2,
        "ticks": style.tick_direction,
        "showgrid": style.show_grid,
        "gridcolor": GRID_COLOR,
        "zeroline": False,
    }
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)

    layout: dict = {
        "template": paper_template(style.font_size),
        "font": {"family": FONT_FAMILY, "size": style.font_size, "color": INK},
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
        "showlegend": style.legend_position != "Hidden",
    }
    if style.legend_position in _LEGENDS:
        layout["legend"] = {**_LEGENDS[style.legend_position], "title": {"text": ""}}
    if fig.layout.height is None:
        layout["height"] = style.height_px
    fig.update_layout(**layout)

    if style.pretty_labels:
        fig.update_layout(title_text=pretty_label(fig.layout.title.text))
        fig.update_xaxes(title_text=pretty_label(fig.layout.xaxis.title.text))
        fig.update_yaxes(title_text=pretty_label(fig.layout.yaxis.title.text))
    return fig
