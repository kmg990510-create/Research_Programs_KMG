"""Run (entry page): choose or upload a batch, set device geometry and method options."""

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
from fet_core.pipeline import effective_geometry, results_frame, status_counts  # noqa: E402
from fet_core.report.export import warnings_frame  # noqa: E402
from fet_core.review import GEOMETRY_FIELDS, run_key  # noqa: E402
from fet_gui.state import (  # noqa: E402
    ACTIVE_BATCH_KEY,
    choose_batch,
    get_review,
    load_run,
    put_review,
    raw_root,
    render_fet_chrome,
    safe_batch_name,
)
from labkit.chrome import panel_title  # noqa: E402

render_fet_chrome("Run", "FET Analysis · Run")
batch = choose_batch()

st.header("Run")
st.caption(
    f"FET Analysis {__version__} · One folder under data/raw is one batch. The analysis runs when a batch is chosen or its settings change."
)

with st.expander("Add measurement files", expanded=batch is None):
    uploaded = st.file_uploader(
        "Keysight B1500 .csv or Keithley 4200A (Clarius) .xls",
        type=["csv", "xls"],
        accept_multiple_files=True,
        key="fet_run_uploader",
    )
    name = st.text_input("Batch name", value=batch or "", key="fet_run_batch_name", help="Files are saved to data/raw/<batch name>.")
    if st.button("Save files to the batch", disabled=not uploaded, key="fet_run_save_files"):
        clean = safe_batch_name(name)
        if not clean:
            st.error("Enter a batch name.")
        else:
            folder = raw_root() / clean
            folder.mkdir(parents=True, exist_ok=True)
            for item in uploaded:
                (folder / Path(item.name).name).write_bytes(item.getvalue())
            st.session_state[ACTIVE_BATCH_KEY] = clean
            st.toast(f"Saved {len(uploaded)} file(s) to {clean}")
            st.rerun()

if batch is None:
    st.info("No batch yet. Add measurement files above.")
    st.stop()

review = get_review(batch)
run = load_run(batch, review)
frame = results_frame(run, review)
counts = status_counts(frame)

cols = st.columns(5)
cols[0].metric("Files read", f"{sum(f.status == 'read' for f in run.loaded.files)} / {len(run.loaded.files)}")
cols[1].metric("Measurements", len(run.loaded.measurements))
cols[2].metric("Valid sweeps", counts["valid"])
cols[3].metric("Need attention", counts["attention"])
cols[4].metric("Invalid", counts["invalid"])

with st.container(border=True):
    panel_title("Device geometry and method")
    geometry = effective_geometry(run.config, review)
    with st.form("fet_run_settings"):
        g1, g2, g3, g4 = st.columns(4)
        width = g1.number_input("Channel width W (µm)", min_value=0.001, value=float(geometry.W_um), format="%.3f")
        length = g2.number_input("Channel length L (µm)", min_value=0.001, value=float(geometry.L_um), format="%.3f")
        thickness = g3.number_input("Gate dielectric thickness (nm)", min_value=0.001, value=float(geometry.t_ox_nm), format="%.2f")
        permittivity = g4.number_input("Relative permittivity", min_value=0.001, value=float(geometry.eps_r), format="%.2f")
        with st.expander("Advanced", expanded=False):
            a1, a2 = st.columns(2)
            half_vds = a1.checkbox(
                "Subtract Vds/2 from the linear-extrapolation Vth",
                value=run.settings.vth_subtract_half_vds,
                help="Linear-regime correction. The method name is recorded with every result.",
            )
            level = a2.number_input(
                "Constant-current Vth level (nA per µm of width)",
                min_value=0.0001,
                value=float(run.settings.vth_const_current_nA_per_um),
                format="%.4f",
            )
        b1, b2, _ = st.columns([1, 1, 3])
        apply = b1.form_submit_button("Apply", type="primary", width="stretch")
        reset = b2.form_submit_button("Reset to config.yaml", width="stretch")
    if apply:
        review.geometry = {"W_um": width, "L_um": length, "t_ox_nm": thickness, "eps_r": permittivity}
        review.vth_subtract_half_vds = bool(half_vds)
        review.vth_const_current_nA_per_um = float(level)
        put_review(batch, review)
        st.rerun()
    if reset:
        review.geometry = None
        review.vth_subtract_half_vds = None
        review.vth_const_current_nA_per_um = None
        put_review(batch, review)
        st.rerun()
    source = "set for this batch" if review.geometry else "from config.yaml"
    st.caption(f"Batch default: W {geometry.W_um:g} µm, L {geometry.L_um:g} µm, t_ox {geometry.t_ox_nm:g} nm, eps_r {geometry.eps_r:g} ({source}).")

with st.expander("Per-device geometry (optional)", expanded=bool(review.geometry_overrides)):
    st.caption("Fill all four values for a device that differs from the batch default. Empty rows use the batch default.")
    table = pd.DataFrame(
        [
            {
                "label": m.label,
                "run_id": m.run_id,
                "source_file": m.source_file.name,
                **{name: review.geometry_overrides.get(run_key(m.source_file.name, m.run_id), {}).get(name) for name in GEOMETRY_FIELDS},
            }
            for m in run.loaded.measurements
        ]
    )
    edited = st.data_editor(
        table,
        hide_index=True,
        width="stretch",
        disabled=["label", "run_id", "source_file"],
        column_config={name: st.column_config.NumberColumn(name, min_value=0.0) for name in GEOMETRY_FIELDS},
        key="fet_run_device_geometry",
    )
    if st.button("Save per-device geometry", key="fet_run_save_device_geometry"):
        overrides: dict[str, dict[str, float]] = {}
        partial: list[str] = []
        for row in edited.to_dict("records"):
            values = {name: row[name] for name in GEOMETRY_FIELDS}
            filled = [v for v in values.values() if pd.notna(v)]
            if len(filled) == len(GEOMETRY_FIELDS) and all(v > 0 for v in filled):
                overrides[run_key(row["source_file"], row["run_id"])] = {k: float(v) for k, v in values.items()}
            elif filled:
                partial.append(str(row["label"]))
        if partial:
            st.error(f"Fill all four positive values or none: {', '.join(partial)}")
        else:
            review.geometry_overrides = overrides
            put_review(batch, review)
            st.rerun()

with st.container(border=True):
    panel_title("Files")
    st.dataframe(
        pd.DataFrame(
            [{"file": f.path.name, "reader": f.reader or "-", "status": f.status, "measurements": f.measurement_count, "reason": f.reason} for f in run.loaded.files]
        ),
        hide_index=True,
        width="stretch",
    )

warnings = warnings_frame(run)
with st.expander(f"Warnings ({len(warnings)})", expanded=False):
    st.dataframe(warnings, hide_index=True, width="stretch")
