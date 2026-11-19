"""Size, grid and image format of every figure of this program, set by the user in Figure settings.

Pages offer figure size inputs via ``figure_settings_popover`` (or
``figure_size_section``); code that draws a figure calls ``show(fig, kind)``.
No page or component calls ``st.plotly_chart`` directly, so every figure gets
the same look (``labkit.plot_theme.finish_figure``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import plotly.graph_objects as go

from labkit.figure_size import (
    FigureSize,
    figure_options_inputs,
    figure_settings_popover as _labkit_figure_settings_popover,
    figure_size_inputs,
    show_figure,
    stored_figure_size,
)
from labkit.sidebar import sidebar_section

# kind -> (label in Figure settings, width in px when "fit to the page" is off, height in px)
KINDS: dict[str, tuple[str, int, int]] = {
    "spectrum": ("Spectrum", 1000, 450),
    "map_editor": ("Map", 800, 620),
    "map_status": ("Status map", 800, 450),
    "model_charts": ("Charts", 800, 450),
    "sample_scatter": ("Comparison plots", 800, 520),
    "sample_square": ("Absolute position and FWHM plots", 800, 720),
    "sample_heatmap": ("LO ratio map", 800, 450),
    "sample_pl": ("PL comparison", 800, 450),
}


def figure_size_section(title: str, kinds: list[str]) -> None:
    """Numbered sidebar section: grid and image format of all figures, then the size of each kind on this page."""
    with sidebar_section(title, expanded=False):
        figure_options_inputs()
        for kind in kinds:
            figure_size_inputs(kind, *KINDS[kind])


def figure_settings_popover(
    kinds: list[str],
    *,
    label: str = "Figure settings",
    extra: Callable[[], None] | None = None,
    container: Any | None = None,
) -> dict[str, FigureSize]:
    """Result-area popover holding global Grid / Image format and the sizes for ``kinds``."""
    specs = [(kind, *KINDS[kind]) for kind in kinds]
    return _labkit_figure_settings_popover(specs, label=label, extra=extra, container=container)


def size_of(kind: str) -> FigureSize:
    _, width_px, height_px = KINDS[kind]
    return stored_figure_size(kind, width_px, height_px)


def show(fig: go.Figure, kind: str, filename: str | None = None, **chart_arguments):
    """Draw ``fig`` at the size chosen for ``kind``; the camera button saves it as ``filename``."""
    return show_figure(fig, size_of(kind), filename=filename or kind, **chart_arguments)
