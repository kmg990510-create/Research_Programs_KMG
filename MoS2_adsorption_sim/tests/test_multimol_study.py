from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ase.geometry import get_distances

from ads_core.builders.molecule import load_molecule_file
from ads_core.builders.multimol import (
    MultiMolCaseSpec,
    StudySettings,
    build_disulfide_dimer,
    build_multimol_assembly,
)
from ads_core.builders.slab import build_mos2_slab
from ads_core.config import Config, load_config
from ads_core.simulation.coverage import run_coverage_study

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRACK_A_YAML = PROJECT_ROOT / "configs" / "track_a_4atp.yaml"


def test_every_track_a_yaml_key_is_read() -> None:
    cfg = load_config(TRACK_A_YAML)
    StudySettings.from_config(cfg, project_root=PROJECT_ROOT)
    assert cfg.unread_keys() == set()


def test_track_a_cases_build_without_overlap(four_atp_xyz_path: Path) -> None:
    cfg = load_config(TRACK_A_YAML)
    study = StudySettings.from_config(cfg, project_root=PROJECT_ROOT)
    base_cfg = load_config(study.base_config_path)

    slab_spec = build_mos2_slab(
        base_cfg,
        supercell=(study.supercell_nx, study.supercell_ny),
        defect_type=study.defect_type,
        vacuum_A=study.vacuum_A,
        fix_bottom_layer=study.fix_bottom_layer,
    )
    mol_spec = load_molecule_file(four_atp_xyz_path, base_cfg, molecule_id=study.molecule_id)

    for case in study.cases:
        if case.base_case:
            continue
        asm = build_multimol_assembly(
            base_atoms=slab_spec.atoms,
            slab_count=len(slab_spec.atoms),
            existing_mol_groups=(),
            mol_spec=mol_spec,
            case=case,
            study=study,
        )
        assert len(asm.new_mol_groups) == case.n_molecules
        # Verify minimum distance between slab and every adsorbate molecule
        slab_pos = asm.atoms.positions[: asm.slab_count]
        for grp in asm.new_mol_groups:
            _, d_slab = get_distances(asm.atoms.positions[list(grp)], slab_pos, cell=asm.atoms.cell, pbc=asm.atoms.pbc)
            assert float(np.min(d_slab)) >= study.min_initial_distance_A - 1e-6


def test_reconfigurable_supercell_grid_and_stacking(tmp_path: Path, four_atp_xyz_path: Path) -> None:
    """Changing supercell, grid count (N=6), and layer stacking works purely via YAML."""
    raw = load_config(TRACK_A_YAML).as_dict()
    raw["substrate"]["supercell_nx"] = 8
    raw["substrate"]["supercell_ny"] = 8
    raw["grid_cases"] = {
        "N6_layer1": {
            "base_case": "",
            "layer_index": 1,
            "grid_nx": 2,
            "grid_ny": 3,
            "pattern": "checkerboard",
            "tilt_deg": 0.0,
            "azimuth_deg": 0.0,
            "stagger_frac": 0.5,
            "row_azimuth_step_deg": 60.0,
            "offset_frac": [0.2, 0.2],
        },
        "N1_layer2": {
            "base_case": "N6_layer1",
            "layer_index": 2,
            "grid_nx": 1,
            "grid_ny": 1,
            "pattern": "parallel",
            "tilt_deg": 0.0,
            "azimuth_deg": 0.0,
            "stagger_frac": 0.0,
            "row_azimuth_step_deg": 0.0,
            "offset_frac": [0.5, 0.5],
        },
    }
    raw["cluster_cases"] = {
        "N2_dummy": {
            "base_case": "",
            "layer_index": 1,
            "motif": "dimer_head_to_tail",
            "center_frac": [0.5, 0.5],
            "rotation_deg": 0.0,
        }
    }
    raw["vacancy_desorption"]["source_cases"] = ["N6_layer1"]
    raw["vacancy_desorption"]["sequential_pairs"] = {"N1_layer2": "N6_layer1"}

    cfg = Config(raw)
    study = StudySettings.from_config(cfg, project_root=PROJECT_ROOT)
    assert cfg.unread_keys() == set()

    base_cfg = load_config(study.base_config_path)
    slab_spec = build_mos2_slab(base_cfg, supercell=(study.supercell_nx, study.supercell_ny), vacuum_A=34.0)
    mol_spec = load_molecule_file(four_atp_xyz_path, base_cfg, molecule_id=study.molecule_id)

    c1 = next(c for c in study.cases if c.case_id == "N6_layer1")
    c2 = next(c for c in study.cases if c.case_id == "N1_layer2")
    asm1 = build_multimol_assembly(slab_spec.atoms, len(slab_spec.atoms), (), mol_spec, c1, study)
    asm2 = build_multimol_assembly(asm1.atoms, len(slab_spec.atoms), asm1.all_mol_groups, mol_spec, c2, study)
    assert len(asm1.new_mol_groups) == 6
    assert len(asm2.all_mol_groups) == 7
    z_l1 = float(np.mean(asm1.atoms.positions[list(asm1.new_mol_groups[0]), 2]))
    z_l2 = float(np.mean(asm2.atoms.positions[list(asm2.new_mol_groups[0]), 2]))
    assert z_l2 > z_l1 + 2.5


def test_disulfide_dimer_geometry(four_atp_xyz_path: Path) -> None:
    cfg = load_config(TRACK_A_YAML)
    study = StudySettings.from_config(cfg, project_root=PROJECT_ROOT)
    base_cfg = load_config(study.base_config_path)
    mol_spec = load_molecule_file(four_atp_xyz_path, base_cfg, molecule_id=study.molecule_id)

    dimer = build_disulfide_dimer(
        mol_spec,
        anchor_element=study.anchor_element,
        s_s_bond_A=study.disulfide.s_s_bond_A,
        c_s_s_angle_deg=study.disulfide.c_s_s_angle_deg,
        dihedral_deg=study.disulfide.dihedral_deg,
        vacuum_box_A=20.0,
    )
    assert len(dimer) == 2 * (len(mol_spec.atoms) - 1)
    s_indices = [i for i, sym in enumerate(dimer.get_chemical_symbols()) if sym == "S"]
    assert len(s_indices) == 2
    assert dimer.get_distance(s_indices[0], s_indices[1]) == pytest.approx(study.disulfide.s_s_bond_A, abs=1e-4)
    # Verify non-collinear C-S-S bond angle
    half = len(dimer) // 2
    c_near_s0 = min(
        (i for i in range(half) if dimer.get_chemical_symbols()[i] == "C"),
        key=lambda i: dimer.get_distance(i, s_indices[0]),
    )
    angle_css = dimer.get_angle(c_near_s0, s_indices[0], s_indices[1])
    assert abs(angle_css - study.disulfide.c_s_s_angle_deg) < 5.0


def test_run_coverage_study_end_to_end_synth(tmp_path: Path, four_atp_xyz_path: Path) -> None:
    """Smoke test the full A1-A2 pipeline with synth_morse and verify exact energy decomposition."""
    raw = load_config(TRACK_A_YAML).as_dict()
    raw["relaxation"]["max_steps"] = 10
    raw["relaxation"]["fmax_eV_per_A"] = 0.2
    raw["grid_cases"] = {
        "N1_monomer_flat": raw["grid_cases"]["N1_monomer_flat"],
        "N4_monolayer_parallel": raw["grid_cases"]["N4_monolayer_parallel"],
    }
    raw["cluster_cases"] = {
        "N2_dimer_head_to_tail": raw["cluster_cases"]["N2_dimer_head_to_tail"],
    }
    raw["vacancy_desorption"]["source_cases"] = ["N4_monolayer_parallel"]
    raw["vacancy_desorption"]["sequential_pairs"] = {"N2_dimer_head_to_tail": "N1_monomer_flat"}

    yaml_path = tmp_path / "study.yaml"
    import yaml

    yaml_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    # Point relative paths inside raw to PROJECT_ROOT
    raw["study"]["base_config_path"] = str(PROJECT_ROOT / "config.yaml")
    raw["adsorbate"]["molecule_path"] = str(four_atp_xyz_path)
    yaml_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    out = run_coverage_study(
        yaml_path,
        backend_override="synth_morse",
        device_override="cpu",
        output_dir_override=tmp_path / "results",
    )
    for res in out["cases"].values():
        assert res.e_ads_per_mol_eV == pytest.approx(res.e_lat_per_mol_eV + res.e_sub_per_mol_eV, abs=1e-6)
        assert res.e_ads_umlip_per_mol_eV == pytest.approx(
            res.e_lat_umlip_per_mol_eV + res.e_sub_umlip_per_mol_eV, abs=1e-6
        )
    out_dir = Path(out["output_dir"])
    assert (out_dir / "coverage_summary.csv").exists()
    assert (out_dir / "desorption_summary.csv").exists()
    assert (out_dir / "disulfide_summary.csv").exists()
    assert (out_dir / "thermal_lifetimes.csv").exists()
    assert (out_dir / "study_metadata.json").exists()

    import csv
    import json

    with (out_dir / "disulfide_summary.csv").open("r", encoding="utf-8-sig") as fh:
        dis_rows = list(csv.DictReader(fh))
    assert dis_rows and "o2_spin_warning" in dis_rows[0]
    assert "e_des_dimer_note" in dis_rows[0]

    with (out_dir / "thermal_lifetimes.csv").open("r", encoding="utf-8-sig") as fh:
        th_rows = list(csv.DictReader(fh))
    assert th_rows and th_rows[0]["prefactor_basis"] == "assumed_constant_not_partition_function"

    meta = json.loads((out_dir / "study_metadata.json").read_text(encoding="utf-8"))
    assert len(meta["method_warnings"]) >= 2


def test_multilayer_yaml_all_keys_read() -> None:
    ml_yaml = PROJECT_ROOT / "configs" / "mos2_6x5_4atp_multilayer.yaml"
    cfg = load_config(ml_yaml)
    StudySettings.from_config(cfg, project_root=PROJECT_ROOT)
    assert cfg.unread_keys() == set()


def test_multilayer_best_of_and_decomposition_synth(tmp_path: Path, four_atp_xyz_path: Path) -> None:
    """Verify 1L -> best_of Layer 2 -> Layer 3 stacking, vacancy desorption, and substrate decay."""
    import yaml

    raw = load_config(TRACK_A_YAML).as_dict()
    raw["substrate"]["supercell_nx"] = 8
    raw["substrate"]["supercell_ny"] = 8
    raw["substrate"]["vacuum_A"] = 38.0
    raw["relaxation"]["max_steps"] = 6
    raw["relaxation"]["fmax_eV_per_A"] = 0.2
    raw["cluster_motifs"] = {}
    raw["cluster_cases"] = {}
    raw["grid_cases"] = {
        "L1_N4": {
            "base_case": "",
            "layer_index": 1,
            "grid_nx": 2,
            "grid_ny": 2,
            "pattern": "parallel",
            "tilt_deg": 0.0,
            "azimuth_deg": 150.0,
            "stagger_frac": 0.0,
            "row_azimuth_step_deg": 0.0,
            "offset_frac": [0.25, 0.25],
        },
        "L2_cand_a": {
            "base_case": "L1_N4",
            "layer_index": 2,
            "grid_nx": 2,
            "grid_ny": 2,
            "pattern": "parallel",
            "tilt_deg": 0.0,
            "azimuth_deg": 150.0,
            "stagger_frac": 0.0,
            "row_azimuth_step_deg": 0.0,
            "offset_frac": [0.27, 0.30],
        },
        "L2_cand_b": {
            "base_case": "L1_N4",
            "layer_index": 2,
            "grid_nx": 2,
            "grid_ny": 2,
            "pattern": "parallel",
            "tilt_deg": 0.0,
            "azimuth_deg": 330.0,
            "stagger_frac": 0.0,
            "row_azimuth_step_deg": 0.0,
            "offset_frac": [0.52, 0.55],
        },
        "L3_N1_probe": {
            "base_case": "best_of:L2_cand_a,L2_cand_b",
            "layer_index": 3,
            "grid_nx": 1,
            "grid_ny": 1,
            "pattern": "parallel",
            "tilt_deg": 0.0,
            "azimuth_deg": 150.0,
            "stagger_frac": 0.0,
            "row_azimuth_step_deg": 0.0,
            "offset_frac": [0.27, 0.30],
        },
        "L3_N4": {
            "base_case": "best_of:L2_cand_a,L2_cand_b",
            "layer_index": 3,
            "grid_nx": 2,
            "grid_ny": 2,
            "pattern": "parallel",
            "tilt_deg": 0.0,
            "azimuth_deg": 150.0,
            "stagger_frac": 0.0,
            "row_azimuth_step_deg": 0.0,
            "offset_frac": [0.27, 0.30],
        },
    }
    raw["vacancy_desorption"]["source_cases"] = [
        "L1_N4",
        "best_of:L2_cand_a,L2_cand_b",
        "L3_N4",
    ]
    raw["vacancy_desorption"]["sequential_pairs"] = {
        "L3_N1_probe": "best_of:L2_cand_a,L2_cand_b",
    }
    raw["study"]["base_config_path"] = str(PROJECT_ROOT / "config.yaml")
    raw["adsorbate"]["molecule_path"] = str(four_atp_xyz_path)

    yaml_path = tmp_path / "ml_study.yaml"
    yaml_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    out = run_coverage_study(
        yaml_path,
        backend_override="synth_morse",
        device_override="cpu",
        output_dir_override=tmp_path / "results",
    )
    cases = out["cases"]
    best_l2 = min(["L2_cand_a", "L2_cand_b"], key=lambda cid: cases[cid].energy_total_eV)
    assert cases["L3_N4"].base_case == best_l2
    assert cases["L3_N1_probe"].base_case == best_l2
    assert cases["L1_N4"].interlayer_min_heavy_A is None
    assert cases[best_l2].interlayer_min_heavy_A is not None
    assert cases["L3_N4"].interlayer_min_heavy_A is not None
    assert cases["L1_N4"].dz_above_slab_top_A < cases[best_l2].dz_above_slab_top_A < cases["L3_N4"].dz_above_slab_top_A
    assert abs(cases["L1_N4"].e_mos2_direct_per_mol_eV) > abs(cases[best_l2].e_mos2_direct_per_mol_eV)
    assert abs(cases[best_l2].e_mos2_direct_per_mol_eV) > abs(cases["L3_N4"].e_mos2_direct_per_mol_eV)
    des_ids = {row["desorption_id"] for row in out["desorption"]}
    assert f"vac_{best_l2}" in des_ids
    assert f"seq_L3_N1_probe_to_{best_l2}" in des_ids
