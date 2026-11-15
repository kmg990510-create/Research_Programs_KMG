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

from mos2_gui.components.derived_parameters import add_derived_map_parameters  # noqa: E402
from mos2_gui.components.figure_sizes import figure_size_section, show, size_of  # noqa: E402
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
    filter_store,
    load_graph_config,
    project_root,
    sidebar_filters_section,
    sidebar_section,
)
from mos2_gui.components.science_settings import strain_doping_settings  # noqa: E402

K = "map_viewer"  # session_state key prefix
CHART_KEY = f"{K}_chart"
SELECTED_KEY = f"{K}_selected_ids"
SIZE_SECTION = "4) Figure size"
STATUS_OPTIONS = ["valid", "attention", "invalid"]
PRESET_DIR = project_root() / "data" / "style_presets" / "map"
ROW_COLUMNS = ("spectrum_id", "map_x", "map_y", "selected_model", "fit_status", "review_decision", "rmse", "r2", "attention_reasons", "invalid_reasons")


def _on_select() -> None:
    st.session_state[SELECTED_KEY] = selected_ids_from_event(st.session_state.get(CHART_KEY))


def _lowered(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].astype(str).str.strip().str.lower()


st.title("Map Viewer")
st.caption("One fitted parameter over the measurement points. Select points on the map with the mouse.")

report_path, payload, df = choose_report_sidebar(K)
if report_path is None or payload is None:
    st.stop()
filters_box = sidebar_filters_section()
ratio_box = sidebar_section("3) Ratio Builder", expanded=False)
figure_size_section("4) Figure size", ["map_editor", "map_status", "spectrum"])
if df.empty or not {"map_x", "map_y", "spectrum_id"}.issubset(df.columns):
    st.warning("This report has no map_x / map_y rows.")
    st.stop()

modality = str(payload.get("modality", "")).strip().lower()
if modality not in {"raman", "pl"}:
    modality = "pl" if "pl" in {part.lower() for part in report_path.parts} else "raman"
graph_cfg = load_graph_config()
work_df = add_derived_map_parameters(df, strain_doping_settings(graph_cfg)["coefficients"])
work_df["spectrum_id"] = work_df["spectrum_id"].astype(str)
with ratio_box:
    work_df, ratio_column = ratio_builder(work_df, "map_custom_ratio")

# Filters hide points (drawn as empty cells); they do not remove them from the map grid.
f_store = filter_store()
has_decisions, has_status = "review_decision" in work_df.columns, "fit_status" in work_df.columns
hide_rejected = filters_box.checkbox(
    "Exclude rejected spectra",
    value=bool(f_store.get("hide_rejected", False)),
    key=f"{K}_hide_rejected",
    disabled=not has_decisions,
)
stored_statuses = [s for s in STATUS_OPTIONS if s in f_store.get("statuses", STATUS_OPTIONS)] or STATUS_OPTIONS
selected_statuses = filters_box.multiselect(
    "Allowed fit_status values", STATUS_OPTIONS, default=stored_statuses, key=f"{K}_status_filter", disabled=not has_status
)
f_store.update(hide_rejected=bool(hide_rejected), statuses=list(selected_statuses) if has_status else stored_statuses)
if has_status and not selected_statuses:
    st.info("Select at least one fit_status value.")
    st.stop()

params = parameter_candidates(work_df, first=(ratio_column,) if ratio_column else ())
if not params:
    st.warning("No numeric parameter columns found.")
    st.stop()
top = st.columns([2, 1])
param = top[0].selectbox("Color by parameter", params, key=f"{K}_param")
map_ids = sorted(work_df["map_id"].dropna().astype(str).unique()) if "map_id" in work_df.columns else ["default_map"]
map_id = top[1].selectbox("Map ID", map_ids, key=f"{K}_map_id")

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
with side_col:
    tab_select, tab_style = st.tabs(["Selection", "Figure style"])
with tab_style:
    style_inputs(K, values, SIZE_SECTION)
style = current_style(K, size_of("map_editor").height_px)
with tab_style:
    preset_inputs(K, style, PRESET_DIR)

with map_col:
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

st.subheader("Map Rows")
row_columns = [c for c in (*ROW_COLUMNS[:6], param, *ROW_COLUMNS[6:]) if c in visible_df.columns]
st.dataframe(visible_df[list(dict.fromkeys(row_columns))], width="stretch", height=320, hide_index=True)

with st.expander("Map Summary", expanded=False):
    st.dataframe(pd.DataFrame(payload.get("map_summary", [])), width="stretch")
