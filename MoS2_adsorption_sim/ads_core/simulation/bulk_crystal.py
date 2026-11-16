"""Bulk 4-ATP Pca2_1 molecular crystal cohesive energy, zwitterion check, and (001) cleavage study."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.build import make_supercell
from ase.filters import FrechetCellFilter
from ase.geometry import get_distances
from ase.io import write as ase_write
from ase.optimize import BFGS, FIRE, LBFGS
from pymatgen.symmetry.groups import SpaceGroup

from ads_core.builders.molecule import load_molecule_file
from ads_core.calculators.factory import CalculatorBundle, build_calculator_bundle
from ads_core.config import Config, load_config
from ads_core.simulation.metrics import single_point_components
from ads_core.simulation.reference import ReferenceResult, relax_reference_molecule

_OPTIMIZERS = {
    "BFGS": BFGS,
    "LBFGS": LBFGS,
    "FIRE": FIRE,
}

# 1 amu / A^3 -> g/cm^3
_AMU_A3_TO_G_CM3 = 1.66053906660


@dataclass(frozen=True)
class BulkCrystalSettings:
    """YAML-backed settings for bulk Pca2_1 4-ATP crystal & (001) cleavage calculations."""

    study_name: str
    base_config_path: Path
    output_dir: Path
    molecule_id: str
    molecule_path: Path
    anchor_element: str
    space_group: str
    cell_a_A: float
    cell_b_A: float
    cell_c_A: float
    min_intermol_dist_A: float
    n_rot_trials: int
    n_candidates_per_tautomer: int
    tautomers: tuple[str, ...]
    relax_cell: bool
    optimizer: str
    fmax_eV_per_A: float
    max_steps: int
    cell_max_steps: int
    supercell_vac: tuple[int, int, int]
    slab_repeat_xy: tuple[int, int]
    slab_vacuum_A: float
    seed: int

    @classmethod
    def from_config(cls, cfg: Config, *, project_root: Path | None = None) -> "BulkCrystalSettings":
        if project_root is None:
            project_root = cfg.source.resolve().parents[1] if cfg.source is not None else Path.cwd()

        def _res(rel: str) -> Path:
            p = Path(rel)
            return p if p.is_absolute() else (project_root / p)

        sc_vac = [int(round(v)) for v in cfg.number_list("vacancy_and_surface.bulk_supercell")]
        slab_rep = [int(round(v)) for v in cfg.number_list("vacancy_and_surface.slab_repeat_xy")]
        if len(sc_vac) != 3 or len(slab_rep) != 2:
            raise ValueError("bulk_supercell must have 3 ints and slab_repeat_xy must have 2 ints")

        return cls(
            study_name=cfg.text("study.name"),
            base_config_path=_res(cfg.text("study.base_config_path")),
            output_dir=_res(cfg.text("study.output_dir")),
            molecule_id=cfg.text("adsorbate.molecule_id"),
            molecule_path=_res(cfg.text("adsorbate.molecule_path")),
            anchor_element=cfg.text("adsorbate.anchor_element"),
            space_group=cfg.text("crystal.space_group"),
            cell_a_A=cfg.number("crystal.a_A"),
            cell_b_A=cfg.number("crystal.b_A"),
            cell_c_A=cfg.number("crystal.c_A"),
            min_intermol_dist_A=cfg.number("crystal.min_intermol_dist_A"),
            n_rot_trials=cfg.integer("candidates.n_rot_trials"),
            n_candidates_per_tautomer=cfg.integer("candidates.n_per_tautomer"),
            tautomers=tuple(cfg.text_list("candidates.tautomers")),
            relax_cell=cfg.boolean("relaxation.relax_cell"),
            optimizer=cfg.text("relaxation.optimizer"),
            fmax_eV_per_A=cfg.number("relaxation.fmax_eV_per_A"),
            max_steps=cfg.integer("relaxation.max_steps"),
            cell_max_steps=cfg.integer("relaxation.cell_max_steps"),
            supercell_vac=(sc_vac[0], sc_vac[1], sc_vac[2]),
            slab_repeat_xy=(slab_rep[0], slab_rep[1]),
            slab_vacuum_A=cfg.number("vacancy_and_surface.slab_vacuum_A"),
            seed=cfg.integer("candidates.seed"),
        )


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def make_zwitterion_molecule(
    atoms: Atoms,
    *,
    anchor_element: str = "S",
    nh_bond_A: float = 1.03,
) -> Atoms:
    """Transfer the thiol H atom onto the amino N atom in tetrahedral NH3+ geometry."""
    work = atoms.copy()
    syms = work.get_chemical_symbols()
    pos = work.get_positions()
    if anchor_element not in syms or "N" not in syms:
        raise ValueError(f"Expected both {anchor_element!r} and 'N' in molecule, got {syms}")

    s_idx = syms.index(anchor_element)
    n_idx = syms.index("N")
    h_indices = [i for i, s in enumerate(syms) if s == "H"]
    h_thiol = min(h_indices, key=lambda i: float(np.linalg.norm(pos[i] - pos[s_idx])))

    # Neighbors currently bonded to N (C_ring and 2 H atoms)
    n_neighbors = [i for i in range(len(syms)) if i not in (n_idx, h_thiol) and np.linalg.norm(pos[i] - pos[n_idx]) < 1.65]
    if len(n_neighbors) < 2:
        raise ValueError(f"Cannot infer tetrahedral NH3+ site around N (found {len(n_neighbors)} neighbors)")

    vecs = np.array([(pos[i] - pos[n_idx]) / np.linalg.norm(pos[i] - pos[n_idx]) for i in n_neighbors])
    outward = -np.sum(vecs, axis=0)
    norm = float(np.linalg.norm(outward))
    if norm < 1e-6:
        raise ValueError("Degenerate N geometry while placing zwitterionic H+")
    outward /= norm

    new_pos = pos.copy()
    new_pos[h_thiol] = pos[n_idx] + nh_bond_A * outward
    work.set_positions(new_pos)
    work.calc = None
    return work


def _rotation_matrix_from_euler(alpha: float, beta: float, gamma: float) -> np.ndarray:
    ca, sa = math.cos(alpha), math.sin(alpha)
    cb, sb = math.cos(beta), math.sin(beta)
    cg, sg = math.cos(gamma), math.sin(gamma)
    rz1 = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])
    ry = np.array([[cb, 0.0, sb], [0.0, 1.0, 0.0], [-sb, 0.0, cb]])
    rz2 = np.array([[cg, -sg, 0.0], [sg, cg, 0.0], [0.0, 0.0, 1.0]])
    return rz2 @ ry @ rz1


def _pca21_contact_metrics(
    atoms: Atoms,
    z_mols: int,
    mol_n: int,
    *,
    hbond_cutoff_A: float = 3.5,
) -> tuple[float, float, int, int, int]:
    """Compute (min_intermol_dist, min_N_S_dist, ns_pair_count, sh_count, nh_count)."""
    syms = atoms.get_chemical_symbols()
    pos = atoms.get_positions()
    cell = atoms.cell
    pbc = atoms.pbc

    min_inter = float("inf")
    min_ns = float("inf")
    ns_pairs = 0
    for i in range(z_mols):
        gi = list(range(i * mol_n, (i + 1) * mol_n))
        ns_i = [idx for idx in gi if syms[idx] in ("N", "S")]
        for j in range(i + 1, z_mols):
            gj = list(range(j * mol_n, (j + 1) * mol_n))
            _, dmat = get_distances(pos[gi], pos[gj], cell=cell, pbc=pbc)
            min_inter = min(min_inter, float(np.min(dmat)))
            ns_j = [idx for idx in gj if syms[idx] in ("N", "S")]
            _, d_ns = get_distances(pos[ns_i], pos[ns_j], cell=cell, pbc=pbc)
            d_ns_min = float(np.min(d_ns))
            min_ns = min(min_ns, d_ns_min)
            if d_ns_min <= hbond_cutoff_A:
                ns_pairs += 1

    # Count H atoms within covalent distance of S (<1.6 A) vs N (<1.35 A) across the cell
    s_idx = [i for i, s in enumerate(syms) if s == "S"]
    n_idx = [i for i, s in enumerate(syms) if s == "N"]
    h_idx = [i for i, s in enumerate(syms) if s == "H"]
    sh_cnt = 0
    nh_cnt = 0
    if h_idx and s_idx:
        _, d_sh = get_distances(pos[h_idx], pos[s_idx], cell=cell, pbc=pbc)
        sh_cnt = int(np.sum(np.min(d_sh, axis=1) < 1.65))
    if h_idx and n_idx:
        _, d_nh = get_distances(pos[h_idx], pos[n_idx], cell=cell, pbc=pbc)
        nh_cnt = int(np.sum(np.min(d_nh, axis=1) < 1.35))

    return min_inter, min_ns, ns_pairs, sh_cnt, nh_cnt


def generate_spacegroup_candidates(
    mol_atoms: Atoms,
    cell_abc: tuple[float, float, float],
    space_group: str = "Pca2_1",
    *,
    min_intermol_dist_A: float = 1.75,
    n_rot_trials: int = 360,
    n_candidates: int = 3,
    seed: int = 42,
) -> list[tuple[str, Atoms, float, float]]:
    """Sample valid low-overlap molecular crystal packings matching ``space_group``."""
    sg = SpaceGroup(space_group)
    ops = sg.symmetry_ops
    cell = np.diag(np.array(cell_abc, dtype=float))
    inv_cell = np.linalg.inv(cell)

    centered = mol_atoms.positions - np.mean(mol_atoms.positions, axis=0)
    mol_syms = mol_atoms.get_chemical_symbols()
    n_per_mol = len(mol_syms)

    rng = np.random.default_rng(seed)
    accepted: list[tuple[float, float, Atoms]] = []

    for _ in range(n_rot_trials):
        alpha = float(rng.uniform(0.0, 2.0 * math.pi))
        beta = float(math.acos(rng.uniform(-1.0, 1.0)))
        gamma = float(rng.uniform(0.0, 2.0 * math.pi))
        shift_frac = rng.uniform([0.05, 0.05, 0.02], [0.45, 0.45, 0.45])
        shift_cart = shift_frac @ cell

        rot_pos = centered @ _rotation_matrix_from_euler(alpha, beta, gamma).T + shift_cart
        asym_frac = rot_pos @ inv_cell

        all_pos: list[np.ndarray] = []
        all_syms: list[str] = []
        for op in ops:
            copy_frac = np.array([op.operate(f) for f in asym_frac])
            all_pos.append(copy_frac @ cell)
            all_syms.extend(mol_syms)

        cand = Atoms(symbols=all_syms, positions=np.vstack(all_pos), cell=cell, pbc=(True, True, True))
        min_inter, min_ns, ns_pairs, _, _ = _pca21_contact_metrics(cand, len(ops), n_per_mol)
        if min_inter >= min_intermol_dist_A:
            # Score favors both larger steric clearance and tight N...S H-bonding
            score = min_inter + 0.35 * max(0.0, 3.8 - min_ns) + 0.1 * ns_pairs
            accepted.append((score, min_inter, cand))

    if not accepted:
        raise RuntimeError(
            f"No overlap-free {space_group} candidate found in {n_rot_trials} trials (min_dist={min_intermol_dist_A} A)"
        )

    accepted.sort(key=lambda x: x[0], reverse=True)
    # Pick diverse top candidates (differing in S/N geometric signature)
    chosen: list[tuple[str, Atoms, float, float]] = []
    seen_sigs: list[float] = []
    for idx, (score, d_inter, atoms) in enumerate(accepted):
        _, d_ns, _, _, _ = _pca21_contact_metrics(atoms, len(ops), n_per_mol)
        sig = round(d_inter * 10.0 + d_ns * 3.0, 1)
        if all(abs(sig - s) >= 0.5 for s in seen_sigs) or len(chosen) == 0:
            seen_sigs.append(sig)
            chosen.append((f"cand_{len(chosen) + 1}", atoms, d_inter, d_ns))
            if len(chosen) >= n_candidates:
                break
    return chosen


def _relax_atomic_or_cell(
    atoms: Atoms,
    calc_bundle: CalculatorBundle,
    optimizer_name: str,
    fmax: float,
    max_steps: int,
    *,
    relax_cell: bool,
) -> tuple[Atoms, bool, int, float]:
    work = atoms.copy()
    work.calc = calc_bundle.total_calc
    opt_cls = _OPTIMIZERS[optimizer_name]
    if relax_cell:
        filt = FrechetCellFilter(work)
        opt = opt_cls(filt, logfile=None)
        conv = bool(opt.run(fmax=fmax, steps=max_steps))
        forces = filt.get_forces()
    else:
        opt = opt_cls(work, logfile=None)
        conv = bool(opt.run(fmax=fmax, steps=max_steps))
        forces = work.get_forces()
    fmax_final = float(np.max(np.linalg.norm(forces, axis=1)))
    return work, conv, int(opt.nsteps), fmax_final


def _density_g_cm3(atoms: Atoms) -> float:
    mass_amu = float(np.sum(atoms.get_masses()))
    vol_A3 = float(atoms.get_volume())
    return float((mass_amu / vol_A3) * _AMU_A3_TO_G_CM3)


def run_bulk_crystal_study(
    yaml_path: Path | str,
    *,
    backend_override: str | None = None,
    device_override: str | None = None,
    output_dir_override: Path | None = None,
) -> dict[str, Any]:
    """Run fixed-cell and variable-cell Pca2_1 bulk crystal + (001) cleavage calculations."""
    cfg = load_config(yaml_path)
    settings = BulkCrystalSettings.from_config(cfg)
    base_cfg = load_config(settings.base_config_path)
    calc_bundle = build_calculator_bundle(base_cfg, backend=backend_override, device=device_override)

    out_root = (output_dir_override if output_dir_override is not None else settings.output_dir) / settings.study_name
    struct_dir = out_root / "structures"
    struct_dir.mkdir(parents=True, exist_ok=True)

    # 1. Neutral gas molecule reference + isolated zwitterion diagnostic check
    mol_spec = load_molecule_file(settings.molecule_path, base_cfg, molecule_id=settings.molecule_id)
    ref_mol: ReferenceResult = relax_reference_molecule(mol_spec, calc_bundle, base_cfg)
    assert ref_mol.energy_total_eV is not None and ref_mol.energy_umlip_eV is not None
    e_mol_gas = ref_mol.energy_total_eV
    e_mol_gas_u = ref_mol.energy_umlip_eV
    e_mol_gas_d3 = ref_mol.energy_d3_eV

    neutral_mol = ref_mol.relaxed_atoms.copy()
    zwit_mol = make_zwitterion_molecule(neutral_mol, anchor_element=settings.anchor_element)
    ase_write(struct_dir / "ref_neutral_gas.xyz", neutral_mol)
    ase_write(struct_dir / "ref_zwitterion_initial.xyz", zwit_mol)

    mol_n = len(neutral_mol)
    z_mols = len(SpaceGroup(settings.space_group).symmetry_ops)
    cell_abc = (settings.cell_a_A, settings.cell_b_A, settings.cell_c_A)

    crystal_rows: list[dict[str, Any]] = []
    relaxed_crystals: dict[str, Atoms] = {}

    for tautomer in settings.tautomers:
        unit_mol = neutral_mol if tautomer == "neutral" else zwit_mol
        cands = generate_spacegroup_candidates(
            unit_mol,
            cell_abc,
            space_group=settings.space_group,
            min_intermol_dist_A=settings.min_intermol_dist_A,
            n_rot_trials=settings.n_rot_trials,
            n_candidates=settings.n_candidates_per_tautomer,
            seed=settings.seed + (0 if tautomer == "neutral" else 101),
        )
        for cname, init_atoms, _, _ in cands:
            cid_fixed = f"{tautomer}_{cname}_fixed"
            ase_write(struct_dir / f"{cid_fixed}_initial.xyz", init_atoms)

            rel_fixed, conv_f, steps_f, fmax_f = _relax_atomic_or_cell(
                init_atoms, calc_bundle, settings.optimizer, settings.fmax_eV_per_A, settings.max_steps, relax_cell=False
            )
            ase_write(struct_dir / f"{cid_fixed}_relaxed.xyz", rel_fixed)
            et, eu, ed = single_point_components(rel_fixed, calc_bundle)
            d_inter, d_ns, ns_pairs, sh_cnt, nh_cnt = _pca21_contact_metrics(rel_fixed, z_mols, mol_n)
            crystal_rows.append(
                {
                    "case_id": cid_fixed,
                    "tautomer_init": tautomer,
                    "mode": "fixed_exp_cell",
                    "z_mols": z_mols,
                    "converged": conv_f,
                    "n_steps": steps_f,
                    "fmax_eV_per_A": fmax_f,
                    "a_A": float(np.linalg.norm(rel_fixed.cell[0])),
                    "b_A": float(np.linalg.norm(rel_fixed.cell[1])),
                    "c_A": float(np.linalg.norm(rel_fixed.cell[2])),
                    "volume_A3": float(rel_fixed.get_volume()),
                    "density_g_cm3": _density_g_cm3(rel_fixed),
                    "e_coh_per_mol_eV": (et - z_mols * e_mol_gas) / z_mols,
                    "e_coh_umlip_per_mol_eV": (eu - z_mols * e_mol_gas_u) / z_mols,
                    "e_coh_d3_per_mol_eV": (
                        None if (ed is None or e_mol_gas_d3 is None) else (ed - z_mols * e_mol_gas_d3) / z_mols
                    ),
                    "min_intermol_A": d_inter,
                    "min_N_S_A": d_ns,
                    "ns_hbond_pairs": ns_pairs,
                    "sh_bonds_count": sh_cnt,
                    "nh_bonds_count": nh_cnt,
                    "energy_total_eV": et,
                }
            )
            relaxed_crystals[cid_fixed] = rel_fixed

            if settings.relax_cell:
                cid_cell = f"{tautomer}_{cname}_cellopt"
                try:
                    rel_cell, conv_c, steps_c, fmax_c = _relax_atomic_or_cell(
                        rel_fixed,
                        calc_bundle,
                        settings.optimizer,
                        settings.fmax_eV_per_A,
                        settings.cell_max_steps,
                        relax_cell=True,
                    )
                    ase_write(struct_dir / f"{cid_cell}_relaxed.xyz", rel_cell)
                    et_c, eu_c, ed_c = single_point_components(rel_cell, calc_bundle)
                    d_inter_c, d_ns_c, ns_pairs_c, sh_c, nh_c = _pca21_contact_metrics(rel_cell, z_mols, mol_n)
                    crystal_rows.append(
                        {
                            "case_id": cid_cell,
                            "tautomer_init": tautomer,
                            "mode": "var_cell_opt",
                            "z_mols": z_mols,
                            "converged": conv_c,
                            "n_steps": steps_c,
                            "fmax_eV_per_A": fmax_c,
                            "a_A": float(np.linalg.norm(rel_cell.cell[0])),
                            "b_A": float(np.linalg.norm(rel_cell.cell[1])),
                            "c_A": float(np.linalg.norm(rel_cell.cell[2])),
                            "volume_A3": float(rel_cell.get_volume()),
                            "density_g_cm3": _density_g_cm3(rel_cell),
                            "e_coh_per_mol_eV": (et_c - z_mols * e_mol_gas) / z_mols,
                            "e_coh_umlip_per_mol_eV": (eu_c - z_mols * e_mol_gas_u) / z_mols,
                            "e_coh_d3_per_mol_eV": (
                                None
                                if (ed_c is None or e_mol_gas_d3 is None)
                                else (ed_c - z_mols * e_mol_gas_d3) / z_mols
                            ),
                            "min_intermol_A": d_inter_c,
                            "min_N_S_A": d_ns_c,
                            "ns_hbond_pairs": ns_pairs_c,
                            "sh_bonds_count": sh_c,
                            "nh_bonds_count": nh_c,
                            "energy_total_eV": et_c,
                        }
                    )
                    relaxed_crystals[cid_cell] = rel_cell
                except Exception as exc:  # e.g. synth_morse without stress property
                    if "stress" not in str(exc).lower():
                        raise

    # 2. Bulk vacancy & (001) surface cleavage detachment from best converged crystal
    best_row = min(crystal_rows, key=lambda r: float(r["e_coh_per_mol_eV"]))
    best_id = str(best_row["case_id"])
    best_atoms = relaxed_crystals[best_id]

    surface_rows: list[dict[str, Any]] = []

    # (a) Bulk supercell 1-molecule vacancy (internal crystal bond cost)
    p_mat = np.diag(list(settings.supercell_vac))
    bulk_sc = make_supercell(best_atoms, p_mat)
    bulk_sc_rel, conv_sc, _, _ = _relax_atomic_or_cell(
        bulk_sc, calc_bundle, settings.optimizer, settings.fmax_eV_per_A, settings.max_steps, relax_cell=False
    )
    e_sc, _, _ = single_point_components(bulk_sc_rel, calc_bundle)
    bulk_vac_atoms = bulk_sc_rel[mol_n:].copy()
    bulk_vac_rel, conv_bv, _, _ = _relax_atomic_or_cell(
        bulk_vac_atoms, calc_bundle, settings.optimizer, settings.fmax_eV_per_A, settings.max_steps, relax_cell=False
    )
    ase_write(struct_dir / f"{best_id}_bulk_vac_relaxed.xyz", bulk_vac_rel)
    e_bv, _, _ = single_point_components(bulk_vac_rel, calc_bundle)
    surface_rows.append(
        {
            "metric_id": f"{best_id}_bulk_1vacancy",
            "kind": "bulk_vacancy",
            "source_crystal": best_id,
            "n_molecules": (len(bulk_sc) // mol_n),
            "e_des_eV": e_bv + e_mol_gas - e_sc,
            "cleavage_energy_eV_per_A2": "",
            "converged": conv_sc and conv_bv,
        }
    )

    # (b) (001) crystal slab (repeat along x, y, add z vacuum, wrap molecules whole, remove topmost molecule)
    rx, ry = settings.slab_repeat_xy
    slab_raw = make_supercell(best_atoms, np.diag([rx, ry, 1]))
    # Unwrap each molecule around its first atom so (001) surface does not sever molecules
    n_slab_mols = len(slab_raw) // mol_n
    slab_pos = slab_raw.get_positions().copy()
    from ase.geometry import find_mic

    mol_coms_z: list[float] = []
    for k in range(n_slab_mols):
        s = slice(k * mol_n, (k + 1) * mol_n)
        rel, _ = find_mic(slab_pos[s] - slab_pos[s.start], cell=slab_raw.cell, pbc=slab_raw.pbc)
        slab_pos[s] = slab_pos[s.start] + rel
        mol_coms_z.append(float(np.mean(slab_pos[s, 2])))
    slab_raw.set_positions(slab_pos)
    c_len = float(np.linalg.norm(slab_raw.cell[2]))
    new_cell = slab_raw.cell.copy()
    new_cell[2, 2] = c_len + settings.slab_vacuum_A
    slab_raw.set_cell(new_cell, scale_atoms=False)
    slab_raw.center(axis=2)
    ase_write(struct_dir / f"{best_id}_001slab_initial.xyz", slab_raw)

    slab_rel, conv_s0, _, _ = _relax_atomic_or_cell(
        slab_raw, calc_bundle, settings.optimizer, settings.fmax_eV_per_A, settings.max_steps, relax_cell=False
    )
    ase_write(struct_dir / f"{best_id}_001slab_relaxed.xyz", slab_rel)
    e_s0, _, _ = single_point_components(slab_rel, calc_bundle)

    # Cleavage surface energy gamma = (E_slab - N_rep * E_bulk_unit) / (2 * Area)
    area_A2 = float(np.linalg.norm(np.cross(slab_rel.cell[0], slab_rel.cell[1])))
    gamma = (e_s0 - (rx * ry) * float(best_row["energy_total_eV"])) / (2.0 * area_A2)

    # Remove topmost exposed molecule on (001) slab
    top_k = int(np.argmax(mol_coms_z))
    keep = [i for i in range(len(slab_rel)) if not (top_k * mol_n <= i < (top_k + 1) * mol_n)]
    slab_vac = slab_rel[keep].copy()
    slab_vac_rel, conv_sv, _, _ = _relax_atomic_or_cell(
        slab_vac, calc_bundle, settings.optimizer, settings.fmax_eV_per_A, settings.max_steps, relax_cell=False
    )
    ase_write(struct_dir / f"{best_id}_001slab_vac_relaxed.xyz", slab_vac_rel)
    e_sv, _, _ = single_point_components(slab_vac_rel, calc_bundle)
    surface_rows.append(
        {
            "metric_id": f"{best_id}_001_surface_1mol_des",
            "kind": "crystal_001_desorption",
            "source_crystal": best_id,
            "n_molecules": n_slab_mols,
            "e_des_eV": e_sv + e_mol_gas - e_s0,
            "cleavage_energy_eV_per_A2": gamma,
            "converged": conv_s0 and conv_sv,
        }
    )

    if crystal_rows:
        _write_csv(out_root / "crystal_summary.csv", list(crystal_rows[0].keys()), crystal_rows)
    if surface_rows:
        _write_csv(out_root / "crystal_surface_desorption.csv", list(surface_rows[0].keys()), surface_rows)

    meta = {
        "study_name": settings.study_name,
        "calculator_id": calc_bundle.calculator_id,
        "space_group": settings.space_group,
        "exp_cell_abc_A": list(cell_abc),
        "ref_mol_gas_eV": e_mol_gas,
        "best_crystal_case": best_id,
    }
    (out_root / "study_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return {
        "output_dir": str(out_root),
        "best_crystal_case": best_id,
        "crystals": crystal_rows,
        "surface_desorption": surface_rows,
    }
