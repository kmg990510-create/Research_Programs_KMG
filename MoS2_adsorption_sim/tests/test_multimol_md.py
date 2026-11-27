"""Tests for finite-temperature multi-molecule MD config, unwrapped MSD, and synthetic run."""

from __future__ import annotations

from pathlib import Path

from ase.io import write as ase_write

from ads_core.builders.molecule import load_molecule_file
from ads_core.builders.multimol import StudySettings, build_multimol_assembly
from ads_core.builders.slab import build_mos2_slab
from ads_core.config import Config, load_config
from ads_core.simulation.multimol_md import MultiMolMdSettings, run_multimol_md_suite

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MD_YAML = PROJECT_ROOT / "configs" / "mos2_5x5_4atp_md.yaml"


def test_md_yaml_all_keys_read() -> None:
    cfg = load_config(MD_YAML)
    settings = MultiMolMdSettings.from_config(cfg, project_root=PROJECT_ROOT)
    assert cfg.unread_keys() == set()
    assert len(settings.runs) == 4


def test_multimol_md_smoke_synth(tmp_path: Path, four_atp_xyz_path: Path) -> None:
    study_cfg = load_config(PROJECT_ROOT / "configs" / "mos2_5x5_4atp_stability.yaml")
    study = StudySettings.from_config(study_cfg, project_root=PROJECT_ROOT)
    base_cfg = load_config(study.base_config_path)
    slab = build_mos2_slab(base_cfg, supercell=(5, 5), vacuum_A=26.0, fix_bottom_layer=True)
    mol = load_molecule_file(four_atp_xyz_path, base_cfg, molecule_id=study.molecule_id)
    case = next(c for c in study.cases if c.case_id == "N4_brick_flat")
    asm = build_multimol_assembly(slab.atoms, len(slab.atoms), (), mol, case, study)

    src_dir = tmp_path / "src_results" / "structures"
    src_dir.mkdir(parents=True)
    ase_write(src_dir / "N4_brick_flat_relaxed.xyz", asm.atoms)

    raw = load_config(MD_YAML).as_dict()
    raw["study"]["study_yaml"] = str(PROJECT_ROOT / "configs" / "mos2_5x5_4atp_stability.yaml")
    raw["study"]["output_dir"] = str(tmp_path / "md_out")
    raw["md"]["trajectory_stride"] = 5
    raw["quench"]["max_steps"] = 3
    raw["runs"] = {
        "smoke_N4": {
            "results_dir": str(tmp_path / "src_results"),
            "source_case": "N4_brick_flat",
            "temperature_K": 333.15,
            "steps": 10,
            "quench_after_md": True,
        }
    }
    yaml_path = tmp_path / "md_smoke.yaml"
    import yaml

    yaml_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    out = run_multimol_md_suite(yaml_path, backend_override="synth_morse", device_override="cpu")
    assert len(out["summary"]) == 1
    assert out["summary"][0]["residence_fraction"] == 1.0
    assert (tmp_path / "md_out" / "md_runs_summary.csv").exists()
    assert (tmp_path / "md_out" / "md_timeseries.csv").exists()
    assert (tmp_path / "md_out" / "trajectories" / "smoke_N4_traj.extxyz").exists()


def test_multilayer_md_yaml_and_two_layer_smoke(tmp_path: Path, four_atp_xyz_path: Path) -> None:
    import yaml

    ml_md_yaml = PROJECT_ROOT / "configs" / "mos2_6x5_4atp_multilayer_md.yaml"
    cfg = load_config(ml_md_yaml)
    MultiMolMdSettings.from_config(cfg, project_root=PROJECT_ROOT)
    assert cfg.unread_keys() == set()

    ml_study_yaml = PROJECT_ROOT / "configs" / "mos2_6x5_4atp_multilayer.yaml"
    study = StudySettings.from_config(load_config(ml_study_yaml), project_root=PROJECT_ROOT)
    base_cfg = load_config(study.base_config_path)
    slab = build_mos2_slab(base_cfg, supercell=(6, 5), vacuum_A=38.0, fix_bottom_layer=True)
    mol = load_molecule_file(four_atp_xyz_path, base_cfg, molecule_id=study.molecule_id)

    c1 = next(c for c in study.cases if c.case_id == "L1_N4_parallel")
    c2a = next(c for c in study.cases if c.case_id == "L2_N4_AB_diag_anti")
    c2b = next(c for c in study.cases if c.case_id == "L2_N4_AA_par")
    asm1 = build_multimol_assembly(slab.atoms, len(slab.atoms), (), mol, c1, study)
    asm2a = build_multimol_assembly(asm1.atoms, len(slab.atoms), asm1.all_mol_groups, mol, c2a, study)
    asm2b = build_multimol_assembly(asm1.atoms, len(slab.atoms), asm1.all_mol_groups, mol, c2b, study)

    src_dir = tmp_path / "src_ml"
    (src_dir / "structures").mkdir(parents=True)
    ase_write(src_dir / "structures" / "L2_N4_AB_diag_anti_relaxed.xyz", asm2a.atoms)
    ase_write(src_dir / "structures" / "L2_N4_AA_par_relaxed.xyz", asm2b.atoms)
    (src_dir / "coverage_summary.csv").write_text(
        "case_id,energy_total_eV\nL2_N4_AB_diag_anti,-100.5\nL2_N4_AA_par,-100.1\n",
        encoding="utf-8",
    )

    raw = load_config(ml_md_yaml).as_dict()
    raw["study"]["study_yaml"] = str(ml_study_yaml)
    raw["study"]["output_dir"] = str(tmp_path / "md_ml_out")
    raw["md"]["trajectory_stride"] = 5
    raw["quench"]["max_steps"] = 2
    raw["runs"] = {
        "ml_2L": {
            "results_dir": str(src_dir),
            "source_case": "best_of:L2_N4_AB_diag_anti,L2_N4_AA_par",
            "temperature_K": 333.15,
            "steps": 10,
            "quench_after_md": False,
        }
    }
    yaml_path = tmp_path / "ml_md_smoke.yaml"
    yaml_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    out = run_multimol_md_suite(yaml_path, backend_override="synth_morse", device_override="cpu")
    row = out["summary"][0]
    assert row["source_case"] == "L2_N4_AB_diag_anti"
    assert row["layer_count"] == 2
    assert row["n_molecules"] == 8
    assert row["residence_fraction"] == 1.0
    assert row["top_layer_mean_dz_A"] > row["mean_dz_A"]
