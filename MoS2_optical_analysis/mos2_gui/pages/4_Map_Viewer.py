"""Page for map-level parameter and quality visualization."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(BOOTSTRAP_ROOT) not in sys.path:
    sys.path.append(str(BOOTSTRAP_ROOT))

from fitting.mos2_core.core.runtime_paths import runtime_project_root  # noqa: E402

ROOT = runtime_project_root(__file__, 2)
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from mos2_gui.components.map_figure import default_colorbar_title  # noqa: E402
from mos2_gui.components.report_loader import (  # noqa: E402
    choose_report_sidebar,
    filter_store,
    load_graph_config,
    sidebar_filters_section,
    sidebar_section,
)
from mos2_gui.components.derived_parameters import add_derived_map_parameters  # noqa: E402
from mos2_gui.components.science_settings import strain_doping_settings  # noqa: E402
from mos2_gui.components.figure_sizes import figure_size_section, show  # noqa: E402
from labkit.plot_theme import INK, LEGEND_RIGHT, MARKER_MAP, OUTLINE_THIN, SEQUENTIAL, STATUS_COLORS  # noqa: E402


st.title("Map Viewer")
st.caption("Spatial view of Raman/PL fit parameters across measurement points.")

report_path, payload, df = choose_report_sidebar("map_viewer")
if report_path is None or payload is None:
    st.stop()
if df.empty:
    st.warning("This report has no spectra rows.")
    st.stop()

modality = str(payload.get("modality", "")).strip().lower()
if modality not in {"raman", "pl"}:
    modality = "pl" if "pl" in {part.lower() for part in report_path.parts} else "raman"

work_df = add_derived_map_parameters(df, strain_doping_settings(load_graph_config())["coefficients"])
status_options = ["valid", "attention", "invalid"]
f_store = filter_store()
filters_box = sidebar_filters_section()
hide_rejected = bool(f_store.get("hide_rejected", False))
if "review_decision" in work_df.columns:
    hide_rejected = filters_box.checkbox(
        "Exclude rejected spectra",
        value=hide_rejected,
        key="map_viewer_hide_rejected",
    )
    if hide_rejected:
        work_df = work_df[work_df["review_decision"].astype(str).str.strip().str.lower() != "rejected"]
if "fit_status" in work_df.columns:
    work_df["fit_status"] = work_df["fit_status"].astype(str).str.strip().str.lower()
    stored_statuses = [s for s in status_options if s in f_store.get("statuses", status_options)] or status_options
    selected_statuses = filters_box.multiselect(
        "Allowed fit_status values",
        options=status_options,
        default=stored_statuses,
        key="map_viewer_status_filter",
    )
    f_store.update(statuses=list(selected_statuses), hide_rejected=bool(hide_rejected))
    if not selected_statuses:
        st.info("Select at least one fit_status value.")
        st.stop()
    work_df = work_df[work_df["fit_status"].isin(selected_statuses)]
else:
    f_store["hide_rejected"] = bool(hide_rejected)
    filters_box.caption("fit_status column not found: status filter disabled.")

if work_df.empty:
    st.warning("No rows left after fit_status filter.")
    st.stop()

custom_ratio_col: str | None = None
ratio_numeric_candidates = [
    col
    for col in work_df.columns
    if pd.api.types.is_numeric_dtype(work_df[col]) and col not in {"map_x", "map_y"}
]
ratio_box = sidebar_section("3) Ratio Builder", expanded=False)
figure_size_section("4) Figure size", ["map_parameter", "map_status"])
with ratio_box:
    has_two_numeric = len(ratio_numeric_candidates) >= 2
    enable_custom_ratio = st.checkbox(
        "Enable custom ratio (numerator / denominator)",
        value=False,
        key="map_custom_ratio_enable",
        disabled=not has_two_numeric,
    )
    ratio_disabled = (not enable_custom_ratio) or (not has_two_numeric)
    num_options = ratio_numeric_candidates if has_two_numeric else ["-"]
    ratio_num = st.selectbox(
        "Numerator",
        options=num_options,
        key="map_custom_ratio_num",
        disabled=ratio_disabled,
    )
    ratio_den_options = [col for col in ratio_numeric_candidates if col != ratio_num] if has_two_numeric else ["-"]
    ratio_den = st.selectbox(
        "Denominator",
        options=ratio_den_options,
        key="map_custom_ratio_den",
        disabled=ratio_disabled,
    )
    default_name = f"{ratio_num}_over_{ratio_den}" if has_two_numeric else "custom_ratio"
    ratio_name_input = st.text_input(
        "Ratio name",
        value=default_name,
        key="map_custom_ratio_name",
        disabled=ratio_disabled,
    ).strip()
    if enable_custom_ratio and has_two_numeric:
        custom_ratio_col = ratio_name_input or default_name
        num_series = pd.to_numeric(work_df[ratio_num], errors="coerce")
        den_series = pd.to_numeric(work_df[ratio_den], errors="coerce")
        valid = num_series.notna() & den_series.notna() & (den_series.abs() > 1.0e-12)
        ratio_series = pd.Series(float("nan"), index=work_df.index, dtype=float)
        ratio_series.loc[valid] = num_series.loc[valid] / den_series.loc[valid]
        work_df[custom_ratio_col] = ratio_series
        st.caption(f"Added ratio column: {custom_ratio_col} = {ratio_num} / {ratio_den}")

preferred_candidates = [
    "pl_position",
    "pl_height",
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
    "delta_e2g_a1g",
    "strain_eps_pct",
    "doping_n_1e13_cm2",
    "e2g_a1g_area_ratio",
    "e2g_position",
    "a1g_position",
    "e2g_fwhm",
    "a1g_fwhm",
    "lo_position",
    "zo_position",
    "la_position",
    "lo_fwhm",
    "zo_fwhm",
    "la_fwhm",
    "si_area",
    "rmse",
    "r2",
    "aic",
    "bic",
]
if custom_ratio_col:
    preferred_candidates = [custom_ratio_col, *preferred_candidates]

numeric_cols = [
    col
    for col in work_df.columns
    if pd.api.types.is_numeric_dtype(work_df[col]) and col not in {"map_x", "map_y"}
]
parameter_candidates: list[str] = []
for col in preferred_candidates + numeric_cols:
    if col in work_df.columns and col not in parameter_candidates:
        parameter_candidates.append(col)
if not parameter_candidates:
    st.warning("No plottable parameter columns found in this report.")
    st.stop()

map_options = (
    sorted(work_df["map_id"].dropna().astype(str).unique())
    if "map_id" in work_df.columns
    else ["default_map"]
)
if not map_options:
    st.warning("No map_id values available after filtering.")
    st.stop()

col1, col2 = st.columns([2, 1])
selected_param = col1.selectbox("Color by parameter", parameter_candidates, index=0)
selected_map = col2.selectbox("Map ID", map_options)
status_label = ", ".join(selected_statuses) if "selected_statuses" in locals() else "all"
state_cols = st.columns(3)
state_cols[0].metric("Selected Map", selected_map)
state_cols[1].metric("Color Parameter", selected_param)
state_cols[2].metric("fit_status Filter", status_label)

plot_df = work_df.copy()
if "map_id" in plot_df.columns:
    plot_df = plot_df[plot_df["map_id"].astype(str) == selected_map]
if plot_df.empty:
    st.warning("No rows available for the selected map after filtering.")
    st.stop()

if "fit_status" in plot_df.columns:
    status_counts = plot_df["fit_status"].value_counts()
    s1, s2, s3 = st.columns(3)
    s1.metric("Valid", int(status_counts.get("valid", 0)))
    s2.metric("Attention", int(status_counts.get("attention", 0)))
    s3.metric("Invalid", int(status_counts.get("invalid", 0)))

st.subheader(f"Map Heatmap: {selected_param}")
required_top_heatmap = {"map_x", "map_y", selected_param}
if required_top_heatmap.issubset(plot_df.columns):
    top_df = plot_df.copy()
    top_df[selected_param] = pd.to_numeric(top_df[selected_param], errors="coerce")
    pivot_top = (
        top_df.pivot_table(index="map_y", columns="map_x", values=selected_param, aggfunc="mean")
        .sort_index(ascending=True)
        .sort_index(axis=1, ascending=True)
    )
    if pivot_top.empty:
        st.info("Pivot table is empty for selected map/parameter.")
    else:
        z_series = pd.Series(pivot_top.to_numpy().ravel()).dropna()
        if z_series.empty:
            st.info("No finite values available for heatmap scaling.")
        else:
            z_min_full = float(z_series.min())
            z_max_full = float(z_series.max())
            z_min_robust = float(z_series.quantile(0.02))
            z_max_robust = float(z_series.quantile(0.98))
            if z_min_robust >= z_max_robust:
                z_min_robust, z_max_robust = z_min_full, z_max_full

            scale_mode = st.radio(
                "Color scale range",
                options=["Auto (full range)", "Auto (robust 2-98%)", "Manual"],
                horizontal=True,
                key=f"map_heat_scale_mode::{selected_map}::{selected_param}",
            )

            zmin: float | None = None
            zmax: float | None = None
            manual_scale = scale_mode == "Manual"
            c1, c2 = st.columns(2)
            manual_zmin = c1.number_input(
                "Color min",
                value=float(z_min_robust),
                format="%.6f",
                key=f"map_heat_zmin::{selected_map}::{selected_param}",
                disabled=not manual_scale,
            )
            manual_zmax = c2.number_input(
                "Color max",
                value=float(z_max_robust),
                format="%.6f",
                key=f"map_heat_zmax::{selected_map}::{selected_param}",
                disabled=not manual_scale,
            )
            if scale_mode == "Auto (robust 2-98%)":
                zmin, zmax = z_min_robust, z_max_robust
            elif manual_scale:
                if manual_zmin < manual_zmax:
                    zmin, zmax = manual_zmin, manual_zmax
                else:
                    st.warning("Color min must be smaller than color max. Reverting to auto full range.")
                    zmin, zmax = z_min_full, z_max_full

            clipped_low = int((z_series < zmin).sum()) if zmin is not None else 0
            clipped_high = int((z_series > zmax).sum()) if zmax is not None else 0

            fig_top = px.imshow(
                pivot_top,
                origin="lower",
                aspect="equal",
                color_continuous_scale=SEQUENTIAL,
                zmin=zmin,
                zmax=zmax,
                labels={
                    "x": "X (point index)",
                    "y": "Y (point index)",
                    "color": default_colorbar_title(selected_param, modality),
                },
                title=f"{selected_map}: {selected_param}",
            )
            fig_top.update_xaxes(constrain="domain")
            fig_top.update_yaxes(scaleanchor="x", scaleratio=1.0)
            show(fig_top, "map_parameter", filename=f"{selected_map}_{selected_param}")
            if zmin is not None and zmax is not None:
                st.caption(
                    f"Color scale fixed to [{zmin:.4f}, {zmax:.4f}] "
                    f"(clipped low: {clipped_low}, clipped high: {clipped_high})"
                )
else:
    st.info("Need map_x/map_y and selected parameter to draw heatmap.")

with st.expander("Fit Status Map", expanded=True):
    required_status = {"map_x", "map_y", "fit_status"}
    if required_status.issubset(plot_df.columns):
        status_df = plot_df.dropna(subset=["map_x", "map_y", "fit_status"]).copy()
        if status_df.empty:
            st.info("No valid points for fit_status map.")
        else:
            fig_status = px.scatter(
                status_df,
                x="map_x",
                y="map_y",
                color="fit_status",
                category_orders={"fit_status": status_options},
                color_discrete_map=STATUS_COLORS,
                labels={"map_x": "X (point index)", "map_y": "Y (point index)"},
                hover_data=["spectrum_id", "selected_model"] if "selected_model" in status_df.columns else ["spectrum_id"],
                title="Spatial distribution of fit_status",
            )
            fig_status.update_traces(marker={"size": MARKER_MAP, "line": {"width": OUTLINE_THIN, "color": INK}})
            fig_status.update_layout(legend_title="fit_status", legend=LEGEND_RIGHT)  # the map fills the plot area
            fig_status.update_xaxes(constrain="domain")
            fig_status.update_yaxes(scaleanchor="x", scaleratio=1.0)
            show(fig_status, "map_status", filename=f"{selected_map}_fit_status")
    else:
        st.info("Need map_x/map_y/fit_status columns to draw status map.")

st.subheader("Map Rows")
preview_cols = [
    c
    for c in [
        "spectrum_id",
        "map_x",
        "map_y",
        "selected_model",
        "fit_status",
        selected_param,
        "rmse",
        "r2",
        "attention_reasons",
        "invalid_reasons",
    ]
    if c in plot_df.columns
]
st.dataframe(plot_df[preview_cols], width="stretch", height=320)

with st.expander("Map Summary", expanded=False):
    st.dataframe(pd.DataFrame(payload.get("map_summary", [])), width="stretch")


