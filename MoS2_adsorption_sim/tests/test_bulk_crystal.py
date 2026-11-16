"""Tests for Pca2_1 bulk 4-ATP crystal builder, zwitterion proton transfer, and (001) cleavage smoke run."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ads_core.builders.molecule import load_molecule_file
from ads_core.config import load_config
from ads_core.simulation.bulk_crystal import (
    BulkCrystalSettings,
    generate_spacegroup_candidates,
    make_zwitterion_molecule,
    run_bulk_crystal_study,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BULK_YAML = PROJECT_ROOT / "configs" / "4atp_bulk_pca21.yaml"


def test_bulk_crystal_yaml_all_keys_read() -> None:
    cfg = load_config(BULK_YAML)
    BulkCrystalSettings.from_config(cfg, project_root=PROJECT_ROOT)
    assert cfg.unread_keys() == set()


def test_zwitterion_and_pca21_packing_valid() -> None:
    cfg = load_config(BULK_YAML)
    settings = BulkCrystalSettings.from_config(cfg, project_root=PROJECT_ROOT)
    base_cfg = load_config(settings.base_config_path)
    mol_spec = load_molecule_file(settings.molecule_path, base_cfg, molecule_id=settings.molecule_id)

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


def test_bulk_crystal_study_smoke_synth(tmp_path: Path) -> None:
    import yaml

    raw = load_config(BULK_YAML).as_dict()
    raw["study"]["base_config_path"] = str(PROJECT_ROOT / "config.yaml")
    raw["adsorbate"]["molecule_path"] = str(PROJECT_ROOT / "data" / "molecules" / "4-ATP.xyz")
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
