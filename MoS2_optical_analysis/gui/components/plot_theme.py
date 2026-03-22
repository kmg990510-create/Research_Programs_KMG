"""Shared Plotly typography theme for Streamlit pages."""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

_THEME_APPLIED = False


def apply_plotly_theme() -> None:
    """Increase default Plotly font sizes across the app."""
    global _THEME_APPLIED
    if _THEME_APPLIED:
        return

    template = go.layout.Template(pio.templates["plotly_white"])
    template.layout.update(
        font={"size": 20},
        title={"font": {"size": 32}},
        legend={"font": {"size": 15}, "title": {"font": {"size": 20}}},
        hoverlabel={"font": {"size": 14}},
        xaxis={"title": {"font": {"size": 24}}, "tickfont": {"size": 18}},
        yaxis={"title": {"font": {"size": 24}}, "tickfont": {"size": 18}},
        coloraxis={"colorbar": {"title": {"font": {"size": 16}}, "tickfont": {"size": 13}}},
    )

    pio.templates["plotly_white"] = template
    pio.templates.default = "plotly_white"
    px.defaults.template = "plotly_white"
    _THEME_APPLIED = True


