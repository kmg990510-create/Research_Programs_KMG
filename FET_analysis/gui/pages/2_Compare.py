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
from gui.components.figures import metric_figure, overlay_figure  # noqa: E402
from gui.state import active, filters, put_review, stop_if_empty  # noqa: E402
from labkit.plot_theme import categorical_colors, export_config  # noqa: E402

GROUPS_NONCE_KEY = "fet_compare_groups_nonce"  # a new editor after every save, so old edits are not applied twice
DEFAULT_METRICS = ("mobility_cm2_per_Vs", "vth_linear_V", "ss_mV_per_dec", "on_off_decades")

st.set_page_config(page_title="Compare · FET Analysis", layout="wide")
st.title("Compare")
st.caption("Statistics use the sweeps that are not invalid and not rejected.")

batch, run, review, frame = active()
groups = ordered_groups(frame, review)
shown = filters(frame, groups)
stop_if_empty(shown)
shown_groups = [g for g in groups if g in set(shown["group_display"])]
colors = categorical_colors(groups)

tab_stats, tab_overlay, tab_table, tab_groups = st.tabs(["Statistics", "Overlay", "Summary table", "Group names and order"])

with tab_stats:
    metrics = st.multiselect("Quantities", list(METRICS), default=list(DEFAULT_METRICS), format_func=metric_label, key="fet_compare_metrics")
    if not metrics:
        st.info("Choose at least one quantity.")
    for start in range(0, len(metrics), 2):
        for column, metric in zip(st.columns(2), metrics[start : start + 2]):
            column.plotly_chart(
                metric_figure(shown, metric, shown_groups, colors, height=380),
                width="stretch",
                theme=None,
                config=export_config(f"{batch}_{metric}"),
                key=f"fet_compare_metric_{metric}",
            )
    st.caption("Filled points are in the statistics. Hollow points are invalid or rejected sweeps shown by the filters.")

with tab_overlay:
    per_width = st.checkbox("Current per channel width (µA/µm)", value=True, key="fet_compare_per_width")
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
    if curves:
        st.plotly_chart(overlay_figure(curves, colors, per_width), width="stretch", theme=None, config=export_config(f"{batch}_overlay"))
    left_out = len(shown) - len(curves)
    st.caption(f"{len(curves)} curve(s) from {len({c['group'] for c in curves})} group(s)." + (f" {left_out} invalid or rejected sweep(s) are not drawn." if left_out else ""))

with tab_table:
    summary = group_summary(shown, shown_groups)
    keep = ["group", "sweep", "n_sweeps", "n_included"] + [f"{m}_{s}" for m in metrics for s in ("median", "mean", "std")]
    st.dataframe(summary[keep], hide_index=True, width="stretch")
    st.caption("Columns follow the quantities chosen on the Statistics tab.")

with tab_groups:
    st.caption("Names and order used in every plot and table. A change is saved at once.")
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
        # a row whose order was just typed goes before the row that already had that number
        ranked = edited.assign(display=[names[g] for g in edited["group in file"]], kept=~moved).sort_values(["order", "kept"], kind="stable")
        review.group_names = {group: name for group, name in names.items() if name != group}
        review.group_order = list(dict.fromkeys(ranked["display"]))
        put_review(batch, review)
        st.session_state[GROUPS_NONCE_KEY] += 1
        st.rerun()
