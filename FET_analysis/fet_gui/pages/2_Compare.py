"""Compare: groups side by side."""

from __future__ import annotations

import sys
from pathlib import Path

_FET_ROOT = Path(__file__).resolve().parents[2]
for _path in (_FET_ROOT, _FET_ROOT.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from fet_core.analysis.sweeps import split_branches  # noqa: E402
from fet_core.pipeline import ordered_groups  # noqa: E402
from fet_core.report.summary import METRICS, group_summary, metric_label  # noqa: E402
from fet_gui.components.figures import metric_figure, overlay_figure  # noqa: E402
from fet_gui.state import (  # noqa: E402
    active,
    filters,
    put_review,
    render_fet_chrome,
    stop_if_empty,
    sync_renamed_filter_groups,
)
from labkit.chrome import panel_title  # noqa: E402
from labkit.figure_size import figure_settings_popover, show_figure  # noqa: E402
from labkit.plot_theme import categorical_colors  # noqa: E402

GROUPS_NONCE_KEY = "fet_compare_groups_nonce"  # a new editor after every save, so old edits are not applied twice
VIEW_OPTIONS = ("Statistics", "Overlay", "Summary table")
VIEW_STORE_KEY = "fet_compare_view_store"
VIEW_CTRL_KEY = "fet_compare_view_ctrl"
METRICS_STORE_KEY = "fet_compare_metrics_store"
METRICS_CTRL_KEY = "fet_compare_metrics"
SCALE_OPTIONS = ("Log", "Linear")
DEFAULT_METRICS = ("mobility_cm2_per_Vs", "vth_linear_V", "ss_mV_per_dec", "on_off_decades")


def _original_groups_map(frame: pd.DataFrame, review) -> dict[str, str]:
    mapping: dict[str, list[str]] = {}
    for orig in dict.fromkeys(frame["group"]):
        disp = review.display_group(orig)
        mapping.setdefault(disp, []).append(str(orig))
    return {disp: ", ".join(origs) for disp, origs in mapping.items()}


render_fet_chrome("Compare", "Compare · FET Analysis")
batch, run, review, frame = active()
groups = ordered_groups(frame, review)
shown = filters(frame, groups)

st.header("Compare")

st.session_state.setdefault(VIEW_STORE_KEY, VIEW_OPTIONS[0])
st.session_state.setdefault(METRICS_STORE_KEY, list(DEFAULT_METRICS))
if st.session_state.get(VIEW_CTRL_KEY) not in VIEW_OPTIONS:
    st.session_state[VIEW_CTRL_KEY] = st.session_state[VIEW_STORE_KEY]

top_left, top_right = st.columns([4, 1], vertical_alignment="bottom")
picked_view = top_left.segmented_control(
    "Compare view",
    VIEW_OPTIONS,
    key=VIEW_CTRL_KEY,
    label_visibility="collapsed",
)
if picked_view in VIEW_OPTIONS:
    st.session_state[VIEW_STORE_KEY] = picked_view
active_view = st.session_state[VIEW_STORE_KEY]

with top_right.popover("Manage groups", width="stretch"):
    st.caption("Names and order used across plots and tables. Saved immediately.")
    st.session_state.setdefault(GROUPS_NONCE_KEY, 0)
    originals = list(dict.fromkeys(frame["group"]))
    table = pd.DataFrame(
        {
            "group in file": originals,
            "name": [review.display_group(g) for g in originals],
            "order": [groups.index(review.display_group(g)) + 1 for g in originals],
        }
    )
    edited = st.data_editor(
        table,
        hide_index=True,
        width="stretch",
        disabled=["group in file"],
        column_config={"order": st.column_config.NumberColumn("order", min_value=1, step=1, required=True)},
        key=f"fet_compare_groups_{batch}_{st.session_state[GROUPS_NONCE_KEY]}",
    )
    names = {row["group in file"]: (str(row["name"] or "").strip() or row["group in file"]) for row in edited.to_dict("records")}
    moved = edited["order"] != table["order"]
    if moved.any() or names != dict(zip(table["group in file"], table["name"])):
        old_to_new = {row["name"]: names[row["group in file"]] for row in table.to_dict("records")}
        ranked = edited.assign(display=[names[g] for g in edited["group in file"]], kept=~moved).sort_values(["order", "kept"], kind="stable")
        review.group_names = {group: name for group, name in names.items() if name != group}
        review.group_order = list(dict.fromkeys(ranked["display"]))
        put_review(batch, review)
        sync_renamed_filter_groups(old_to_new)
        st.session_state[GROUPS_NONCE_KEY] += 1
        st.rerun()

stop_if_empty(shown)
shown_groups = [g for g in groups if g in set(shown["group_display"])]
colors = categorical_colors(groups)

if active_view == "Statistics":
    if METRICS_CTRL_KEY not in st.session_state:
        st.session_state[METRICS_CTRL_KEY] = [m for m in st.session_state[METRICS_STORE_KEY] if m in METRICS]
    q_col, cfg_col = st.columns([4, 1], vertical_alignment="bottom")
    metrics = q_col.multiselect("Quantities", list(METRICS), format_func=metric_label, key=METRICS_CTRL_KEY)
    st.session_state[METRICS_STORE_KEY] = list(metrics)
    stats_size = figure_settings_popover(
        [("fet_statistics", "Statistics: one quantity", 520, 340)],
        container=cfg_col,
    )["fet_statistics"]

    st.caption(f"{int(shown['included'].sum())} of {len(shown)} matching sweep(s) in statistics · Invalid and rejected sweeps omitted.")
    if not metrics:
        st.info("Choose at least one quantity.")
    elif not int(shown["included"].sum()):
        st.info("No valid, non-rejected sweeps in the current selection for statistics.")
    else:
        if stats_size.width_px is None:
            places = [column for start in range(0, len(metrics), 2) for column in st.columns(2)]
        else:
            places = [st.container(horizontal=True)] * len(metrics)
        for place, metric in zip(places, metrics):
            with place, st.container(border=True):
                panel_title(metric_label(metric))
                show_figure(metric_figure(shown, metric, shown_groups, colors), stats_size, filename=f"{batch}_{metric}", key=f"fet_compare_metric_{metric}")
        st.caption("Filled points enter statistics. Hollow points are invalid or rejected sweeps shown by the filters.")

elif active_view == "Overlay":
    c_norm, c_scale, c_cfg = st.columns([2.2, 1.8, 1.0], vertical_alignment="bottom")
    per_width = c_norm.checkbox("Current per channel width (µA/µm)", value=True, key="fet_compare_per_width")
    scale_choice = c_scale.segmented_control("Current axis scale", SCALE_OPTIONS, default="Log", key="fet_compare_overlay_scale")
    log_scale = (scale_choice or "Log") != "Linear"
    overlay_size = figure_settings_popover(
        [("fet_overlay", "Overlay", 900, 480)],
        container=c_cfg,
    )["fet_overlay"]

    curves = []
    for row in shown[shown["included"]].itertuples():
        measurement = run.measurement(row.source_file, row.run_id)
        branch = next((b for b in split_branches(measurement.data, run.settings)[0] if b.direction == row.sweep), None)
        if branch is not None:
            curves.append(
                {
                    "group": row.group_display,
                    "label": f"{row.label} · {row.sweep}",
                    "vg": branch.data["Vg"].to_numpy(),
                    "current": branch.data["Id"].to_numpy(),
                    "W_um": row.W_um,
                }
            )
    curves.sort(key=lambda curve: shown_groups.index(curve["group"]))
    left_out = len(shown) - len(curves)
    st.caption(f"{len(curves)} curve(s) from {len({c['group'] for c in curves})} group(s)." + (f" {left_out} invalid or rejected sweep(s) are not drawn." if left_out else ""))
    if curves:
        with st.container(border=True):
            panel_title("Transfer Overlay")
            show_figure(overlay_figure(curves, colors, per_width, log_scale=log_scale), overlay_size, filename=f"{batch}_overlay")
    else:
        st.info("No included sweeps to draw in the overlay.")

else:
    metrics = [m for m in st.session_state[METRICS_STORE_KEY] if m in METRICS] or list(DEFAULT_METRICS)
    summary = group_summary(shown, shown_groups)
    orig_map = _original_groups_map(frame, review)
    summary.insert(1, "original_group", summary["group"].map(lambda g: orig_map.get(g, g)))
    keep = ["group", "original_group", "sweep", "n_sweeps", "n_included"] + [f"{m}_{s}" for m in metrics for s in ("median", "mean", "std")]
    st.caption(f"{len(shown)} matching sweeps · `original_group` preserves raw identifiers · `n_included` matches statistics.")
    with st.container(border=True):
        panel_title("Group Summary")
        st.dataframe(summary[keep], hide_index=True, width="stretch")
    with st.expander("Per-sweep table", expanded=False):
        sweep_cols = ["group", "group_display", "label", "sweep", "status", "decision", "included", *metrics]
        st.dataframe(shown[[c for c in sweep_cols if c in shown.columns]], hide_index=True, width="stretch")
