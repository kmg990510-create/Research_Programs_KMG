"""Coverage & Dimer Inspector: graphical 3D/2D viewer for N=1..4 packing, intermolecular distances, and dimer formation."""

from __future__ import annotations

import sys
from pathlib import Path

_SIM_ROOT = Path(__file__).resolve().parents[2]
for _path in (_SIM_ROOT, _SIM_ROOT.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from ads_core.report.coverage_view import (  # noqa: E402
    CoverageStudyBundle,
    analyze_disulfide_geometry,
    analyze_multimol_contacts,
    list_coverage_studies,
    load_coverage_study,
    overview_distances_df,
)
from ads_gui.components.atoms2d import multimol_top_side_png  # noqa: E402
from ads_gui.components.figures import coverage_distance_summary_figure, pair_distance_heatmap_figure  # noqa: E402
from ads_gui.components.viewer3d import multimol_3d_html  # noqa: E402
from ads_gui.state import results_root  # noqa: E402
from labkit.figure_size import figure_options_inputs, figure_size_inputs, show_figure  # noqa: E402
from labkit.sidebar import sidebar_section  # noqa: E402

STUDY_KEY = "ads_cov_study"
CONTACT_MODES = ("All key contacts", "S···S", "N···S", "N···N", "H···S/N", "Heavy···Heavy", "COM···COM", "None")

st.set_page_config(page_title="Coverage & Dimer · MoS2 Adsorption", layout="wide")
st.title("Coverage & Dimer Inspector")
st.caption("Inspect N=1–4 spatial packing, periodic intermolecular distances (S···S, N···S, Heavy···Heavy), and dimer formation in 3D/2D.")

root = results_root()
studies = list_coverage_studies(root)
with sidebar_section("1) Study"):
    if not studies:
        st.caption("No coverage/multilayer study found under data/results/. Run scripts/run_multilayer_study.py first.")
        chosen_study = None
    else:
        cur = st.session_state.get(STUDY_KEY)
        idx = studies.index(cur) if cur in studies else len(studies) - 1
        chosen_study = st.selectbox("Coverage study", studies, index=idx, key="cov_study_select")
        st.session_state[STUDY_KEY] = chosen_study
        st.caption(f"Folder: {root / chosen_study}")

if chosen_study is None:
    st.info("No coverage/multilayer study to display yet. Run `scripts/run_multilayer_study.py --study configs/track_a_4atp.yaml`.")
    st.stop()


@st.cache_resource(show_spinner="Loading coverage structures...", max_entries=6)
def _cached_study(folder_str: str) -> CoverageStudyBundle:
    return load_coverage_study(folder_str)


bundle = _cached_study(str(root / chosen_study))
overview_df = overview_distances_df(bundle)

with sidebar_section("2) Display & Distance Options"):
    repeat_label = st.radio("Periodic XY tiling", ["1×1 unit cell", "2×2 periodic repeat"], index=1, key="cov_repeat_xy")
    repeat_xy = 2 if repeat_label.startswith("2×2") else 1
    show_ghost = st.checkbox("Show initial unrelaxed Ghost", value=True, key="cov_show_ghost")
    color_by_mol = st.checkbox("Color each molecule differently", value=True, key="cov_color_mol")
    contact_mode = st.selectbox("3D/2D distance highlights", CONTACT_MODES, index=0, key="cov_contact_mode")

with sidebar_section("3) Figure size", expanded=False):
    figure_options_inputs()
    overview_size = figure_size_inputs("cov_overview", "Overview chart", 880, 500)
    heatmap_size = figure_size_inputs("cov_heatmap", "Pair distance heatmap", 420, 340)


def _select_lines(contacts: dict, mode: str) -> list:
    if mode == "None":
        return []
    if mode == "All key contacts":
        return [contacts[k] for k in ("S···S", "N···S", "Heavy···Heavy", "S–S bond") if k in contacts]
    return [contacts[mode]] if mode in contacts else []


tab_over, tab_inspect, tab_dimer = st.tabs(
    ["N=1–4 Coverage & Distances", "N=1–4 3D & 2D Viewer", "Dimer & Disulfide Formation"]
)

with tab_over:
    if overview_df.empty:
        st.warning("No coverage cases found in coverage_summary.csv.")
    else:
        nx, ny = bundle.metadata.get("supercell", [6, 6])
        area = float(bundle.metadata.get("slab_area_A2", 0.0))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Supercell", f"{nx}×{ny} MoS2")
        c2.metric("Slab area", f"{area:.1f} Å²")
        c3.metric("Cases relaxed", len(overview_df))
        min_ss_all = overview_df["min_S_S_A"].dropna()
        c4.metric("Closest intact S···S", "-" if min_ss_all.empty else f"{float(min_ss_all.min()):.2f} Å")

        show_figure(
            coverage_distance_summary_figure(overview_df, height=overview_size.height_px),
            overview_size,
            filename=f"{bundle.study_name}_coverage_distances",
            key="cov_overview_chart",
        )
        st.subheader("Intermolecular Distances & Energy Table")
        st.dataframe(overview_df, hide_index=True, width="stretch")

with tab_inspect:
    case_ids = list(overview_df["case_id"]) if not overview_df.empty else []
    extra_vac = [k.removesuffix("_relaxed") for k in sorted(bundle.structures) if k.endswith("_vacancy_relaxed")]
    inspect_choices = case_ids + [v for v in extra_vac if v not in case_ids]
    if not inspect_choices:
        st.info("No relaxed case XYZ structures found in structures/.")
    else:
        sel_case = st.selectbox("Select structure (N=1..4 or vacancy)", inspect_choices, index=0, key="cov_inspect_case")
        rel_key = f"{sel_case}_relaxed"
        init_key = f"{sel_case}_initial"
        rel_atoms = bundle.structures[rel_key]
        init_atoms = bundle.structures.get(init_key)

        geo = analyze_multimol_contacts(rel_atoms, bundle.slab_count, bundle.mol_count)
        lines = _select_lines(geo.contacts, contact_mode)

        row_meta = overview_df[overview_df["case_id"] == sel_case]
        mc = st.columns(5)
        mc[0].metric("Molecules (N)", geo.n_molecules)
        mc[1].metric("E_ads / mol", "-" if row_meta.empty else f"{float(row_meta.iloc[0]['e_ads_per_mol_eV']):+.3f} eV")
        mc[2].metric("min Heavy···Heavy", "-" if "Heavy···Heavy" not in geo.contacts else f"{geo.contacts['Heavy···Heavy'].distance_A:.2f} Å")
        mc[3].metric("min S···S", "-" if "S···S" not in geo.contacts else f"{geo.contacts['S···S'].distance_A:.2f} Å")
        mc[4].metric("min N···S", "-" if "N···S" not in geo.contacts else f"{geo.contacts['N···S'].distance_A:.2f} Å")

        col_3d, col_2d = st.columns([6, 5], gap="medium")
        with col_3d:
            st.markdown("**Interactive 3D View** *(drag to rotate, scroll to zoom)*")
            components.html(
                multimol_3d_html(
                    rel_atoms,
                    slab_count=bundle.slab_count,
                    mol_count=bundle.mol_count,
                    initial_atoms=init_atoms,
                    repeat_xy=repeat_xy,
                    show_ghost=show_ghost,
                    color_by_molecule=color_by_mol,
                    distance_lines=lines,
                    width=640,
                    height=460,
                ),
                height=475,
            )
        with col_2d:
            st.markdown("**Orthographic Top (xy) & Side (xz) Projections**")
            png_bytes = multimol_top_side_png(
                rel_atoms,
                slab_count=bundle.slab_count,
                mol_count=bundle.mol_count,
                title=f"{sel_case} ({repeat_label})",
                repeat_xy=repeat_xy,
                distance_lines=lines,
            )
            st.image(png_bytes, width="stretch")

        st.markdown("**Per-Molecule Position, Tilt & Nearest-Neighbor Distances**")
        st.dataframe(geo.per_molecule, hide_index=True, width="stretch")

        if geo.n_molecules >= 2:
            mat_col, mat_sel_col = st.columns([3, 2])
            mat_kind = mat_sel_col.selectbox(
                "Pairwise matrix metric",
                ["S···S", "N···S", "Heavy···Heavy", "N···N", "COM···COM"],
                index=0,
                key="cov_matrix_kind",
            )
            mol_labels = [f"Mol {i + 1}" for i in range(geo.n_molecules)]
            with mat_col:
                show_figure(
                    pair_distance_heatmap_figure(
                        geo.matrices[mat_kind],
                        mol_labels,
                        f"{sel_case} — Pairwise MIC {mat_kind} Distances (Å)",
                        height=heatmap_size.height_px,
                    ),
                    heatmap_size,
                    filename=f"{sel_case}_{mat_kind}_matrix",
                    key="cov_pair_heatmap",
                )
            with mat_sel_col:
                st.markdown("**Shortest Key Contact Vectors (MIC)**")
                c_rows = [
                    {
                        "Contact": c.kind,
                        "Pair": f"Mol {c.mol_i + 1} ↔ Mol {c.mol_j + 1}" if c.mol_i != c.mol_j else "Periodic image",
                        "Distance (Å)": round(c.distance_A, 3),
                        "Crosses PBC": c.crosses_pbc,
                    }
                    for c in geo.contacts.values()
                ]
                st.dataframe(pd.DataFrame(c_rows), hide_index=True, width="stretch")

with tab_dimer:
    precursor_cases = [cid for cid in overview_df["case_id"] if cid.startswith("N2_")] if not overview_df.empty else []
    pre_col, dis_col = st.columns(2, gap="medium")

    with pre_col:
        st.subheader("1) Intact Precursor Dimers (2 × 4-ATP)")
        if not precursor_cases:
            st.info("No N=2 precursor dimer cases found.")
        else:
            sel_n2 = st.selectbox("Precursor N=2 geometry", precursor_cases, index=0, key="cov_dimer_n2")
            n2_rel = bundle.structures[f"{sel_n2}_relaxed"]
            n2_init = bundle.structures.get(f"{sel_n2}_initial")
            n2_geo = analyze_multimol_contacts(n2_rel, bundle.slab_count, bundle.mol_count)
            n2_lines = _select_lines(n2_geo.contacts, contact_mode)
            n2_ss = "-" if "S···S" not in n2_geo.contacts else f"{n2_geo.contacts['S···S'].distance_A:.2f} Å"
            n2_ns = "-" if "N···S" not in n2_geo.contacts else f"{n2_geo.contacts['N···S'].distance_A:.2f} Å"
            st.caption(f"Relaxed contacts: **S···S = {n2_ss}** · **N···S = {n2_ns}**")
            components.html(
                multimol_3d_html(
                    n2_rel,
                    slab_count=bundle.slab_count,
                    mol_count=bundle.mol_count,
                    initial_atoms=n2_init,
                    repeat_xy=repeat_xy,
                    show_ghost=show_ghost,
                    color_by_molecule=color_by_mol,
                    distance_lines=n2_lines,
                    width=560,
                    height=420,
                ),
                height=435,
            )
            st.image(
                multimol_top_side_png(
                    n2_rel,
                    slab_count=bundle.slab_count,
                    mol_count=bundle.mol_count,
                    title=sel_n2,
                    repeat_xy=1,
                    distance_lines=n2_lines,
                ),
                width="stretch",
            )

    with dis_col:
        st.subheader("2) Disulfide Dimer (4-ATP–S–S–4-ATP)")
        gas_rel = bundle.structures.get("disulfide_gas_relaxed")
        ads_init = bundle.structures.get("disulfide_adsorbed_initial")
        ads_rel = bundle.structures.get("disulfide_adsorbed_relaxed")
        slab_ref = bundle.structures.get("reference_slab_relaxed")
        if ads_rel is None and gas_rel is None:
            st.info("No disulfide structures found in this study.")
        else:
            drep = analyze_disulfide_geometry(slab_ref, gas_rel, ads_init, ads_rel, bundle.slab_count)
            dis_view_choice = st.radio(
                "Disulfide view",
                ["Adsorbed on MoS2 (with initial Ghost)", "Gas-phase relaxed"],
                horizontal=True,
                key="cov_dis_view",
            )
            d_lines = [x for x in (drep.ss_bond_line, drep.n_span_line) if x is not None]
            if dis_view_choice.startswith("Adsorbed") and ads_rel is not None:
                st.caption(
                    f"d(S–S) relaxed = **{drep.d_ss_relaxed_A:.2f} Å** "
                    f"(initial {drep.d_ss_initial_A:.2f} Å) · "
                    f"C–S–S–C dihedral = **{drep.dihedral_cssc_relaxed_deg:.1f}°**"
                    if drep.d_ss_relaxed_A and drep.d_ss_initial_A and drep.dihedral_cssc_relaxed_deg is not None
                    else ""
                )
                components.html(
                    multimol_3d_html(
                        ads_rel,
                        slab_count=bundle.slab_count,
                        mol_count=len(ads_rel) - bundle.slab_count,
                        initial_atoms=ads_init,
                        repeat_xy=repeat_xy,
                        show_ghost=show_ghost,
                        color_by_molecule=False,
                        distance_lines=d_lines,
                        width=560,
                        height=420,
                    ),
                    height=435,
                )
                st.image(
                    multimol_top_side_png(
                        ads_rel,
                        slab_count=bundle.slab_count,
                        mol_count=len(ads_rel) - bundle.slab_count,
                        title="disulfide_adsorbed_relaxed",
                        repeat_xy=1,
                        distance_lines=d_lines,
                    ),
                    width="stretch",
                )
            elif gas_rel is not None:
                components.html(
                    multimol_3d_html(
                        gas_rel,
                        slab_count=0,
                        mol_count=len(gas_rel),
                        show_ghost=False,
                        color_by_molecule=False,
                        width=560,
                        height=420,
                    ),
                    height=435,
                )

            st.markdown("**Disulfide Geometry & Formation Energetics**")
            geom_rows = [
                {"Metric": "d(S–S) gas relaxed (Å)", "Value": None if drep.d_ss_gas_A is None else round(drep.d_ss_gas_A, 3)},
                {"Metric": "d(S–S) adsorbed initial / relaxed (Å)", "Value": f"{drep.d_ss_initial_A:.3f} → {drep.d_ss_relaxed_A:.3f}" if drep.d_ss_initial_A and drep.d_ss_relaxed_A else None},
                {"Metric": "∠C–S–S relaxed (deg)", "Value": f"{drep.angle_css_relaxed_deg[0]:.1f}, {drep.angle_css_relaxed_deg[1]:.1f}" if drep.angle_css_relaxed_deg else None},
                {"Metric": "C–S–S–C dihedral gas / ads (deg)", "Value": f"{drep.dihedral_cssc_gas_deg:.1f} / {drep.dihedral_cssc_relaxed_deg:.1f}" if drep.dihedral_cssc_gas_deg is not None and drep.dihedral_cssc_relaxed_deg is not None else None},
                {"Metric": "Ring tilts on MoS2 (deg)", "Value": f"{drep.ring_tilts_relaxed_deg[0]:.1f}, {drep.ring_tilts_relaxed_deg[1]:.1f}" if drep.ring_tilts_relaxed_deg else None},
                {"Metric": "S heights above MoS2 top (Å)", "Value": f"{drep.s_heights_above_slab_A[0]:.2f}, {drep.s_heights_above_slab_A[1]:.2f}" if drep.s_heights_above_slab_A else None},
                {"Metric": "N···N end-to-end span (Å)", "Value": None if drep.n_to_n_span_A is None else round(drep.n_to_n_span_A, 2)},
            ]
            st.dataframe(pd.DataFrame(geom_rows), hide_index=True, width="stretch")
            if not bundle.disulfide_df.empty:
                st.dataframe(bundle.disulfide_df, hide_index=True, width="stretch")
