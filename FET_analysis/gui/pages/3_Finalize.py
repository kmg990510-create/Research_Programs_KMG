"""Finalize: write the result files and download them."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

_FET_ROOT = Path(__file__).resolve().parents[2]
for _path in (_FET_ROOT, _FET_ROOT.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from fet_core.pipeline import ordered_groups, status_counts  # noqa: E402
from fet_core.report.export import export_run  # noqa: E402
from fet_core.report.summary import group_summary  # noqa: E402
from gui.state import REVIEW_FILE, active, results_root  # noqa: E402

st.set_page_config(page_title="Finalize · FET Analysis", layout="wide")
st.title("Finalize")
st.caption("Writes the tables and run_metadata.json for this batch. The review (geometry, decisions, group names) is recorded in the metadata.")

batch, run, review, frame = active()
counts = status_counts(frame)
output_dir = results_root() / batch

cols = st.columns(5)
cols[0].metric("Sweeps", len(frame))
cols[1].metric("In statistics", int(frame["included"].sum()))
cols[2].metric("Rejected", int((frame["decision"] == "rejected").sum()))
cols[3].metric("Invalid", counts["invalid"])
cols[4].metric("Still need attention", int(((frame["status"] == "attention") & (frame["decision"] == "auto")).sum()))

open_items = frame[(frame["status"] == "attention") & (frame["decision"] == "auto")]
if not open_items.empty:
    st.warning(f"{len(open_items)} sweep(s) need attention and have no decision yet. They are exported and counted in the statistics as they are.")

st.subheader("Group summary")
summary = group_summary(frame, ordered_groups(frame, review))
st.dataframe(
    summary[["group", "sweep", "n_sweeps", "n_included", "mobility_cm2_per_Vs_median", "vth_linear_V_median", "ss_mV_per_dec_median", "on_off_decades_median"]],
    hide_index=True,
    width="stretch",
)

st.subheader("Result files")
if st.button("Write result files", type="primary", key="fet_finalize_export"):
    files = export_run(run, review, output_dir)
    st.session_state["fet_finalize_written"] = (batch, len(files))
written = st.session_state.get("fet_finalize_written")
if written and written[0] == batch:
    st.success(f"Wrote {written[1]} file(s) to {output_dir}")

existing = sorted(p for p in output_dir.rglob("*") if p.is_file()) if output_dir.is_dir() else []
exported = [p for p in existing if p.name != REVIEW_FILE]
if exported:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "file": p.relative_to(output_dir).as_posix(),
                    "size (kB)": round(p.stat().st_size / 1024, 1),
                    "written": pd.Timestamp(p.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S"),
                }
                for p in exported
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in existing:  # review.json travels with the results
            archive.write(path, f"{batch}/{path.relative_to(output_dir).as_posix()}")
    st.download_button("Download all as zip", data=buffer.getvalue(), file_name=f"{batch}_results.zip", mime="application/zip", key="fet_finalize_zip")
else:
    st.info("No result files yet for this batch.")
