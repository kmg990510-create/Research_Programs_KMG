"""Width and height of every figure, set by the user.

``figure_size_inputs`` draws the inputs for one kind of figure and remembers the
choice for the session, also across pages. ``show_figure`` draws a Plotly figure
at that size; the saved image (camera button) has the same size.
"""

from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go
import streamlit as st

STORE_KEY = "labkit_figure_sizes"
MIN_PX = 150
MAX_PX = 4000
STEP_PX = 10


@dataclass(frozen=True)
class FigureSize:
    width_px: int | None  # None: as wide as the place it is drawn in
    height_px: int


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


def show_figure(fig: go.Figure, size: FigureSize, theme: str | None = None, **chart_arguments):
    """``st.plotly_chart`` at the chosen size. Other arguments are passed on.

    ``theme=None`` keeps the figure's own look; ``"streamlit"`` lets Streamlit restyle it.
    """
    fig.update_layout(height=size.height_px, width=size.width_px)
    return st.plotly_chart(fig, width=size.width_px or "stretch", theme=theme, **chart_arguments)
