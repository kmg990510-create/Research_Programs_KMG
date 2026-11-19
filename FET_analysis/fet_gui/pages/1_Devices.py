"""Devices: the list of sweeps next to the curves of the selected one, with its decision.

Review and viewer in one place: the row selected on the left is drawn in the
center and judged on the right. Decisions and notes are saved immediately.
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
from fet_gui.components.figures import gallery_figure, gallery_size, transfer_linear_figure, transfer_log_figure  # noqa: E402
from fet_gui.components.values import extracted_values  # noqa: E402
from fet_gui.state import active, filters, get_review, put_review, render_fet_chrome, stop_if_empty  # noqa: E402
from labkit.chrome import panel_title  # noqa: E402
from labkit.figure_size import FigureSize, figure_settings_popover, show_figure  # noqa: E402

SELECTED_KEY = "fet_devices_selected"
VIEW_KEY = "fet_devices_view"
VIEW_CTRL_KEY = "fet_devices_view_ctrl"
NONCE_KEY = "fet_devices_nonce"  # changes the widget keys so a stale table or plot selection is dropped
VIEWS = ("Detail", "Gallery")
STATUS_RANK = {"attention": 0, "invalid": 1, "valid": 2}
STATUS_MARK = {"attention": "⚠", "invalid": "✕", "valid": "✓"}
STATUS_TEXT_COLOR = {"attention": "orange", "invalid": "red"}
GALLERY_COLUMNS = 5
GALLERY_COLUMNS_KEY = "fet_devices_gallery_columns"


def _status_text(status: str) -> str:
    return f":{STATUS_TEXT_COLOR[status]}[{status}]" if status in STATUS_TEXT_COLOR else status


def _device_name(group: str, label: str) -> str:
    """The label alone when it already starts with the group name."""
    return label if str(label).startswith(str(group)) else f"{group} · {label}"


def _select(key: str, view: str | None = None) -> None:
    st.session_state[SELECTED_KEY] = key
    st.session_state[NONCE_KEY] += 1
    if view:
        st.session_state[VIEW_KEY] = view
        st.session_state[VIEW_CTRL_KEY] = view


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


render_fet_chrome("Devices", "Devices · FET Analysis")
batch, run, review, frame = active()
groups = ordered_groups(frame, review)
shown = filters(frame, groups)

st.header("Devices")
stop_if_empty(shown)

# Sweeps that need a look come first.
shown = shown.assign(_rank=shown["status"].map(STATUS_RANK), _group=shown["group_display"].map(groups.index))
shown = shown.sort_values(["_rank", "_group", "label", "run_id", "sweep"], kind="stable").reset_index(drop=True)
keys = [sweep_key(r.source_file, r.run_id, r.sweep) for r in shown.itertuples()]
st.session_state.setdefault(NONCE_KEY, 0)
st.session_state.setdefault(VIEW_KEY, VIEWS[0])
st.session_state.setdefault(GALLERY_COLUMNS_KEY, GALLERY_COLUMNS)
if st.session_state.get(SELECTED_KEY) not in keys:
    st.session_state[SELECTED_KEY] = keys[0]

v_left, v_mid, v_right = st.columns([1.4, 3.6, 1.1], vertical_alignment="center")
if st.session_state.get(VIEW_CTRL_KEY) not in VIEWS:
    st.session_state[VIEW_CTRL_KEY] = st.session_state[VIEW_KEY]
picked_view = v_left.segmented_control(
    "View",
    VIEWS,
    key=VIEW_CTRL_KEY,
    label_visibility="collapsed",
)
if picked_view in VIEWS:
    st.session_state[VIEW_KEY] = picked_view
active_view = st.session_state[VIEW_KEY]

open_count = int(((shown["status"] == "attention") & (shown["decision"] == "auto")).sum())
v_mid.caption(
    f"{len(shown)} of {len(frame)} sweep(s) shown · {open_count} need a decision · "
    f"{int((shown['decision'] == 'approved').sum())} approved · {int((shown['decision'] == 'rejected').sum())} rejected."
)

if active_view == "Gallery":
    def _gallery_extra() -> None:
        st.number_input("Gallery: panels per row", 1, 12, step=1, key=GALLERY_COLUMNS_KEY)

    sizes = figure_settings_popover(
        [("fet_gallery_panel", "Gallery: one panel", 240, 190)],
        extra=_gallery_extra,
        container=v_right,
    )
    panel_size = sizes["fet_gallery_panel"]
    gallery_columns = int(st.session_state[GALLERY_COLUMNS_KEY])
else:
    sizes = figure_settings_popover(
        [("fet_curves", "Detail: log and linear curves", 520, 340)],
        container=v_right,
    )
    curve_size = sizes["fet_curves"]

nonce = st.session_state[NONCE_KEY]

if active_view == "Gallery":
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
    with st.container(border=True):
        panel_title("Device Gallery")
        show_figure(
            gallery_figure(panels, gallery_columns),
            FigureSize(*gallery_size(len(panels), gallery_columns, panel_size.width_px, panel_size.height_px)),
            filename=f"{batch}_gallery",
            key=gallery_key,
            on_select=partial(_gallery_clicked, gallery_key, trace_keys),
            selection_mode="points",
        )
        st.caption("Black: valid · orange: needs attention · red: invalid · grey dotted: rejected. Click a panel to inspect it in Detail.")
    st.stop()

selected = st.session_state[SELECTED_KEY]
position = keys.index(selected)
row = shown.iloc[position]
identity = (row["source_file"], row["run_id"], row["sweep"])
next_key = keys[(position + 1) % len(keys)] if len(keys) > 1 else None
result = next(r for r in run.analysis.results if (r.source_file, r.run_id, r.sweep) == identity)
measurement = run.measurement(result.source_file, result.run_id)
results = {r.sweep: r for r in run.analysis.results if (r.source_file, r.run_id) == identity[:2]}
branches, _ = split_branches(measurement.data, run.settings)

with st.container(key="kmg_review_workspace"):
    list_box, chart_box, review_box = st.columns([1.45, 3.85, 1.6], gap="medium")

with list_box, st.container(border=True):
    panel_title("Devices")
    st.caption(f"{len(shown)} matching sweeps")
    table = pd.DataFrame(
        {
            "": ["▶" if key == selected else "" for key in keys],
            "status": shown["status"].map(STATUS_MARK),
            "device": [_device_name(r.group_display, r.label) for r in shown.itertuples()],
            "sweep": shown["sweep"],
            "decision": shown["decision"].replace("auto", ""),
        }
    )
    if shown["sweep"].nunique() == 1:
        table = table.drop(columns="sweep")
    table_key = f"fet_devices_table_{nonce}"
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        height=min(560, 40 + 35 * len(table)),
        column_config={
            "": st.column_config.TextColumn(width=24),
            "status": st.column_config.TextColumn(width=44, help="⚠ needs attention · ✕ invalid · ✓ valid"),
            "decision": st.column_config.TextColumn(width=68),
        },
        key=table_key,
        on_select=partial(_table_clicked, table_key, keys),
        selection_mode="single-row",
    )
    st.caption("⚠ needs attention · ✕ invalid · ✓ valid (attention listed first)")

with chart_box:
    title_col, prev_col, next_col = st.columns([5, 1, 1], vertical_alignment="center")
    run_part = f" · run {result.run_id}" if result.run_id not in (row["label"], "1") else ""
    title_col.caption(
        f"**{_device_name(row['group_display'], row['label'])}{run_part} · {result.sweep} sweep** · "
        f"{_status_text(result.status)} · {position + 1} of {len(keys)} · `{result.source_file}`"
    )
    prev_col.button("Previous", on_click=_step, args=(-1, keys), width="stretch", key="fet_devices_prev", disabled=len(keys) < 2)
    next_col.button("Next", on_click=_step, args=(1, keys), width="stretch", key="fet_devices_next", disabled=len(keys) < 2)

    file_stem = f"{measurement.label}_{result.sweep}"
    with st.container(key="kmg_curves_pair"):
        left_c, right_c = st.columns(2) if curve_size.width_px is None else (st.container(horizontal=True),) * 2
        with left_c, st.container(border=True):
            panel_title("Linear")
            show_figure(transfer_linear_figure(branches, results, result.sweep), curve_size, filename=f"{file_stem}_linear")
        with right_c, st.container(border=True):
            panel_title("Log")
            show_figure(transfer_log_figure(branches, results, result.sweep), curve_size, filename=f"{file_stem}_log")

    if result.reasons:
        with st.expander(f"Quality warnings ({len(result.reasons)})", expanded=False):
            for code in result.reasons:
                level, message = REASONS[code]
                (st.error if level == "invalid" else st.warning if level == "attention" else st.info)(f"**{code}** · {message}")

    with st.expander("Extracted values", expanded=False):
        st.dataframe(extracted_values(result, row["i_on_uA_per_um"]), hide_index=True, width="stretch", height=420)
    with st.expander("What the reasons mean", expanded=False):
        st.dataframe(
            pd.DataFrame([{"reason": code, "level": "note" if status == "valid" else status, "meaning": message} for code, (status, message) in REASONS.items()]),
            hide_index=True,
            width="stretch",
        )

with review_box, st.container(border=True):
    panel_title("Review")
    vth_str = "-" if result.vth_linear_V is None else f"{result.vth_linear_V:.2f}"
    mob_str = "-" if result.mobility_cm2_per_Vs is None else f"{result.mobility_cm2_per_Vs:.3g}"
    ss_str = "-" if result.ss_mV_per_dec is None else f"{result.ss_mV_per_dec:.0f}"
    ratio_str = "-" if result.on_off_decades is None else f"{result.on_off_decades:.2f}"
    st.markdown(
        f"**Vth (V)**　{vth_str}  \n"
        f"**Mobility (cm²/V·s)**　{mob_str}  \n"
        f"**SS (mV/dec)**　{ss_str}  \n"
        f"**log₁₀(on/off)**　{ratio_str}"
    )

    if result.reasons:
        summary_codes = ", ".join(result.reasons[:3]) + ("…" if len(result.reasons) > 3 else "")
        (st.error if result.status == "invalid" else st.warning if result.status == "attention" else st.info)(
            f"**{result.status.capitalize()}** · {summary_codes}"
        )
    else:
        st.caption(result.status.capitalize())

    decision = row["decision"]
    st.button("Approve", type="primary", on_click=_decide, args=(batch, identity, "approved", next_key), width="stretch", key="fet_devices_approve", disabled=decision == "approved")
    st.button("Reject", on_click=_decide, args=(batch, identity, "rejected", next_key), width="stretch", key="fet_devices_reject", disabled=decision == "rejected")
    st.button("Clear", on_click=_decide, args=(batch, identity, "auto", None), width="stretch", key="fet_devices_clear", disabled=decision == "auto", help="Back to the automatic status.")
    note_key = f"fet_devices_note_{selected}"
    st.text_input("Note", value=row["note"], key=note_key, on_change=_save_note, args=(batch, identity, note_key), placeholder="Saved when you press Enter")
    st.caption(
        f"Decision: **{decision if decision != 'auto' else 'automatic'}**. "
        "Saved immediately."
    )
