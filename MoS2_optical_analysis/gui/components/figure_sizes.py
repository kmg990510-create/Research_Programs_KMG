"""Width and height of every figure of this program, set by the user in the sidebar.

Pages call ``figure_size_section`` once; code that draws a figure calls
``show(fig, kind)``. No page or component calls ``st.plotly_chart`` directly.
"""

from __future__ import annotations

import plotly.graph_objects as go

from labkit.figure_size import FigureSize, figure_size_inputs, show_figure, stored_figure_size
from labkit.sidebar import sidebar_section

# kind -> (label in the sidebar, width in px when "fit to the page" is off, height in px)
KINDS: dict[str, tuple[str, int, int]] = {
    "spectrum": ("Spectrum", 1000, 450),
    "map_parameter": ("Parameter map", 800, 720),
    "map_status": ("Status map", 800, 450),
    "model_charts": ("Charts", 800, 450),
    "sample_scatter": ("Comparison plots", 800, 520),
    "sample_square": ("Absolute position and FWHM plots", 800, 720),
    "sample_heatmap": ("LO ratio map", 800, 450),
    "sample_pl": ("PL comparison", 800, 450),
    "map_editor": ("Map", 800, 620),
}


def figure_size_section(title: str, kinds: list[str]) -> None:
    """Numbered sidebar section with the size inputs of the figures on this page."""
    with sidebar_section(title, expanded=False):
        for kind in kinds:
            figure_size_inputs(kind, *KINDS[kind])


def size_of(kind: str) -> FigureSize:
    _, width_px, height_px = KINDS[kind]
    return stored_figure_size(kind, width_px, height_px)


def show(fig: go.Figure, kind: str, theme: str | None = "streamlit", **chart_arguments):
    """Draw ``fig`` at the size chosen for ``kind``. ``theme=None`` keeps the figure's own look."""
    return show_figure(fig, size_of(kind), theme=theme, **chart_arguments)
