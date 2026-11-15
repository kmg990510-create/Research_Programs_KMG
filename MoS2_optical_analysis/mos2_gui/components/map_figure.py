"""Map heatmap figure builder with an editable style (prototype).

No Streamlit import: the page passes data and a ``MapStyle`` and gets a figure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yaml

from labkit.plot_theme import FONT_FAMILY, INK, MISSING_CELL, SURFACE, colorbar_style, paper_template

COLORMAPS = ("Viridis", "Cividis", "Magma", "Inferno", "Blues", "Greys", "RdBu")
RANGE_MODES = ("Full range", "Robust 2-98%", "Manual")
AXIS_MODES = ("Index", "Physical")
MOUSE_MODES = {"Box": "select", "Lasso": "lasso", "Click": "zoom"}
DECISION_MARKERS = {
    "rejected": {"symbol": "x-thin", "label": "rejected"},
    "refit": {"symbol": "circle-open", "label": "refit"},
    "approved": {"symbol": "diamond-open", "label": "approved"},
}
_PLOT_CHROME_PX = 120  # title + axis margins around the plot area


@dataclass
class MapStyle:
    colormap: str = "Viridis"
    reverse_colormap: bool = False
    range_mode: str = "Robust 2-98%"
    zmin: float | None = None
    zmax: float | None = None
    title: str = ""
    x_label: str = "X (point index)"
    y_label: str = "Y (point index)"
    colorbar_title: str = ""
    font_size: int = 14
    height_px: int = 620
    cell_gap_px: int = 0
    show_values: bool = False
    value_decimals: int = 2
    y_origin_top: bool = False
    # "Physical": first/last scan point sit at start/end, points evenly spaced between.
    axis_mode: str = "Index"
    axis_unit: str = "µm"
    x_start: float = 0.0
    x_end: float = 10.0
    y_start: float = 0.0
    y_end: float = 10.0


def style_from_dict(data: dict[str, Any] | None) -> MapStyle:
    known = {f.name for f in fields(MapStyle)}
    return MapStyle(**{k: v for k, v in (data or {}).items() if k in known})


def save_style_preset(path: Path, style: MapStyle) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(asdict(style), sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_style_preset(path: Path) -> MapStyle:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return style_from_dict(payload if isinstance(payload, dict) else {})


def default_unit(param: str, modality: str) -> str:
    """Unit shown in the default colorbar title. Empty when unknown or unitless."""
    name = param.lower()
    if name == "strain_eps_pct":
        return "%"
    if name == "doping_n_1e13_cm2":
        return "10¹³ cm⁻²"
    if "ratio" in name or "fraction" in name or name in {"r2", "aic", "bic"}:
        return ""
    if name.endswith(("_position", "_fwhm")) or name.startswith("delta_") or name.endswith("_split"):
        return "eV" if modality == "pl" else "cm⁻¹"
    return ""


def default_colorbar_title(param: str, modality: str) -> str:
    unit = default_unit(param, modality)
    return f"{param} ({unit})" if unit else param


def finite_values(frame: pd.DataFrame, param: str) -> pd.Series:
    return pd.to_numeric(frame[param], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def resolve_color_range(values: pd.Series, style: MapStyle) -> tuple[float | None, float | None]:
    if values.empty:
        return None, None
    if style.range_mode == "Manual" and style.zmin is not None and style.zmax is not None and style.zmin < style.zmax:
        return float(style.zmin), float(style.zmax)
    if style.range_mode == "Robust 2-98%":
        low, high = float(values.quantile(0.02)), float(values.quantile(0.98))
        if low < high:
            return low, high
    return float(values.min()), float(values.max())


def default_axis_labels(style: MapStyle) -> tuple[str, str]:
    if style.axis_mode == "Physical":
        suffix = f" ({style.axis_unit})" if style.axis_unit.strip() else ""
        return f"X{suffix}", f"Y{suffix}"
    return "X (point index)", "Y (point index)"


def physical_axis_usable(style: MapStyle) -> bool:
    return style.axis_mode == "Physical" and style.x_start != style.x_end and style.y_start != style.y_end


def to_physical(index_values: pd.Series, start: float, end: float) -> pd.Series:
    """Map scan indices onto [start, end]: lowest index -> start, highest -> end."""
    levels = np.sort(pd.unique(index_values.dropna()))
    if len(levels) < 2:
        return pd.Series(float(start), index=index_values.index)
    positions = np.linspace(float(start), float(end), len(levels))
    return index_values.map(dict(zip(levels, positions)))


def _cell_px(style: MapStyle, nx: int, ny: int) -> float:
    return max(6.0, (style.height_px - _PLOT_CHROME_PX) / max(nx, ny, 1))


def _customdata(frame: pd.DataFrame, param: str) -> np.ndarray:
    status = frame["fit_status"] if "fit_status" in frame.columns else pd.Series("", index=frame.index)
    decision = frame["review_decision"] if "review_decision" in frame.columns else pd.Series("", index=frame.index)
    return np.column_stack(
        [
            frame["spectrum_id"].astype(str).to_numpy(),
            pd.to_numeric(frame[param], errors="coerce").to_numpy(),
            status.astype(str).to_numpy(),
            decision.astype(str).to_numpy(),
        ]
    )


def build_map_figure(
    frame: pd.DataFrame,
    param: str,
    style: MapStyle,
    *,
    selected_ids: Iterable[str] = (),
    hidden_ids: Iterable[str] = (),
    dragmode: str = "select",
) -> go.Figure:
    """Heatmap of ``param`` with a selectable point layer on top.

    ``frame`` needs ``spectrum_id``, ``map_x``, ``map_y`` and ``param``.
    ``hidden_ids`` are drawn as missing cells; ``selected_ids`` get an outline.
    ``dragmode``: "select" (box), "lasso", or "zoom". Streamlit only reports a
    single click as a selection when the drag mode is not box/lasso.
    """
    data = frame.dropna(subset=["map_x", "map_y"]).copy()
    data["spectrum_id"] = data["spectrum_id"].astype(str)
    data[param] = pd.to_numeric(data[param], errors="coerce")
    hidden = set(map(str, hidden_ids))
    selected = set(map(str, selected_ids))
    physical = physical_axis_usable(style)
    if physical:
        data["map_x"] = to_physical(data["map_x"], style.x_start, style.x_end)
        data["map_y"] = to_physical(data["map_y"], style.y_start, style.y_end)

    shown = data.copy()
    shown.loc[shown["spectrum_id"].isin(hidden), param] = np.nan
    pivot = (
        shown.pivot_table(index="map_y", columns="map_x", values=param, aggfunc="mean", dropna=False)
        .sort_index(ascending=True)
        .sort_index(axis=1, ascending=True)
    )
    nx, ny = pivot.shape[1], pivot.shape[0]
    zmin, zmax = resolve_color_range(finite_values(shown, param), style)
    cell = _cell_px(style, nx, ny)

    fig = go.Figure()
    fig.add_trace(
        go.Heatmap(
            z=pivot.to_numpy(),
            x=pivot.columns.to_numpy(),
            y=pivot.index.to_numpy(),
            colorscale=style.colormap,
            reversescale=style.reverse_colormap,
            zmin=zmin,
            zmax=zmax,
            xgap=style.cell_gap_px,
            ygap=style.cell_gap_px,
            hoverinfo="skip",
            colorbar=colorbar_style(style.font_size, style.colorbar_title),
            texttemplate=f"%{{z:.{style.value_decimals}f}}" if style.show_values else None,
            textfont={"size": max(8, style.font_size - 4)},
        )
    )

    # Invisible square per point: receives hover, click, box and lasso selection.
    fig.add_trace(
        go.Scatter(
            x=data["map_x"],
            y=data["map_y"],
            mode="markers",
            marker={"symbol": "square", "size": cell * 0.9, "color": INK, "opacity": 0.0},
            selected={"marker": {"opacity": 0.0}},
            unselected={"marker": {"opacity": 0.0}},
            customdata=_customdata(data, param),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>x=%{x:.4g}, y=%{y:.4g}<br>"
                + param
                + "=%{customdata[1]:.4f}<br>fit_status=%{customdata[2]}<br>decision=%{customdata[3]}<extra></extra>"
            ),
            showlegend=False,
            name="points",
        )
    )

    if "review_decision" in data.columns:
        for decision, spec in DECISION_MARKERS.items():
            part = data[data["review_decision"].astype(str) == decision]
            if part.empty:
                continue
            for color, width in ((SURFACE, 4.5), (INK, 2.0)):  # light ring under dark mark
                fig.add_trace(
                    go.Scatter(
                        x=part["map_x"],
                        y=part["map_y"],
                        mode="markers",
                        marker={
                            "symbol": spec["symbol"],
                            "size": cell * 0.45,
                            "color": color,
                            "line": {"color": color, "width": width},
                        },
                        selected={"marker": {"opacity": 1.0}},
                        unselected={"marker": {"opacity": 1.0}},
                        customdata=_customdata(part, param),
                        hoverinfo="skip",
                        showlegend=color == INK,
                        name=spec["label"],
                    )
                )

    picked = data[data["spectrum_id"].isin(selected)]
    if not picked.empty:
        for color, width in ((INK, 4.5), (SURFACE, 2.0)):  # dark ring under light outline
            fig.add_trace(
                go.Scatter(
                    x=picked["map_x"],
                    y=picked["map_y"],
                    mode="markers",
                    marker={
                        "symbol": "square-open",
                        "size": cell * 0.88,
                        "color": color,
                        "line": {"color": color, "width": width},
                    },
                    selected={"marker": {"opacity": 1.0}},
                    unselected={"marker": {"opacity": 1.0}},
                    customdata=_customdata(picked, param),
                    hoverinfo="skip",
                    showlegend=False,
                    name="selected",
                )
            )

    fig.update_layout(
        template=paper_template(style.font_size),
        title={"text": style.title},
        height=style.height_px,
        paper_bgcolor=SURFACE,
        font={"family": FONT_FAMILY, "size": style.font_size, "color": INK},
        plot_bgcolor=MISSING_CELL,
        dragmode=dragmode,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "right", "x": 1.0},
        uirevision="map",
    )
    x_values, y_values = pivot.columns.to_numpy(dtype=float), pivot.index.to_numpy(dtype=float)
    x_step = float(np.min(np.diff(x_values))) if nx > 1 else 1.0
    y_step = float(np.min(np.diff(y_values))) if ny > 1 else 1.0
    if physical:
        fig.update_xaxes(ticks="outside", nticks=8)
        fig.update_yaxes(ticks="outside", nticks=8)
    x_range = [x_values[0] - x_step / 2, x_values[-1] + x_step / 2]
    y_range = [y_values[0] - y_step / 2, y_values[-1] + y_step / 2]
    # Explicit ranges: marker sizes would otherwise pad the autorange around the cells.
    fig.update_xaxes(title_text=style.x_label, constrain="domain", range=x_range, dtick=x_step if nx <= 20 and not physical else None)
    fig.update_yaxes(
        title_text=style.y_label,
        scaleanchor="x",
        scaleratio=1.0,
        constrain="domain",
        range=y_range[::-1] if style.y_origin_top else y_range,
        dtick=y_step if ny <= 20 and not physical else None,
    )
    return fig
