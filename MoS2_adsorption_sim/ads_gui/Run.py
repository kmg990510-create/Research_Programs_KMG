"""Run (entry page): select an existing batch or launch a new adsorption screening batch."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_SIM_ROOT = Path(__file__).resolve().parents[1]
for _path in (_SIM_ROOT, _SIM_ROOT.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from ads_core import __version__  # noqa: E402
from ads_core.config import Config, load_config  # noqa: E402
from ads_core.model import (  # noqa: E402
    MoleculeSettings,
    PoseSettings,
    RelaxationSettings,
    ReportSettings,
    SITE_BRIDGE,
    SITE_HOLLOW,
    SITE_MO_TOP,
    SITE_S_TOP,
    SITE_VS,
    SITE_VS2,
    SITE_VS_RIM,
    SlabSettings,
    VALID_BACKENDS,
    VALID_DEFECT_TYPES,
    VALID_OPTIMIZERS,
    VALID_ORIENTATIONS,
)
from ads_core.pipeline import ordered_groups, poses_frame, run_batch, status_counts  # noqa: E402
from ads_core.report.export import export_run, warnings_frame  # noqa: E402
from ads_core.report.summary import molecule_summary  # noqa: E402
from ads_gui.state import (  # noqa: E402
    ACTIVE_BATCH_KEY,
    choose_batch,
    clear_run_cache,
    delete_trashed_item_permanently,
    get_review,
    list_trashed_items,
    load_run,
    molecules_root,
    restore_trashed_item,
    results_root,
    safe_batch_name,
    trash_batch,
    trash_molecule_file,
)

SITE_OPTIONS = [SITE_MO_TOP, SITE_S_TOP, SITE_HOLLOW, SITE_BRIDGE, SITE_VS, SITE_VS_RIM, SITE_VS2]

st.set_page_config(page_title="MoS2 Adsorption · Run", layout="wide")
st.title("Run")
st.caption(
    f"MoS2_adsorption_sim {__version__} · Run uMLIP + DFT-D3 (or synthetic potential) screening batches into `data/results/<batch>`. "
    "Reviewers then inspect 3D structures and convergence on **Poses**, compare energetics on **Compare**, and export files on **Finalize**."
)

base_cfg = load_config()
mol_defaults = MoleculeSettings.from_config(base_cfg)
slab_defaults = SlabSettings.from_config(base_cfg)
pose_defaults = PoseSettings.from_config(base_cfg)
relax_defaults = RelaxationSettings.from_config(base_cfg)

batch = choose_batch()

mol_dir = molecules_root()
existing_mol_files = sorted(p for p in mol_dir.iterdir() if p.is_file() and p.suffix.lower() in {".xyz", ".mol", ".sdf"}) if mol_dir.is_dir() else []

with st.expander("Create and run a simulation batch", expanded=batch is None):
    batch_raw = st.text_input("Batch name", value="demo_screening", key="run_batch_name", help="Saved under data/results/<batch name>.")

    s1, s2, s3 = st.columns([2, 1, 1])
    substrate_options = list(slab_defaults.substrate_candidates)
    substrate_idx = substrate_options.index(slab_defaults.substrate) if slab_defaults.substrate in substrate_options else 0
    chosen_substrate = s1.selectbox(
        "Substrate",
        substrate_options,
        index=substrate_idx,
        format_func=lambda s: f"{s} (active)" if s in slab_defaults.supported_substrates else f"{s} (planned)",
        disabled=len(slab_defaults.supported_substrates) <= 1,
        key="run_substrate",
        help="Currently fixed to 2H-MoS2; additional substrates in config.yaml will be enabled in upcoming updates.",
    )
    nx = int(
        s2.number_input(
            "Supercell nx",
            min_value=slab_defaults.supercell_min_n,
            max_value=slab_defaults.supercell_max_n,
            value=slab_defaults.supercell_nx,
            step=1,
            key="run_nx",
        )
    )
    ny = int(
        s3.number_input(
            "Supercell ny",
            min_value=slab_defaults.supercell_min_n,
            max_value=slab_defaults.supercell_max_n,
            value=slab_defaults.supercell_ny,
            step=1,
            key="run_ny",
        )
    )
    planned_substrates = [s for s in slab_defaults.substrate_candidates if s not in slab_defaults.supported_substrates]
    st.caption(
        f"Active substrate: `{chosen_substrate}` ({nx}×{ny} supercell) · "
        f"Planned candidates: {', '.join(planned_substrates) if planned_substrates else 'none'}"
    )

    c1, c2 = st.columns(2)
    chosen_surfaces = c1.multiselect("Surfaces", list(VALID_DEFECT_TYPES), default=["pristine", "V_S"], key="run_surfaces")
    chosen_presets = c2.multiselect("Preset molecules", list(mol_defaults.presets), default=["H2O"], key="run_presets")

    uploaded = st.file_uploader(
        "Upload custom molecules (.xyz, .mol, .sdf)",
        type=["xyz", "mol", "sdf"],
        accept_multiple_files=True,
        key="run_upload_molecules",
    )
    chosen_custom = st.multiselect(
        "Existing uploaded molecule files",
        [p.name for p in existing_mol_files],
        default=[],
        key="run_custom_molecules",
    )

    p1, p2, p3 = st.columns(3)
    default_backend_idx = VALID_BACKENDS.index("synth_morse")
    chosen_backend = p1.selectbox(
        "Calculator backend",
        list(VALID_BACKENDS),
        index=default_backend_idx,
        key="run_backend",
        help="Use synth_morse for instant local/CPU tests; use mace_mp or mattersim in WSL2 GPU environments.",
    )
    enable_d3 = p2.checkbox("Enable DFT-D3 dispersion", value=True, key="run_enable_d3")
    scan_curves = p3.checkbox("Scan 1D E(z) binding curves", value=True, key="run_scan_curves")
    d1, d2 = st.columns(2)
    compare_no_d3 = d1.checkbox(
        "Compare with no-D3 baseline",
        value=False,
        disabled=not enable_d3,
        key="run_compare_no_d3",
        help="Also run without DFT-D3 to isolate dispersion binding contribution.",
    )
    scan_all_sites = d2.checkbox(
        "Scan E(z) for all site types",
        value=False,
        disabled=not scan_curves,
        key="run_scan_all_sites",
        help="Scan one 1D E(z) curve per selected site type instead of one per pair.",
    )

    chosen_optimizer = relax_defaults.optimizer
    chosen_fmax = relax_defaults.fmax_eV_per_A
    chosen_steps = relax_defaults.max_steps
    chosen_sites: list[str] = []
    chosen_orientations = list(pose_defaults.orientations)
    chosen_azimuths = list(pose_defaults.azimuth_angles_deg)

    if st.checkbox("Advanced pose & optimizer settings", value=False, key="run_show_advanced"):
        a1, a2, a3 = st.columns(3)
        chosen_optimizer = str(a1.selectbox("Optimizer", list(VALID_OPTIMIZERS), index=list(VALID_OPTIMIZERS).index(relax_defaults.optimizer), key="run_opt"))
        chosen_fmax = float(a2.number_input("fmax (eV/Å)", min_value=0.005, max_value=0.5, value=float(relax_defaults.fmax_eV_per_A), step=0.005, format="%.3f", key="run_fmax"))
        chosen_steps = int(a3.number_input("Max steps", min_value=10, max_value=1000, value=int(relax_defaults.max_steps), step=10, key="run_max_steps"))

        b1, b2, b3 = st.columns(3)
        chosen_sites = b1.multiselect("Restrict sites (empty = all)", SITE_OPTIONS, default=[], key="run_sites")
        chosen_orientations = b2.multiselect("Orientations", list(VALID_ORIENTATIONS), default=list(pose_defaults.orientations), key="run_orientations")
        az_opts = sorted({float(a) for a in (*pose_defaults.azimuth_candidates_deg, *pose_defaults.azimuth_angles_deg)})
        chosen_azimuths = b3.multiselect("Azimuth angles (deg)", az_opts, default=list(pose_defaults.azimuth_angles_deg), key="run_azimuths")

    cli_surfs = " ".join(f"{s}_{nx}x{ny}" for s in (chosen_surfaces or ["pristine"]))
    cli_mols = " ".join((chosen_presets or ["H2O"]) + chosen_custom)
    cli_flags = (
        f"--backend {chosen_backend}"
        + ("" if enable_d3 else " --no-d3")
        + (" --compare-no-d3" if (enable_d3 and compare_no_d3) else "")
        + (" --scan-binding-curves" if scan_curves else "")
        + (" --scan-all-sites" if (scan_curves and scan_all_sites) else "")
    )
    st.code(f"python -m ads_core run --batch {safe_batch_name(batch_raw) or 'batch'} --surfaces {cli_surfs} --molecules {cli_mols} {cli_flags}", language="bash")

    if st.button("Run simulation batch", type="primary", key="run_execute_btn"):
        clean_name = safe_batch_name(batch_raw)
        saved_uploads: list[Path] = []
        if uploaded:
            mol_dir.mkdir(parents=True, exist_ok=True)
            for item in uploaded:
                dest = mol_dir / Path(item.name).name
                dest.write_bytes(item.getvalue())
                saved_uploads.append(dest)
        molecule_inputs: list[str | Path] = list(chosen_presets) + [mol_dir / fname for fname in chosen_custom]
        for up_path in saved_uploads:
            if up_path not in molecule_inputs:
                molecule_inputs.append(up_path)

        if not clean_name:
            st.error("Enter a valid batch name.")
        elif not chosen_surfaces:
            st.error("Select at least one surface.")
        elif not molecule_inputs:
            st.error("Select at least one preset molecule or upload a structure file.")
        elif not chosen_orientations:
            st.error("Select at least one orientation.")
        else:
            payload = copy.deepcopy(base_cfg.as_dict())
            payload["slab"]["supercell_nx"] = nx
            payload["slab"]["supercell_ny"] = ny
            payload["relaxation"]["optimizer"] = chosen_optimizer
            payload["relaxation"]["fmax_eV_per_A"] = chosen_fmax
            payload["relaxation"]["max_steps"] = chosen_steps
            run_cfg = Config(payload, source=base_cfg.source)

            prog = st.progress(0.0, text="Starting batch simulation...")

            def _on_progress(cur: int, tot: int, pid: str) -> None:
                frac = min(1.0, max(0.0, cur / max(1, tot)))
                prog.progress(frac, text=f"Relaxing pose {cur}/{tot}: {pid}")

            try:
                sim_run = run_batch(
                    clean_name,
                    run_cfg,
                    surfaces=chosen_surfaces,
                    molecules=molecule_inputs,
                    supercell=(nx, ny),
                    backend=chosen_backend,
                    d3_enabled=enable_d3,
                    site_types=chosen_sites or None,
                    orientations=chosen_orientations,
                    azimuth_angles_deg=chosen_azimuths or [0.0],
                    scan_binding_curves=scan_curves,
                    scan_all_sites=bool(scan_curves and scan_all_sites),
                    compare_no_d3=bool(enable_d3 and compare_no_d3),
                    progress_callback=_on_progress,
                )
                out_dir = results_root() / clean_name
                review_existing = get_review(clean_name)
                export_run(sim_run, review_existing, out_dir)
                clear_run_cache()
                st.session_state[ACTIVE_BATCH_KEY] = clean_name
                st.rerun()
            except Exception as exc:
                st.error(f"Batch run failed: {exc}")

trashed_batches = list_trashed_items("results")
trashed_molecules = list_trashed_items("molecules")
trash_total = len(trashed_batches) + len(trashed_molecules)

with st.expander(f"Manage data (delete / trash: {trash_total})", expanded=False):
    if batch is not None:
        st.markdown("**Active simulation batch**")
        if st.button(f"Move batch '{batch}' to trash", key="run_trash_active_batch"):
            trash_batch(batch)
            st.toast(f"Moved batch '{batch}' to trash.")
            st.rerun()
    if existing_mol_files:
        st.markdown("**Uploaded molecule files**")
        del_mols = st.multiselect(
            "Select molecule files to move to trash",
            [p.name for p in existing_mol_files],
            default=[],
            key="run_trash_mol_select",
        )
        if st.button("Move selected molecule(s) to trash", disabled=not del_mols, key="run_trash_mols_btn"):
            for fname in del_mols:
                trash_molecule_file(fname)
            st.toast(f"Moved {len(del_mols)} molecule file(s) to trash.")
            st.rerun()

    st.divider()
    st.markdown("**Trash bin (restore or permanently delete)**")
    if not trashed_batches and not trashed_molecules:
        st.caption("Trash is empty.")
    else:
        trash_items = [
            {"scope": "results", "label": f"[Batch] {e['original_name']} ({e['deleted_at'][:19]})", **e}
            for e in trashed_batches
        ] + [
            {"scope": "molecules", "label": f"[Molecule] {e['original_name']} ({e['deleted_at'][:19]})", **e}
            for e in trashed_molecules
        ]
        labels = [item["label"] for item in trash_items]
        selected_label = st.selectbox("Trashed item", labels, key="run_trash_selected")
        selected_item = trash_items[labels.index(selected_label)]

        t1, t2 = st.columns(2)
        if t1.button("Restore selected item", key="run_restore_trash_btn"):
            try:
                restored_name = restore_trashed_item(selected_item["scope"], selected_item["entry_id"])
                if selected_item["scope"] == "results":
                    st.session_state[ACTIVE_BATCH_KEY] = restored_name
                st.toast(f"Restored '{restored_name}'.")
                st.rerun()
            except Exception as exc:
                st.error(f"Restore failed: {exc}")

        confirm_perm = t2.checkbox("Confirm permanent deletion", value=False, key="run_confirm_perm_delete")
        if t2.button(
            "Delete permanently",
            disabled=not confirm_perm,
            type="secondary",
            key="run_perm_delete_btn",
        ):
            delete_trashed_item_permanently(selected_item["scope"], selected_item["entry_id"])
            st.toast(f"Permanently deleted '{selected_item['original_name']}'.")
            st.rerun()

if batch is None:
    st.info("No batch yet. Configure parameters above and click **Run simulation batch**.")
    st.stop()

run = load_run(batch)
review = get_review(batch)
frame = poses_frame(run, review)
counts = status_counts(frame)

m_cols = st.columns(5)
m_cols[0].metric("Surfaces", len(run.slabs))
m_cols[1].metric("Molecules", len(run.molecules))
m_cols[2].metric("Valid poses", counts["valid"])
m_cols[3].metric("Need attention", counts["attention"])
m_cols[4].metric("Invalid", counts["invalid"])

st.caption(
    f"Calculator: `{run.calculator_id}` · DFT-D3: `{'enabled' if run.d3_enabled else 'disabled'}` · "
    f"1D binding curves: `{len(run.binding_curves)}`"
)

st.subheader("Group summary (active batch)")
temp_K = ReportSettings.from_config(run.config).boltzmann_temp_K
summary = molecule_summary(frame, temp_K, ordered_groups(frame, review))
if not summary.empty:
    show_cols = [
        "group_display",
        "n_poses",
        "n_included",
        "best_site",
        "e_ads_min_eV",
        "e_ads_boltzmann_eV",
        "vdw_fraction_at_best",
        "d_min_at_best_A",
    ]
    st.dataframe(summary[show_cols], hide_index=True, width="stretch")

with st.expander(f"All poses ({len(frame)})", expanded=False):
    pose_cols = ["pose_id", "surface_id", "molecule_id", "site_type", "orientation", "status", "e_ads_eV", "d_min_A", "decision"]
    st.dataframe(frame[pose_cols], hide_index=True, width="stretch")

warn_df = warnings_frame(run)
with st.expander(f"Warnings ({len(warn_df)})", expanded=False):
    st.dataframe(warn_df, hide_index=True, width="stretch")
