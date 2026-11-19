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

from ads_core.model import MdSettings, RelaxationSettings  # noqa: E402
from ads_core.pipeline import ordered_groups  # noqa: E402
from ads_core.simulation.md import MdResult  # noqa: E402
from ads_core.simulation.quality import REASONS, REASON_MESSAGES  # noqa: E402
from ads_gui.components.atoms2d import pose_top_side_png  # noqa: E402
from ads_gui.components.figures import convergence_figure, gallery_figure, gallery_size, md_trajectory_figure  # noqa: E402
from ads_gui.components.values import pose_values_table  # noqa: E402
from ads_gui.components.viewer3d import md_3d_html, pose_3d_html  # noqa: E402
from ads_gui.state import active, filters, get_review, put_review, render_ads_chrome, stop_if_empty  # noqa: E402
from labkit.chrome import panel_title  # noqa: E402
from labkit.figure_size import FigureSize, figure_settings_popover, show_figure  # noqa: E402

SELECTED_KEY = "poses_selected"
VIEW_KEY = "poses_view"
NONCE_KEY = "poses_nonce"
VIEWS = ("Detail", "Gallery")
STATUS_RANK = {"attention": 0, "invalid": 1, "valid": 2}
STATUS_MARK = {"attention": "⚠", "invalid": "✕", "valid": "✓"}
STATUS_TEXT_COLOR = {"attention": "orange", "invalid": "red", "valid": "green"}
GALLERY_COLUMNS_KEY = "poses_gallery_columns"

render_ads_chrome("Poses", "Poses · MoS2 Adsorption", poses_sub="Single-Molecule Poses")
st.header("Poses")

batch, run, review, frame = active()
groups = ordered_groups(frame, review)
shown = filters(frame, groups)
if shown.empty and not run.md_results:
    stop_if_empty(shown)

view_store = st.session_state.setdefault("poses_view_store", {"view": VIEWS[0]})
if st.session_state.get(VIEW_KEY) not in VIEWS:
    st.session_state[VIEW_KEY] = view_store["view"] if view_store.get("view") in VIEWS else VIEWS[0]
st.session_state.setdefault(GALLERY_COLUMNS_KEY, 4)

c_view, c_info, c_fig = st.columns([1.5, 2.6, 1.3], vertical_alignment="center")
active_view = (
    c_view.segmented_control(
        "View",
        VIEWS,
        key=VIEW_KEY,
        label_visibility="collapsed",
        disabled=shown.empty,
    )
    or VIEWS[0]
)
view_store["view"] = active_view


def _gallery_extra() -> None:
    st.divider()
    st.number_input("Gallery: panels per row", 1, 8, step=1, key=GALLERY_COLUMNS_KEY)


sizes = figure_settings_popover(
    [
        ("ads_convergence", "Detail: convergence curve", 520, 440),
        ("ads_gallery_panel", "Gallery: one panel", 240, 200),
    ],
    extra=_gallery_extra,
    container=c_fig,
)
detail_size = sizes["ads_convergence"]
panel_size = sizes["ads_gallery_panel"]
gallery_columns = int(st.session_state.get(GALLERY_COLUMNS_KEY, 4))

md_cutoff = MdSettings.from_config(run.config).adsorption_cutoff_A


def _render_md_inspector(md_list: list[MdResult], default_pose_id: str | None = None) -> None:
    md_ids = [m.pose_id for m in md_list]
    default_idx = md_ids.index(default_pose_id) if default_pose_id in md_ids else 0
    if st.session_state.get("poses_md_select") not in md_ids:
        st.session_state["poses_md_select"] = md_ids[default_idx]
    chosen_md_id = st.selectbox("MD trajectory pose", md_ids, key="poses_md_select")
    md_res = next(m for m in md_list if m.pose_id == chosen_md_id)
    mc = st.columns(4)
    mc[0].metric("Stayed adsorbed", "Yes" if md_res.stayed_adsorbed else "No")
    mc[1].metric("Residence", "-" if md_res.residence_fraction is None else f"{100.0 * md_res.residence_fraction:.1f}%")
    mc[2].metric("Final dz_com (Å)", "-" if md_res.final_dz_com_A is None else f"{md_res.final_dz_com_A:.2f}")
    mc[3].metric("Mean dz_com (Å)", "-" if md_res.mean_dz_com_A is None else f"{md_res.mean_dz_com_A:.2f}")
    if md_res.failed and md_res.failure_message:
        st.error(f"MD failed: {md_res.failure_message}")
    l_md, r_md = st.columns(2) if detail_size.width_px is None else (st.container(horizontal=True),) * 2
    with l_md:
        components.html(md_3d_html(md_res, height=detail_size.height_px), height=detail_size.height_px + 12)
    with r_md:
        show_figure(
            md_trajectory_figure(
                md_res.trajectory_steps,
                target_temp_K=md_res.temperature_K,
                cutoff_A=md_cutoff,
                height=detail_size.height_px,
            ),
            detail_size,
            filename=f"{batch}_{md_res.pose_id}_md",
            key=f"poses_md_chart_{md_res.pose_id}",
        )


if shown.empty:
    c_info.caption(f"MD-only batch · {len(run.md_results)} trajectory run(s)")
    st.info("This batch has MD trajectories without relaxation poses.")
    with st.container(border=True):
        panel_title("MD Trajectory Inspector")
        _render_md_inspector(run.md_results)
    st.stop()

shown = shown.assign(_rank=shown["status"].map(STATUS_RANK), _group=shown["group_display"].map(groups.index))
shown = shown.sort_values(["_rank", "_group", "pose_id"], kind="stable").reset_index(drop=True)
pose_ids = shown["pose_id"].astype(str).tolist()
st.session_state.setdefault(NONCE_KEY, 0)
if st.session_state.get(SELECTED_KEY) not in pose_ids:
    st.session_state[SELECTED_KEY] = pose_ids[0]


def _select(pose_id: str, view: str | None = None) -> None:
    st.session_state[SELECTED_KEY] = pose_id
    st.session_state[NONCE_KEY] += 1
    if view:
        st.session_state[VIEW_KEY] = view
        st.session_state.setdefault("poses_view_store", {})["view"] = view


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
c_info.caption(
    f"{len(shown)} pose(s) shown · {open_count} need a decision · "
    f"{int((shown['decision'] == 'approved').sum())} approved · {int((shown['decision'] == 'rejected').sum())} rejected."
)
nonce = st.session_state[NONCE_KEY]

if active_view == "Gallery":
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
    with st.container(border=True):
        panel_title("Pose Convergence Gallery")
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

with st.container(key="kmg_review_workspace"):
    list_box, center_box, review_box = st.columns([1.6, 3.6, 1.85], gap="medium")

    with list_box, st.container(border=True):
        panel_title("Pose List")
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
        st.caption("Click a row to inspect. ⚠ attention · ✕ invalid · ✓ valid.")

    with center_box, st.container(border=True):
        head_t, prev_b, next_b = st.columns([3.6, 1.5, 1.4], vertical_alignment="center")
        head_t.markdown(f"#### {result.surface_id} · {result.molecule_id} — {result.site_type} ({result.orientation}) · :{STATUS_TEXT_COLOR[result.status]}[{result.status}]")
        head_t.caption(f"{position + 1} of {len(pose_ids)} · `{result.pose_id}`")
        prev_b.button("Previous", on_click=_step, args=(-1, pose_ids), width="stretch", key="poses_prev", disabled=len(pose_ids) < 2)
        next_b.button("Next", on_click=_step, args=(1, pose_ids), width="stretch", key="poses_next", disabled=len(pose_ids) < 2)

        m = st.columns(4)
        m[0].metric("E_ads (eV)", "-" if result.e_ads_eV is None else f"{result.e_ads_eV:.3f}")
        m[1].metric("vdW fraction", "-" if result.vdw_fraction is None else f"{100.0 * result.vdw_fraction:.1f}%")
        m[2].metric("d_min (Å)", "-" if result.d_min_A is None else f"{result.d_min_A:.2f}")
        m[3].metric("dz_com (Å)", "-" if result.dz_com_A is None else f"{result.dz_com_A:.2f}")

        with st.container(key="kmg_curves_pair"):
            left_v, right_v = st.columns(2) if detail_size.width_px is None else (st.container(horizontal=True),) * 2
            with left_v:
                mode_opts = ("Relaxed + Initial Ghost", "Relaxation Trajectory Animation")
                mode_store = st.session_state.setdefault("poses_3d_mode_store", {"mode": mode_opts[0]})
                if st.session_state.get("poses_3d_mode") not in mode_opts:
                    st.session_state["poses_3d_mode"] = mode_store["mode"] if mode_store.get("mode") in mode_opts else mode_opts[0]
                mode_choice = st.radio("3D View", mode_opts, horizontal=True, key="poses_3d_mode")
                mode_store["mode"] = mode_choice
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
        with st.expander("Extracted values & energy decomposition", expanded=False):
            st.dataframe(pose_values_table(result, run), hide_index=True, width="stretch", height=420)
        if run.md_results:
            with st.expander(
                f"Finite-temperature MD trajectory ({len(run.md_results)})",
                expanded=any(m.pose_id == selected for m in run.md_results),
            ):
                _render_md_inspector(run.md_results, default_pose_id=selected)

    with review_box, st.container(border=True):
        panel_title("Review")
        decision = str(row["decision"])
        st.caption(f"Status: **:{STATUS_TEXT_COLOR[result.status]}[{result.status}]** · Decision: `{decision}`")
        for code in result.reasons:
            level = REASONS[code]
            msg = REASON_MESSAGES[code]
            (st.error if level == "invalid" else st.warning if level == "attention" else st.info)(f"**{code}** · {msg}")
        if not result.reasons:
            st.caption("No quality warnings raised.")

        st.button("Approve", type="primary", on_click=_decide, args=(batch, selected, "approved", next_id), width="stretch", key="poses_approve", disabled=decision == "approved")
        st.button("Reject", on_click=_decide, args=(batch, selected, "rejected", next_id), width="stretch", key="poses_reject", disabled=decision == "rejected")
        st.button("Clear", on_click=_decide, args=(batch, selected, "auto", None), width="stretch", key="poses_clear", disabled=decision == "auto")
        note_key = f"poses_note_{selected}"
        st.text_input("Note", value=str(row["note"]), key=note_key, on_change=_save_note, args=(batch, selected, note_key), placeholder="Saved when you press Enter")

        with st.expander("What the reasons mean", expanded=False):
            st.dataframe(
                pd.DataFrame([{"reason": code, "level": lvl, "meaning": REASON_MESSAGES[code]} for code, lvl in REASONS.items()]),
                hide_index=True,
                width="stretch",
            )
