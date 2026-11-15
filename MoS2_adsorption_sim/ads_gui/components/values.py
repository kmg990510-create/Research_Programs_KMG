"""Pose metric and energy decomposition tables for the detail view. No Streamlit import."""

from __future__ import annotations

import pandas as pd

from ads_core.model import PoseResult
from ads_core.pipeline import BatchRun


def _fmt(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def pose_values_table(result: PoseResult, run: BatchRun | None = None) -> pd.DataFrame:
    """Every extracted energy and geometry metric of one pose as quantity / value / unit rows."""
    e_slab_ref = None
    e_mol_ref = None
    e_total_relaxed = None
    if run is not None:
        ref_slab = next((r for r in run.references if r.kind == "slab" and r.item_id == result.surface_id), None)
        ref_mol = next((r for r in run.references if r.kind == "molecule" and r.item_id == result.molecule_id), None)
        e_slab_ref = ref_slab.energy_total_eV if ref_slab is not None else None
        e_mol_ref = ref_mol.energy_total_eV if ref_mol is not None else None
        art = run.artifacts.get(result.pose_id)
        if art is not None and art.trajectory_steps:
            e_total_relaxed = art.trajectory_steps[-1].energy_eV

    rows = [
        ("E_ads (total)", result.e_ads_eV, "eV"),
        ("E_ads (uMLIP)", result.e_ads_umlip_eV, "eV"),
        ("E_ads (DFT-D3)", result.e_ads_d3_eV, "eV"),
        ("vdW fraction", result.vdw_fraction, "-"),
        ("E_int (interaction)", result.e_int_eV, "eV"),
        ("E_def, slab", result.e_def_slab_eV, "eV"),
        ("E_def, mol", result.e_def_mol_eV, "eV"),
        ("E_total (slab+mol)", e_total_relaxed, "eV"),
        ("E_slab (reference)", e_slab_ref, "eV"),
        ("E_mol (reference)", e_mol_ref, "eV"),
        ("d_min (slab-mol)", result.d_min_A, "Å"),
        ("d_min atom pair", result.d_min_pair or "-", "-"),
        ("dz_com (above top S)", result.dz_com_A, "Å"),
        ("Lateral shift", result.lateral_shift_A, "Å"),
        ("Tilt change", result.tilt_deg, "deg"),
        ("Max bond stretch", result.max_bond_stretch_pct, "%"),
        ("Slab RMSD", result.slab_rmsd_A, "Å"),
        ("Final fmax", result.fmax_final_eV_per_A, "eV/Å"),
        ("Relaxation steps", result.n_steps, "steps"),
        ("Converged", result.converged, "-"),
        ("Initial site", result.site_type, "-"),
        ("Orientation", f"{result.orientation} (az={result.azimuth_deg:.0f} deg, z0={result.initial_height_A:.2f} Å)", "-"),
        ("Calculator", f"{result.calculator_id} (D3={'on' if result.d3_enabled else 'off'})", "-"),
        ("Status", result.status, "-"),
        ("Reasons", ", ".join(result.reasons) if result.reasons else "-", "-"),
    ]
    return pd.DataFrame([{"quantity": name, "value": _fmt(val), "unit": unit} for name, val, unit in rows])
