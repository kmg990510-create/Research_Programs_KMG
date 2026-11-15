"""Finalize: review status check, molecule/Boltzmann summary, Origin CSV export, and zip download."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

_SIM_ROOT = Path(__file__).resolve().parents[2]
for _path in (_SIM_ROOT, _SIM_ROOT.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from ads_core.model import ReportSettings  # noqa: E402
from ads_core.pipeline import ordered_groups, status_counts  # noqa: E402
from ads_core.report.export import export_run  # noqa: E402
from ads_core.report.summary import molecule_summary  # noqa: E402
from ads_gui.state import REVIEW_FILE, active, results_root  # noqa: E402

st.set_page_config(page_title="Finalize · MoS2 Adsorption", layout="wide")
st.title("Finalize")
st.caption("Write Origin-ready CSVs, extended XYZ relaxed structures, and run_metadata.json (including review.json).")

batch, run, review, frame = active()
counts = status_counts(frame)
output_dir = results_root() / batch
temp_K = ReportSettings.from_config(run.config).boltzmann_temp_K

cols = st.columns(5)
cols[0].metric("Poses", len(frame))
cols[1].metric("In statistics", int(frame["included"].sum()))
cols[2].metric("Rejected", int((frame["decision"] == "rejected").sum()))
cols[3].metric("Invalid", counts["invalid"])
open_attention = int(((frame["status"] == "attention") & (frame["decision"] == "auto")).sum())
cols[4].metric("Still need attention", open_attention)

if open_attention > 0:
    st.warning(f"{open_attention} pose(s) still need attention and have no explicit Approve/Reject decision yet.")
else:
    st.success("All attention poses have been reviewed.")

st.subheader("Molecule & Surface Summary")
summary = molecule_summary(frame, temp_K, ordered_groups(frame, review))
if not summary.empty:
    display_cols = [
        "group_display",
        "surface_id",
        "molecule_id",
        "n_poses",
        "n_included",
        "best_site",
        "e_ads_min_eV",
        "e_ads_boltzmann_eV",
        "e_ads_corrugation_eV",
        "vdw_fraction_at_best",
        "d_min_at_best_A",
    ]
    st.dataframe(summary[display_cols], hide_index=True, width="stretch")

st.subheader("Result files")
if st.button("Write result files", type="primary", key="finalize_export_btn"):
    files = export_run(run, review, output_dir)
    st.session_state["finalize_written"] = (batch, len(files))

written = st.session_state.get("finalize_written")
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
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in existing:
            archive.write(path, f"{batch}/{path.relative_to(output_dir).as_posix()}")
    st.download_button(
        "Download all as zip",
        data=buf.getvalue(),
        file_name=f"{batch}_results.zip",
        mime="application/zip",
        key="finalize_zip_btn",
    )
else:
    st.info("No exported result files found yet for this batch.")
