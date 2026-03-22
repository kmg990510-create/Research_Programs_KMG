"""Page for final approval and export actions."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from gui.components.report_loader import choose_report_sidebar, paired_csv_path  # noqa: E402


st.title("Finalize")
st.caption("Freeze review decisions and export final artifacts.")
st.info("Use this page as the final handoff step after review is complete.")

report_path, payload, df = choose_report_sidebar("finalize")
if report_path is None or payload is None:
    st.stop()

counts = payload.get("counts", {})
col1, col2, col3 = st.columns(3)
col1.metric("Accepted", int(counts.get("accepted", 0)))
col2.metric("Flagged", int(counts.get("flagged", 0)))
col3.metric("Fit Failures", int(payload.get("fit_failure_count", 0)))

st.subheader("Export")
json_bytes = report_path.read_bytes()
csv_path = paired_csv_path(report_path)

st.download_button(
    "Download Final JSON Report",
    data=json_bytes,
    file_name=report_path.name,
    mime="application/json",
    width="stretch",
)

if csv_path.exists():
    st.download_button(
        "Download Final CSV Parameters",
        data=csv_path.read_bytes(),
        file_name=csv_path.name,
        mime="text/csv",
        width="stretch",
    )
else:
    st.info("Paired CSV file not found.")

st.subheader("Finalize Manifest")
reviewer = st.text_input("Reviewer ID", value="reviewer_1")
notes = st.text_area("Finalize notes", value="")
check_cols = st.columns(3)
check_cols[0].checkbox("Report selected", value=(report_path is not None), disabled=True)
check_cols[1].checkbox("Rows available", value=(df is not None and not df.empty), disabled=True)
check_cols[2].checkbox("Counts loaded", value=bool(counts), disabled=True)

if st.button("Write finalize manifest", type="primary"):
    manifest = {
        "run_id": payload.get("run_id"),
        "reviewer_id": reviewer,
        "notes": notes,
        "accepted_count": counts.get("accepted"),
        "flagged_count": counts.get("flagged"),
        "fit_failure_count": payload.get("fit_failure_count", 0),
        "report_json": str(report_path),
        "report_csv": str(csv_path) if csv_path.exists() else None,
        "finalized_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    out_path = report_path.with_name(f"{payload.get('run_id', 'run')}_finalized.json")
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    st.success(f"Manifest written: {out_path}")
    st.code(str(out_path), language="text")
    st.download_button(
        "Download Finalize Manifest",
        data=out_path.read_bytes(),
        file_name=out_path.name,
        mime="application/json",
        width="stretch",
    )


