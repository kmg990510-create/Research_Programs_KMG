"""Paper-style Plotly template (prototype).

Unlike ``plot_theme.apply_plotly_theme`` this does not change the global
Plotly default: figures opt in with ``fig.update_layout(template=paper_template())``.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

INK = "#111111"
MUTED_INK = "#555555"
SURFACE = "#ffffff"
MISSING_CELL = "#e4e4e4"
FONT_FAMILY = "Arial, Helvetica, sans-serif"

# Okabe-Ito colorblind-safe categorical order.
CATEGORICAL = ("#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#000000")


def _axis(font_size: int) -> dict[str, Any]:
    return {
        "showline": True,
        "linecolor": INK,
        "linewidth": 1.2,
        "mirror": True,
        "ticks": "outside",
        "ticklen": 5,
        "tickwidth": 1.2,
        "tickcolor": INK,
        "tickfont": {"size": font_size - 1, "color": INK},
        "title": {"font": {"size": font_size + 1, "color": INK}, "standoff": 8},
        "showgrid": False,
        "zeroline": False,
        "automargin": True,
    }


def colorbar_style(font_size: int, title: str = "") -> dict[str, Any]:
    return {
        "title": {"text": title, "side": "right", "font": {"size": font_size + 1, "color": INK}},
        "thickness": 16,
        "len": 1.0,
        "outlinecolor": INK,
        "outlinewidth": 1.2,
        "ticks": "outside",
        "ticklen": 4,
        "tickwidth": 1.2,
        "tickcolor": INK,
        "tickfont": {"size": font_size - 1, "color": INK},
    }


def paper_template(font_size: int = 14) -> go.layout.Template:
    """Boxed axes, outside ticks, no grid, white surface."""
    template = go.layout.Template()
    template.layout.update(
        font={"family": FONT_FAMILY, "size": font_size, "color": INK},
        title={"font": {"size": font_size + 2, "color": INK}, "x": 0.0, "xanchor": "left"},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        colorway=list(CATEGORICAL),
        xaxis=_axis(font_size),
        yaxis=_axis(font_size),
        legend={
            "font": {"size": font_size - 1, "color": INK},
            "bgcolor": "rgba(255,255,255,0.85)",
            "bordercolor": INK,
            "borderwidth": 0,
        },
        hoverlabel={"font": {"family": FONT_FAMILY, "size": font_size - 1}, "bgcolor": SURFACE},
        margin={"l": 70, "r": 20, "t": 56, "b": 60},
    )
    return template


def export_config(filename: str, image_format: str = "png", scale: int = 3) -> dict[str, Any]:
    """Plotly config: the modebar camera button saves a figure-quality image."""
    return {
        "displaylogo": False,
        "toImageButtonOptions": {"format": image_format, "filename": filename, "scale": scale},
        "modeBarButtonsToRemove": ["autoScale2d", "toggleSpikelines"],
    }
