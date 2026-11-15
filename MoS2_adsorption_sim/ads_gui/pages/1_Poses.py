"""Poses: inspect 3D relaxed structures, convergence curves, and record human decisions."""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

_SIM_ROOT = Path(__file__).resolve().parents[2]
for _path in (_SIM_ROOT, _SIM_ROOT.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from ads_core.model import RelaxationSettings  # noqa: E402
from ads_core.pipeline import ordered_groups  # noqa: E402
from ads_core.simulation.quality import REASONS, REASON_MESSAGES  # noqa: E402
from ads_gui.components.atoms2d import pose_top_side_png  # noqa: E402
from ads_gui.components.figures import convergence_figure, gallery_figure, gallery_size  # noqa: E402
from ads_gui.components.values import pose_values_table  # noqa: E402
from ads_gui.components.viewer3d import pose_3d_html  # noqa: E402
from ads_gui.state import active, filters, get_review, put_review, stop_if_empty  # noqa: E402
from labkit.figure_size import FigureSize, figure_options_inputs, figure_size_inputs, show_figure  # noqa: E402
from labkit.sidebar import sidebar_section  # noqa: E402

SELECTED_KEY = "poses_selected"
VIEW_KEY = "poses_view"
NONCE_KEY = "poses_nonce"
VIEWS = ("Detail", "Gallery")
STATUS_RANK = {"attention": 0, "invalid": 1, "valid": 2}
STATUS_MARK = {"attention": "⚠", "invalid": "✕", "valid": "✓"}
STATUS_TEXT_COLOR = {"attention": "orange", "invalid": "red", "valid": "green"}
GALLERY_COLUMNS_KEY = "poses_gallery_columns"

st.set_page_config(page_title="Poses · MoS2 Adsorption", layout="wide")
st.title("Poses")

batch, run, review, frame = active()
groups = ordered_groups(frame, review)
shown = filters(frame, groups)
with sidebar_section("3) Figure size", expanded=False):
    figure_options_inputs()
    detail_size = figure_size_inputs("ads_convergence", "Detail: convergence curve", 520, 440)
    panel_size = figure_size_inputs("ads_gallery_panel", "Gallery: one panel", 240, 200)
    st.session_state.setdefault(GALLERY_COLUMNS_KEY, 4)
    gallery_columns = int(st.number_input("Gallery: panels per row", 1, 8, step=1, key=GALLERY_COLUMNS_KEY))
stop_if_empty(shown)

shown = shown.assign(_rank=shown["status"].map(STATUS_RANK), _group=shown["group_display"].map(groups.index))
shown = shown.sort_values(["_rank", "_group", "pose_id"], kind="stable").reset_index(drop=True)
pose_ids = shown["pose_id"].astype(str).tolist()
st.session_state.setdefault(NONCE_KEY, 0)
st.session_state.setdefault(VIEW_KEY, VIEWS[0])
if st.session_state.get(SELECTED_KEY) not in pose_ids:
    st.session_state[SELECTED_KEY] = pose_ids[0]


def _select(pose_id: str, view: str | None = None) -> None:
    st.session_state[SELECTED_KEY] = pose_id
    st.session_state[NONCE_KEY] += 1
    if view:
        st.session_state[VIEW_KEY] = view


def _step(delta: int, all_ids: list[str]) -> None:
    idx = all_ids.index(st.session_state[SELECTED_KEY])
    _select(all_ids[(idx + delta) % len(all_ids)])


def _table_clicked(widget_key: str, all_ids: list[str]) -> None:
    rows = st.session_state[widget_key]["selection"]["rows"]
    if rows:
        st.session_state[SELECTED_KEY] = all_ids[rows[0]]


def _gallery_clicked(widget_key: str, trace_ids: list[str]) -> None:
    points = st.session_state[widget_key]["selection"]["points"]
    if points:
        _select(trace_ids[points[0]["curve_number"]], view=VIEWS[0])


def _decide(batch_name: str, pose_id: str, decision: str, next_id: str | None) -> None:
    current = get_review(batch_name)
    current.set_decision(pose_id, decision)
    put_review(batch_name, current)
    if next_id:
        _select(next_id)


def _save_note(batch_name: str, pose_id: str, widget_key: str) -> None:
    current = get_review(batch_name)
    current.set_decision(pose_id, current.decision(pose_id), st.session_state[widget_key])
    put_review(batch_name, current)


open_count = int(((shown["status"] == "attention") & (shown["decision"] == "auto")).sum())
top_left, top_right = st.columns([1, 3], vertical_alignment="center")
top_left.radio("View", VIEWS, horizontal=True, key=VIEW_KEY, label_visibility="collapsed")
top_right.caption(
    f"{len(shown)} pose(s) shown · {open_count} need a decision · "
    f"{int((shown['decision'] == 'approved').sum())} approved · {int((shown['decision'] == 'rejected').sum())} rejected."
)
nonce = st.session_state[NONCE_KEY]

if st.session_state[VIEW_KEY] == "Gallery":
    panels: list[dict] = []
    for item in shown.itertuples():
        art = run.artifacts[item.pose_id]
        steps = art.trajectory_steps
        x_vals = [s.step for s in steps] if steps else [0]
        e0 = float(steps[0].energy_eV) if steps else 0.0
        de_vals = [float(s.energy_eV) - e0 for s in steps] if steps else [0.0]
        e_str = f"{item.e_ads_eV:.2f} eV" if pd.notna(item.e_ads_eV) else "-"
        panels.append(
            {
                "pose_id": item.pose_id,
                "title": f"{item.surface_id} · {item.molecule_id} · {item.site_type} ({e_str})",
                "steps": x_vals,
                "energies": de_vals,
                "status": item.status,
                "rejected": item.decision == "rejected",
                "e_ads_eV": None if pd.isna(item.e_ads_eV) else float(item.e_ads_eV),
            }
        )
    trace_ids = [p["pose_id"] for p in panels]
    g_key = f"poses_gallery_{nonce}"
    show_figure(
        gallery_figure(panels, columns=gallery_columns, row_height=panel_size.height_px),
        FigureSize(*gallery_size(len(panels), gallery_columns, panel_size.width_px, panel_size.height_px)),
        filename=f"{batch}_gallery",
        key=g_key,
        on_select=partial(_gallery_clicked, g_key, trace_ids),
        selection_mode="points",
    )
    st.caption("Black: valid · orange: needs attention · red: invalid · grey dotted: rejected. Click a panel to inspect it in Detail.")

    with st.expander("2D Orthographic Thumbnails (Top / Side via ASE plot_atoms)", expanded=False):
        grid_cols = st.columns(min(3, max(1, len(shown))))
        for idx, item in enumerate(shown.itertuples()):
            art = run.artifacts[item.pose_id]
            png = pose_top_side_png(art.relaxed_atoms, title=f"{item.site_type} ({item.orientation})", status=item.status)
            grid_cols[idx % len(grid_cols)].image(png, width="stretch", caption=item.pose_id)
    st.stop()

selected = st.session_state[SELECTED_KEY]
position = pose_ids.index(selected)
row = shown.iloc[position]
next_id = pose_ids[(position + 1) % len(pose_ids)] if len(pose_ids) > 1 else None
result = next(r for r in run.results if r.pose_id == selected)
artifact = run.artifacts[selected]
fmax_target = RelaxationSettings.from_config(run.config).fmax_eV_per_A

list_box, detail_box = st.columns([3, 7], gap="medium")

with list_box:
    table = pd.DataFrame(
        {
            "": ["▶" if pid == selected else "" for pid in pose_ids],
            "status": shown["status"].map(STATUS_MARK),
            "group": shown["surface_id"].astype(str) + " / " + shown["molecule_id"].astype(str),
            "site": shown["site_type"].astype(str) + " (" + shown["orientation"].astype(str) + ")",
            "decision": shown["decision"].replace("auto", ""),
            "E_ads (eV)": shown["e_ads_eV"],
            "d_min (Å)": shown["d_min_A"],
        }
    )
    t_key = f"poses_table_{nonce}"
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        height=min(760, 40 + 35 * len(table)),
        column_config={
            "": st.column_config.TextColumn(width=24),
            "status": st.column_config.TextColumn(width=48),
            "decision": st.column_config.TextColumn(width=72),
            "E_ads (eV)": st.column_config.NumberColumn(format="%.3f", width=76),
            "d_min (Å)": st.column_config.NumberColumn(format="%.2f", width=70),
        },
        key=t_key,
        on_select=partial(_table_clicked, t_key, pose_ids),
        selection_mode="single-row",
    )
    st.caption("Click a row to inspect. ⚠ needs attention · ✕ invalid · ✓ valid (attention listed first).")

with detail_box:
    head_t, prev_b, next_b = st.columns([6, 1, 1], vertical_alignment="center")
    head_t.markdown(f"#### {result.surface_id} · {result.molecule_id} — {result.site_type} ({result.orientation}) · :{STATUS_TEXT_COLOR[result.status]}[{result.status}]")
    head_t.caption(f"{position + 1} of {len(pose_ids)} · `{result.pose_id}`")
    prev_b.button("Previous", on_click=_step, args=(-1, pose_ids), width="stretch", key="poses_prev", disabled=len(pose_ids) < 2)
    next_b.button("Next", on_click=_step, args=(1, pose_ids), width="stretch", key="poses_next", disabled=len(pose_ids) < 2)

    m = st.columns(4)
    m[0].metric("E_ads (eV)", "-" if result.e_ads_eV is None else f"{result.e_ads_eV:.3f}")
    m[1].metric("vdW fraction", "-" if result.vdw_fraction is None else f"{100.0 * result.vdw_fraction:.1f}%")
    m[2].metric("d_min (Å)", "-" if result.d_min_A is None else f"{result.d_min_A:.2f}")
    m[3].metric("dz_com (Å)", "-" if result.dz_com_A is None else f"{result.dz_com_A:.2f}")

    for code in result.reasons:
        level = REASONS[code]
        msg = REASON_MESSAGES[code]
        (st.error if level == "invalid" else st.warning if level == "attention" else st.info)(f"**{code}** · {msg}")

    left_v, right_v = st.columns(2) if detail_size.width_px is None else (st.container(horizontal=True),) * 2
    with left_v:
        mode_choice = st.radio(
            "3D View",
            ["Relaxed + Initial Ghost", "Relaxation Trajectory Animation"],
            horizontal=True,
            key="poses_3d_mode",
        )
        viewer_mode = "trajectory" if mode_choice.startswith("Relaxation") else "relaxed_with_ghost"
        html = pose_3d_html(artifact, result, mode=viewer_mode, height=detail_size.height_px)
        components.html(html, height=detail_size.height_px + 12)
    with right_v:
        show_figure(
            convergence_figure(artifact.trajectory_steps, fmax_target, height=detail_size.height_px),
            detail_size,
            filename=f"{batch}_{result.pose_id}_convergence",
        )

    with st.expander("2D Orthographic Views (Top / Side via ASE plot_atoms)", expanded=False):
        st.image(pose_top_side_png(artifact.relaxed_atoms, title=result.pose_id, status=result.status), width="stretch")

    decision = str(row["decision"])
    c_app, c_rej, c_clr, c_note = st.columns([1, 1, 1, 4], vertical_alignment="bottom")
    c_app.button("Approve", type="primary", on_click=_decide, args=(batch, selected, "approved", next_id), width="stretch", key="poses_approve", disabled=decision == "approved")
    c_rej.button("Reject", on_click=_decide, args=(batch, selected, "rejected", next_id), width="stretch", key="poses_reject", disabled=decision == "rejected")
    c_clr.button("Clear", on_click=_decide, args=(batch, selected, "auto", None), width="stretch", key="poses_clear", disabled=decision == "auto")
    note_key = f"poses_note_{selected}"
    c_note.text_input("Note", value=str(row["note"]), key=note_key, on_change=_save_note, args=(batch, selected, note_key), placeholder="Saved when you press Enter")

    with st.expander("Extracted values & energy decomposition", expanded=False):
        st.dataframe(pose_values_table(result, run), hide_index=True, width="stretch", height=420)
    with st.expander("What the reasons mean", expanded=False):
        st.dataframe(
            pd.DataFrame([{"reason": code, "level": lvl, "meaning": REASON_MESSAGES[code]} for code, lvl in REASONS.items()]),
            hide_index=True,
            width="stretch",
        )
