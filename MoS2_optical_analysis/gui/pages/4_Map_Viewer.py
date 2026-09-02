"""Page for map-level parameter and quality visualization."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from fitting.mos2_core.core.runtime_paths import runtime_project_root  # noqa: E402

ROOT = runtime_project_root(__file__, 2)
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from gui.components.report_loader import choose_report_sidebar, sidebar_filters_header  # noqa: E402
from gui.components.plot_theme import apply_plotly_theme  # noqa: E402


apply_plotly_theme()


def _add_derived_map_parameters(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    required = {"e2g_area", "a1g_area"}
    if required.issubset(out.columns):
        e2g_area = pd.to_numeric(out["e2g_area"], errors="coerce")
        a1g_area = pd.to_numeric(out["a1g_area"], errors="coerce")
        valid = e2g_area.notna() & a1g_area.notna() & (a1g_area != 0.0)
        ratio = pd.Series(float("nan"), index=out.index, dtype=float)
        ratio.loc[valid] = e2g_area.loc[valid] / a1g_area.loc[valid]
        out["e2g_a1g_area_ratio"] = ratio
    return out


st.title("Map Viewer")
st.caption("Spatial view of Raman fit parameters across measurement points.")

report_path, payload, df = choose_report_sidebar("map_viewer")
if report_path is None or payload is None:
    st.stop()
if df.empty:
    st.warning("This report has no spectra rows.")
    st.stop()

work_df = _add_derived_map_parameters(df)
status_options = ["valid", "attention", "invalid"]
sidebar_filters_header()
if "fit_status" in work_df.columns:
    work_df["fit_status"] = work_df["fit_status"].astype(str).str.strip().str.lower()
    available_statuses = set(work_df["fit_status"].dropna().tolist())
    default_statuses = [s for s in ["valid", "attention"] if s in available_statuses]
    if not default_statuses:
        default_statuses = [s for s in status_options if s in available_statuses] or ["valid", "attention"]
    selected_statuses = st.sidebar.multiselect(
        "Allowed fit_status values",
        options=status_options,
        default=default_statuses,
        key="map_viewer_status_filter",
    )
    if not selected_statuses:
        st.info("Select at least one fit_status value.")
        st.stop()
    work_df = work_df[work_df["fit_status"].isin(selected_statuses)]
else:
    st.sidebar.caption("fit_status column not found: status filter disabled.")

if work_df.empty:
    st.warning("No rows left after fit_status filter.")
    st.stop()

custom_ratio_col: str | None = None
ratio_numeric_candidates = [
    col
    for col in work_df.columns
    if pd.api.types.is_numeric_dtype(work_df[col]) and col not in {"map_x", "map_y"}
]
with st.sidebar.expander("3) Ratio Builder", expanded=False):
    enable_custom_ratio = st.checkbox(
        "Enable custom ratio (numerator / denominator)",
        value=False,
        key="map_custom_ratio_enable",
    )
    if enable_custom_ratio:
        if len(ratio_numeric_candidates) < 2:
            st.warning("Need at least two numeric columns for ratio.")
        else:
            ratio_num = st.selectbox(
                "Numerator",
                options=ratio_numeric_candidates,
                key="map_custom_ratio_num",
            )
            ratio_den_options = [col for col in ratio_numeric_candidates if col != ratio_num]
            ratio_den = st.selectbox(
                "Denominator",
                options=ratio_den_options,
                key="map_custom_ratio_den",
            )
            default_name = f"{ratio_num}_over_{ratio_den}"
            ratio_name_input = st.text_input(
                "Ratio name",
                value=default_name,
                key="map_custom_ratio_name",
            ).strip()
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
    "delta_e2g_a1g",
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
            if scale_mode == "Auto (robust 2-98%)":
                zmin, zmax = z_min_robust, z_max_robust
            elif scale_mode == "Manual":
                c1, c2 = st.columns(2)
                zmin = c1.number_input(
                    "Color min",
                    value=float(z_min_robust),
                    format="%.6f",
                    key=f"map_heat_zmin::{selected_map}::{selected_param}",
                )
                zmax = c2.number_input(
                    "Color max",
                    value=float(z_max_robust),
                    format="%.6f",
                    key=f"map_heat_zmax::{selected_map}::{selected_param}",
                )
                if zmin >= zmax:
                    st.warning("Color min must be smaller than color max. Reverting to auto full range.")
                    zmin, zmax = z_min_full, z_max_full

            clipped_low = int((z_series < zmin).sum()) if zmin is not None else 0
            clipped_high = int((z_series > zmax).sum()) if zmax is not None else 0

            fig_top = px.imshow(
                pivot_top,
                origin="lower",
                aspect="equal",
                color_continuous_scale="Viridis",
                zmin=zmin,
                zmax=zmax,
                labels={"x": "map_x", "y": "map_y", "color": selected_param},
                title=f"{selected_map}: {selected_param}",
            )
            fig_top.update_layout(height=720)
            fig_top.update_xaxes(constrain="domain")
            fig_top.update_yaxes(scaleanchor="x", scaleratio=1.0)
            st.plotly_chart(fig_top, width="stretch", theme=None)
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
                hover_data=["spectrum_id", "selected_model"] if "selected_model" in status_df.columns else ["spectrum_id"],
                title="Spatial distribution of fit_status",
            )
            fig_status.update_traces(marker={"size": 14, "line": {"width": 0.5, "color": "black"}})
            fig_status.update_layout(yaxis={"autorange": "reversed"}, legend_title="fit_status")
            st.plotly_chart(fig_status, width="stretch", theme=None)
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


