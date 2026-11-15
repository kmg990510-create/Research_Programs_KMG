"""The shared plot theme, as FET_analysis uses it."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fet_gui.components.figures import STATUS_COLORS, gallery_figure, metric_figure, overlay_figure  # noqa: E402
from labkit.plot_theme import CATEGORICAL, FONT_FAMILY, SURFACE, apply_paper_layout, categorical_colors, export_config  # noqa: E402


def test_paper_layout_is_written_on_the_layout_itself() -> None:
    fig = apply_paper_layout(go.Figure(go.Scatter(x=[1, 2], y=[1, 2])), font_size=16, height=400)
    # Streamlit replaces template fonts and colours, so they must be set directly
    assert fig.layout.font.family == FONT_FAMILY and fig.layout.font.size == 16
    assert fig.layout.paper_bgcolor == SURFACE and fig.layout.height == 400
    assert fig.layout.xaxis.mirror is True and fig.layout.xaxis.showgrid is False


def test_categorical_colors_are_fixed_by_order() -> None:
    colors = categorical_colors(["a", "b", "c"])
    assert list(colors.values()) == list(CATEGORICAL[:3])
    assert categorical_colors(["a", "b", "c", "d"])["b"] == colors["b"]  # adding a group does not repaint the others
    assert export_config("x", "svg")["toImageButtonOptions"] == {"format": "svg", "filename": "x", "scale": 3}


def test_comparison_figures() -> None:
    colors = categorical_colors(["P", "T"])
    curves = [
        {"group": "P", "label": "a", "vg": [0, 1, 2], "current": [1e-9, -1e-7, 1e-6], "W_um": 10.0},
        {"group": "P", "label": "b", "vg": [0, 1, 2], "current": [0.0, 1e-7, 2e-6], "W_um": 10.0},
        {"group": "T", "label": "c", "vg": [0, 1, 2], "current": [1e-9, 1e-8, 1e-7], "W_um": 20.0},
    ]
    fig = overlay_figure(curves, colors, per_width=True)
    assert [t.showlegend for t in fig.data] == [True, False, True]  # one legend entry per group
    assert fig.data[0].y[1] == 1e-7 * 1e6 / 10.0  # absolute value, per micrometre of width
    assert pd.isna(fig.data[1].y[0])  # a zero current cannot be drawn on a log axis
    assert fig.layout.yaxis.type == "log" and "µA/µm" in fig.layout.yaxis.title.text

    frame = pd.DataFrame(
        {
            "group_display": ["P", "P", "T", "T"],
            "included": [True, True, True, False],
            "mobility_cm2_per_Vs": [10.0, 12.0, 5.0, 50.0],
            "label": list("abcd"),
            "sweep": ["forward"] * 4,
        }
    )
    stats = metric_figure(frame, "mobility_cm2_per_Vs", ["P", "T"], colors)
    boxes = [t for t in stats.data if t.type == "box"]
    assert [list(b.y) for b in boxes] == [[10.0, 12.0], [5.0]]  # the excluded sweep is not in the box
    hollow = [t for t in stats.data if t.type == "scatter" and t.marker.symbol == "circle-open"]
    assert [list(t.y) for t in hollow] == [[50.0]]
    assert list(stats.layout.xaxis.ticktext) == ["P", "T"]


def test_gallery_figure_maps_traces_back_to_sweeps() -> None:
    def curve(key: str, status: str, rejected: bool = False) -> dict:
        return {"key": key, "label": "forward", "vg": [0, 1, 2], "current": [1e-12, -1e-9, 1e-6], "status": status, "rejected": rejected}

    panels = [
        {"title": "a", "curves": [curve("a|f", "valid"), curve("a|b", "attention")]},
        {"title": "b", "curves": [curve("b|f", "invalid")]},
        {"title": "c", "curves": [curve("c|f", "valid", rejected=True)]},
    ]
    fig = gallery_figure(panels, columns=2)
    assert [t.meta for t in fig.data] == ["a|f", "a|b", "b|f", "c|f"]  # trace order = click order
    assert all("markers" in t.mode for t in fig.data)  # a click is only reported for traces with markers
    assert fig.layout.hoverdistance == -1 and fig.layout.yaxis.type == "log"
    titles = {a.text: a.font.color for a in fig.layout.annotations if a.text in {"a", "b", "c"}}
    assert titles == {"a": STATUS_COLORS["attention"], "b": STATUS_COLORS["invalid"], "c": STATUS_COLORS["valid"]}  # worst status of the panel
    assert fig.data[3].line.dash == "dot" and fig.data[0].line.dash == "solid"


def test_figures_use_the_shared_roles_and_finish_step() -> None:
    from fet_gui.components.figures import transfer_log_figure
    from labkit import plot_theme as theme

    assert theme.STATUS_COLORS is STATUS_COLORS  # one definition for both programs
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1e-9, 1e-6]))
    fig.update_layout(xaxis_title="Raman shift (cm^-1)")
    theme.finish_figure(fig, grid=True)
    assert theme.has_paper_look(fig) and fig.layout.xaxis.title.text == "Raman shift (cm⁻¹)"
    assert fig.layout.xaxis.showgrid is True and fig.layout.legend.x == theme.LEGEND_INSIDE["x"]
    assert theme.axis_label("Doping n", "10^13 cm^-2") == "Doping n (10¹³ cm⁻²)" and theme.axis_label("Ratio") == "Ratio"

    shown = transfer_log_figure([], {}, "forward")
    theme.finish_figure(shown)
    assert shown.layout.legend.x == theme.LEGEND_INSIDE["x"] and shown.layout.xaxis.showgrid is False
