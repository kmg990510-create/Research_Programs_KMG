"""Plotly figures of the FET pages. No Streamlit import."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from fet_core.analysis.results import SweepResult
from fet_core.analysis.sweeps import Branch
from fet_core.report.summary import metric_label
from labkit.plot_theme import (
    AUX,
    DATA,
    FIT,
    LEGEND_INSIDE,
    LINE_AUX,
    LINE_DATA,
    LINE_FIT,
    MARK,
    MARKER_CENTER,
    MARKER_ON_LINE,
    MARKER_RAW,
    OUTLINE,
    OUTLINE_THIN,
    STATUS_COLORS,
    SURFACE,
    apply_paper_layout,
)


def _positive(values: np.ndarray) -> np.ndarray:
    return np.where(values > 0, values, np.nan)


def _span(start: float | None, end: float | None) -> tuple[float, float] | None:
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return None
    return (min(start, end), max(start, end))


def transfer_log_figure(branches: list[Branch], results: dict[str, SweepResult], shown: str, height: int = 460) -> go.Figure:
    """|Id| and |Ig| on a log axis, with the off window, SS line and constant-current Vth of ``shown``."""
    fig = go.Figure()
    for branch in branches:
        active = branch.direction == shown
        fig.add_trace(
            go.Scatter(
                x=branch.data["Vg"],
                y=_positive(branch.data["Id"].abs().to_numpy()),
                mode="lines+markers",
                name=f"|Id| {branch.direction}",
                line={"color": DATA if active else AUX, "width": LINE_DATA if active else LINE_AUX},
                marker={"size": MARKER_ON_LINE},
                opacity=1.0 if active else 0.55,
            )
        )
    current = next((b for b in branches if b.direction == shown), None)
    if current is not None and current.data["Ig"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=current.data["Vg"],
                y=_positive(current.data["Ig"].abs().to_numpy()),
                mode="lines",
                name="|Ig|",
                line={"color": AUX, "width": LINE_AUX, "dash": "dot"},
            )
        )
    result = results.get(shown)
    if result is not None:
        off = _span(result.i_off_window_start_V, result.i_off_window_end_V)
        if off and result.i_off_A:
            fig.add_trace(
                go.Scatter(
                    x=list(off),
                    y=[result.i_off_A, result.i_off_A],
                    mode="lines",
                    name="I_off window",
                    line={"color": MARK, "width": LINE_FIT},
                )
            )
        ss = _span(result.ss_window_start_V, result.ss_window_end_V)
        if ss and result.ss_mV_per_dec and current is not None:
            inside = current.data[(current.data["Vg"] >= ss[0]) & (current.data["Vg"] <= ss[1])]
            log_i = np.log10(_positive(inside["Id"].abs().to_numpy()))
            if np.isfinite(log_i).sum() >= 2:
                slope, intercept = np.polyfit(inside["Vg"].to_numpy()[np.isfinite(log_i)], log_i[np.isfinite(log_i)], 1)
                pad = 0.5 * (ss[1] - ss[0])
                x_line = np.array([ss[0] - pad, ss[1] + pad])
                fig.add_trace(
                    go.Scatter(
                        x=x_line,
                        y=10 ** (slope * x_line + intercept),
                        mode="lines",
                        name=f"SS {result.ss_mV_per_dec:.0f} mV/dec",
                        line={"color": FIT, "width": LINE_FIT},
                    )
                )
        if result.vth_const_current_V is not None and result.vth_const_current_level_A:
            fig.add_trace(
                go.Scatter(
                    x=[result.vth_const_current_V],
                    y=[result.vth_const_current_level_A],
                    mode="markers",
                    name="Vth (constant current)",
                    marker={"symbol": "diamond", "size": MARKER_CENTER, "color": MARK, "line": {"color": SURFACE, "width": OUTLINE}},
                )
            )
    apply_paper_layout(fig, height=height)
    fig.update_yaxes(type="log", title_text="|I| (A)", exponentformat="power")
    fig.update_xaxes(title_text="Vg (V)")
    fig.update_layout(title_text="Log scale", legend=LEGEND_INSIDE)
    return fig


def transfer_linear_figure(branches: list[Branch], results: dict[str, SweepResult], shown: str, height: int = 460) -> go.Figure:
    """|Id| on a linear axis with the gm tangent and the linear-extrapolation Vth of ``shown``."""
    fig = go.Figure()
    top = 0.0
    for branch in branches:
        active = branch.direction == shown
        current = branch.data["Id"].abs()
        top = max(top, float(current.max()))
        fig.add_trace(
            go.Scatter(
                x=branch.data["Vg"],
                y=current,
                mode="lines+markers",
                name=f"|Id| {branch.direction}",
                line={"color": DATA if active else AUX, "width": LINE_DATA if active else LINE_AUX},
                marker={"size": MARKER_ON_LINE},
                opacity=1.0 if active else 0.55,
            )
        )
    result = results.get(shown)
    if result is not None and result.gm_peak_S and result.vth_linear_V is not None:
        sign = -1.0 if result.polarity == "p" else 1.0
        window = _span(result.gm_window_start_V, result.gm_window_end_V)
        # tangent through (gm_peak_Vg, gm_tangent_current) with slope gm in turn-on direction
        far = result.gm_peak_Vg_V + sign * (top - result.gm_tangent_current_A) / result.gm_peak_S
        zero = result.gm_peak_Vg_V - sign * result.gm_tangent_current_A / result.gm_peak_S
        fig.add_trace(
            go.Scatter(x=[zero, far], y=[0.0, top], mode="lines", name="gm tangent", line={"color": FIT, "width": LINE_FIT, "dash": "dash"})
        )
        if window:
            inside = [b for b in branches if b.direction == shown][0].data
            inside = inside[(inside["Vg"] >= window[0]) & (inside["Vg"] <= window[1])]
            fig.add_trace(
                go.Scatter(
                    x=inside["Vg"],
                    y=inside["Id"].abs(),
                    mode="markers",
                    name="gm window",
                    marker={"size": MARKER_RAW, "color": FIT},
                )
            )
        fig.add_trace(
            go.Scatter(
                x=[result.vth_linear_V],
                y=[0.0],
                mode="markers",
                name="Vth (linear extrapolation)",
                marker={"symbol": "diamond", "size": MARKER_CENTER, "color": MARK, "line": {"color": SURFACE, "width": OUTLINE}},
            )
        )
    apply_paper_layout(fig, height=height)
    fig.update_yaxes(title_text="|Id| (A)", rangemode="tozero", exponentformat="power")
    fig.update_xaxes(title_text="Vg (V)")
    fig.update_layout(title_text="Linear scale", legend=LEGEND_INSIDE)
    return fig


def overlay_figure(curves: list[dict], colors: dict[str, str], per_width: bool, height: int = 560, log_scale: bool = True) -> go.Figure:
    """Transfer curves of many devices, one colour per group.

    ``curves``: dicts with ``group``, ``label``, ``vg``, ``current`` (A) and ``W_um``.
    """
    fig = go.Figure()
    seen: set[str] = set()
    for curve in curves:
        y = np.abs(np.asarray(curve["current"], dtype=float))
        if per_width:
            y = y * 1e6 / curve["W_um"]
        fig.add_trace(
            go.Scatter(
                x=curve["vg"],
                y=_positive(y) if log_scale else y,
                mode="lines",
                name=curve["group"],
                legendgroup=curve["group"],
                showlegend=curve["group"] not in seen,
                line={"color": colors[curve["group"]], "width": LINE_DATA},
                opacity=0.8,
                hovertemplate=f"{curve['label']}<br>Vg=%{{x}} V<br>%{{y:.3e}}<extra>{curve['group']}</extra>",
            )
        )
        seen.add(curve["group"])
    apply_paper_layout(fig, height=height)
    fig.update_yaxes(
        type="log" if log_scale else "linear",
        title_text="|Id| (µA/µm)" if per_width else "|Id| (A)",
        exponentformat="power",
    )
    fig.update_xaxes(title_text="Vg (V)")
    fig.update_layout(legend=LEGEND_INSIDE)
    return fig


def metric_figure(frame: pd.DataFrame, metric: str, groups: list[str], colors: dict[str, str], height: int = 520) -> go.Figure:
    """Box of the included sweeps per group with every point drawn; rejected or invalid points are hollow."""
    fig = go.Figure()
    rng = np.random.default_rng(0)  # fixed jitter: the picture does not change between reruns
    for index, group in enumerate(groups):
        part = frame[frame["group_display"] == group]
        used = pd.to_numeric(part.loc[part["included"], metric], errors="coerce").dropna()
        unused = part.loc[~part["included"]]
        unused_values = pd.to_numeric(unused[metric], errors="coerce").dropna()
        if not used.empty:
            fig.add_trace(
                go.Box(
                    x=[index] * len(used),
                    y=used,
                    name=group,
                    boxpoints=False,
                    width=0.5,
                    line={"color": colors[group], "width": LINE_DATA},
                    fillcolor="rgba(0,0,0,0)",
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=index + rng.uniform(-0.16, 0.16, len(used)),
                    y=used,
                    mode="markers",
                    name=group,
                    marker={"size": MARKER_RAW, "color": colors[group], "line": {"color": SURFACE, "width": OUTLINE_THIN}},
                    text=part.loc[used.index, "label"] + " · " + part.loc[used.index, "sweep"],
                    hovertemplate="%{text}<br>%{y:.4g}<extra></extra>",
                    showlegend=False,
                )
            )
        if not unused_values.empty:
            fig.add_trace(
                go.Scatter(
                    x=index + rng.uniform(-0.16, 0.16, len(unused_values)),
                    y=unused_values,
                    mode="markers",
                    name="not in statistics",
                    marker={"size": MARKER_RAW, "symbol": "circle-open", "color": colors[group], "line": {"width": OUTLINE}},
                    text=unused.loc[unused_values.index, "label"] + " · " + unused.loc[unused_values.index, "sweep"],
                    hovertemplate="%{text}<br>%{y:.4g}<br>not in statistics<extra></extra>",
                    showlegend=False,
                )
            )
    apply_paper_layout(fig, height=height)
    fig.update_xaxes(tickmode="array", tickvals=list(range(len(groups))), ticktext=groups, range=[-0.6, len(groups) - 0.4], ticks="")
    fig.update_yaxes(title_text=metric_label(metric), exponentformat="power")
    return fig


GALLERY_FONT_SIZE = 11  # panels are small: the one figure with a smaller font
GALLERY_MARGIN_WIDTH_PX = 74
GALLERY_MARGIN_HEIGHT_PX = 94


def gallery_size(panel_count: int, columns: int, panel_width_px: int | None, panel_height_px: int) -> tuple[int | None, int]:
    """Width and height of the whole gallery from the size of one panel (width None: fit the page)."""
    columns = max(1, min(columns, panel_count))
    rows = -(-panel_count // columns)
    width = None if panel_width_px is None else panel_width_px * columns + GALLERY_MARGIN_WIDTH_PX
    return width, panel_height_px * rows + GALLERY_MARGIN_HEIGHT_PX


def gallery_figure(panels: list[dict], columns: int = 5, row_height: int = 190) -> go.Figure:
    """Every device as a small log-scale panel, coloured by status.

    ``panels``: dicts with ``title`` and ``curves``; a curve has ``key``, ``label``,
    ``vg``, ``current`` (A), ``status`` and ``rejected``. ``trace.meta`` is the
    curve key, and traces are added in panel order, so a click maps back to a sweep.
    """
    severity = list(STATUS_COLORS)
    columns = max(1, min(columns, len(panels)))
    rows = -(-len(panels) // columns)
    fig = make_subplots(
        rows=rows,
        cols=columns,
        shared_xaxes="all",
        shared_yaxes="all",
        subplot_titles=[panel["title"] for panel in panels],
        horizontal_spacing=0.012,
        vertical_spacing=min(0.08, 0.5 / rows),
    )
    for index, panel in enumerate(panels):
        worst = "valid"
        for curve in panel["curves"]:
            rejected = bool(curve["rejected"])
            if severity.index(curve["status"]) > severity.index(worst):
                worst = curve["status"]
            fig.add_trace(
                go.Scatter(
                    x=curve["vg"],
                    y=_positive(np.abs(np.asarray(curve["current"], dtype=float))),
                    mode="lines+markers",  # a click is reported only for a trace that has markers
                    marker={"size": MARKER_RAW, "opacity": 0},
                    meta=curve["key"],
                    line={"color": AUX if rejected else STATUS_COLORS[curve["status"]], "width": LINE_DATA, "dash": "dot" if rejected else "solid"},
                    hovertemplate=f"{panel['title']} · {curve['label']}<br>Vg=%{{x}} V<br>%{{y:.3e}} A<extra></extra>",
                    showlegend=False,
                ),
                row=index // columns + 1,
                col=index % columns + 1,
            )
        fig.layout.annotations[index].update(font={"size": GALLERY_FONT_SIZE + 1, "color": STATUS_COLORS[worst]})
    apply_paper_layout(fig, font_size=GALLERY_FONT_SIZE, height=row_height * rows + GALLERY_MARGIN_HEIGHT_PX)
    fig.update_yaxes(type="log", exponentformat="power")
    fig.update_xaxes(showticklabels=True)
    # hoverdistance -1: a click anywhere in a panel picks the nearest point of that panel
    fig.update_layout(margin={"l": 64, "r": 10, "t": 40, "b": 54}, dragmode="zoom", hovermode="closest", hoverdistance=-1)
    fig.add_annotation(text="Vg (V)", xref="paper", yref="paper", x=0.5, y=0, yshift=-40, showarrow=False, font={"size": GALLERY_FONT_SIZE + 2})
    fig.add_annotation(text="|Id| (A)", xref="paper", yref="paper", x=0, y=0.5, xshift=-54, textangle=-90, showarrow=False, font={"size": GALLERY_FONT_SIZE + 2})
    return fig
