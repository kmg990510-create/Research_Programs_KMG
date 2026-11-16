"""Step 1-2 stability verification routines for close-packed molecular monolayers."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.geometry import find_mic
from ase.io import read as ase_read
from ase.io import write as ase_write
from ase.optimize import BFGS, FIRE, LBFGS

from ads_core.builders.molecule import load_molecule_file
from ads_core.builders.multimol import StudySettings
from ads_core.builders.slab import build_mos2_slab
from ads_core.calculators.factory import CalculatorBundle, build_calculator_bundle
from ads_core.config import Config, load_config

_OPTIMIZERS = {
    "BFGS": BFGS,
    "LBFGS": LBFGS,
    "FIRE": FIRE,
}

# 1 eV/Å^3 = 160.2176634 GPa; 1 GPa * 1 Å = 0.1 N/m
_EV_A3_TO_GPA = 160.2176634


@dataclass(frozen=True)
class StabilitySettings:
    """Configuration for local-basin, sheet-strain, and 2nd-vacancy stability checks."""

    study_yaml_path: Path
    results_dir: Path
    pert_target_cases: tuple[str, ...]
    pert_amplitudes_A: tuple[float, ...]
    pert_seed: int
    basin_energy_tol_eV: float
    basin_rmsd_tol_A: float
    strain_target_cases: tuple[str, ...]
    strain_scale_factors: tuple[float, ...]
    dbl_vac_source_cases: tuple[str, ...]
    dbl_vac_second_indices: tuple[int, ...]

    @classmethod
    def from_config(cls, cfg: Config, *, project_root: Path) -> "StabilitySettings":
        return cls(
            study_yaml_path=(project_root / cfg.text("source_study.study_yaml")).resolve(),
            results_dir=(project_root / cfg.text("source_study.results_dir")).resolve(),
            pert_target_cases=tuple(cfg.text_list("perturbation_check.target_cases")),
            pert_amplitudes_A=tuple(cfg.number_list("perturbation_check.amplitudes_A")),
            pert_seed=cfg.integer("perturbation_check.seed"),
            basin_energy_tol_eV=cfg.number("perturbation_check.basin_energy_tol_eV"),
            basin_rmsd_tol_A=cfg.number("perturbation_check.basin_rmsd_tol_A"),
            strain_target_cases=tuple(cfg.text_list("sheet_strain_check.target_cases")),
            strain_scale_factors=tuple(cfg.number_list("sheet_strain_check.scale_factors")),
            dbl_vac_source_cases=tuple(cfg.text_list("double_vacancy_check.source_cases")),
            dbl_vac_second_indices=tuple(int(round(v)) for v in cfg.number_list("double_vacancy_check.second_remove_mol_indices")),
        )


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _relax(
    atoms: Atoms,
    calc_bundle: CalculatorBundle,
    optimizer_name: str,
    fmax: float,
    max_steps: int,
) -> tuple[Atoms, bool, int, float, float]:
    work = atoms.copy()
    work.calc = calc_bundle.total_calc
    opt = _OPTIMIZERS[optimizer_name](work, logfile=None)
    converged = bool(opt.run(fmax=fmax, steps=max_steps))
    energy = float(work.get_potential_energy())
    forces = work.get_forces()
    fmax_final = float(np.max(np.linalg.norm(forces, axis=1)))
    return work, converged, int(opt.nsteps), fmax_final, energy


def _mean_tilt_deg(atoms: Atoms, mol_groups: list[list[int]]) -> float:
    tilts: list[float] = []
    for grp in mol_groups:
        pos = atoms.positions[grp]
        centered = pos - np.mean(pos, axis=0)
        _, _, vt = np.linalg.svd(centered)
        cos_t = min(1.0, max(0.0, float(abs(vt[-1][2]))))
        tilts.append(math.degrees(math.acos(cos_t)))
    return float(np.mean(tilts)) if tilts else 0.0


def _pbc_heavy_rmsd_A(atoms_a: Atoms, atoms_b: Atoms, slab_count: int) -> float:
    """Compute minimum-image heavy-atom RMSD over adsorbate atoms after removing rigid COM drift."""
    symbols = atoms_a.get_chemical_symbols()
    heavy_idx = [i for i in range(slab_count, len(atoms_a)) if symbols[i] != "H"]
    disp = atoms_b.positions[heavy_idx] - atoms_a.positions[heavy_idx]
    mic_disp, _ = find_mic(disp, cell=atoms_a.cell, pbc=atoms_a.pbc)
    mic_disp = mic_disp - np.mean(mic_disp, axis=0, keepdims=True)
    return float(np.sqrt(np.mean(np.sum(mic_disp ** 2, axis=1))))


def _scale_sheet_molecular_coms(
    sheet: Atoms,
    mol_atom_count: int,
    scale: float,
) -> Atoms:
    """Scale 2D cell and molecular COM xy positions while keeping internal molecular geometries intact."""
    n_mol = len(sheet) // mol_atom_count
    scaled = sheet.copy()
    new_cell = scaled.cell.copy()
    new_cell[0] *= scale
    new_cell[1] *= scale
    scaled.set_cell(new_cell, scale_atoms=False)
    pos = scaled.positions.copy()
    for m_idx in range(n_mol):
        s = slice(m_idx * mol_atom_count, (m_idx + 1) * mol_atom_count)
        com = np.mean(pos[s], axis=0)
        delta_xy = com[:2] * (scale - 1.0)
        pos[s, 0] += delta_xy[0]
        pos[s, 1] += delta_xy[1]
    scaled.positions = pos
    return scaled


def run_stability_checks(
    mech_yaml: Path | str,
    *,
    backend_override: str | None = None,
    device_override: str | None = None,
    checks: tuple[str, ...] = ("perturbation", "strain", "double_vacancy"),
) -> dict[str, Any]:
    """Execute perturbation, standalone sheet-strain, and double-vacancy stability checks."""
    mech_path = Path(mech_yaml).resolve()
    project_root = mech_path.parents[1] if mech_path.parent.name == "configs" else mech_path.parent
    mech_cfg = load_config(mech_path)
    stab = StabilitySettings.from_config(mech_cfg, project_root=project_root)

    study_cfg = load_config(stab.study_yaml_path)
    study = StudySettings.from_config(study_cfg, project_root=project_root)
    base_cfg = load_config(study.base_config_path)

    meta = json.loads((stab.results_dir / "study_metadata.json").read_text(encoding="utf-8"))
    ref_mol_eV = float(meta["ref_mol_eV"])

    slab_spec = build_mos2_slab(
        base_cfg,
        supercell=(study.supercell_nx, study.supercell_ny),
        vacuum_A=study.vacuum_A,
        defect_type=study.defect_type,
        fix_bottom_layer=study.fix_bottom_layer,
    )
    slab_count = len(slab_spec.atoms)
    mol_spec = load_molecule_file(study.molecule_path, base_cfg, molecule_id=study.molecule_id)
    mol_n = len(mol_spec.atoms)

    calc_bundle = build_calculator_bundle(
        base_cfg,
        backend=backend_override,
        device=device_override,
    )
    struct_dir = stab.results_dir / "structures"

    # 1. Perturbation re-relaxation stability check
    pert_rows: list[dict[str, Any]] = []
    if "perturbation" in checks:
        rng = np.random.default_rng(stab.pert_seed)
        for cid in stab.pert_target_cases:
            orig = ase_read(struct_dir / f"{cid}_relaxed.xyz")
            orig.calc = calc_bundle.total_calc
            e_orig = float(orig.get_potential_energy())
            n_mol = (len(orig) - slab_count) // mol_n
            groups = [list(range(slab_count + k * mol_n, slab_count + (k + 1) * mol_n)) for k in range(n_mol)]
            tilt_orig = _mean_tilt_deg(orig, groups)
            for amp in stab.pert_amplitudes_A:
                pert = orig.copy()
                pert.positions[slab_count:] += rng.normal(loc=0.0, scale=amp, size=(len(pert) - slab_count, 3))
                rel, conv, steps, fmax_val, e_rel = _relax(
                    pert, calc_bundle, study.optimizer, study.fmax_eV_per_A, study.max_steps
                )
                rmsd = _pbc_heavy_rmsd_A(orig, rel, slab_count)
                tilt_rel = _mean_tilt_deg(rel, groups)
                de = e_rel - e_orig
                returns = bool(conv and abs(de) <= stab.basin_energy_tol_eV and rmsd <= stab.basin_rmsd_tol_A)
                pert_rows.append(
                    {
                        "case_id": cid,
                        "amplitude_A": amp,
                        "e_orig_eV": e_orig,
                        "e_rerelax_eV": e_rel,
                        "delta_E_eV": de,
                        "heavy_rmsd_A": rmsd,
                        "tilt_orig_deg": tilt_orig,
                        "tilt_rerelax_deg": tilt_rel,
                        "delta_tilt_deg": tilt_rel - tilt_orig,
                        "converged": conv,
                        "n_steps": steps,
                        "fmax_final_eV_per_A": fmax_val,
                        "returns_to_basin": returns,
                    }
                )
        if pert_rows:
            _write_csv(stab.results_dir / "perturbation_check.csv", list(pert_rows[0].keys()), pert_rows)

    # 2. Standalone 4-ATP sheet lateral strain & stress check
    strain_rows: list[dict[str, Any]] = []
    if "strain" in checks:
        for cid in stab.strain_target_cases:
            orig = ase_read(struct_dir / f"{cid}_relaxed.xyz")
            sheet_base = orig[slab_count:].copy()
            n_mol = len(sheet_base) // mol_n
            for scale in stab.strain_scale_factors:
                scaled = _scale_sheet_molecular_coms(sheet_base, mol_n, scale)
                rel, conv, steps, fmax_val, e_sheet = _relax(
                    scaled, calc_bundle, study.optimizer, study.fmax_eV_per_A, study.max_steps
                )
                cell = rel.cell
                area_A2 = float(np.linalg.norm(np.cross(cell[0], cell[1])))
                lz_A = float(cell[2, 2])
                try:
                    stress = rel.get_stress(voigt=True)
                    p_xx_gpa: float | None = float(stress[0] * _EV_A3_TO_GPA)
                    p_yy_gpa: float | None = float(stress[1] * _EV_A3_TO_GPA)
                    p_2d_Nm: float | None = 0.5 * (p_xx_gpa + p_yy_gpa) * lz_A * 0.1
                except Exception:
                    p_xx_gpa = None
                    p_yy_gpa = None
                    p_2d_Nm = None
                groups = [list(range(k * mol_n, (k + 1) * mol_n)) for k in range(n_mol)]
                strain_rows.append(
                    {
                        "case_id": cid,
                        "scale_factor": scale,
                        "area_per_mol_A2": area_A2 / n_mol,
                        "e_lat_per_mol_eV": (e_sheet - n_mol * ref_mol_eV) / n_mol,
                        "mean_tilt_deg": _mean_tilt_deg(rel, groups),
                        "p_xx_GPa": p_xx_gpa,
                        "p_yy_GPa": p_yy_gpa,
                        "lateral_pressure_2D_N_per_m": p_2d_Nm,
                        "converged": conv,
                        "n_steps": steps,
                        "fmax_final_eV_per_A": fmax_val,
                    }
                )
        if strain_rows:
            _write_csv(stab.results_dir / "sheet_strain_check.csv", list(strain_rows[0].keys()), strain_rows)

    # 3. Second-vacancy check (N=4 -> N=3_vac -> N=2_2vac)
    dbl_rows: list[dict[str, Any]] = []
    if "double_vacancy" in checks:
        for cid in stab.dbl_vac_source_cases:
            vac1 = ase_read(struct_dir / f"{cid}_vacancy_relaxed.xyz")
            vac1.calc = calc_bundle.total_calc
            e_vac1 = float(vac1.get_potential_energy())
            n_rem = (len(vac1) - slab_count) // mol_n
            for sec_idx in stab.dbl_vac_second_indices:
                if not (0 <= sec_idx < n_rem):
                    continue
                drop_start = slab_count + sec_idx * mol_n
                keep = [i for i in range(len(vac1)) if not (drop_start <= i < drop_start + mol_n)]
                vac2_init = vac1[keep]
                rel2, conv, steps, fmax_val, e_vac2 = _relax(
                    vac2_init, calc_bundle, study.optimizer, study.fmax_eV_per_A, study.max_steps
                )
                ase_write(struct_dir / f"{cid}_minus_2_idx{sec_idx}_relaxed.xyz", rel2)
                e_des_2nd = e_vac2 + ref_mol_eV - e_vac1
                dbl_rows.append(
                    {
                        "source_case": cid,
                        "second_remove_idx": sec_idx,
                        "n_after": n_rem - 1,
                        "e_des_2nd_vac_eV": e_des_2nd,
                        "converged": conv,
                        "n_steps": steps,
                        "fmax_final_eV_per_A": fmax_val,
                    }
                )
        if dbl_rows:
            _write_csv(stab.results_dir / "double_vacancy_check.csv", list(dbl_rows[0].keys()), dbl_rows)

    return {
        "results_dir": str(stab.results_dir),
        "perturbation": pert_rows,
        "strain": strain_rows,
        "double_vacancy": dbl_rows,
    }
