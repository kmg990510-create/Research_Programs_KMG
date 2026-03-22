"""Page for comparing ensemble model fits."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from gui.components.fit_plot_component import render_metric_histogram  # noqa: E402
from gui.components.plot_theme import apply_plotly_theme  # noqa: E402
from gui.components.report_loader import choose_report_sidebar, sidebar_filters_header  # noqa: E402

apply_plotly_theme()


st.title("Model Comparison")
st.caption("Compare quality metrics across selected fit models.")

report_path, payload, df = choose_report_sidebar("model_cmp")
if report_path is None or payload is None:
    st.stop()
if df.empty:
    st.warning("This report has no spectra rows.")
    st.stop()
if "selected_model" not in df.columns:
    st.warning("`selected_model` column not present in this report.")
    st.stop()

work_df = df.copy()
if "fit_status" in work_df.columns:
    sidebar_filters_header()
    status_options = ["valid", "attention", "invalid"]
    work_df["fit_status"] = work_df["fit_status"].astype(str).str.strip().str.lower()
    available = [item for item in status_options if item in set(work_df["fit_status"].dropna().tolist())]
    default_statuses = [item for item in ["valid", "attention"] if item in available] or available
    selected_statuses = st.sidebar.multiselect(
        "Allowed fit_status values",
        options=status_options,
        default=default_statuses,
        key="model_cmp_status_filter",
    )
    if selected_statuses:
        work_df = work_df[work_df["fit_status"].isin(selected_statuses)]
if work_df.empty:
    st.warning("No rows left after filters.")
    st.stop()

st.subheader("Selected Model Distribution")
model_counts = work_df["selected_model"].value_counts().rename_axis("model").reset_index(name="count")
fig_counts = px.bar(model_counts, x="model", y="count", title="Model usage")
st.plotly_chart(fig_counts, width="stretch")

metric_cols = [c for c in ["rmse", "r2", "aic", "bic"] if c in work_df.columns]
if metric_cols:
    selected_metric = st.selectbox("Metric for boxplot", metric_cols, index=0)
    fig_box = px.box(work_df, x="selected_model", y=selected_metric, points="outliers", title=f"{selected_metric} by model")
    st.plotly_chart(fig_box, width="stretch")

    render_metric_histogram(work_df, selected_metric, title=f"{selected_metric} histogram")

if metric_cols:
    grouped = work_df.groupby("selected_model")[metric_cols].agg(["mean", "median", "std"]).round(4)
    grouped.columns = [f"{a}_{b}" for a, b in grouped.columns]
    st.subheader("Metric Summary by Model")
    st.dataframe(grouped.reset_index(), width="stretch")
else:
    st.info("No metric columns found for model comparison.")


