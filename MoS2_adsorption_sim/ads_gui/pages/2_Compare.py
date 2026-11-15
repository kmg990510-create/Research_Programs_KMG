"""Compare: group statistics, energy decomposition, 1D E(z) binding curves, and surface site map."""

from __future__ import annotations

import sys
from pathlib import Path

_SIM_ROOT = Path(__file__).resolve().parents[2]
for _path in (_SIM_ROOT, _SIM_ROOT.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from ads_core.model import ReportSettings  # noqa: E402
from ads_core.pipeline import ordered_groups  # noqa: E402
from ads_core.report.export import binding_curves_summary_table  # noqa: E402
from ads_core.report.summary import METRICS, metric_label, molecule_summary  # noqa: E402
from ads_gui.components.atoms2d import slab_sites_png  # noqa: E402
from ads_gui.components.figures import (  # noqa: E402
    binding_curves_figure,
    energy_decomposition_figure,
    metric_figure,
    site_energy_map_figure,
)
from ads_gui.state import active, filters, put_review, stop_if_empty  # noqa: E402
from labkit.figure_size import figure_options_inputs, figure_size_inputs, show_figure  # noqa: E402
from labkit.plot_theme import categorical_colors  # noqa: E402
from labkit.sidebar import sidebar_section  # noqa: E402

GROUPS_NONCE_KEY = "ads_compare_groups_nonce"
DEFAULT_METRICS = ("e_ads_eV", "vdw_fraction", "d_min_A", "dz_com_A")

st.set_page_config(page_title="Compare · MoS2 Adsorption", layout="wide")
st.title("Compare")
st.caption("Statistics, Boltzmann averages, and energy decomposition use included poses (status != invalid and decision != rejected).")

batch, run, review, frame = active()
groups = ordered_groups(frame, review)
shown = filters(frame, groups)
with sidebar_section("3) Figure size", expanded=False):
    figure_options_inputs()
    stats_size = figure_size_inputs("ads_stats", "Statistics: one quantity", 560, 400)
    wide_size = figure_size_inputs("ads_wide", "Energy / Binding / Site charts", 860, 460)
stop_if_empty(shown)

shown_groups = [g for g in groups if g in set(shown["group_display"])]
colors = categorical_colors(groups)
temp_K = ReportSettings.from_config(run.config).boltzmann_temp_K
summary_df = molecule_summary(shown, temp_K, shown_groups)

tab_stats, tab_energy, tab_sites, tab_groups = st.tabs(
    ["Statistics", "Energy & Binding Curves", "Surface Site Map", "Summary & Group Names"]
)

with tab_stats:
    metrics = st.multiselect(
        "Quantities",
        list(METRICS),
        default=[m for m in DEFAULT_METRICS if m in METRICS],
        format_func=metric_label,
        key="ads_compare_metrics",
    )
    if not metrics:
        st.info("Select at least one quantity to plot.")
    if stats_size.width_px is None:
        places = [col for start in range(0, len(metrics), 2) for col in st.columns(2)]
    else:
        places = [st.container(horizontal=True)] * len(metrics)
    for place, metric in zip(places, metrics):
        with place:
            show_figure(
                metric_figure(shown, metric, shown_groups, colors, height=stats_size.height_px),
                stats_size,
                filename=f"{batch}_{metric}",
                key=f"ads_compare_metric_{metric}",
            )
    st.caption("Filled points enter statistics; hollow points are invalid or rejected poses.")

with tab_energy:
    decomp_mode = st.radio(
        "Decomposition view",
        ["uMLIP vs DFT-D3 (vdW)", "Interaction vs Deformation (E_int + E_def)"],
        horizontal=True,
        key="ads_compare_decomp_mode",
    )
    mode_arg = "int_vs_def" if decomp_mode.startswith("Interaction") else "umlip_vs_d3"
    if not summary_df.empty:
        show_figure(
            energy_decomposition_figure(summary_df, mode=mode_arg, height=wide_size.height_px),
            wide_size,
            filename=f"{batch}_decomp_{mode_arg}",
            key="ads_compare_decomp_chart",
        )

    st.subheader("1D E(z) Binding Curves")
    if run.binding_curves:
        curve_labels = [
            f"{c.surface_id} | {c.molecule_id} ({c.site_type}) [{c.calculator_id}]"
            for c in run.binding_curves
        ]
        options = ["All curves (Total E_ads)"] + curve_labels
        choice = st.selectbox("Curve view", options, index=1 if len(curve_labels) == 1 else 0, key="ads_compare_curve_select")
        sel_idx = None if choice == options[0] else curve_labels.index(choice)
        show_figure(
            binding_curves_figure(run.binding_curves, selected_idx=sel_idx, height=wide_size.height_px),
            wide_size,
            filename=f"{batch}_binding_curve",
            key="ads_compare_binding_chart",
        )
        st.dataframe(binding_curves_summary_table(run.binding_curves), hide_index=True, width="stretch")
    else:
        st.info("No 1D binding curves recorded in this batch. Enable 'Scan 1D E(z) binding curves' on Run.")

with tab_sites:
    surface_choices = list(dict.fromkeys(shown["surface_id"].astype(str)))
    chosen_surf = st.selectbox("Surface", surface_choices, key="ads_compare_site_surface")
    left_map, right_map = st.columns([1.3, 1.0])
    with left_map:
        show_figure(
            site_energy_map_figure(run, shown, chosen_surf, height=wide_size.height_px),
            wide_size,
            filename=f"{batch}_{chosen_surf}_site_map",
            key="ads_compare_site_map_chart",
        )
    with right_map:
        slab = run.slabs.get(chosen_surf)
        if slab is not None:
            st.image(slab_sites_png(slab, run.config), width="stretch", caption=f"pymatgen AdsorbateSiteFinder map — {chosen_surf}")

with tab_groups:
    st.subheader("Molecule & Surface Summary")
    if not summary_df.empty:
        st.dataframe(summary_df, hide_index=True, width="stretch")

    st.subheader("Group display names and order")
    st.caption("Used across every plot and exported CSV. Changes are saved immediately to review.json.")
    st.session_state.setdefault(GROUPS_NONCE_KEY, 0)
    originals = list(dict.fromkeys(frame["group_key"].astype(str)))
    table = pd.DataFrame(
        {
            "group key": originals,
            "name": [review.display_group(g) for g in originals],
            "order": [groups.index(review.display_group(g)) + 1 for g in originals],
        }
    )
    edited = st.data_editor(
        table,
        hide_index=True,
        width="stretch",
        disabled=["group key"],
        column_config={"order": st.column_config.NumberColumn("order", min_value=1, step=1, required=True)},
        key=f"ads_compare_groups_{batch}_{st.session_state[GROUPS_NONCE_KEY]}",
    )
    names = {r["group key"]: (str(r["name"] or "").strip() or r["group key"]) for r in edited.to_dict("records")}
    moved = edited["order"] != table["order"]
    if moved.any() or names != dict(zip(table["group key"], table["name"])):
        ranked = edited.assign(display=[names[g] for g in edited["group key"]], kept=~moved).sort_values(["order", "kept"], kind="stable")
        review.group_names = {g: n for g, n in names.items() if n != g}
        review.group_order = list(dict.fromkeys(ranked["display"]))
        put_review(batch, review)
        st.session_state[GROUPS_NONCE_KEY] += 1
        st.rerun()
