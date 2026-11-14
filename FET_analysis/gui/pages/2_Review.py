"""Review: sweeps that need attention, with a decision for each."""

from __future__ import annotations

import sys
from pathlib import Path

_FET_ROOT = Path(__file__).resolve().parents[2]
for _path in (_FET_ROOT, _FET_ROOT.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from fet_core.analysis.results import REASONS  # noqa: E402
from fet_core.pipeline import ordered_groups  # noqa: E402
from fet_core.review import DECISIONS  # noqa: E402
from gui.state import active, filters, put_review, stop_if_empty  # noqa: E402

st.set_page_config(page_title="Review · FET Analysis", layout="wide")
st.title("Review")
st.caption("Automatic results are never changed. A decision is stored in review.json: rejected sweeps stay in the tables but leave the statistics.")

batch, run, review, frame = active()

cols = st.columns(4)
cols[0].metric("Need attention", int((frame["status"] == "attention").sum()))
cols[1].metric("Invalid", int((frame["status"] == "invalid").sum()))
cols[2].metric("Approved", int((frame["decision"] == "approved").sum()))
cols[3].metric("Rejected", int((frame["decision"] == "rejected").sum()))

shown = filters(frame, ordered_groups(frame, review), default_statuses=("attention", "invalid"))
stop_if_empty(shown)

columns = [
    "group_display",
    "label",
    "run_id",
    "sweep",
    "status",
    "reasons",
    "decision",
    "note",
    "vth_linear_V",
    "ss_mV_per_dec",
    "mobility_cm2_per_Vs",
    "on_off_decades",
    "gm_relative_error",
    "source_file",
]
table = shown[columns].reset_index(drop=True)
edited = st.data_editor(
    table,
    hide_index=True,
    width="stretch",
    height=min(620, 60 + 35 * len(table)),
    disabled=[c for c in columns if c not in ("decision", "note")],
    column_config={
        "group_display": "group",
        "decision": st.column_config.SelectboxColumn("decision", options=list(DECISIONS), required=True),
        "note": st.column_config.TextColumn("note"),
        "vth_linear_V": st.column_config.NumberColumn("Vth (V)", format="%.2f"),
        "ss_mV_per_dec": st.column_config.NumberColumn("SS (mV/dec)", format="%.0f"),
        "mobility_cm2_per_Vs": st.column_config.NumberColumn("mobility (cm²/Vs)", format="%.3g"),
        "on_off_decades": st.column_config.NumberColumn("log10(on/off)", format="%.2f"),
        "gm_relative_error": st.column_config.NumberColumn("gm error", format="%.3f"),
    },
    key=f"fet_review_editor_{batch}",
)

changed = (edited["decision"] != table["decision"]) | (edited["note"].fillna("") != table["note"].fillna(""))
left, right = st.columns([1, 4])
if left.button(f"Save {int(changed.sum())} change(s)", type="primary", disabled=not changed.any(), key="fet_review_save", width="stretch"):
    for row in edited[changed].to_dict("records"):
        review.set_decision(row["source_file"], row["run_id"], row["sweep"], row["decision"], row["note"] or "")
    put_review(batch, review)
    st.rerun()
right.caption("auto: follow the automatic status · approved: checked and kept · rejected: left out of the statistics")

with st.expander("What the reasons mean", expanded=False):
    st.dataframe(
        pd.DataFrame(
            [{"reason": code, "level": "note" if status == "valid" else status, "meaning": message} for code, (status, message) in REASONS.items()]
        ),
        hide_index=True,
        width="stretch",
    )
