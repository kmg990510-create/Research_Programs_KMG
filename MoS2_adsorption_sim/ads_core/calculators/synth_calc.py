"""Smooth analytical ASE calculators (uMLIP + D3 surrogate) for fast GPU-free testing.

All energies and forces are C2-smooth pairwise functions evaluated under exact
periodic minimum-image conventions via ``ase.neighborlist.neighbor_list``, with
analytical derivatives ``F = -grad(E)`` so BFGS/LBFGS/FIRE converge reliably.
"""

from __future__ import annotations

import numpy as np
from ase import Atoms
from ase.calculators.calculator import Calculator, all_changes
from ase.data import covalent_radii
from ase.neighborlist import neighbor_list


def _taper(r: np.ndarray, r_on: float, r_off: float) -> tuple[np.ndarray, np.ndarray]:
    """C2 quintic switching function s(r) in [0, 1] and ds/dr."""
    span = r_off - r_on
    t = np.clip((r - r_on) / span, 0.0, 1.0)
    t2 = t * t
    t3 = t2 * t
    s = 1.0 - 10.0 * t3 + 15.0 * t3 * t - 6.0 * t3 * t2
    ds = np.where(
        (r > r_on) & (r < r_off),
        (-30.0 * t2 + 60.0 * t3 - 30.0 * t3 * t) / span,
        0.0,
    )
    return s, ds


def _morse_with_taper(
    r: np.ndarray,
    de: float,
    alpha: float,
    r0: float,
    r_on: float,
    r_off: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Shifted Morse potential D_e * [(1 - exp(-a(r-r0)))^2 - 1] * taper(r)."""
    exp_term = np.exp(-alpha * (r - r0))
    one_minus = 1.0 - exp_term
    v = de * (one_minus * one_minus - 1.0)
    dv = 2.0 * de * alpha * one_minus * exp_term
    s, ds = _taper(r, r_on, r_off)
    return v * s, dv * s + v * ds


def _exp_repulsion_with_taper(
    r: np.ndarray,
    amp: float,
    r_ref: float,
    rho: float,
    r_on: float,
    r_off: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Soft exponential Pauli repulsion amp * exp(-(r - r_ref)/rho) * taper(r)."""
    v = amp * np.exp(-(r - r_ref) / rho)
    dv = -(1.0 / rho) * v
    s, ds = _taper(r, r_on, r_off)
    return v * s, dv * s + v * ds


def _unique_pairs(atoms: Atoms, cutoff: float):
    """Return unique (i < j) periodic neighbor pairs within ``cutoff``."""
    if len(atoms) < 2:
        empty_i = np.array([], dtype=int)
        empty_f = np.array([], dtype=float)
        return empty_i, empty_i, np.zeros((0, 3), dtype=float), empty_f
    i_idx, j_idx, d_vec, d_len = neighbor_list("ijDd", atoms, cutoff)
    mask = (i_idx < j_idx) & (d_len > 1.0e-8)
    return i_idx[mask], j_idx[mask], d_vec[mask], d_len[mask]


def _accumulate_forces(
    n_atoms: int,
    i_idx: np.ndarray,
    j_idx: np.ndarray,
    d_vec: np.ndarray,
    d_len: np.ndarray,
    de_dr: np.ndarray,
) -> np.ndarray:
    forces = np.zeros((n_atoms, 3), dtype=float)
    if len(i_idx) == 0:
        return forces
    # D = r_j - r_i => d(r_ij)/dr_j = +D/d, d(r_ij)/dr_i = -D/d => F_i = +(dE/dr)(D/d), F_j = -(dE/dr)(D/d)
    prefactor = (de_dr / d_len)[:, None] * d_vec
    np.add.at(forces, i_idx, prefactor)
    np.add.at(forces, j_idx, -prefactor)
    return forces


class SynthUmlipCalculator(Calculator):
    """Surrogate short-range/chemical potential (no long-range dispersion)."""

    implemented_properties = ["energy", "forces"]

    def __init__(
        self,
        *,
        mo_s_de_eV: float = 1.8,
        mo_s_r0_A: float = 2.414,
        mo_adsorbate_de_eV: float = 0.70,
        mo_adsorbate_r0_A: float = 2.25,
        s_repulsion_eV: float = 0.65,
    ) -> None:
        super().__init__()
        self.mo_s_de_eV = float(mo_s_de_eV)
        self.mo_s_r0_A = float(mo_s_r0_A)
        self.mo_adsorbate_de_eV = float(mo_adsorbate_de_eV)
        self.mo_adsorbate_r0_A = float(mo_adsorbate_r0_A)
        self.s_repulsion_eV = float(s_repulsion_eV)
        self._cutoff = 4.7

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        numbers = self.atoms.get_atomic_numbers()
        i_idx, j_idx, d_vec, r = _unique_pairs(self.atoms, self._cutoff)

        total_e = 0.0
        de_dr = np.zeros_like(r)

        if len(r) > 0:
            zi = numbers[i_idx]
            zj = numbers[j_idx]
            is_slab_i = (zi == 42) | (zi == 16)
            is_slab_j = (zj == 42) | (zj == 16)

            # 1. Intra-slab pairs (Mo=42, S=16)
            both_slab = is_slab_i & is_slab_j
            mo_s = both_slab & (((zi == 42) & (zj == 16)) | ((zi == 16) & (zj == 42)))
            same_slab_elem = both_slab & (zi == zj)

            if np.any(mo_s):
                e, g = _morse_with_taper(r[mo_s], self.mo_s_de_eV, 1.6, self.mo_s_r0_A, 2.75, 3.05)
                total_e += float(np.sum(e))
                de_dr[mo_s] += g
            if np.any(same_slab_elem):
                e, g = _morse_with_taper(r[same_slab_elem], 0.35, 1.4, 3.165, 3.45, 3.85)
                total_e += float(np.sum(e))
                de_dr[same_slab_elem] += g

            # 2. Intra-molecule pairs (neither atom is Mo or S)
            both_mol = (~is_slab_i) & (~is_slab_j)
            if np.any(both_mol):
                has_h = both_mol & ((zi == 1) | (zj == 1))
                both_h = both_mol & (zi == 1) & (zj == 1)
                al_h = has_h & (~both_h) & ((zi == 13) | (zj == 13))
                xh_bond = has_h & (~both_h) & (~al_h)
                heavy_mol = both_mol & (~has_h)

                if np.any(al_h):
                    # Geminal 1-3 Al...H in TMA is non-bonded: prevent methyl hydrogens from folding onto Al
                    e, g = _exp_repulsion_with_taper(r[al_h], 0.45, 2.25, 0.25, 2.45, 2.75)
                    total_e += float(np.sum(e))
                    de_dr[al_h] += g
                if np.any(xh_bond):
                    r0_xh = covalent_radii[zi[xh_bond]] + covalent_radii[zj[xh_bond]]
                    e, g = _morse_with_taper(r[xh_bond], 4.0, 1.9, r0_xh, 1.15 * r0_xh, 1.30 * r0_xh)
                    total_e += float(np.sum(e))
                    de_dr[xh_bond] += g
                if np.any(heavy_mol):
                    r0_hh = covalent_radii[zi[heavy_mol]] + covalent_radii[zj[heavy_mol]]
                    e, g = _morse_with_taper(r[heavy_mol], 3.5, 1.8, r0_hh, 1.12 * r0_hh, 1.26 * r0_hh)
                    total_e += float(np.sum(e))
                    de_dr[heavy_mol] += g
                    # Non-bonded heavy-heavy repulsion (keeps angles e.g. C-Al-C open)
                    e_rep, g_rep = _exp_repulsion_with_taper(r[heavy_mol], 0.55, 2.95, 0.30, 3.35, 3.80)
                    # Only apply beyond bond cutoff so bonded heavy pairs are unaffected
                    beyond_bond = r[heavy_mol] > 1.28 * r0_hh
                    idx_hm = np.where(heavy_mol)[0][beyond_bond]
                    total_e += float(np.sum(e_rep[beyond_bond]))
                    de_dr[idx_hm] += g_rep[beyond_bond]
                if np.any(both_h):
                    e, g = _exp_repulsion_with_taper(r[both_h], 0.25, 1.45, 0.25, 1.75, 2.25)
                    total_e += float(np.sum(e))
                    de_dr[both_h] += g

            # 3. Slab-molecule pairs (uMLIP without D3: S repulsion + exposed-Mo chemical bond)
            cross = is_slab_i ^ is_slab_j
            if np.any(cross):
                slab_z = np.where(is_slab_i, zi, zj)
                mol_z = np.where(is_slab_i, zj, zi)

                s_cross_heavy = cross & (slab_z == 16) & (mol_z > 1)
                if np.any(s_cross_heavy):
                    e, g = _exp_repulsion_with_taper(r[s_cross_heavy], self.s_repulsion_eV, 2.3, 0.35, 2.9, 3.5)
                    total_e += float(np.sum(e))
                    de_dr[s_cross_heavy] += g

                s_cross_h = cross & (slab_z == 16) & (mol_z == 1)
                if np.any(s_cross_h):
                    e, g = _exp_repulsion_with_taper(r[s_cross_h], 0.40 * self.s_repulsion_eV, 2.1, 0.30, 2.7, 3.45)
                    total_e += float(np.sum(e))
                    de_dr[s_cross_h] += g

                mo_heavy_other = cross & (slab_z == 42) & (mol_z > 1) & (mol_z != 13)
                if np.any(mo_heavy_other):
                    e, g = _morse_with_taper(
                        r[mo_heavy_other],
                        self.mo_adsorbate_de_eV,
                        1.7,
                        self.mo_adsorbate_r0_A,
                        3.1,
                        3.85,
                    )
                    total_e += float(np.sum(e))
                    de_dr[mo_heavy_other] += g

                mo_al = cross & (slab_z == 42) & (mol_z == 13)
                if np.any(mo_al):
                    # Bulky Lewis-acid Al in TMA coordinates to exposed rim Mo around V_S
                    e, g = _morse_with_taper(
                        r[mo_al],
                        1.20 * self.mo_adsorbate_de_eV,
                        1.40,
                        self.mo_adsorbate_r0_A + 0.35,
                        3.6,
                        4.55,
                    )
                    total_e += float(np.sum(e))
                    de_dr[mo_al] += g

                mo_h = cross & (slab_z == 42) & (mol_z == 1)
                if np.any(mo_h):
                    e, g = _exp_repulsion_with_taper(r[mo_h], 0.50, 2.15, 0.32, 2.65, 3.25)
                    total_e += float(np.sum(e))
                    de_dr[mo_h] += g

        self.results["energy"] = float(total_e)
        self.results["forces"] = _accumulate_forces(len(self.atoms), i_idx, j_idx, d_vec, r, de_dr)


class SynthD3Calculator(Calculator):
    """Surrogate damped C6 van der Waals dispersion calculator (DFT-D3 analog)."""

    implemented_properties = ["energy", "forces"]

    def __init__(self, *, c6_eV_A6: float = 36.0, damp_r0_A: float = 3.1) -> None:
        super().__init__()
        self.c6_eV_A6 = float(c6_eV_A6)
        self.damp_r0_A = float(damp_r0_A)
        self._r_on = 8.0
        self._r_off = 10.5

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        numbers = self.atoms.get_atomic_numbers()
        i_idx, j_idx, d_vec, r = _unique_pairs(self.atoms, self._r_off)

        total_e = 0.0
        de_dr = np.zeros_like(r)

        if len(r) > 0:
            zi = numbers[i_idx]
            zj = numbers[j_idx]
            is_slab_i = (zi == 42) | (zi == 16)
            is_slab_j = (zj == 42) | (zj == 16)
            # Scale effective C6 by atomic weight factor (stronger for heavy atoms than H)
            w_i = np.where(zi == 1, 0.35, np.sqrt(zi / 8.0))
            w_j = np.where(zj == 1, 0.35, np.sqrt(zj / 8.0))
            # Keep D3 focused on non-bonded long-range pairs (cross slab-mol and long intra-slab/mol)
            cross = is_slab_i ^ is_slab_j
            long_same = (~cross) & (r > 2.8)
            active = cross | long_same
            if np.any(active):
                r_act = r[active]
                c6_eff = self.c6_eV_A6 * w_i[active] * w_j[active]
                denom = r_act**6 + self.damp_r0_A**6
                v = -c6_eff / denom
                dv = 6.0 * c6_eff * (r_act**5) / (denom * denom)
                s, ds = _taper(r_act, self._r_on, self._r_off)
                total_e += float(np.sum(v * s))
                de_dr[active] += dv * s + v * ds

        self.results["energy"] = float(total_e)
        self.results["forces"] = _accumulate_forces(len(self.atoms), i_idx, j_idx, d_vec, r, de_dr)
