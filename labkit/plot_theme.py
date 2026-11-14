"""Paper-style Plotly look shared by the lab programs. No Streamlit import.

Figures opt in with ``apply_paper_layout(fig)``: the global Plotly default is
left alone. Streamlit replaces a template's font and paper colour with its own
theme, so they are also written on the layout itself.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

INK = "#111111"
SURFACE = "#ffffff"
GRID = "#e3e3e3"
MISSING_CELL = "#e4e4e4"
FONT_FAMILY = "Arial, Helvetica, sans-serif"

# Okabe-Ito colourblind-safe categorical order.
CATEGORICAL = ("#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#000000")


def categorical_colors(names: list[str]) -> dict[str, str]:
    """A fixed colour per name, assigned in order; the palette repeats after seven names."""
    return {name: CATEGORICAL[index % len(CATEGORICAL)] for index, name in enumerate(names)}


def _axis(font_size: int, ticks: str) -> dict[str, Any]:
    return {
        "showline": True,
        "linecolor": INK,
        "linewidth": 1.2,
        "mirror": True,
        "ticks": ticks,
        "ticklen": 5,
        "tickwidth": 1.2,
        "tickcolor": INK,
        "tickfont": {"size": font_size - 1, "color": INK},
        "title": {"font": {"size": font_size + 1, "color": INK}, "standoff": 8},
        "showgrid": False,
        "gridcolor": GRID,
        "zeroline": False,
        "automargin": True,
    }


def paper_template(font_size: int = 14, ticks: str = "inside") -> go.layout.Template:
    """Boxed axes, no grid, white surface."""
    template = go.layout.Template()
    template.layout.update(
        font={"family": FONT_FAMILY, "size": font_size, "color": INK},
        title={"font": {"size": font_size + 2, "color": INK}, "x": 0.0, "xanchor": "left"},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        colorway=list(CATEGORICAL),
        xaxis=_axis(font_size, ticks),
        yaxis=_axis(font_size, ticks),
        legend={"font": {"size": font_size - 1, "color": INK}, "bgcolor": "rgba(255,255,255,0.85)"},
        hoverlabel={"font": {"family": FONT_FAMILY, "size": font_size - 1}, "bgcolor": SURFACE},
        margin={"l": 70, "r": 20, "t": 56, "b": 60},
    )
    return template


def apply_paper_layout(fig: go.Figure, font_size: int = 14, height: int | None = None, ticks: str = "inside") -> go.Figure:
    """Give ``fig`` the paper look, in place. Works for subplots too."""
    fig.update_layout(
        template=paper_template(font_size, ticks),
        font={"family": FONT_FAMILY, "size": font_size, "color": INK},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
    )
    if height is not None:
        fig.update_layout(height=height)
    axis = _axis(font_size, ticks)
    axis.pop("title")
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


def export_config(filename: str, image_format: str = "png", scale: int = 3) -> dict[str, Any]:
    """Plotly config: the modebar camera button saves a figure-quality image."""
    return {
        "displaylogo": False,
        "toImageButtonOptions": {"format": image_format, "filename": filename, "scale": scale},
        "modeBarButtonsToRemove": ["autoScale2d", "toggleSpikelines"],
    }
