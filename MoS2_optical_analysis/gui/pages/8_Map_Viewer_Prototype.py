"""Prototype: paper-style map with on-screen style editing and point selection.

Kept next to ``4_Map_Viewer.py`` so the two can be compared. Layout only: the
figure lives in ``components/map_figure.py``, edits in ``components/map_editing.py``.
"""

from __future__ import annotations

import sys
from dataclasses import asdict
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

from gui.components.map_editing import REVIEW_DECISIONS, apply_decision, selected_ids_from_event  # noqa: E402
from gui.components.map_figure import (  # noqa: E402
    AXIS_MODES,
    COLORMAPS,
    MOUSE_MODES,
    RANGE_MODES,
    MapStyle,
    build_map_figure,
    default_axis_labels,
    physical_axis_usable,
    default_colorbar_title,
    finite_values,
    load_style_preset,
    resolve_color_range,
    save_style_preset,
)
from gui.components.figure_sizes import figure_size_section, show, size_of  # noqa: E402
from gui.components.report_loader import (  # noqa: E402
    choose_report_sidebar,
    filter_store,
    load_graph_config,
    load_report_payload,
    load_spectra_dataframe,
    project_root,
)
from gui.components.science_settings import strain_doping_settings  # noqa: E402
from gui.components.spectrum_viewer import load_raw_xy, render_spectrum_overlay, resolve_source_file  # noqa: E402

K = "mapproto"  # session_state key prefix
CHART_KEY = f"{K}_chart"
SELECTED_KEY = f"{K}_selected_ids"
STYLE_FIELDS = tuple(asdict(MapStyle()).keys())
PRESET_DIR = project_root() / "data" / "style_presets" / "map"
PREFERRED_PARAMS = (
    "delta_e2g_a1g",
    "strain_eps_pct",
    "doping_n_1e13_cm2",
    "e2g_a1g_area_ratio",
    "e2g_position",
    "a1g_position",
    "e2g_fwhm",
    "a1g_fwhm",
    "pl_position",
    "pl_fwhm",
    "pl_area",
    "a_minus_position",
    "a0_position",
    "a_minus_a0_energy_split",
    "a_minus_a0_area_ratio",
    "a0_fraction_of_a_total",
    "b_to_a_total_area_ratio",
    "defect_to_a_total_area_ratio",
    "a_minus_fwhm",
    "a0_fwhm",
    "b_position",
    "i1_position",
    "i2_position",
    "rmse",
    "r2",
)


def _add_derived_map_parameters(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if {"e2g_area", "a1g_area"}.issubset(out.columns):
        e2g_area = pd.to_numeric(out["e2g_area"], errors="coerce")
        a1g_area = pd.to_numeric(out["a1g_area"], errors="coerce")
        valid = e2g_area.notna() & a1g_area.notna() & (a1g_area != 0.0)
        ratio = pd.Series(float("nan"), index=out.index, dtype=float)
        ratio.loc[valid] = e2g_area.loc[valid] / a1g_area.loc[valid]
        out["e2g_a1g_area_ratio"] = ratio

    if {"e2g_position", "a1g_position"}.issubset(out.columns):
        e2g = pd.to_numeric(out["e2g_position"], errors="coerce")
        a1g = pd.to_numeric(out["a1g_position"], errors="coerce")
        ref_mask = e2g.notna() & a1g.notna()
        if "fit_status" in out.columns:
            ref_mask &= out["fit_status"].astype(str).str.strip().str.lower() != "invalid"
        if "review_decision" in out.columns:
            ref_mask &= out["review_decision"].astype(str).str.strip().str.lower() != "rejected"
        if bool(ref_mask.any()):
            coeffs = strain_doping_settings(load_graph_config())["coefficients"]
            s_e, s_a = float(coeffs["s_e"]), float(coeffs["s_a"])
            d_e, d_a = float(coeffs["d_e"]), float(coeffs["d_a"])
            det_k = s_e * d_a - s_a * d_e
            if abs(det_k) > 1.0e-12:
                omega_e0 = float(e2g.loc[ref_mask].mean())
                omega_a0 = float(a1g.loc[ref_mask].mean())
                d_e2g = e2g - omega_e0
                d_a1g = a1g - omega_a0
                out["strain_eps_pct"] = (d_a * d_e2g - d_e * d_a1g) / det_k
                out["doping_n_1e13_cm2"] = (-s_a * d_e2g + s_e * d_a1g) / det_k
    return out


def _style_key(name: str) -> str:
    return f"{K}_style_{name}"


def _set_style_state(style: MapStyle) -> None:
    for name, value in asdict(style).items():
        st.session_state[_style_key(name)] = value


def _on_axis_mode_change() -> None:
    """Reset the axis labels to match the chosen coordinate mode and unit."""
    probe = MapStyle(
        axis_mode=st.session_state[_style_key("axis_mode")],
        axis_unit=st.session_state[_style_key("axis_unit")],
    )
    st.session_state[_style_key("x_label")], st.session_state[_style_key("y_label")] = default_axis_labels(probe)


def _on_select() -> None:
    st.session_state[SELECTED_KEY] = selected_ids_from_event(st.session_state.get(CHART_KEY))


st.set_page_config(page_title="Map Viewer (prototype)", layout="wide")
st.title("Map Viewer (prototype)")
st.caption("Select points on the map with the mouse. Style changes apply immediately.")

report_path, payload, df = choose_report_sidebar("map_proto")
if report_path is None or payload is None:
    st.stop()
df = _add_derived_map_parameters(df)
figure_size_section("2) Figure size", ["map_editor", "spectrum"])
if df.empty or not {"map_x", "map_y", "spectrum_id"}.issubset(df.columns):
    st.warning("This report has no map_x / map_y rows.")
    st.stop()

modality = str(payload.get("modality", "raman")).strip().lower()
numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c not in {"map_x", "map_y"}]
params = [c for c in PREFERRED_PARAMS if c in numeric_cols] + [c for c in numeric_cols if c not in PREFERRED_PARAMS]
if not params:
    st.warning("No numeric parameter columns found.")
    st.stop()

top = st.columns([2, 1, 1])
param = top[0].selectbox("Color by parameter", params, key=f"{K}_param")
map_ids = sorted(df["map_id"].dropna().astype(str).unique()) if "map_id" in df.columns else ["default_map"]
map_id = top[1].selectbox("Map ID", map_ids, key=f"{K}_map_id")
f_store = filter_store()
hide_rejected = top[2].toggle("Hide rejected points", value=bool(f_store.get("hide_rejected", False)), key=f"{K}_hide_rejected")
f_store["hide_rejected"] = bool(hide_rejected)

plot_df = df[df["map_id"].astype(str) == map_id].copy() if "map_id" in df.columns else df.copy()
plot_df["spectrum_id"] = plot_df["spectrum_id"].astype(str)

# Reset selection and per-parameter titles when the view context changes.
context = (str(report_path), map_id)
if st.session_state.get(f"{K}_context") != context:
    st.session_state[f"{K}_context"] = context
    st.session_state[SELECTED_KEY] = []
if st.session_state.get(f"{K}_title_param") != (context, param):
    st.session_state[f"{K}_title_param"] = (context, param)
    st.session_state[_style_key("title")] = f"{map_id}: {param}"
    st.session_state[_style_key("colorbar_title")] = default_colorbar_title(param, modality)
for field_name, default in asdict(MapStyle()).items():
    st.session_state.setdefault(_style_key(field_name), default)
pending = st.session_state.pop(f"{K}_pending_style", None)
if pending is not None:
    _set_style_state(pending)

selected_ids = [s for s in st.session_state.get(SELECTED_KEY, []) if s in set(plot_df["spectrum_id"])]
values = finite_values(plot_df, param)

map_col, side_col = st.columns([3, 2], gap="large")

with side_col:
    tab_select, tab_style = st.tabs(["Selection", "Figure style"])

with tab_style:
    c1, c2 = st.columns(2)
    c1.selectbox("Colormap", COLORMAPS, key=_style_key("colormap"))
    c2.checkbox("Reverse colormap", key=_style_key("reverse_colormap"))
    st.radio("Color range", RANGE_MODES, horizontal=True, key=_style_key("range_mode"))
    manual_range = st.session_state[_style_key("range_mode")] == "Manual"
    if manual_range and not values.empty and st.session_state[_style_key("zmin")] is None:
        st.session_state[_style_key("zmin")] = float(values.quantile(0.02))
        st.session_state[_style_key("zmax")] = float(values.quantile(0.98))
    m1, m2 = st.columns(2)
    m1.number_input("Color min", format="%.4f", key=_style_key("zmin"), disabled=not manual_range)
    m2.number_input("Color max", format="%.4f", key=_style_key("zmax"), disabled=not manual_range)
    st.text_input("Title", key=_style_key("title"))
    st.text_input("Colorbar title", key=_style_key("colorbar_title"))
    st.radio(
        "Axis coordinates",
        AXIS_MODES,
        horizontal=True,
        key=_style_key("axis_mode"),
        on_change=_on_axis_mode_change,
        help="Physical: the first and last scan points are placed at Start and End, evenly spaced in between.",
    )
    # Always rendered (disabled when unused): Streamlit drops the stored value of a
    # keyed widget on runs where the widget is not drawn.
    index_axes = st.session_state[_style_key("axis_mode")] != "Physical"
    a1, a2, a3 = st.columns(3)
    a1.number_input("X start", format="%.3f", key=_style_key("x_start"), disabled=index_axes)
    a2.number_input("X end", format="%.3f", key=_style_key("x_end"), disabled=index_axes)
    a3.text_input("Unit", key=_style_key("axis_unit"), on_change=_on_axis_mode_change, disabled=index_axes)
    a4, a5, _ = st.columns(3)
    a4.number_input("Y start", format="%.3f", key=_style_key("y_start"), disabled=index_axes)
    a5.number_input("Y end", format="%.3f", key=_style_key("y_end"), disabled=index_axes)
    l1, l2 = st.columns(2)
    l1.text_input("X label", key=_style_key("x_label"))
    l2.text_input("Y label", key=_style_key("y_label"))
    s1, s3 = st.columns(2)
    s1.number_input("Font size", min_value=8, max_value=28, step=1, key=_style_key("font_size"))
    s3.number_input("Cell gap (px)", min_value=0, max_value=6, step=1, key=_style_key("cell_gap_px"))
    st.caption("Width and height: sidebar section 2) Figure size.")
    v1, v2, v3 = st.columns(3)
    v1.checkbox("Show values", key=_style_key("show_values"))
    v2.number_input("Decimals", min_value=0, max_value=6, step=1, key=_style_key("value_decimals"))
    v3.checkbox("Y origin at top", key=_style_key("y_origin_top"))

# the height comes from the sidebar size inputs; the cell size of the map follows it
style = MapStyle(**{**{name: st.session_state[_style_key(name)] for name in STYLE_FIELDS}, "height_px": size_of("map_editor").height_px})

with tab_style:
    if style.axis_mode == "Physical" and not physical_axis_usable(style):
        st.warning("Start and End must differ on both axes. Showing point index instead.")
    st.divider()
    presets = sorted(p.stem for p in PRESET_DIR.glob("*.yaml")) if PRESET_DIR.exists() else []
    p1, p2 = st.columns(2)
    preset_name = p1.text_input("Preset name", value="my_map_style", key=f"{K}_preset_name").strip()
    if p1.button("Save preset", key=f"{K}_preset_save", width="stretch") and preset_name:
        save_style_preset(PRESET_DIR / f"{preset_name}.yaml", style)
        st.toast(f"Saved preset: {preset_name}")
        st.rerun()
    chosen = p2.selectbox("Saved presets", presets, key=f"{K}_preset_pick") if presets else None
    if p2.button("Load preset", key=f"{K}_preset_load", width="stretch", disabled=not presets) and chosen:
        st.session_state[f"{K}_pending_style"] = load_style_preset(PRESET_DIR / f"{chosen}.yaml")
        st.rerun()
    st.caption("Use the camera button on the figure to download it. Grid and image format: sidebar section 2) Figure size.")

hidden_ids: list[str] = []
if hide_rejected and "review_decision" in plot_df.columns:
    hidden_ids = plot_df.loc[plot_df["review_decision"].astype(str) == "rejected", "spectrum_id"].tolist()

with map_col:
    mouse_mode = st.radio(
        "Mouse mode",
        list(MOUSE_MODES),
        horizontal=True,
        key=f"{K}_mouse_mode",
        help="Box / Lasso: drag to select several points. Click: click one point (drag zooms, double-click resets).",
    )
    fig = build_map_figure(
        plot_df,
        param,
        style,
        selected_ids=selected_ids,
        hidden_ids=hidden_ids,
        dragmode=MOUSE_MODES[mouse_mode],
    )
    show(
        fig,
        "map_editor",
        filename=f"{map_id}_{param}",
        key=CHART_KEY,
        on_select=_on_select,
        selection_mode=("points", "box", "lasso"),
    )
    zmin, zmax = resolve_color_range(finite_values(plot_df[~plot_df["spectrum_id"].isin(hidden_ids)], param), style)
    if zmin is not None and zmax is not None:
        clipped = int(((values < zmin) | (values > zmax)).sum())
        st.caption(f"Color range [{zmin:.4f}, {zmax:.4f}] · {clipped} point(s) outside the range · {len(hidden_ids)} hidden")

with tab_select:
    picked = plot_df[plot_df["spectrum_id"].isin(selected_ids)]
    if picked.empty:
        st.info("No points selected. Drag a box on the map, or switch Mouse mode to Click.")
    else:
        picked_values = finite_values(picked, param)
        n1, n2, n3 = st.columns(3)
        n1.metric("Selected", len(picked))
        n2.metric(f"Mean {param}", f"{picked_values.mean():.4f}" if not picked_values.empty else "-")
        n3.metric("Std", f"{picked_values.std(ddof=0):.4f}" if not picked_values.empty else "-")

        d1, d2 = st.columns([1, 2])
        decision = d1.selectbox("Set review decision", REVIEW_DECISIONS, key=f"{K}_decision")
        note = d2.text_input("Note", key=f"{K}_note")
        b1, b2 = st.columns(2)
        if b1.button(f"Apply to {len(picked)} point(s)", type="primary", key=f"{K}_apply", width="stretch"):
            count = apply_decision(report_path, plot_df, selected_ids, decision, note)
            load_report_payload.clear()
            load_spectra_dataframe.clear()
            st.toast(f"Recorded '{decision}' for {count} point(s) in manual overrides.")
            st.rerun()
        if b2.button("Clear selection", key=f"{K}_clear", width="stretch"):
            st.session_state[SELECTED_KEY] = []
            st.rerun()

        show_cols = [c for c in ["spectrum_id", "map_x", "map_y", param, "fit_status", "review_decision"] if c in picked.columns]
        st.dataframe(picked[show_cols], width="stretch", height=180, hide_index=True)

        if len(picked) == 1:
            row = picked.iloc[0].to_dict()
            x_raw_obj, y_raw_obj = row.get("raw_x"), row.get("raw_y")
            if isinstance(x_raw_obj, list) and isinstance(y_raw_obj, list) and len(x_raw_obj) == len(y_raw_obj) and x_raw_obj:
                x_raw = [float(v) for v in x_raw_obj]
                y_raw = [float(v) for v in y_raw_obj]
            else:
                src_path = resolve_source_file(row.get("source_file"), ROOT)
                if src_path is not None:
                    x_raw, y_raw = load_raw_xy(str(src_path))
                else:
                    x_raw, y_raw = [], []

            if x_raw and y_raw:
                try:
                    cal_offset = float(row.get("calibration_offset", 0.0) or 0.0)
                except (TypeError, ValueError):
                    cal_offset = 0.0
                x_for_plot = [xv + cal_offset for xv in x_raw]
                row_mod = str(row.get("modality", modality)).strip().lower() or modality
                if row_mod == "pl" and str(row.get("x_unit", "")).strip().lower() == "ev" and max(x_for_plot) > 100.0:
                    pairs = sorted(
                        ((1239.8419843320026 / float(xv), float(yv)) for xv, yv in zip(x_for_plot, y_raw) if float(xv) > 0.0),
                        key=lambda item: item[0],
                    )
                    x_for_plot = [xv for xv, _ in pairs]
                    y_raw = [yv for _, yv in pairs]

                if row_mod == "pl":
                    try:
                        pl_val = float(row.get("pl_position") or row.get("a0_position"))
                        span = max(x_for_plot) - min(x_for_plot)
                        pad = max(0.08, min(0.25, span * 0.25)) if span <= 10.0 else 60.0
                        lo = max(float(min(x_for_plot)), pl_val - pad)
                        hi = min(float(max(x_for_plot)), pl_val + pad)
                    except (TypeError, ValueError):
                        lo, hi = float(min(x_for_plot)), float(max(x_for_plot))
                else:
                    try:
                        lo = min(float(row["e2g_position"]), float(row["a1g_position"])) - 30.0
                        hi = max(float(row["e2g_position"]), float(row["a1g_position"])) + 30.0
                    except (KeyError, TypeError, ValueError):
                        lo, hi = float(min(x_for_plot)), float(max(x_for_plot))
                render_spectrum_overlay(
                    spectrum_id=str(row["spectrum_id"]),
                    row=row,
                    x_raw=x_for_plot,
                    y_raw=y_raw,
                    x_view_min=lo,
                    x_view_max=hi,
                )
            else:
                st.caption("Raw spectrum is not embedded in this report row and source file was not found.")
