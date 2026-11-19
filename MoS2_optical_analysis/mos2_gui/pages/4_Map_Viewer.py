"""Map Viewer: one fitted parameter over the measurement points, with point selection.

Layout only. The figures are in ``components/map_figure.py``, the style inputs in
``components/map_style_panel.py``, the selection panel in ``components/map_selection.py``
and the parameter list and ratio builder in ``components/map_parameters.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(BOOTSTRAP_ROOT) not in sys.path:
    sys.path.append(str(BOOTSTRAP_ROOT))

from fitting.mos2_core.core.runtime_paths import runtime_project_root  # noqa: E402

ROOT = runtime_project_root(__file__, 2)
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from labkit.chrome import panel_title  # noqa: E402
from mos2_gui.components.chrome import render_mos2_chrome  # noqa: E402
from mos2_gui.components.derived_parameters import add_derived_map_parameters  # noqa: E402
from mos2_gui.components.figure_sizes import figure_settings_popover, show, size_of  # noqa: E402
from mos2_gui.components.map_editing import selected_ids_from_event  # noqa: E402
from mos2_gui.components.map_figure import (  # noqa: E402
    MOUSE_MODES,
    build_map_figure,
    default_colorbar_title,
    finite_values,
    resolve_color_range,
    status_map_figure,
)
from mos2_gui.components.map_parameters import parameter_candidates, ratio_builder  # noqa: E402
from mos2_gui.components.map_selection import selection_panel  # noqa: E402
from mos2_gui.components.map_style_panel import current_style, init_style_state, preset_inputs, style_inputs  # noqa: E402
from mos2_gui.components.report_loader import (  # noqa: E402
    choose_report_sidebar,
    load_graph_config,
    project_root,
    render_status_rejected_filters,
)
from mos2_gui.components.science_settings import strain_doping_settings  # noqa: E402

K = "map_viewer"  # session_state key prefix
CHART_KEY = f"{K}_chart"
SELECTED_KEY = f"{K}_selected_ids"
SIZE_SECTION = "Figure settings"
STATUS_OPTIONS = ["valid", "attention", "invalid"]
PRESET_DIR = project_root() / "data" / "style_presets" / "map"
ROW_COLUMNS = ("spectrum_id", "map_x", "map_y", "selected_model", "fit_status", "review_decision", "rmse", "r2", "attention_reasons", "invalid_reasons")


def _on_select() -> None:
    st.session_state[SELECTED_KEY] = selected_ids_from_event(st.session_state.get(CHART_KEY))


def _lowered(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].astype(str).str.strip().str.lower()


render_mos2_chrome("Viewer", "Map Viewer · MoS2 Optical Analysis", viewer_sub="Map")
report_path, payload, df = choose_report_sidebar(K)

if report_path is None or payload is None:
    st.header("Map Viewer")
    st.stop()
if df.empty or not {"map_x", "map_y", "spectrum_id"}.issubset(df.columns):
    st.header("Map Viewer")
    st.warning("This report has no map_x / map_y rows.")
    st.stop()

modality = str(payload.get("modality", "")).strip().lower()
if modality not in {"raman", "pl"}:
    modality = "pl" if "pl" in {part.lower() for part in report_path.parts} else "raman"
graph_cfg = load_graph_config()
work_df = add_derived_map_parameters(df, strain_doping_settings(graph_cfg)["coefficients"])
work_df["spectrum_id"] = work_df["spectrum_id"].astype(str)

# Body filters hide points (drawn as empty cells); they stay selectable and keep grid geometry intact.
_, selected_statuses, hide_rejected = render_status_rejected_filters(work_df, key_prefix=K)
has_decisions, has_status = "review_decision" in work_df.columns, "fit_status" in work_df.columns

st.header("Map Viewer")
st.caption("One fitted parameter over the measurement points. Drag or click on the map to inspect or review points.")

if has_status and not selected_statuses:
    st.info("Select at least one fit_status value.")
    st.stop()

p_col, m_col, r_col, f_col = st.columns([2.0, 1.2, 1.1, 1.1], vertical_alignment="bottom")
with r_col.popover("Custom ratio", width="stretch"):
    work_df, ratio_column = ratio_builder(work_df, "map_custom_ratio")

params = parameter_candidates(work_df, first=(ratio_column,) if ratio_column else ())
if not params:
    st.warning("No numeric parameter columns found.")
    st.stop()
param = p_col.selectbox("Color by parameter", params, key=f"{K}_param")
map_ids = sorted(work_df["map_id"].dropna().astype(str).unique()) if "map_id" in work_df.columns else ["default_map"]
map_id = m_col.selectbox("Map ID", map_ids, key=f"{K}_map_id")
figure_settings_popover(["map_editor", "map_status", "spectrum"], container=f_col)

plot_df = work_df[work_df["map_id"].astype(str) == map_id].copy() if "map_id" in work_df.columns else work_df.copy()
if plot_df.dropna(subset=["map_x", "map_y"]).empty:
    st.info("This report has no map coordinates (map_x / map_y), so there is no map to draw.")
    st.stop()

hidden = pd.Series(False, index=plot_df.index)
if has_decisions and hide_rejected:
    hidden |= _lowered(plot_df, "review_decision") == "rejected"
if has_status:
    plot_df["fit_status"] = _lowered(plot_df, "fit_status")
    hidden |= ~plot_df["fit_status"].isin(selected_statuses)
hidden_ids = plot_df.loc[hidden, "spectrum_id"].tolist()
visible_df = plot_df[~hidden]

if has_status:
    counts = visible_df["fit_status"].value_counts()
    metrics = st.columns(4)
    for column, status in zip(metrics, STATUS_OPTIONS):
        column.metric(status.capitalize(), int(counts.get(status, 0)))
    metrics[3].metric("Hidden by filters", len(hidden_ids))

# Reset the selection when the report or map changes; titles follow the map and parameter.
context = (str(report_path), map_id)
if st.session_state.get(f"{K}_context") != context:
    st.session_state[f"{K}_context"] = context
    st.session_state[SELECTED_KEY] = []
init_style_state(K, f"{map_id}: {param}", default_colorbar_title(param, modality), (context, param))
selected_ids = [s for s in st.session_state.get(SELECTED_KEY, []) if s in set(visible_df["spectrum_id"])]
values = finite_values(visible_df, param)

map_col, side_col = st.columns([3, 2], gap="large")
with side_col, st.container(border=True):
    tab_select, tab_style = st.tabs(["Selection", "Figure style"])
with tab_style:
    style_inputs(K, values, SIZE_SECTION)
style = current_style(K, size_of("map_editor").height_px)
with tab_style:
    preset_inputs(K, style, PRESET_DIR)

with map_col, st.container(border=True):
    panel_title(f"{map_id}: {param}")
    mouse_mode = st.radio(
        "Mouse mode",
        list(MOUSE_MODES),
        horizontal=True,
        key=f"{K}_mouse_mode",
        help="Box / Lasso: drag to select several points. Click: click one point (drag zooms, double-click resets).",
    )
    fig = build_map_figure(
        plot_df, param, style, selected_ids=selected_ids, hidden_ids=hidden_ids, dragmode=MOUSE_MODES[mouse_mode]
    )
    show(
        fig,
        "map_editor",
        filename=f"{map_id}_{param}",
        key=CHART_KEY,
        on_select=_on_select,
        selection_mode=("points", "box", "lasso"),
    )
    zmin, zmax = resolve_color_range(values, style)
    if zmin is not None and zmax is not None:
        clipped = int(((values < zmin) | (values > zmax)).sum())
        st.caption(f"Color range [{zmin:.4f}, {zmax:.4f}] · {clipped} point(s) outside the range · {len(hidden_ids)} hidden")

with tab_select:
    selection_panel(visible_df, selected_ids, param, report_path, modality, graph_cfg, ROOT, K, SELECTED_KEY)

with st.expander("Fit Status Map", expanded=False):
    if has_status:
        status_fig = status_map_figure(visible_df)
        show(status_fig, "map_status", filename=f"{map_id}_fit_status")
    else:
        st.info("This report has no fit_status column.")

with st.container(border=True):
    panel_title("Map Rows")
    row_columns = [c for c in (*ROW_COLUMNS[:6], param, *ROW_COLUMNS[6:]) if c in visible_df.columns]
    st.dataframe(visible_df[list(dict.fromkeys(row_columns))], width="stretch", height=320, hide_index=True)

with st.expander("Map Summary", expanded=False):
    st.dataframe(pd.DataFrame(payload.get("map_summary", [])), width="stretch")
