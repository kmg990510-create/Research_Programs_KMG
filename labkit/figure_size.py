"""Size, grid and image format of every figure, set by the user.

``figure_options_inputs`` draws the options that hold for all figures (grid,
image format) and ``figure_size_inputs`` the size of one kind of figure. The
choices are remembered for the session, also across pages. ``show_figure`` is
the one place where a figure is drawn: it finishes the figure
(``labkit.plot_theme.finish_figure``), gives it the chosen size and sets the
camera button to save a figure-quality image of the same size.
"""

from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go
import streamlit as st

from labkit.plot_theme import export_config, finish_figure, set_default_theme

set_default_theme()  # before any figure is built: Plotly Express fixes colours at creation

STORE_KEY = "labkit_figure_sizes"
OPTIONS_KEY = "labkit_figure_options"
GRID_KEY = "labkit_figure_grid"
IMAGE_FORMAT_KEY = "labkit_figure_image_format"
IMAGE_FORMATS = ("png", "svg")
MIN_PX = 150
MAX_PX = 4000
STEP_PX = 10


@dataclass(frozen=True)
class FigureSize:
    width_px: int | None  # None: as wide as the place it is drawn in
    height_px: int


@dataclass(frozen=True)
class FigureOptions:
    grid: bool = False
    image_format: str = "png"


def figure_options_inputs() -> FigureOptions:
    """Inputs that hold for every figure, drawn where this is called (normally the figure sidebar section)."""
    store = st.session_state.setdefault(OPTIONS_KEY, {})
    grid = st.checkbox("Grid", value=store.get("grid", False), key=GRID_KEY, help="Grid lines on every figure.")
    image_format = st.radio(
        "Image format",
        IMAGE_FORMATS,
        index=IMAGE_FORMATS.index(store.get("image_format", "png")),
        horizontal=True,
        key=IMAGE_FORMAT_KEY,
        help="Format of the image saved with the camera button of a figure.",
    )
    store.update(grid=bool(grid), image_format=str(image_format))
    return FigureOptions(bool(grid), str(image_format))


def figure_options() -> FigureOptions:
    """The chosen options without drawing inputs. Reads the input widgets first, then the remembered choice."""
    store = st.session_state.get(OPTIONS_KEY, {})
    grid = st.session_state.get(GRID_KEY, store.get("grid", False))
    image_format = st.session_state.get(IMAGE_FORMAT_KEY, store.get("image_format", "png"))
    return FigureOptions(bool(grid), str(image_format))


def figure_size_inputs(kind: str, label: str, default_width_px: int, default_height_px: int) -> FigureSize:
    """Inputs for one kind of figure, drawn where this is called (normally a sidebar section)."""
    store = st.session_state.setdefault(STORE_KEY, {})
    fit, width, height = store.get(kind, (True, default_width_px, default_height_px))
    st.markdown(f"**{label}**")
    fit = st.checkbox("Fit width to the page", value=fit, key=f"labkit_size_fit_{kind}")
    left, right = st.columns(2)
    # the width input stays visible and is disabled while the figure follows the page width
    width = left.number_input("Width (px)", MIN_PX, MAX_PX, int(width), STEP_PX, key=f"labkit_size_width_{kind}", disabled=fit)
    height = right.number_input("Height (px)", MIN_PX, MAX_PX, int(height), STEP_PX, key=f"labkit_size_height_{kind}")
    store[kind] = (bool(fit), int(width), int(height))
    return FigureSize(None if fit else int(width), int(height))


def stored_figure_size(kind: str, default_width_px: int, default_height_px: int) -> FigureSize:
    """The size chosen for ``kind`` without drawing inputs (for code that only draws the figure).

    Reads the input widgets first, so it does not matter whether the inputs are
    drawn before or after the figure in the script.
    """
    fit, width, height = st.session_state.get(STORE_KEY, {}).get(kind, (True, default_width_px, default_height_px))
    fit = st.session_state.get(f"labkit_size_fit_{kind}", fit)
    width = st.session_state.get(f"labkit_size_width_{kind}", width)
    height = st.session_state.get(f"labkit_size_height_{kind}", height)
    return FigureSize(None if fit else int(width), int(height))


def show_figure(fig: go.Figure, size: FigureSize, filename: str = "figure", **chart_arguments):
    """Draw ``fig``: common look, chosen size, image saved as ``filename``. Other arguments go to ``st.plotly_chart``."""
    options = figure_options()
    finish_figure(fig, grid=options.grid)
    fig.update_layout(height=size.height_px, width=size.width_px)
    return st.plotly_chart(
        fig,
        width=size.width_px or "stretch",
        theme=None,  # Streamlit's own theme would replace the font and colours
        config=export_config(filename, options.image_format),
        **chart_arguments,
    )
