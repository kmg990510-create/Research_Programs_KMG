"""Paper-style Plotly look shared by the lab programs. No Streamlit import.

One look for every figure:

- ``apply_paper_layout(fig)`` gives a figure the look; ``finish_figure(fig)`` is
  the last step before drawing (labels, exponents, grid, legend, colour bar) and
  applies the look itself when the figure does not have it yet.
- Figure code takes colours, line widths and marker sizes from the names below
  instead of writing numbers.

Streamlit replaces a template's font and paper colour with its own theme, so
figures are drawn with ``theme=None`` (see ``labkit.figure_size.show_figure``).
"""

from __future__ import annotations

import re
from typing import Any

import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

INK = "#111111"
MUTED_INK = "#555555"
SURFACE = "#ffffff"
GRID = "#e3e3e3"
MISSING_CELL = "#e4e4e4"
FONT_FAMILY = "Arial, Helvetica, sans-serif"
FONT_SIZE = 14
TEMPLATE_NAME = "labkit_paper"

# Okabe-Ito colourblind-safe categorical order.
CATEGORICAL = ("#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#000000")

# Colour by role.
DATA = INK  # the measured curve
AUX = "#8a8a8a"  # secondary curve, reference line, item that is not counted
FIT = "#0072B2"  # fitted line, tangent, window used for a fit
MARK = "#D55E00"  # extracted value drawn on the curve
STATUS_COLORS = {"valid": INK, "attention": "#E69F00", "invalid": MARK}  # in order of severity

# Colour scales: one for ordered values, one for values around a centre.
SEQUENTIAL = "Viridis"
DIVERGING = "RdBu"

# Line widths (px).
LINE_DATA = 1.6
LINE_AUX = 1.0
LINE_FIT = 2.4

# Marker sizes (px).
MARKER_ON_LINE = 4  # points of a curve that is drawn as a line
MARKER_RAW = 7  # single measured points
MARKER_CENTER = 11  # representative value (mean, median, extracted value)
MARKER_MAP = 14  # one measurement point of a map, drawn as a marker

# Marker outlines and error bars (px).
OUTLINE = 1.5  # outline of a marker that carries a value
OUTLINE_THIN = 0.8  # outline that only separates neighbouring points
ERRORBAR_WIDTH = 1.4  # thickness of an error bar
ERRORBAR_CAP = 4  # half-length of the cap of an error bar

# Legend places. Inside: line and point plots. Right: plots whose area is filled
# (maps, bars, histograms, boxes) or that have many entries.
LEGEND_INSIDE = {"orientation": "v", "x": 0.02, "xanchor": "left", "y": 0.98, "yanchor": "top"}
LEGEND_RIGHT = {"orientation": "v", "x": 1.02, "xanchor": "left", "y": 1.0, "yanchor": "top"}

_SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
_AXIS_KEY = re.compile(r"^[xy]axis\d*$")
_COLORAXIS_KEY = re.compile(r"^coloraxis\d*$")


def categorical_colors(names: list[str]) -> dict[str, str]:
    """A fixed colour per name, assigned in order; the palette repeats after seven names."""
    return {name: CATEGORICAL[index % len(CATEGORICAL)] for index, name in enumerate(names)}


def pretty_label(text: str | None) -> str:
    """``cm^-1`` -> ``cm⁻¹``, ``10^13`` -> ``10¹³``, ``eps`` -> ``ε``."""
    if not text:
        return ""
    out = re.sub(r"\^(-?\d+)", lambda m: m.group(1).translate(_SUPERSCRIPT), str(text))
    return re.sub(r"\beps\b", "ε", out)


def axis_label(name: str, unit: str = "") -> str:
    """``name (unit)``; the unit is left out when there is none."""
    unit = pretty_label(unit.strip())
    return f"{pretty_label(name)} ({unit})" if unit else pretty_label(name)


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


def colorbar_style(font_size: int, title: str = "") -> dict[str, Any]:
    """Colour bar that matches the boxed axes."""
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
        "exponentformat": "power",
    }


def paper_template(font_size: int = FONT_SIZE, ticks: str = "inside") -> go.layout.Template:
    """Boxed axes, no grid, white surface."""
    template = go.layout.Template()
    template.layout.update(
        meta=TEMPLATE_NAME,  # how finish_figure recognises a figure that already has the look
        font={"family": FONT_FAMILY, "size": font_size, "color": INK},
        title={"font": {"size": font_size + 2, "color": INK}, "x": 0.0, "xanchor": "left"},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        colorway=list(CATEGORICAL),
        colorscale={"sequential": SEQUENTIAL, "diverging": DIVERGING},
        xaxis=_axis(font_size, ticks),
        yaxis=_axis(font_size, ticks),
        legend={"font": {"size": font_size - 1, "color": INK}, "bgcolor": "rgba(255,255,255,0.85)"},
        hoverlabel={"font": {"family": FONT_FAMILY, "size": font_size - 1}, "bgcolor": SURFACE},
        margin={"l": 70, "r": 20, "t": 56, "b": 60},
    )
    return template


def set_default_theme() -> None:
    """Make the paper look the Plotly default of this process.

    Plotly Express writes colours into a figure when it is created, so the
    default has to be set before the figure is built.
    """
    if pio.templates.default == TEMPLATE_NAME:
        return
    pio.templates[TEMPLATE_NAME] = paper_template()
    pio.templates.default = TEMPLATE_NAME
    px.defaults.template = TEMPLATE_NAME
    px.defaults.color_discrete_sequence = list(CATEGORICAL)
    px.defaults.color_continuous_scale = SEQUENTIAL


def apply_paper_layout(fig: go.Figure, font_size: int = FONT_SIZE, height: int | None = None, ticks: str = "inside") -> go.Figure:
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


def has_paper_look(fig: go.Figure) -> bool:
    return fig.layout.template.layout.meta == TEMPLATE_NAME


def _font_size(fig: go.Figure) -> int:
    return int(fig.layout.font.size or fig.layout.template.layout.font.size or FONT_SIZE)


def _only_points_and_lines(fig: go.Figure) -> bool:
    return all(trace.type in ("scatter", "scattergl") for trace in fig.data)


def finish_figure(fig: go.Figure, grid: bool = False) -> go.Figure:
    """Last step before a figure is drawn, in place. The same for every figure.

    - the paper look, when the figure does not have it yet
    - superscripts in the title, axis titles, legend title and colour bar titles
    - powers of ten written as 10⁻⁶
    - grid lines on or off
    - legend place, unless the figure chose one
    - one colour bar style
    """
    # Streamlit puts its own font over a template font, so the look also has to be on the layout itself.
    if not has_paper_look(fig):
        apply_paper_layout(fig)
    elif fig.layout.font.family != FONT_FAMILY:
        apply_paper_layout(fig, font_size=_font_size(fig))
    font_size = _font_size(fig)
    layout = fig.layout

    if layout.title.text:
        layout.title.text = pretty_label(layout.title.text)
    if layout.legend.title.text:
        layout.legend.title.text = pretty_label(layout.legend.title.text)
    for key in layout:
        if _AXIS_KEY.match(key) and layout[key].title.text:
            layout[key].title.text = pretty_label(layout[key].title.text)

    fig.update_xaxes(exponentformat="power", showgrid=grid, gridcolor=GRID)
    fig.update_yaxes(exponentformat="power", showgrid=grid, gridcolor=GRID)

    if layout.legend.x is None and layout.legend.y is None:
        fig.update_layout(legend=LEGEND_INSIDE if _only_points_and_lines(fig) else LEGEND_RIGHT)

    for key in layout:
        if _COLORAXIS_KEY.match(key):
            bar = layout[key].colorbar
            bar.update(colorbar_style(font_size, pretty_label(bar.title.text)))
    for trace in fig.data:
        if trace.type in ("heatmap", "contour") and trace.coloraxis is None and trace.showscale is not False:
            trace.colorbar.update(colorbar_style(font_size, pretty_label(trace.colorbar.title.text)))
    return fig


def export_config(filename: str, image_format: str = "png", scale: int = 3) -> dict[str, Any]:
    """Plotly config: the modebar camera button saves a figure-quality image."""
    filename = re.sub(r'[\\/:*?"<>|\s]+', "_", filename).strip("_") or "figure"  # a name every file system accepts
    return {
        "displaylogo": False,
        "toImageButtonOptions": {"format": image_format, "filename": filename, "scale": scale},
        "modeBarButtonsToRemove": ["autoScale2d", "toggleSpikelines"],
    }
