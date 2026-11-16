"""Multi-molecule coverage, layer-by-layer decomposition, and thermal desorption analysis."""

from __future__ import annotations

import csv
import json
import logging
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.geometry import get_distances
from ase.io import write as ase_write
from ase.optimize import BFGS, FIRE, LBFGS

from ads_core.builders.molecule import detect_covalent_bonds, load_molecule_file
from ads_core.builders.multimol import (
    MultiMolAssembly,
    MultiMolCaseSpec,
    MultiMolPlacement,
    StudySettings,
    build_disulfide_dimer,
    build_multimol_assembly,
    build_reference_gases,
)
from ads_core.builders.slab import build_mos2_slab
from ads_core.calculators.factory import CalculatorBundle, build_calculator_bundle
from ads_core.config import Config, load_config
from ads_core.model import MoleculeSettings, MoleculeSpec
from ads_core.simulation.reference import (
    ReferenceResult,
    relax_reference_molecule,
    relax_reference_slab,
    single_point_components,
)

LOGGER = logging.getLogger(__name__)

_KB_EV_PER_K = 8.617333262e-5
_KELVIN_OFFSET = 273.15

_OPTIMIZERS = {
    "BFGS": BFGS,
    "LBFGS": LBFGS,
    "FIRE": FIRE,
}


@dataclass(frozen=True)
class CaseResult:
    """Relaxed energy, vertical/lateral decomposition, and geometry for one coverage case."""

    case_id: str
    kind: str
    base_case: str
    layer_index: int
    n_molecules: int
    area_per_mol_A2: float
    pattern: str
    converged: bool
    n_steps: int
    fmax_final_eV_per_A: float
    energy_total_eV: float
    energy_umlip_eV: float
    energy_d3_eV: float | None
    e_ads_total_eV: float
    e_ads_per_mol_eV: float
    e_ads_umlip_per_mol_eV: float
    e_ads_d3_per_mol_eV: float | None
    vdw_fraction: float | None
    e_lat_per_mol_eV: float
    e_lat_umlip_per_mol_eV: float
    e_lat_d3_per_mol_eV: float | None
    e_sub_per_mol_eV: float
    e_sub_umlip_per_mol_eV: float
    e_sub_d3_per_mol_eV: float | None
    mean_tilt_deg: float
    mean_z_com_A: float
    dz_above_slab_top_A: float
    dz_above_base_top_A: float
    min_intermol_heavy_A: float | None
    hbond_pair_count: int
    interlayer_min_heavy_A: float | None
    interlayer_hbond_count: int
    e_mos2_direct_per_mol_eV: float
    e_mos2_direct_d3_per_mol_eV: float | None


def _best_of_candidates(ref: str) -> list[str]:
    if not ref.startswith("best_of:"):
        return [ref] if ref else []
    cands = [item.strip() for item in ref[len("best_of:") :].split(",") if item.strip()]
    if not cands:
        raise ValueError(f"Empty candidate list in case reference {ref!r}")
    return cands


def _resolve_case_ref(ref: str, case_results: dict[str, CaseResult]) -> str:
    if not ref:
        return ""
    cands = _best_of_candidates(ref)
    if len(cands) == 1:
        return cands[0]
    return min(cands, key=lambda cid: case_results[cid].energy_total_eV)


def _relax_atoms(
    atoms: Atoms,
    calc_bundle: CalculatorBundle,
    optimizer_name: str,
    fmax: float,
    max_steps: int,
) -> tuple[Atoms, bool, int, float]:
    work = atoms.copy()
    work.calc = calc_bundle.total_calc
    opt_cls = _OPTIMIZERS[optimizer_name]
    opt = opt_cls(work, logfile=None)
    converged = bool(opt.run(fmax=fmax, steps=max_steps))
    forces = work.get_forces()
    fmax_final = float(np.max(np.linalg.norm(forces, axis=1)))
    return work, converged, int(opt.nsteps), fmax_final


def _molecule_tilt_deg(atoms: Atoms, mol_indices: tuple[int, ...]) -> float:
    pos = atoms.positions[list(mol_indices)]
    if len(pos) < 3:
        return 0.0
    centered = pos - np.mean(pos, axis=0)
    _, _, vt = np.linalg.svd(centered)
    normal = vt[-1]
    cos_t = min(1.0, max(0.0, float(abs(normal[2]))))
    return float(math.degrees(math.acos(cos_t)))


def _group_pair_contacts(
    atoms: Atoms,
    groups_a: tuple[tuple[int, ...], ...],
    groups_b: tuple[tuple[int, ...], ...],
    hbond_cutoff_A: float,
    *,
    same_pool: bool,
) -> tuple[float | None, int]:
    """Compute shortest heavy-atom distance and N/S proximity pair count across two group pools."""
    if not groups_a or not groups_b or (same_pool and len(groups_a) < 2):
        return None, 0
    symbols = atoms.get_chemical_symbols()
    min_heavy = float("inf")
    hbond_pairs = 0
    for i, grp_a in enumerate(groups_a):
        heavy_i = [idx for idx in grp_a if symbols[idx] != "H"]
        ns_i = [idx for idx in grp_a if symbols[idx] in ("N", "S")]
        j_start = i + 1 if same_pool else 0
        for grp_b in groups_b[j_start:]:
            heavy_j = [idx for idx in grp_b if symbols[idx] != "H"]
            ns_j = [idx for idx in grp_b if symbols[idx] in ("N", "S")]
            if heavy_i and heavy_j:
                _, dmat = get_distances(
                    atoms.positions[heavy_i],
                    atoms.positions[heavy_j],
                    cell=atoms.cell,
                    pbc=atoms.pbc,
                )
                min_heavy = min(min_heavy, float(np.min(dmat)))
            if ns_i and ns_j:
                _, d_ns = get_distances(
                    atoms.positions[ns_i],
                    atoms.positions[ns_j],
                    cell=atoms.cell,
                    pbc=atoms.pbc,
                )
                if float(np.min(d_ns)) <= hbond_cutoff_A:
                    hbond_pairs += 1
    return (None if not math.isfinite(min_heavy) else min_heavy), hbond_pairs


def _intermolecular_contacts(
    atoms: Atoms,
    groups: tuple[tuple[int, ...], ...],
    hbond_cutoff_A: float,
) -> tuple[float | None, int]:
    return _group_pair_contacts(atoms, groups, groups, hbond_cutoff_A, same_pool=True)


def _polanyi_wigner_half_life_s(e_des_eV: float, temp_C: float, prefactor_hz: float) -> float:
    temp_K = temp_C + _KELVIN_OFFSET
    exponent = min(700.0, e_des_eV / (_KB_EV_PER_K * temp_K))
    return float((math.log(2.0) / prefactor_hz) * math.exp(exponent))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_coverage_study(
    study_config_path: Path | str,
    *,
    backend_override: str | None = None,
    device_override: str | None = None,
    output_dir_override: Path | None = None,
) -> dict[str, Any]:
    """Execute Track A (and any YAML-configured multilayer cases) up to Step A2."""
    study_cfg = load_config(study_config_path)
    study = StudySettings.from_config(study_cfg)
    base_cfg = load_config(study.base_config_path)
    calc_bundle = build_calculator_bundle(base_cfg, backend=backend_override, device=device_override)

    out_root = (output_dir_override if output_dir_override is not None else study.output_dir) / study.study_name
    struct_dir = out_root / "structures"
    struct_dir.mkdir(parents=True, exist_ok=True)

    # 1. Relax bare substrate and isolated adsorbate molecule
    slab_spec = build_mos2_slab(
        base_cfg,
        supercell=(study.supercell_nx, study.supercell_ny),
        defect_type=study.defect_type,
        vacuum_A=study.vacuum_A,
        fix_bottom_layer=study.fix_bottom_layer,
    )
    mol_spec = load_molecule_file(study.molecule_path, base_cfg, molecule_id=study.molecule_id)
    ref_slab: ReferenceResult = relax_reference_slab(slab_spec, calc_bundle, base_cfg)
    ref_mol: ReferenceResult = relax_reference_molecule(mol_spec, calc_bundle, base_cfg)

    assert ref_slab.energy_total_eV is not None and ref_slab.energy_umlip_eV is not None
    assert ref_mol.energy_total_eV is not None and ref_mol.energy_umlip_eV is not None

    ase_write(struct_dir / "reference_slab_relaxed.xyz", ref_slab.relaxed_atoms)
    ase_write(struct_dir / "reference_mol_relaxed.xyz", ref_mol.relaxed_atoms)

    slab_cell = ref_slab.relaxed_atoms.cell
    slab_area_A2 = float(np.linalg.norm(np.cross(slab_cell[0], slab_cell[1])))
    slab_top_z_A = float(np.max(ref_slab.relaxed_atoms.positions[:, 2]))

    # Relax all cases in dependency order (base_case="" before stacked layers)
    pending = list(study.cases)
    case_results: dict[str, CaseResult] = {}
    relaxed_atoms_map: dict[str, Atoms] = {}
    assemblies_map: dict[str, MultiMolAssembly] = {}

    # Replace mol_spec.atoms with tightly relaxed isolated geometry so internal bonds are equilibrium
    relaxed_mol_spec = replace(mol_spec, atoms=ref_mol.relaxed_atoms.copy())

    while pending:
        progressed = False
        next_pending: list[MultiMolCaseSpec] = []
        for case in pending:
            needed = _best_of_candidates(case.base_case)
            if needed and not all(cid in case_results for cid in needed):
                next_pending.append(case)
                continue

            resolved_base = _resolve_case_ref(case.base_case, case_results)
            if not resolved_base:
                base_atoms = ref_slab.relaxed_atoms
                existing_groups: tuple[tuple[int, ...], ...] = ()
                e_base_tot = ref_slab.energy_total_eV
                e_base_umlip = ref_slab.energy_umlip_eV
                e_base_d3 = ref_slab.energy_d3_eV
            else:
                parent_res = case_results[resolved_base]
                base_atoms = relaxed_atoms_map[resolved_base]
                existing_groups = assemblies_map[resolved_base].all_mol_groups
                e_base_tot = parent_res.energy_total_eV
                e_base_umlip = parent_res.energy_umlip_eV
                e_base_d3 = parent_res.energy_d3_eV

            base_top_z_A = float(np.max(base_atoms.positions[:, 2]))

            assembly = build_multimol_assembly(
                base_atoms=base_atoms,
                slab_count=len(ref_slab.relaxed_atoms),
                existing_mol_groups=existing_groups,
                mol_spec=relaxed_mol_spec,
                case=case,
                study=study,
            )
            ase_write(struct_dir / f"{case.case_id}_initial.xyz", assembly.atoms)

            relaxed, conv, n_steps, fmax_final = _relax_atoms(
                assembly.atoms,
                calc_bundle,
                study.optimizer,
                study.fmax_eV_per_A,
                study.max_steps,
            )
            ase_write(struct_dir / f"{case.case_id}_relaxed.xyz", relaxed)

            e_tot, e_umlip, e_d3 = single_point_components(relaxed, calc_bundle)

            # Evaluate isolated active layer (without substrate or lower layers) for lateral cohesion E_lat
            active_indices = [idx for grp in assembly.new_mol_groups for idx in grp]
            sheet_atoms = relaxed[active_indices]
            sheet_atoms.constraints = []
            e_sheet_tot, e_sheet_umlip, e_sheet_d3 = single_point_components(sheet_atoms, calc_bundle)

            # Evaluate direct MoS2 <-> active layer attraction at fixed geometry (isolating substrate D3 decay)
            slab_len = len(ref_slab.relaxed_atoms)
            slab_def_atoms = relaxed[:slab_len]
            slab_def_atoms.constraints = []
            e_slab_def_tot, _, e_slab_def_d3 = single_point_components(slab_def_atoms, calc_bundle)
            slab_plus_active = relaxed[list(range(slab_len)) + active_indices]
            slab_plus_active.constraints = []
            e_sa_tot, _, e_sa_d3 = single_point_components(slab_plus_active, calc_bundle)

            n_mol = case.n_molecules
            e_ads_tot = e_tot - e_base_tot - n_mol * ref_mol.energy_total_eV
            e_ads_umlip = e_umlip - e_base_umlip - n_mol * ref_mol.energy_umlip_eV
            e_ads_d3 = (
                None
                if (e_d3 is None or e_base_d3 is None or ref_mol.energy_d3_eV is None)
                else (e_d3 - e_base_d3 - n_mol * ref_mol.energy_d3_eV)
            )

            e_ads_pm = e_ads_tot / n_mol
            e_ads_u_pm = e_ads_umlip / n_mol
            e_ads_d_pm = None if e_ads_d3 is None else (e_ads_d3 / n_mol)
            vdw_frac = None if (e_ads_d_pm is None or abs(e_ads_pm) < 1e-8) else (e_ads_d_pm / e_ads_pm)

            e_lat_pm = (e_sheet_tot - n_mol * ref_mol.energy_total_eV) / n_mol
            e_lat_u_pm = (e_sheet_umlip - n_mol * ref_mol.energy_umlip_eV) / n_mol
            e_lat_d_pm = (
                None
                if (e_sheet_d3 is None or ref_mol.energy_d3_eV is None)
                else ((e_sheet_d3 - n_mol * ref_mol.energy_d3_eV) / n_mol)
            )

            e_sub_pm = e_ads_pm - e_lat_pm
            e_sub_u_pm = e_ads_u_pm - e_lat_u_pm
            e_sub_d_pm = None if (e_ads_d_pm is None or e_lat_d_pm is None) else (e_ads_d_pm - e_lat_d_pm)

            e_mos2_direct_pm = (e_sa_tot - e_slab_def_tot - e_sheet_tot) / n_mol
            e_mos2_direct_d3_pm = (
                None
                if (e_sa_d3 is None or e_slab_def_d3 is None or e_sheet_d3 is None)
                else ((e_sa_d3 - e_slab_def_d3 - e_sheet_d3) / n_mol)
            )

            mean_tilt = float(np.mean([_molecule_tilt_deg(relaxed, grp) for grp in assembly.new_mol_groups]))
            mean_z = float(np.mean([np.mean(relaxed.positions[list(grp), 2]) for grp in assembly.new_mol_groups]))
            min_heavy, hbond_cnt = _intermolecular_contacts(
                relaxed, assembly.new_mol_groups, study.thermal.min_intermol_hbond_cutoff_A
            )
            inter_min_heavy, inter_hb_cnt = _group_pair_contacts(
                relaxed,
                assembly.new_mol_groups,
                assembly.existing_mol_groups,
                study.thermal.min_intermol_hbond_cutoff_A,
                same_pool=False,
            )

            case_results[case.case_id] = CaseResult(
                case_id=case.case_id,
                kind=case.kind,
                base_case=resolved_base,
                layer_index=case.layer_index,
                n_molecules=n_mol,
                area_per_mol_A2=slab_area_A2 / n_mol,
                pattern=case.pattern,
                converged=conv,
                n_steps=n_steps,
                fmax_final_eV_per_A=fmax_final,
                energy_total_eV=e_tot,
                energy_umlip_eV=e_umlip,
                energy_d3_eV=e_d3,
                e_ads_total_eV=e_ads_tot,
                e_ads_per_mol_eV=e_ads_pm,
                e_ads_umlip_per_mol_eV=e_ads_u_pm,
                e_ads_d3_per_mol_eV=e_ads_d_pm,
                vdw_fraction=vdw_frac,
                e_lat_per_mol_eV=e_lat_pm,
                e_lat_umlip_per_mol_eV=e_lat_u_pm,
                e_lat_d3_per_mol_eV=e_lat_d_pm,
                e_sub_per_mol_eV=e_sub_pm,
                e_sub_umlip_per_mol_eV=e_sub_u_pm,
                e_sub_d3_per_mol_eV=e_sub_d_pm,
                mean_tilt_deg=mean_tilt,
                mean_z_com_A=mean_z,
                dz_above_slab_top_A=mean_z - slab_top_z_A,
                dz_above_base_top_A=mean_z - base_top_z_A,
                min_intermol_heavy_A=min_heavy,
                hbond_pair_count=hbond_cnt,
                interlayer_min_heavy_A=inter_min_heavy,
                interlayer_hbond_count=inter_hb_cnt,
                e_mos2_direct_per_mol_eV=e_mos2_direct_pm,
                e_mos2_direct_d3_per_mol_eV=e_mos2_direct_d3_pm,
            )
            relaxed_atoms_map[case.case_id] = relaxed
            assemblies_map[case.case_id] = assembly
            progressed = True

        if next_pending and not progressed:
            missing = [(c.case_id, c.base_case) for c in next_pending]
            raise ValueError(f"Unresolvable base_case dependency in YAML cases: {missing}")
        pending = next_pending

    # 2. Sequential & Vacancy desorption energies
    desorption_rows: list[dict[str, Any]] = []
    for cid, res in case_results.items():
        if res.n_molecules == 1:
            desorption_rows.append(
                {
                    "desorption_id": f"{cid}_monomer",
                    "mode": "monomer",
                    "source_case": cid,
                    "reference_case": "bare_slab",
                    "e_des_eV": -res.e_ads_per_mol_eV,
                    "e_des_vertical_eV": "",
                    "converged": res.converged,
                }
            )

    for child_spec, parent_spec in study.sequential_pairs.items():
        child_id = _resolve_case_ref(child_spec, case_results)
        parent_id = _resolve_case_ref(parent_spec, case_results)
        if child_id in case_results and parent_id in case_results:
            c_res = case_results[child_id]
            p_res = case_results[parent_id]
            e_des_seq = p_res.energy_total_eV + ref_mol.energy_total_eV - c_res.energy_total_eV
            desorption_rows.append(
                {
                    "desorption_id": f"seq_{child_id}_to_{parent_id}",
                    "mode": "sequential",
                    "source_case": child_id,
                    "reference_case": parent_id,
                    "e_des_eV": e_des_seq,
                    "e_des_vertical_eV": "",
                    "converged": c_res.converged and p_res.converged,
                }
            )

    seen_vac_sources: set[str] = set()
    for src_spec in study.vacancy_source_cases:
        src_id = _resolve_case_ref(src_spec, case_results)
        if src_id in seen_vac_sources:
            continue
        seen_vac_sources.add(src_id)
        if src_id not in assemblies_map:
            raise KeyError(f"vacancy_desorption.source_cases references unknown case {src_id!r}")
        asm = assemblies_map[src_id]
        if not (0 <= study.vacancy_remove_mol_index < len(asm.new_mol_groups)):
            raise IndexError(f"remove_mol_index {study.vacancy_remove_mol_index} out of range for {src_id}")
        remove_set = set(asm.new_mol_groups[study.vacancy_remove_mol_index])
        full_relaxed = relaxed_atoms_map[src_id]
        keep_idx = [i for i in range(len(full_relaxed)) if i not in remove_set]
        hole_atoms = full_relaxed[keep_idx]

        e_hole_vert, _, _ = single_point_components(hole_atoms, calc_bundle)
        hole_rel, hole_conv, _, _ = _relax_atoms(
            hole_atoms,
            calc_bundle,
            study.optimizer,
            study.fmax_eV_per_A,
            study.max_steps,
        )
        ase_write(struct_dir / f"{src_id}_vacancy_relaxed.xyz", hole_rel)
        e_hole_rel, _, _ = single_point_components(hole_rel, calc_bundle)

        e_full = case_results[src_id].energy_total_eV
        e_des_vert = e_hole_vert + ref_mol.energy_total_eV - e_full
        e_des_rel = e_hole_rel + ref_mol.energy_total_eV - e_full
        desorption_rows.append(
            {
                "desorption_id": f"vac_{src_id}",
                "mode": "vacancy_1hole",
                "source_case": src_id,
                "reference_case": f"{src_id}_minus_1",
                "e_des_eV": e_des_rel,
                "e_des_vertical_eV": e_des_vert,
                "converged": hole_conv,
            }
        )

    # 3. Disulfide coupling check (optional via YAML)
    disulfide_rows: list[dict[str, Any]] = []
    if study.disulfide.enabled:
        mol_settings = MoleculeSettings.from_config(base_cfg)
        dimer_raw = build_disulfide_dimer(
            relaxed_mol_spec,
            anchor_element=study.anchor_element,
            s_s_bond_A=study.disulfide.s_s_bond_A,
            c_s_s_angle_deg=study.disulfide.c_s_s_angle_deg,
            dihedral_deg=study.disulfide.dihedral_deg,
            vacuum_box_A=mol_settings.vacuum_box_A,
        )
        dimer_rel, dimer_conv, _, _ = _relax_atoms(
            dimer_raw, calc_bundle, study.optimizer, min(study.fmax_eV_per_A * 0.1, 0.005), study.max_steps
        )
        ase_write(struct_dir / "disulfide_gas_relaxed.xyz", dimer_rel)
        e_dimer_gas, e_dimer_gas_u, e_dimer_gas_d3 = single_point_components(dimer_rel, calc_bundle)

        gases = build_reference_gases(study.disulfide, mol_settings.vacuum_box_A)
        gas_energies: dict[str, float] = {}
        for gname, gatoms in gases.items():
            grel, _, _, _ = _relax_atoms(
                gatoms, calc_bundle, study.optimizer, min(study.fmax_eV_per_A * 0.1, 0.005), study.max_steps
            )
            ge, _, _ = single_point_components(grel, calc_bundle)
            gas_energies[gname] = ge

        dimer_spec = MoleculeSpec(
            molecule_id=f"{study.molecule_id}_disulfide",
            atoms=dimer_rel,
            formula=dimer_rel.get_chemical_formula(),
            source="disulfide_builder",
            box_size_A=mol_settings.vacuum_box_A,
            anchor_index=0,
            reference_bonds=detect_covalent_bonds(dimer_rel, mol_settings.covalent_bond_scale),
        )
        dimer_case = MultiMolCaseSpec(
            case_id="disulfide_adsorbed",
            kind="grid",
            base_case="",
            layer_index=1,
            n_molecules=1,
            placements=(
                MultiMolPlacement(
                    dx_A=0.0,
                    dy_A=0.0,
                    xy_frac=(0.5, 0.5),
                    azimuth_deg=study.disulfide.azimuth_deg,
                    tilt_deg=0.0,
                ),
            ),
            pattern="parallel",
            motif="disulfide",
            tilt_deg=0.0,
        )
        dimer_asm = build_multimol_assembly(
            ref_slab.relaxed_atoms,
            len(ref_slab.relaxed_atoms),
            (),
            dimer_spec,
            dimer_case,
            study,
        )
        ase_write(struct_dir / "disulfide_adsorbed_initial.xyz", dimer_asm.atoms)
        dimer_ads_rel, dimer_ads_conv, _, _ = _relax_atoms(
            dimer_asm.atoms, calc_bundle, study.optimizer, study.fmax_eV_per_A, study.max_steps
        )
        ase_write(struct_dir / "disulfide_adsorbed_relaxed.xyz", dimer_ads_rel)
        e_dads, e_dads_u, e_dads_d3 = single_point_components(dimer_ads_rel, calc_bundle)

        e_ads_dimer = e_dads - ref_slab.energy_total_eV - e_dimer_gas
        e_ads_dimer_u = e_dads_u - ref_slab.energy_umlip_eV - e_dimer_gas_u
        e_ads_dimer_d3 = (
            None
            if (e_dads_d3 is None or ref_slab.energy_d3_eV is None or e_dimer_gas_d3 is None)
            else (e_dads_d3 - ref_slab.energy_d3_eV - e_dimer_gas_d3)
        )

        # Reaction energies relative to 2 isolated or 2 adsorbed thiol monomers
        de_gas_h2 = e_dimer_gas + gas_energies["H2"] - 2.0 * ref_mol.energy_total_eV
        de_gas_ox = e_dimer_gas + gas_energies["H2O"] - (2.0 * ref_mol.energy_total_eV + 0.5 * gas_energies["O2"])

        n2_h2t = next((r for r in case_results.values() if r.n_molecules == 2), None)
        de_ads_h2 = (
            None
            if n2_h2t is None
            else (e_dads + gas_energies["H2"] - n2_h2t.energy_total_eV)
        )
        de_ads_ox = (
            None
            if n2_h2t is None
            else (e_dads + gas_energies["H2O"] - (n2_h2t.energy_total_eV + 0.5 * gas_energies["O2"]))
        )

        disulfide_rows.append(
            {
                "species": f"{study.molecule_id}-S-S-{study.molecule_id}",
                "e_ads_total_eV": e_ads_dimer,
                "e_ads_umlip_eV": e_ads_dimer_u,
                "e_ads_d3_eV": e_ads_dimer_d3,
                "e_des_dimer_eV": -e_ads_dimer,
                "rxn_2RSH_to_RSSR_H2_gas_eV": de_gas_h2,
                "rxn_2RSH_to_RSSR_H2_ads_eV": de_ads_h2,
                "rxn_oxidative_H2O_gas_eV": de_gas_ox,
                "rxn_oxidative_H2O_ads_eV": de_ads_ox,
                "converged_gas": dimer_conv,
                "converged_ads": dimer_ads_conv,
            }
        )
        desorption_rows.append(
            {
                "desorption_id": "disulfide_dimer_ads",
                "mode": "disulfide_dimer",
                "source_case": "disulfide_adsorbed",
                "reference_case": "bare_slab",
                "e_des_eV": -e_ads_dimer,
                "e_des_vertical_eV": "",
                "converged": dimer_ads_conv,
            }
        )

    # 4. Polanyi-Wigner thermal lifetime estimates
    thermal_rows: list[dict[str, Any]] = []
    for drow in desorption_rows:
        e_des = float(drow["e_des_eV"])
        for temp_C in study.thermal.temperatures_C:
            for nu in study.thermal.prefactors_hz:
                tau = _polanyi_wigner_half_life_s(e_des, temp_C, nu)
                thermal_rows.append(
                    {
                        "desorption_id": drow["desorption_id"],
                        "mode": drow["mode"],
                        "e_des_eV": e_des,
                        "temp_C": temp_C,
                        "temp_K": temp_C + _KELVIN_OFFSET,
                        "prefactor_hz": nu,
                        "tau_half_s": tau,
                        "survives_anneal": tau >= study.thermal.anneal_duration_s,
                    }
                )

    # 5. Export CSVs & metadata JSON
    cov_rows = [vars(case_results[c.case_id]) for c in study.cases]
    if cov_rows:
        _write_csv(out_root / "coverage_summary.csv", list(cov_rows[0].keys()), cov_rows)
    if desorption_rows:
        _write_csv(out_root / "desorption_summary.csv", list(desorption_rows[0].keys()), desorption_rows)
    if disulfide_rows:
        _write_csv(out_root / "disulfide_summary.csv", list(disulfide_rows[0].keys()), disulfide_rows)
    if thermal_rows:
        _write_csv(out_root / "thermal_lifetimes.csv", list(thermal_rows[0].keys()), thermal_rows)

    metadata = {
        "study_name": study.study_name,
        "calculator_id": calc_bundle.calculator_id,
        "calculator_metadata": calc_bundle.metadata,
        "supercell": [study.supercell_nx, study.supercell_ny],
        "defect_type": study.defect_type,
        "slab_area_A2": slab_area_A2,
        "ref_slab_eV": ref_slab.energy_total_eV,
        "ref_mol_eV": ref_mol.energy_total_eV,
        "study_config": study_cfg.as_dict(),
    }
    (out_root / "study_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "output_dir": str(out_root),
        "cases": case_results,
        "desorption": desorption_rows,
        "disulfide": disulfide_rows,
        "thermal": thermal_rows,
    }
