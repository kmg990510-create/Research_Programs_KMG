"""Scatter figure style used by Sample Comparison."""

from __future__ import annotations

import plotly.graph_objects as go

from gui.components.scatter_style import ScatterStyle, apply_scatter_style, pretty_label


def test_pretty_label() -> None:
    assert pretty_label("A1g FWHM (cm^-1)") == "A1g FWHM (cm⁻¹)"
    assert pretty_label("Doping n (10^13 cm^-2)") == "Doping n (10¹³ cm⁻²)"
    assert pretty_label("Strain eps (%)") == "Strain ε (%)"
    assert pretty_label("eps-n scatter") == "ε-n scatter"
    assert pretty_label(None) == ""


def test_apply_scatter_style_separates_points_centers_and_lines() -> None:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[1, 2], y=[1, 2], mode="markers", marker={"size": 5}))
    fig.add_trace(go.Scatter(x=[1.5], y=[1.5], mode="markers", marker={"size": 11}, error_x={"array": [0.1]}))
    fig.add_trace(go.Scatter(x=[0, 3], y=[0, 3], mode="lines", line={"width": 1}))
    fig.update_layout(xaxis_title="E2g FWHM (cm^-1)", height=None)
    style = ScatterStyle(point_size=9, point_opacity=0.4, center_size=16, legend_position="Hidden", height_px=480)
    apply_scatter_style(fig, style)
    assert fig.data[0].marker.size == 9 and fig.data[0].marker.opacity == 0.4
    assert fig.data[1].marker.size == 16
    assert fig.data[2].marker.size is None
    assert fig.layout.showlegend is False
    assert fig.layout.height == 480
    assert fig.layout.xaxis.title.text == "E2g FWHM (cm⁻¹)"
    assert fig.layout.xaxis.mirror is True


def test_apply_scatter_style_keeps_explicit_height() -> None:
    fig = go.Figure(go.Scatter(x=[1], y=[1], mode="markers"))
    fig.update_layout(height=720)
    assert apply_scatter_style(fig, ScatterStyle(height_px=400)).layout.height == 720
