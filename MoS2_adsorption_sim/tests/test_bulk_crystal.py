"""Tests for bulk molecular crystal builder, monoclinic Pc packing, CIF load, and (001) cleavage."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from ase.io import write as ase_write

from ads_core.builders.molecule import load_molecule_file
from ads_core.config import Config, load_config
from ads_core.simulation.bulk_crystal import (
    BulkCrystalSettings,
    generate_spacegroup_candidates,
    make_zwitterion_molecule,
    run_bulk_crystal_study,
)

from synth_helpers import make_synthetic_bulk_dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_bulk_crystal_yaml_all_keys_read(tmp_path: Path, four_atp_xyz_path: Path) -> None:
    cfg = Config(make_synthetic_bulk_dict(four_atp_xyz_path, tmp_path / "out"))
    BulkCrystalSettings.from_config(cfg, project_root=PROJECT_ROOT)
    assert cfg.unread_keys() == set()


def test_zwitterion_and_pca21_packing_valid(tmp_path: Path, four_atp_xyz_path: Path) -> None:
    cfg = Config(make_synthetic_bulk_dict(four_atp_xyz_path, tmp_path / "out"))
    settings = BulkCrystalSettings.from_config(cfg, project_root=PROJECT_ROOT)
    base_cfg = load_config(settings.base_config_path)
    mol_spec = load_molecule_file(four_atp_xyz_path, base_cfg, molecule_id=settings.molecule_id)

    zwit = make_zwitterion_molecule(mol_spec.atoms, anchor_element=settings.anchor_element)
    syms = zwit.get_chemical_symbols()
    n_idx = syms.index("N")
    s_idx = syms.index("S")
    h_idx = [i for i, s in enumerate(syms) if s == "H"]
    # Thiol S should have 0 H neighbors < 1.65 A; N should have 3 H neighbors < 1.25 A
    assert sum(1 for h in h_idx if zwit.get_distance(s_idx, h) < 1.65) == 0
    assert sum(1 for h in h_idx if zwit.get_distance(n_idx, h) < 1.25) == 3

    cands = generate_spacegroup_candidates(
        mol_spec.atoms,
        (settings.cell_a_A, settings.cell_b_A, settings.cell_c_A),
        space_group=settings.space_group,
        min_intermol_dist_A=1.70,
        n_rot_trials=200,
        n_candidates=2,
        seed=42,
    )
    assert len(cands) >= 1
    _, atoms, d_inter, _ = cands[0]
    assert len(atoms) == 4 * len(mol_spec.atoms)
    assert d_inter >= 1.70


def test_bulk_crystal_study_smoke_synth(tmp_path: Path, four_atp_xyz_path: Path) -> None:
    import yaml

    raw = make_synthetic_bulk_dict(four_atp_xyz_path, tmp_path / "bulk_out")
    raw["candidates"]["n_rot_trials"] = 120
    raw["candidates"]["n_per_tautomer"] = 1
    raw["relaxation"]["relax_cell"] = False
    raw["relaxation"]["max_steps"] = 3
    raw["relaxation"]["fmax_eV_per_A"] = 0.5
    raw["vacancy_and_surface"]["bulk_supercell"] = [1, 1, 1]
    raw["vacancy_and_surface"]["slab_repeat_xy"] = [1, 1]

    yaml_path = tmp_path / "bulk_smoke.yaml"
    yaml_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    out = run_bulk_crystal_study(
        yaml_path,
        backend_override="synth_morse",
        device_override="cpu",
        output_dir_override=tmp_path / "bulk_out",
    )
    out_dir = Path(out["output_dir"])
    assert (out_dir / "crystal_summary.csv").exists()
    assert (out_dir / "crystal_surface_desorption.csv").exists()
    assert len(out["crystals"]) == 2
    assert len(out["surface_desorption"]) == 2
    meta = json.loads((out_dir / "study_metadata.json").read_text(encoding="utf-8"))
    assert any("DEPRECATED" in w.upper() for w in meta["method_warnings"])


def test_pc_monoclinic_yaml_and_packing(tmp_path: Path, four_atp_xyz_path: Path) -> None:
    raw = make_synthetic_bulk_dict(
        four_atp_xyz_path,
        tmp_path / "pc_out",
        space_group="Pc",
        cell_abc=(7.2305, 5.8513, 7.7552),
        cell_angles=(90.0, 107.364, 90.0),
        source="Synthetic monoclinic Pc cell (Z=2)",
    )
    cfg = Config(raw)
    settings = BulkCrystalSettings.from_config(cfg, project_root=PROJECT_ROOT)
    assert cfg.unread_keys() == set()
    assert settings.space_group == "Pc"
    assert settings.cell_beta_deg == pytest.approx(107.364)

    base_cfg = load_config(settings.base_config_path)
    mol_spec = load_molecule_file(four_atp_xyz_path, base_cfg, molecule_id=settings.molecule_id)

    cands = generate_spacegroup_candidates(
        mol_spec.atoms,
        (settings.cell_a_A, settings.cell_b_A, settings.cell_c_A),
        space_group=settings.space_group,
        cell_angles_deg=(settings.cell_alpha_deg, settings.cell_beta_deg, settings.cell_gamma_deg),
        min_intermol_dist_A=1.70,
        n_rot_trials=250,
        n_candidates=2,
        seed=42,
    )
    assert len(cands) >= 1
    _, atoms, d_inter, _ = cands[0]
    assert len(atoms) == 2 * len(mol_spec.atoms)
    assert d_inter >= 1.70
    assert atoms.get_volume() == pytest.approx(313.15, rel=0.01)


def test_bulk_crystal_cif_direct_load_smoke(tmp_path: Path, four_atp_xyz_path: Path) -> None:
    import yaml

    raw = make_synthetic_bulk_dict(
        four_atp_xyz_path,
        tmp_path / "pc_out",
        space_group="Pc",
        cell_abc=(7.2305, 5.8513, 7.7552),
        cell_angles=(90.0, 107.364, 90.0),
        source="Synthetic monoclinic Pc cell (Z=2)",
    )
    cfg = Config(raw)
    settings = BulkCrystalSettings.from_config(cfg, project_root=PROJECT_ROOT)
    base_cfg = load_config(settings.base_config_path)
    mol_spec = load_molecule_file(four_atp_xyz_path, base_cfg, molecule_id=settings.molecule_id)
    _, pc_atoms, _, _ = generate_spacegroup_candidates(
        mol_spec.atoms,
        (settings.cell_a_A, settings.cell_b_A, settings.cell_c_A),
        space_group=settings.space_group,
        cell_angles_deg=(settings.cell_alpha_deg, settings.cell_beta_deg, settings.cell_gamma_deg),
        min_intermol_dist_A=1.70,
        n_rot_trials=250,
        n_candidates=1,
        seed=42,
    )[0]

    cif_file = tmp_path / "pc_mock.cif"
    ase_write(cif_file, pc_atoms, format="cif")

    raw["crystal"]["cif_path"] = str(cif_file)
    raw["relaxation"]["relax_cell"] = False
    raw["relaxation"]["max_steps"] = 3
    raw["relaxation"]["fmax_eV_per_A"] = 0.5
    raw["vacancy_and_surface"]["bulk_supercell"] = [1, 1, 1]
    raw["vacancy_and_surface"]["slab_repeat_xy"] = [1, 1]

    yaml_path = tmp_path / "pc_cif_smoke.yaml"
    yaml_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    out = run_bulk_crystal_study(
        yaml_path,
        backend_override="synth_morse",
        device_override="cpu",
        output_dir_override=tmp_path / "pc_out",
    )
    out_dir = Path(out["output_dir"])
    assert len(out["crystals"]) == 1
    assert out["crystals"][0]["case_id"] == "cif_exp_fixed"

    with (out_dir / "crystal_summary.csv").open("r", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert "beta_deg" in rows[0]
    assert "pressure_GPa" in rows[0]
    assert float(rows[0]["beta_deg"]) == pytest.approx(107.364, abs=0.2)

    meta = json.loads((out_dir / "study_metadata.json").read_text(encoding="utf-8"))
    assert "monoclinic Pc" in meta["crystal_source"]
    assert isinstance(meta["method_warnings"], list)
    assert meta["cif_path"] == str(cif_file)
