"""Device Viewer: one device at a time, curves with the extracted windows and values."""

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
from fet_core.analysis.sweeps import split_branches  # noqa: E402
from fet_core.pipeline import ordered_groups  # noqa: E402
from fet_core.review import DECISIONS  # noqa: E402
from gui.components.figures import transfer_linear_figure, transfer_log_figure  # noqa: E402
from gui.state import active, filters, put_review, stop_if_empty  # noqa: E402
from labkit.plot_theme import export_config  # noqa: E402
from labkit.sidebar import sidebar_section  # noqa: E402

DEVICE_KEY = "fet_viewer_device"

st.set_page_config(page_title="Device Viewer · FET Analysis", layout="wide")
st.title("Device Viewer")

batch, run, review, frame = active()
shown = filters(frame, ordered_groups(frame, review), default_statuses=("valid", "attention", "invalid"))
stop_if_empty(shown)

devices = shown.drop_duplicates(["source_file", "run_id"])
names = [
    f"{row.group_display} · {row.label}" + (f" · {row.run_id}" if row.run_id not in (row.label, "1") else "")
    for row in devices.itertuples()
]
if st.session_state.get(DEVICE_KEY) not in names:
    st.session_state[DEVICE_KEY] = names[0]


def _step(delta: int) -> None:
    index = names.index(st.session_state[DEVICE_KEY])
    st.session_state[DEVICE_KEY] = names[(index + delta) % len(names)]


with sidebar_section("3) Device"):
    choice = st.selectbox("Device", names, key=DEVICE_KEY)
    previous, following = st.columns(2)
    previous.button("Previous", on_click=_step, args=(-1,), width="stretch", key="fet_viewer_prev")
    following.button("Next", on_click=_step, args=(1,), width="stretch", key="fet_viewer_next")
    st.caption(f"{names.index(choice) + 1} of {len(names)}")

device = devices.iloc[names.index(choice)]
measurement = run.measurement(device["source_file"], device["run_id"])
results = {r.sweep: r for r in run.analysis.results if (r.source_file, r.run_id) == (device["source_file"], device["run_id"])}
branches, _ = split_branches(measurement.data, run.settings)

sweeps = list(results)
sweep = st.radio("Sweep", sweeps, horizontal=True, key="fet_viewer_sweep") if len(sweeps) > 1 else sweeps[0]
result = results[sweep]
row = frame[(frame["source_file"] == result.source_file) & (frame["run_id"] == result.run_id) & (frame["sweep"] == sweep)].iloc[0]

head = st.columns(5)
head[0].metric("Status", result.status)
head[1].metric("Vth, linear (V)", "-" if result.vth_linear_V is None else f"{result.vth_linear_V:.2f}")
head[2].metric("SS (mV/dec)", "-" if result.ss_mV_per_dec is None else f"{result.ss_mV_per_dec:.0f}")
head[3].metric("Mobility (cm²/Vs)", "-" if result.mobility_cm2_per_Vs is None else f"{result.mobility_cm2_per_Vs:.3g}")
head[4].metric("log10(on/off)", "-" if result.on_off_decades is None else f"{result.on_off_decades:.2f}")

file_stem = f"{measurement.label}_{sweep}"
left, right = st.columns(2)
left.plotly_chart(transfer_log_figure(branches, results, sweep), width="stretch", theme=None, config=export_config(f"{file_stem}_log"))
right.plotly_chart(transfer_linear_figure(branches, results, sweep), width="stretch", theme=None, config=export_config(f"{file_stem}_linear"))

if result.reasons:
    for code in result.reasons:
        level, message = REASONS[code]
        (st.error if level == "invalid" else st.warning if level == "attention" else st.info)(f"**{code}** · {message}")

details, decision_box = st.columns([3, 2])
with details:
    st.subheader("Extracted values")
    values = [
        ("Polarity", result.polarity, ""),
        ("Vds", result.vds_V, "V"),
        ("W / L / t_ox / eps_r", f"{result.W_um:g} / {result.L_um:g} / {result.t_ox_nm:g} / {result.eps_r:g}", "µm / µm / nm / -"),
        ("Off current", result.i_off_A, "A"),
        ("Off window", f"{result.i_off_window_start_V} .. {result.i_off_window_end_V}" if result.i_off_A else None, "V"),
        ("Off method", result.i_off_method, ""),
        ("On current", result.i_on_A, "A"),
        ("On current per width", row["i_on_uA_per_um"], "µA/µm"),
        ("Peak gm", result.gm_peak_S, "S"),
        ("gm peak position", result.gm_peak_Vg_V, "V"),
        ("gm relative error", result.gm_relative_error, ""),
        ("Vth, linear extrapolation", result.vth_linear_V, "V"),
        ("Vth method", result.vth_linear_method, ""),
        ("Vth, constant current", result.vth_const_current_V, "V"),
        ("SS", result.ss_mV_per_dec, "mV/dec"),
        ("SS window", f"{result.ss_window_start_V} .. {result.ss_window_end_V}" if result.ss_mV_per_dec else None, "V"),
        ("SS fit R²", result.ss_r2, ""),
        ("Mobility", result.mobility_cm2_per_Vs, "cm²/Vs"),
        ("Hysteresis, linear Vth", result.hysteresis_vth_linear_V, "V"),
        ("Leakage |Ig|/|Id|, transition median", result.leak_transition_median, ""),
        ("Leakage |Ig|/|Id|, on median", result.leak_on_median, ""),
    ]
    st.dataframe(
        pd.DataFrame(
            [
                {"quantity": name, "value": "-" if value is None or (isinstance(value, float) and pd.isna(value)) else (f"{value:.4g}" if isinstance(value, float) else str(value)), "unit": unit}
                for name, value, unit in values
            ]
        ),
        hide_index=True,
        width="stretch",
        height=420,
    )

with decision_box:
    st.subheader("Decision")
    current = review.decision(result.source_file, result.run_id, sweep)
    key_suffix = f"{result.source_file}|{result.run_id}|{sweep}"
    decision = st.radio("Decision for this sweep", list(DECISIONS), index=DECISIONS.index(current), horizontal=True, key=f"fet_viewer_decision_{key_suffix}")
    note = st.text_input("Note", value=row["note"], key=f"fet_viewer_note_{key_suffix}")
    if st.button("Save decision", type="primary", disabled=(decision == current and note == row["note"]), key="fet_viewer_save"):
        review.set_decision(result.source_file, result.run_id, sweep, decision, note)
        put_review(batch, review)
        st.rerun()
    st.caption(f"File: {result.source_file} · run {result.run_id}")
