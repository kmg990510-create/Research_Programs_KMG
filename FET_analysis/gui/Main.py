"""FET analysis: home page."""

from __future__ import annotations

import sys
from pathlib import Path

_FET_ROOT = Path(__file__).resolve().parents[1]
for _path in (_FET_ROOT, _FET_ROOT.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from fet_core import __version__  # noqa: E402
from fet_core.pipeline import results_frame, status_counts  # noqa: E402
from gui.state import choose_batch, get_review, load_run  # noqa: E402

st.set_page_config(page_title="FET Analysis", layout="wide")
st.title("FET Analysis")
st.caption(f"Transfer-curve parameter extraction · version {__version__}")

batch = choose_batch()
if batch is None:
    st.info("Start on the **Run** page: add measurement files to create a batch.")
else:
    review = get_review(batch)
    run = load_run(batch, review)
    frame = results_frame(run, review)
    counts = status_counts(frame)
    cols = st.columns(5)
    cols[0].metric("Batch", batch)
    cols[1].metric("Measurements", len(run.loaded.measurements))
    cols[2].metric("Valid sweeps", counts["valid"])
    cols[3].metric("Need attention", counts["attention"])
    cols[4].metric("Invalid", counts["invalid"])

st.subheader("Pages")
st.dataframe(
    pd.DataFrame(
        [
            ("Run", "Choose or upload a batch, set device geometry and method options."),
            ("Review", "Sweeps that need attention: approve or reject them."),
            ("Device Viewer", "One device at a time: curves with the extracted windows and values."),
            ("Compare", "Groups side by side: overlay, statistics, group names and order."),
            ("Finalize", "Write the result tables and metadata, download them as a zip."),
        ],
        columns=["Page", "What it is for"],
    ),
    hide_index=True,
    width="stretch",
)
