"""Devices: the list of sweeps next to the curves of the selected one, with its decision.

Review and viewer in one place: the row that is selected on the left is drawn on
the right. A decision or a note is saved the moment it is made.
"""

from __future__ import annotations

import sys
from functools import partial
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
from fet_core.review import sweep_key  # noqa: E402
from gui.components.figures import gallery_figure, gallery_size, transfer_linear_figure, transfer_log_figure  # noqa: E402
from gui.components.values import extracted_values  # noqa: E402
from gui.state import active, filters, get_review, put_review, stop_if_empty  # noqa: E402
from labkit.figure_size import FigureSize, figure_options_inputs, figure_size_inputs, show_figure  # noqa: E402
from labkit.sidebar import sidebar_section  # noqa: E402

SELECTED_KEY = "fet_devices_selected"
VIEW_KEY = "fet_devices_view"
NONCE_KEY = "fet_devices_nonce"  # changes the widget keys so a stale table or plot selection is dropped
VIEWS = ("Detail", "Gallery")
STATUS_RANK = {"attention": 0, "invalid": 1, "valid": 2}
STATUS_MARK = {"attention": "⚠", "invalid": "✕", "valid": "✓"}
# Streamlit text colours nearest to labkit.plot_theme.STATUS_COLORS; valid is plain text, as it is black in the figures.
STATUS_TEXT_COLOR = {"attention": "orange", "invalid": "red"}


def _status_text(status: str) -> str:
    return f":{STATUS_TEXT_COLOR[status]}[{status}]" if status in STATUS_TEXT_COLOR else status
GALLERY_COLUMNS = 5
GALLERY_COLUMNS_KEY = "fet_devices_gallery_columns"

st.set_page_config(page_title="Devices · FET Analysis", layout="wide")
st.title("Devices")

batch, run, review, frame = active()
groups = ordered_groups(frame, review)
shown = filters(frame, groups)
with sidebar_section("3) Figure size", expanded=False):
    figure_options_inputs()
    curve_size = figure_size_inputs("fet_curves", "Detail: log and linear curves", 520, 420)
    panel_size = figure_size_inputs("fet_gallery_panel", "Gallery: one panel", 240, 190)
    st.session_state.setdefault(GALLERY_COLUMNS_KEY, GALLERY_COLUMNS)
    gallery_columns = st.number_input("Gallery: panels per row", 1, 12, step=1, key=GALLERY_COLUMNS_KEY)
stop_if_empty(shown)

# sweeps that need a look come first
shown = shown.assign(_rank=shown["status"].map(STATUS_RANK), _group=shown["group_display"].map(groups.index))
shown = shown.sort_values(["_rank", "_group", "label", "run_id", "sweep"], kind="stable").reset_index(drop=True)
keys = [sweep_key(r.source_file, r.run_id, r.sweep) for r in shown.itertuples()]
st.session_state.setdefault(NONCE_KEY, 0)
st.session_state.setdefault(VIEW_KEY, VIEWS[0])
if st.session_state.get(SELECTED_KEY) not in keys:
    st.session_state[SELECTED_KEY] = keys[0]


def _device_name(group: str, label: str) -> str:
    """The label alone when it already starts with the group name."""
    return label if str(label).startswith(str(group)) else f"{group} · {label}"


def _select(key: str, view: str | None = None) -> None:
    st.session_state[SELECTED_KEY] = key
    st.session_state[NONCE_KEY] += 1
    if view:
        st.session_state[VIEW_KEY] = view


def _step(delta: int, all_keys: list[str]) -> None:
    index = all_keys.index(st.session_state[SELECTED_KEY])
    _select(all_keys[(index + delta) % len(all_keys)])


def _table_clicked(widget_key: str, all_keys: list[str]) -> None:
    rows = st.session_state[widget_key]["selection"]["rows"]
    if rows:
        st.session_state[SELECTED_KEY] = all_keys[rows[0]]


def _gallery_clicked(widget_key: str, trace_keys: list[str]) -> None:
    points = st.session_state[widget_key]["selection"]["points"]
    if points:
        _select(trace_keys[points[0]["curve_number"]], view=VIEWS[0])


def _decide(batch_name: str, identity: tuple[str, str, str], decision: str, next_key: str | None) -> None:
    current = get_review(batch_name)
    current.set_decision(*identity, decision)
    put_review(batch_name, current)
    if next_key:
        _select(next_key)


def _save_note(batch_name: str, identity: tuple[str, str, str], widget_key: str) -> None:
    current = get_review(batch_name)
    current.set_decision(*identity, current.decision(*identity), st.session_state[widget_key])
    put_review(batch_name, current)


open_count = int(((shown["status"] == "attention") & (shown["decision"] == "auto")).sum())
top_left, top_right = st.columns([1, 3], vertical_alignment="center")
top_left.radio("View", VIEWS, horizontal=True, key=VIEW_KEY, label_visibility="collapsed")
top_right.caption(
    f"{len(shown)} sweep(s) shown · {open_count} need a decision · "
    f"{int((shown['decision'] == 'approved').sum())} approved · {int((shown['decision'] == 'rejected').sum())} rejected. "
    "Automatic results are never changed; a rejected sweep stays in the tables and leaves the statistics."
)
nonce = st.session_state[NONCE_KEY]

if st.session_state[VIEW_KEY] == "Gallery":
    panels: list[dict] = []
    by_device: dict[tuple[str, str], dict] = {}
    for item, key in zip(shown.itertuples(), keys):
        panel = by_device.get((item.source_file, item.run_id))
        if panel is None:
            panel = {"title": _device_name(item.group_display, item.label), "curves": []}
            by_device[(item.source_file, item.run_id)] = panel
            panels.append(panel)
        branches, _ = split_branches(run.measurement(item.source_file, item.run_id).data, run.settings)
        branch = next((b for b in branches if b.direction == item.sweep), None)
        if branch is not None:
            panel["curves"].append(
                {
                    "key": key,
                    "label": item.sweep,
                    "vg": branch.data["Vg"].to_numpy(),
                    "current": branch.data["Id"].to_numpy(),
                    "status": item.status,
                    "rejected": item.decision == "rejected",
                }
            )
    trace_keys = [curve["key"] for panel in panels for curve in panel["curves"]]
    gallery_key = f"fet_devices_gallery_{nonce}"
    show_figure(
        gallery_figure(panels, gallery_columns),
        FigureSize(*gallery_size(len(panels), gallery_columns, panel_size.width_px, panel_size.height_px)),
        filename=f"{batch}_gallery",
        key=gallery_key,
        on_select=partial(_gallery_clicked, gallery_key, trace_keys),
        selection_mode="points",
    )
    st.caption("Black: valid · orange: needs attention · red: invalid · grey dotted: rejected. Click a panel to open it in the detail view.")
    st.stop()

selected = st.session_state[SELECTED_KEY]
position = keys.index(selected)
row = shown.iloc[position]
identity = (row["source_file"], row["run_id"], row["sweep"])
next_key = keys[(position + 1) % len(keys)] if len(keys) > 1 else None

list_box, detail_box = st.columns([3, 7], gap="medium")

with list_box:
    table = pd.DataFrame(
        {
            "": ["▶" if key == selected else "" for key in keys],
            "status": shown["status"].map(STATUS_MARK),
            "device": [_device_name(r.group_display, r.label) for r in shown.itertuples()],
            "sweep": shown["sweep"],
            "decision": shown["decision"].replace("auto", ""),
            "Vth (V)": shown["vth_linear_V"],
            "µ (cm²/Vs)": shown["mobility_cm2_per_Vs"],
        }
    )
    if shown["sweep"].nunique() == 1:
        table = table.drop(columns="sweep")  # one direction is shown: the column says nothing
    table_key = f"fet_devices_table_{nonce}"
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        height=min(760, 40 + 35 * len(table)),
        column_config={
            "": st.column_config.TextColumn(width=24),
            "status": st.column_config.TextColumn(width=48, help="⚠ needs attention · ✕ invalid · ✓ valid"),
            "decision": st.column_config.TextColumn(width=72),
            "Vth (V)": st.column_config.NumberColumn(format="%.2f", width=64),
            "µ (cm²/Vs)": st.column_config.NumberColumn(format="%.3g", width=72),
        },
        key=table_key,
        on_select=partial(_table_clicked, table_key, keys),
        selection_mode="single-row",
    )
    st.caption("Click a row to show it. ⚠ needs attention · ✕ invalid · ✓ valid; sweeps that need attention are listed first.")

with detail_box:
    result = next(r for r in run.analysis.results if (r.source_file, r.run_id, r.sweep) == identity)
    measurement = run.measurement(result.source_file, result.run_id)
    results = {r.sweep: r for r in run.analysis.results if (r.source_file, r.run_id) == identity[:2]}
    branches, _ = split_branches(measurement.data, run.settings)

    title, previous, following = st.columns([6, 1, 1], vertical_alignment="center")
    run_part = f" · run {result.run_id}" if result.run_id not in (row["label"], "1") else ""
    title.markdown(
        f"#### {_device_name(row['group_display'], row['label'])}{run_part} — {result.sweep} sweep · {_status_text(result.status)}"
    )
    title.caption(f"{position + 1} of {len(keys)} · {result.source_file}")
    previous.button("Previous", on_click=_step, args=(-1, keys), width="stretch", key="fet_devices_prev", disabled=len(keys) < 2)
    following.button("Next", on_click=_step, args=(1, keys), width="stretch", key="fet_devices_next", disabled=len(keys) < 2)

    head = st.columns(4)
    head[0].metric("Vth, linear (V)", "-" if result.vth_linear_V is None else f"{result.vth_linear_V:.2f}")
    head[1].metric("SS (mV/dec)", "-" if result.ss_mV_per_dec is None else f"{result.ss_mV_per_dec:.0f}")
    head[2].metric("Mobility (cm²/Vs)", "-" if result.mobility_cm2_per_Vs is None else f"{result.mobility_cm2_per_Vs:.3g}")
    head[3].metric("log10(on/off)", "-" if result.on_off_decades is None else f"{result.on_off_decades:.2f}")

    for code in result.reasons:
        level, message = REASONS[code]
        (st.error if level == "invalid" else st.warning if level == "attention" else st.info)(f"**{code}** · {message}")

    file_stem = f"{measurement.label}_{result.sweep}"
    # a fixed width: the two figures sit side by side and wrap when they do not fit
    left, right = st.columns(2) if curve_size.width_px is None else (st.container(horizontal=True),) * 2
    with left:
        show_figure(transfer_log_figure(branches, results, result.sweep), curve_size, filename=f"{file_stem}_log")
    with right:
        show_figure(transfer_linear_figure(branches, results, result.sweep), curve_size, filename=f"{file_stem}_linear")

    decision = row["decision"]
    approve, reject, clear, note_box = st.columns([1, 1, 1, 4], vertical_alignment="bottom")
    approve.button("Approve", type="primary", on_click=_decide, args=(batch, identity, "approved", next_key), width="stretch", key="fet_devices_approve", disabled=decision == "approved")
    reject.button("Reject", on_click=_decide, args=(batch, identity, "rejected", next_key), width="stretch", key="fet_devices_reject", disabled=decision == "rejected")
    clear.button("Clear", on_click=_decide, args=(batch, identity, "auto", None), width="stretch", key="fet_devices_clear", disabled=decision == "auto", help="Back to the automatic status.")
    note_key = f"fet_devices_note_{selected}"
    note_box.text_input("Note", value=row["note"], key=note_key, on_change=_save_note, args=(batch, identity, note_key), placeholder="Saved when you press Enter")
    st.caption(
        f"Decision: **{decision if decision != 'auto' else 'none (the automatic status is used)'}**. "
        "Approve and Reject are saved at once and move to the next sweep."
    )

    with st.expander("Extracted values", expanded=False):
        st.dataframe(extracted_values(result, row["i_on_uA_per_um"]), hide_index=True, width="stretch", height=420)
    with st.expander("What the reasons mean", expanded=False):
        st.dataframe(
            pd.DataFrame([{"reason": code, "level": "note" if status == "valid" else status, "meaning": message} for code, (status, message) in REASONS.items()]),
            hide_index=True,
            width="stretch",
        )
