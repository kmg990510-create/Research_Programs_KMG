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
from ads_core.pipeline import md_results_table, ordered_groups  # noqa: E402
from ads_core.report.export import binding_curves_summary_table  # noqa: E402
from ads_core.report.summary import METRICS, metric_label, molecule_summary  # noqa: E402
from ads_gui.components.atoms2d import slab_sites_png  # noqa: E402
from ads_gui.components.figures import (  # noqa: E402
    binding_curves_figure,
    energy_decomposition_figure,
    metric_figure,
    site_energy_map_figure,
)
from ads_gui.state import (  # noqa: E402
    active,
    filters,
    render_ads_chrome,
    render_group_manager_popover,
    stop_if_empty,
)
from labkit.chrome import panel_title  # noqa: E402
from labkit.figure_size import figure_settings_popover, show_figure  # noqa: E402
from labkit.plot_theme import categorical_colors  # noqa: E402

CMP_VIEWS = ("Statistics", "Energy & Binding Curves", "Surface Site Map", "Summary table")
DEFAULT_METRICS = ("e_ads_eV", "vdw_fraction", "d_min_A", "dz_com_A")

render_ads_chrome("Compare", "Compare · MoS2 Adsorption")
st.header("Compare")
st.caption("Statistics, Boltzmann averages, and energy decomposition use included poses (status != invalid and decision != rejected).")

batch, run, review, frame = active()
groups = ordered_groups(frame, review)
shown = filters(frame, groups)
if shown.empty and not run.md_results:
    stop_if_empty(shown)

shown_groups = [g for g in groups if g in set(shown["group_display"])]
colors = categorical_colors(groups)
temp_K = ReportSettings.from_config(run.config).boltzmann_temp_K
summary_df = molecule_summary(shown, temp_K, shown_groups)

view_store = st.session_state.setdefault("ads_compare_view_store", {"view": CMP_VIEWS[0]})
if st.session_state.get("ads_compare_view") not in CMP_VIEWS:
    st.session_state["ads_compare_view"] = (
        view_store["view"] if view_store.get("view") in CMP_VIEWS else CMP_VIEWS[0]
    )

c_view, c_grp, c_fig = st.columns([3.4, 1.0, 1.0], vertical_alignment="center")
active_view = (
    c_view.segmented_control(
        "Compare view",
        CMP_VIEWS,
        key="ads_compare_view",
        label_visibility="collapsed",
    )
    or CMP_VIEWS[0]
)
view_store["view"] = active_view
render_group_manager_popover(batch, frame, review, groups, container=c_grp)
sizes = figure_settings_popover(
    [
        ("ads_stats", "Statistics: one quantity", 560, 400),
        ("ads_wide", "Energy / Binding / Site charts", 860, 460),
    ],
    container=c_fig,
)
stats_size = sizes["ads_stats"]
wide_size = sizes["ads_wide"]

if active_view == "Statistics":
    with st.container(border=True):
        panel_title("Group Statistics")
        if shown.empty:
            st.info("No relaxation poses in this MD-only batch. Check **Energy & Binding Curves** for MD results.")
        else:
            metric_opts = list(METRICS)
            m_store = st.session_state.setdefault("ads_compare_metrics_store", {})
            default_metrics = [m for m in DEFAULT_METRICS if m in metric_opts]
            if "ads_compare_metrics" not in st.session_state:
                stored_m = [m for m in m_store.get("metrics", default_metrics) if m in metric_opts]
                st.session_state["ads_compare_metrics"] = stored_m if "metrics" in m_store else default_metrics
            else:
                st.session_state["ads_compare_metrics"] = [
                    m for m in st.session_state["ads_compare_metrics"] if m in metric_opts
                ]
            metrics = st.multiselect(
                "Quantities",
                metric_opts,
                format_func=metric_label,
                key="ads_compare_metrics",
            )
            m_store["metrics"] = list(metrics)
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

elif active_view == "Energy & Binding Curves":
    with st.container(border=True):
        panel_title("Energy Decomposition")
        decomp_opts = ("uMLIP vs DFT-D3 (vdW)", "Interaction vs Deformation (E_int + E_def)")
        d_store = st.session_state.setdefault("ads_compare_decomp_store", {"mode": decomp_opts[0]})
        if st.session_state.get("ads_compare_decomp_mode") not in decomp_opts:
            st.session_state["ads_compare_decomp_mode"] = (
                d_store["mode"] if d_store.get("mode") in decomp_opts else decomp_opts[0]
            )
        decomp_mode = st.radio("Decomposition view", decomp_opts, horizontal=True, key="ads_compare_decomp_mode")
        d_store["mode"] = decomp_mode
        mode_arg = "int_vs_def" if decomp_mode.startswith("Interaction") else "umlip_vs_d3"
        if not summary_df.empty:
            show_figure(
                energy_decomposition_figure(summary_df, mode=mode_arg, height=wide_size.height_px),
                wide_size,
                filename=f"{batch}_decomp_{mode_arg}",
                key="ads_compare_decomp_chart",
            )

    with st.container(border=True):
        panel_title("1D E(z) Binding Curves")
        if run.binding_curves:
            curve_labels = [
                f"{c.surface_id} | {c.molecule_id} ({c.site_type}) [{c.calculator_id}]"
                for c in run.binding_curves
            ]
            options = ["All curves (Total E_ads)"] + curve_labels
            c_store = st.session_state.setdefault("ads_compare_curve_store", {})
            default_curve = curve_labels[0] if len(curve_labels) == 1 else options[0]
            if st.session_state.get("ads_compare_curve_select") not in options:
                st.session_state["ads_compare_curve_select"] = (
                    c_store["choice"] if c_store.get("choice") in options else default_curve
                )
            choice = st.selectbox("Curve view", options, key="ads_compare_curve_select")
            c_store["choice"] = choice
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

    if run.md_results:
        with st.container(border=True):
            panel_title("Finite-Temperature MD Summary")
            st.dataframe(md_results_table(run.md_results), hide_index=True, width="stretch")

elif active_view == "Surface Site Map":
    with st.container(border=True):
        panel_title("Surface Site Map")
        surface_choices = list(dict.fromkeys(shown["surface_id"].astype(str)))
        if not surface_choices:
            st.info("No relaxation poses available to plot on the surface site map.")
        else:
            s_store = st.session_state.setdefault("ads_compare_site_store", {})
            if st.session_state.get("ads_compare_site_surface") not in surface_choices:
                st.session_state["ads_compare_site_surface"] = (
                    s_store["surface"] if s_store.get("surface") in surface_choices else surface_choices[0]
                )
            chosen_surf = st.selectbox("Surface", surface_choices, key="ads_compare_site_surface")
            s_store["surface"] = chosen_surf
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

else:
    with st.container(border=True):
        panel_title("Molecule & Surface Summary")
        if summary_df.empty:
            st.info("No relaxation poses in this MD-only batch.")
        else:
            table_df = summary_df.copy()
            if not frame.empty and "group_key" in frame.columns and "group_key" not in table_df.columns:
                key_by_display = dict(zip(frame["group_display"].astype(str), frame["group_key"].astype(str)))
                table_df.insert(
                    1,
                    "group_key",
                    table_df["group_display"].astype(str).map(lambda g: key_by_display.get(g, g)),
                )
            st.dataframe(table_df, hide_index=True, width="stretch")
        st.caption("Rename or reorder groups from **Manage groups** above. Edits save immediately to review.json.")
