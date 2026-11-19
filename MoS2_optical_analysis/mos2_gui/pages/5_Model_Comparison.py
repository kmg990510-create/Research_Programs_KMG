"""Page for comparing ensemble model fits."""

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

from labkit.chrome import panel_title  # noqa: E402
from mos2_gui.components.chrome import render_mos2_chrome  # noqa: E402
from mos2_gui.components.figure_sizes import figure_settings_popover, show  # noqa: E402
from mos2_gui.components.fit_plot_component import render_metric_histogram  # noqa: E402
from mos2_gui.components.map_figure import default_colorbar_title  # noqa: E402
from mos2_gui.components.report_loader import choose_report_sidebar, render_status_rejected_filters  # noqa: E402

render_mos2_chrome("Compare", "Model Comparison · MoS2 Optical Analysis", compare_sub="Models")
report_path, payload, df = choose_report_sidebar("model_cmp")

if report_path is None or payload is None:
    st.header("Model Comparison")
    st.stop()
if df.empty:
    st.header("Model Comparison")
    st.warning("This report has no spectra rows.")
    st.stop()
if "selected_model" not in df.columns:
    st.header("Model Comparison")
    st.warning("`selected_model` column not present in this report.")
    st.stop()

modality = str(payload.get("modality", "")).strip().lower()
if modality not in {"raman", "pl"}:
    modality = "pl" if "pl" in {part.lower() for part in report_path.parts} else "raman"

work_df = df.copy()
_, selected_statuses, hide_rejected = render_status_rejected_filters(work_df, key_prefix="model_cmp")
if hide_rejected and "review_decision" in work_df.columns:
    work_df = work_df[work_df["review_decision"].astype(str).str.strip().str.lower() != "rejected"]
if "fit_status" in work_df.columns:
    work_df["fit_status"] = work_df["fit_status"].astype(str).str.strip().str.lower()
    work_df = work_df[work_df["fit_status"].isin(selected_statuses)]

h_left, h_right = st.columns([4, 1], vertical_alignment="bottom")
h_left.header("Model Comparison")
h_left.caption(f"Compare quality metrics across selected fit models · {len(work_df)} of {len(df)} rows shown.")
figure_settings_popover(["model_charts"], container=h_right)

if work_df.empty:
    st.warning("No rows left after filters.")
    st.stop()

with st.container(border=True):
    panel_title("Selected Model Distribution")
    model_counts = work_df["selected_model"].value_counts().rename_axis("model").reset_index(name="count")
    fig_counts = px.bar(
        model_counts,
        x="model",
        y="count",
        labels={"model": "Model", "count": "Spectra (count)"},
        title="Model usage",
    )
    show(fig_counts, "model_charts", filename="model_usage", key="model_cmp_counts")

metric_cols = [
    c
    for c in [
        "rmse",
        "r2",
        "aic",
        "bic",
        "pl_position",
        "pl_fwhm",
        "a_minus_position",
        "a0_position",
        "a_minus_a0_energy_split",
        "a_minus_a0_area_ratio",
        "a0_fraction_of_a_total",
        "b_to_a_total_area_ratio",
        "defect_to_a_total_area_ratio",
        "delta_e2g_a1g",
        "e2g_position",
        "a1g_position",
        "e2g_fwhm",
        "a1g_fwhm",
    ]
    if c in work_df.columns and pd.to_numeric(work_df[c], errors="coerce").notna().any()
]
if metric_cols:
    selected_metric = st.selectbox("Metric for boxplot & histogram", metric_cols, index=0)
    metric_label = default_colorbar_title(selected_metric, modality)
    c1, c2 = st.columns(2, gap="medium")
    with c1, st.container(border=True):
        panel_title(f"{selected_metric} by model")
        fig_box = px.box(
            work_df,
            x="selected_model",
            y=selected_metric,
            points="outliers",
            labels={"selected_model": "Model", selected_metric: metric_label},
            title=f"{selected_metric} by model",
        )
        show(fig_box, "model_charts", filename=f"{selected_metric}_by_model", key="model_cmp_box")
    with c2, st.container(border=True):
        panel_title(f"{selected_metric} histogram")
        render_metric_histogram(work_df, selected_metric, title=f"{selected_metric} histogram", x_label=metric_label)

    grouped = work_df.groupby("selected_model")[metric_cols].agg(["mean", "median", "std"]).round(4)
    grouped.columns = [f"{a}_{b}" for a, b in grouped.columns]
    with st.container(border=True):
        panel_title("Metric Summary by Model")
        st.dataframe(grouped.reset_index(), width="stretch")
else:
    st.info("No metric columns found for model comparison.")
