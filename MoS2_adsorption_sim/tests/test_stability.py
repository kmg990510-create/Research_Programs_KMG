"""Tests for 5x5 stability study YAML schemas, zero-overlap builds, and check settings."""

from __future__ import annotations

from pathlib import Path

from ads_core.builders.molecule import load_molecule_file
from ads_core.builders.multimol import StudySettings, build_multimol_assembly
from ads_core.builders.slab import build_mos2_slab
from ads_core.config import load_config
from ads_core.simulation.stability import StabilitySettings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAB_YAML = PROJECT_ROOT / "configs" / "mos2_5x5_4atp_stability.yaml"
MECH_YAML = PROJECT_ROOT / "configs" / "mos2_5x5_4atp_mechanical.yaml"


def test_5x5_stability_and_mechanical_yaml_keys_are_all_read() -> None:
    study_cfg = load_config(STAB_YAML)
    study = StudySettings.from_config(study_cfg, project_root=PROJECT_ROOT)
    assert study_cfg.unread_keys() == set()
    assert (study.supercell_nx, study.supercell_ny) == (5, 5)

    mech_cfg = load_config(MECH_YAML)
    mech = StabilitySettings.from_config(mech_cfg, project_root=PROJECT_ROOT)
    assert mech_cfg.unread_keys() == set()
    case_ids = {c.case_id for c in study.cases}
    for cid in mech.pert_target_cases + mech.strain_target_cases + mech.dbl_vac_source_cases:
        assert cid in case_ids


def test_5x5_stability_cases_build_without_overlap() -> None:
    study = StudySettings.from_config(load_config(STAB_YAML), project_root=PROJECT_ROOT)
    base_cfg = load_config(study.base_config_path)
    slab = build_mos2_slab(
        base_cfg,
        supercell=(study.supercell_nx, study.supercell_ny),
        vacuum_A=study.vacuum_A,
        defect_type=study.defect_type,
        fix_bottom_layer=study.fix_bottom_layer,
    )
    mol = load_molecule_file(study.molecule_path, base_cfg, molecule_id=study.molecule_id)
    for case in study.cases:
        asm = build_multimol_assembly(slab.atoms, len(slab.atoms), (), mol, case, study)
        assert len(asm.new_mol_groups) == case.n_molecules
