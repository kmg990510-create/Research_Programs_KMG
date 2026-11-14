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
from labkit.sidebar import sidebar_section  # noqa: E402

st.set_page_config(page_title="Compare · FET Analysis", layout="wide")
st.title("Compare")
st.caption("Statistics use the sweeps that are not invalid and not rejected.")

batch, run, review, frame = active()
groups = ordered_groups(frame, review)
shown = filters(frame, groups)

with sidebar_section("3) Groups", expanded=False):
    st.caption("Rename groups and set their order in plots and tables.")
    originals = list(dict.fromkeys(frame["group"]))
    table = pd.DataFrame(
        {
            "group": originals,
            "name": [review.display_group(g) for g in originals],
            "order": [groups.index(review.display_group(g)) + 1 for g in originals],
        }
    )
    edited = st.data_editor(
        table,
        hide_index=True,
        disabled=["group"],
        column_config={"order": st.column_config.NumberColumn("order", min_value=1, step=1)},
        key=f"fet_compare_groups_{batch}",
    )
    if st.button("Save groups", key="fet_compare_save_groups", width="stretch"):
        names = {row["group"]: (str(row["name"]).strip() or row["group"]) for row in edited.to_dict("records")}
        review.group_names = {group: name for group, name in names.items() if name != group}
        ranked = edited.assign(display=[names[g] for g in edited["group"]]).sort_values("order", kind="stable")
        review.group_order = list(dict.fromkeys(ranked["display"]))
        put_review(batch, review)
        st.rerun()

stop_if_empty(shown)
shown_groups = [g for g in groups if g in set(shown["group_display"])]
colors = categorical_colors(groups)

tab_overlay, tab_stats, tab_table = st.tabs(["Overlay", "Statistics", "Summary table"])

with tab_overlay:
    per_width = st.checkbox("Current per channel width (µA/µm)", value=True, key="fet_compare_per_width")
    curves = []
    for row in shown.itertuples():
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
    st.plotly_chart(overlay_figure(curves, colors, per_width), width="stretch", theme=None, config=export_config(f"{batch}_overlay"))
    st.caption(f"{len(curves)} curve(s) from {len(shown_groups)} group(s).")

with tab_stats:
    metric = st.selectbox("Quantity", list(METRICS), format_func=metric_label, key="fet_compare_metric")
    st.plotly_chart(metric_figure(shown, metric, shown_groups, colors), width="stretch", theme=None, config=export_config(f"{batch}_{metric}"))
    st.caption("Filled points are in the statistics. Hollow points are invalid or rejected sweeps shown by the filters.")

with tab_table:
    summary = group_summary(shown, shown_groups)
    pick = st.multiselect("Quantities", list(METRICS), default=list(METRICS)[:4], format_func=metric_label, key="fet_compare_table_metrics")
    keep = ["group", "sweep", "n_sweeps", "n_included"] + [f"{m}_{s}" for m in pick for s in ("median", "mean", "std")]
    st.dataframe(summary[keep], hide_index=True, width="stretch")
