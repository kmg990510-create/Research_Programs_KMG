"""Main entry point for Streamlit review application."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from fitting.mos2_core.core.runtime_paths import runtime_project_root  # noqa: E402

ROOT = runtime_project_root(__file__, 1)
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from gui.components.report_loader import choose_report_sidebar, paired_csv_path  # noqa: E402


st.set_page_config(
    page_title="MoS2 Raman Review",
    page_icon=":microscope:",
    layout="wide",
)

st.title("MoS2 Raman/PL Analysis Viewer")
st.caption("Pipeline output browser for fit results, model quality, and map-wise summaries.")

report_path, payload, spectra_df = choose_report_sidebar("home")
if report_path is None or payload is None:
    st.stop()

counts = payload.get("counts", {})
metric_cols = st.columns(6)
metric_cols[0].metric("QC Total", int(counts.get("qc_total", 0)))
metric_cols[1].metric("Accepted", int(counts.get("accepted", 0)))
metric_cols[2].metric("Flagged", int(counts.get("flagged", 0)))
metric_cols[3].metric("Maps", int(counts.get("maps", 0)))
metric_cols[4].metric("Fit Failures", int(payload.get("fit_failure_count", 0)))
metric_cols[5].metric("Rows", int(len(spectra_df)))

left, right = st.columns([2, 1])
with left:
    st.subheader("Map Summary")
    map_summary = payload.get("map_summary", [])
    st.dataframe(pd.DataFrame(map_summary), width="stretch", height=240)

    st.subheader("Preview: Spectra Fit Results")
    preview_cols = [
        c
        for c in [
            "spectrum_id",
            "selected_model",
            "e2g_position",
            "a1g_position",
            "delta_e2g_a1g",
            "rmse",
            "r2",
            "aic",
            "bic",
        ]
        if c in spectra_df.columns
    ]
    st.dataframe(spectra_df[preview_cols].head(30), width="stretch", height=360)

with right:
    st.subheader("Active Artifacts")
    st.caption("A single selected run is represented by a JSON report and its paired CSV.")
    st.markdown("`JSON report`")
    st.code(str(report_path), language="text")
    csv_path = paired_csv_path(report_path)
    if csv_path.exists():
        st.markdown("`Paired CSV`")
        st.code(str(csv_path), language="text")
        st.download_button(
            "Download Parameters CSV",
            data=csv_path.read_bytes(),
            file_name=csv_path.name,
            mime="text/csv",
            width="stretch",
        )

    with st.expander("Configuration Snapshot (advanced)", expanded=False):
        st.json(payload.get("config", {}))

st.subheader("Next Steps")
nav_cols = st.columns(4)
nav_cols[0].page_link("pages/1_Run_Analysis.py", label="Run Analysis")
nav_cols[1].page_link("pages/2_All_Spectra_Viewer.py", label="All Spectra")
nav_cols[2].page_link("pages/3_Flagged_Spectra.py", label="Flagged")
nav_cols[3].page_link("pages/7_Finalize.py", label="Finalize")


