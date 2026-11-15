"""Energy decomposition (uMLIP/D3, interaction/deformation) and geometric descriptors."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from ase import Atoms
from ase.geometry import find_mic, get_distances

from ads_core.calculators.factory import CalculatorBundle
from ads_core.model import MoleculeSpec, PoseSpec
from ads_core.simulation.reference import ReferenceResult, single_point_components
from ads_core.simulation.relax import RelaxationResult


@dataclass(frozen=True)
class PoseMetrics:
    """Numeric energy decomposition and structural descriptors for one relaxed pose."""

    e_ads_eV: float | None
    e_ads_umlip_eV: float | None
    e_ads_d3_eV: float | None
    vdw_fraction: float | None
    e_int_eV: float | None
    e_def_slab_eV: float | None
    e_def_mol_eV: float | None
    d_min_A: float | None
    d_min_pair: str | None
    dz_com_A: float | None
    lateral_shift_A: float | None
    tilt_deg: float | None
    max_bond_stretch_pct: float | None
    slab_rmsd_A: float | None


def _unwrap_positions(atoms: Atoms, indices: tuple[int, ...]) -> np.ndarray:
    pos = atoms.get_positions()[list(indices)]
    if len(pos) <= 1:
        return pos.copy()
    rel, _ = find_mic(pos - pos[0], cell=atoms.cell, pbc=atoms.pbc)
    return pos[0] + rel


def _principal_axis(positions: np.ndarray) -> np.ndarray | None:
    if len(positions) < 2:
        return None
    centered = positions - np.mean(positions, axis=0)
    cov = np.cov(centered.T)
    _, eigvecs = np.linalg.eigh(cov)
    vec = eigvecs[:, 2]
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 1e-10 else None


def compute_pose_metrics(
    pose: PoseSpec,
    relaxation: RelaxationResult,
    ref_slab: ReferenceResult,
    ref_mol: ReferenceResult,
    molecule: MoleculeSpec,
    calc_bundle: CalculatorBundle,
) -> PoseMetrics:
    """Compute energy decomposition and structural descriptors from a relaxed pose."""
    if relaxation.failed:
        return PoseMetrics(
            e_ads_eV=None,
            e_ads_umlip_eV=None,
            e_ads_d3_eV=None,
            vdw_fraction=None,
            e_int_eV=None,
            e_def_slab_eV=None,
            e_def_mol_eV=None,
            d_min_A=None,
            d_min_pair=None,
            dz_com_A=None,
            lateral_shift_A=None,
            tilt_deg=None,
            max_bond_stretch_pct=None,
            slab_rmsd_A=None,
        )

    relaxed = relaxation.relaxed_atoms
    initial = relaxation.initial_atoms
    slab_idx = list(pose.slab_indices)
    mol_idx = list(pose.mol_indices)

    # 1. Geometric descriptors
    _, dist_matrix = get_distances(
        relaxed.positions[slab_idx],
        relaxed.positions[mol_idx],
        cell=relaxed.cell,
        pbc=relaxed.pbc,
    )
    flat_argmin = int(np.argmin(dist_matrix))
    s_local, m_local = divmod(flat_argmin, len(mol_idx))
    d_min_A = float(dist_matrix[s_local, m_local])
    symbols = relaxed.get_chemical_symbols()
    d_min_pair = f"{symbols[mol_idx[m_local]]}-{symbols[slab_idx[s_local]]}"

    tags = relaxed.get_tags()
    top_s_idx = [i for i in slab_idx if tags[i] == 2]
    top_s_z = float(np.mean(relaxed.positions[top_s_idx, 2])) if top_s_idx else float(np.mean(relaxed.positions[slab_idx, 2]))

    mol_init_pos = _unwrap_positions(initial, pose.mol_indices)
    mol_fin_pos = _unwrap_positions(relaxed, pose.mol_indices)
    masses = relaxed.get_masses()[mol_idx]
    total_mass = float(np.sum(masses))
    com_init = np.sum(mol_init_pos * masses[:, None], axis=0) / total_mass
    com_fin = np.sum(mol_fin_pos * masses[:, None], axis=0) / total_mass

    dz_com_A = float(com_fin[2] - top_s_z)
    lz = float(relaxed.cell[2, 2])
    if relaxed.pbc[2] and lz > 0:
        dz_com_A -= lz * round(dz_com_A / lz)

    _, shift_mat = get_distances(
        np.array([[com_init[0], com_init[1], 0.0]]),
        np.array([[com_fin[0], com_fin[1], 0.0]]),
        cell=relaxed.cell,
        pbc=(relaxed.pbc[0], relaxed.pbc[1], False),
    )
    lateral_shift_A = float(shift_mat[0, 0])

    ax_init = _principal_axis(mol_init_pos)
    ax_fin = _principal_axis(mol_fin_pos)
    if ax_init is not None and ax_fin is not None:
        dot = float(np.clip(abs(np.dot(ax_init, ax_fin)), 0.0, 1.0))
        tilt_deg: float | None = float(math.degrees(math.acos(dot)))
    else:
        tilt_deg = None

    if molecule.reference_bonds:
        stretches: list[float] = []
        for i, j, r_ref in molecule.reference_bonds:
            r_fin = float(np.linalg.norm(mol_fin_pos[i] - mol_fin_pos[j]))
            stretches.append(100.0 * (r_fin - r_ref) / r_ref)
        max_bond_stretch_pct: float | None = float(max(stretches))
    else:
        max_bond_stretch_pct = None

    if len(ref_slab.relaxed_atoms) == len(slab_idx):
        disp, _ = find_mic(
            relaxed.positions[slab_idx] - ref_slab.relaxed_atoms.positions,
            cell=relaxed.cell,
            pbc=relaxed.pbc,
        )
        slab_rmsd_A: float | None = float(np.sqrt(np.mean(np.sum(disp * disp, axis=1))))
    else:
        slab_rmsd_A = None

    # 2. Energy decomposition (requires converged or valid reference energies)
    if (
        ref_slab.energy_total_eV is None
        or ref_mol.energy_total_eV is None
        or ref_slab.energy_umlip_eV is None
        or ref_mol.energy_umlip_eV is None
    ):
        return PoseMetrics(
            e_ads_eV=None,
            e_ads_umlip_eV=None,
            e_ads_d3_eV=None,
            vdw_fraction=None,
            e_int_eV=None,
            e_def_slab_eV=None,
            e_def_mol_eV=None,
            d_min_A=d_min_A,
            d_min_pair=d_min_pair,
            dz_com_A=dz_com_A,
            lateral_shift_A=lateral_shift_A,
            tilt_deg=tilt_deg,
            max_bond_stretch_pct=max_bond_stretch_pct,
            slab_rmsd_A=slab_rmsd_A,
        )

    e_comp_tot, e_comp_umlip, e_comp_d3 = single_point_components(relaxed, calc_bundle)
    e_ads_eV = float(e_comp_tot - (ref_slab.energy_total_eV + ref_mol.energy_total_eV))
    e_ads_umlip_eV = float(e_comp_umlip - (ref_slab.energy_umlip_eV + ref_mol.energy_umlip_eV))

    if (
        e_comp_d3 is not None
        and ref_slab.energy_d3_eV is not None
        and ref_mol.energy_d3_eV is not None
    ):
        e_ads_d3_eV: float | None = float(e_comp_d3 - (ref_slab.energy_d3_eV + ref_mol.energy_d3_eV))
        vdw_fraction: float | None = float(e_ads_d3_eV / e_ads_eV) if e_ads_eV < -1.0e-6 else None
    else:
        e_ads_d3_eV = None
        vdw_fraction = None

    # Deformation energies: single-point evaluations of deformed fragments
    deformed_slab = relaxed[slab_idx].copy()
    e_def_slab_tot, _, _ = single_point_components(deformed_slab, calc_bundle)
    e_def_slab_eV = float(e_def_slab_tot - ref_slab.energy_total_eV)

    deformed_mol = relaxed[mol_idx].copy()
    # Unwrap molecule and place inside the gas-phase box to avoid artificial PBC self-interaction
    deformed_mol.set_positions(mol_fin_pos)
    deformed_mol.set_cell(ref_mol.relaxed_atoms.cell)
    deformed_mol.set_pbc(ref_mol.relaxed_atoms.pbc)
    deformed_mol.center()
    e_def_mol_tot, _, _ = single_point_components(deformed_mol, calc_bundle)
    e_def_mol_eV = float(e_def_mol_tot - ref_mol.energy_total_eV)

    e_int_eV = float(e_ads_eV - (e_def_slab_eV + e_def_mol_eV))

    return PoseMetrics(
        e_ads_eV=e_ads_eV,
        e_ads_umlip_eV=e_ads_umlip_eV,
        e_ads_d3_eV=e_ads_d3_eV,
        vdw_fraction=vdw_fraction,
        e_int_eV=e_int_eV,
        e_def_slab_eV=e_def_slab_eV,
        e_def_mol_eV=e_def_mol_eV,
        d_min_A=d_min_A,
        d_min_pair=d_min_pair,
        dz_com_A=dz_com_A,
        lateral_shift_A=lateral_shift_A,
        tilt_deg=tilt_deg,
        max_bond_stretch_pct=max_bond_stretch_pct,
        slab_rmsd_A=slab_rmsd_A,
    )
