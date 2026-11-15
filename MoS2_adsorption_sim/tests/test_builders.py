from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.constraints import FixAtoms
from ase.geometry import get_distances
from ase.io import write as ase_write

from ads_core.builders.molecule import build_preset_molecule, load_molecule_file
from ads_core.builders.poses import build_poses, find_adsorption_sites, orient_molecule_positions
from ads_core.builders.slab import build_mos2_slab
from ads_core.config import load_config
from ads_core.model import (
    DEFECT_PRISTINE,
    DEFECT_VS,
    DEFECT_VS2,
    ORIENTATION_ANCHOR_DOWN,
    ORIENTATION_ANCHOR_UP,
    ORIENTATION_FLAT,
    SITE_BRIDGE,
    SITE_HOLLOW,
    SITE_MO_TOP,
    SITE_S_TOP,
    SITE_VS,
    SITE_VS2,
)


def test_pristine_slab_stoichiometry_vacuum_and_constraints() -> None:
    config = load_config()
    slab = build_mos2_slab(config, supercell=(4, 4), defect_type=DEFECT_PRISTINE, vacuum_A=20.0, fix_bottom_layer=True)

    assert slab.surface_id == "pristine_4x4"
    assert len(slab.atoms) == 48
    symbols = slab.atoms.get_chemical_symbols()
    assert symbols.count("Mo") == 16
    assert symbols.count("S") == 32
    assert slab.defect_positions_A == ()

    # Thickness and total vacuum
    assert slab.top_s_z_A - slab.bottom_s_z_A == pytest.approx(3.17, abs=1e-4)
    assert slab.atoms.cell[2, 2] == pytest.approx(23.17, abs=1e-4)
    assert tuple(slab.atoms.pbc) == (True, True, True)

    # Bottom S layer (16 atoms) fixed
    assert len(slab.atoms.constraints) == 1
    assert isinstance(slab.atoms.constraints[0], FixAtoms)
    assert len(slab.atoms.constraints[0].index) == 16

    # Unconstrained when fix_bottom_layer=False
    free_slab = build_mos2_slab(config, fix_bottom_layer=False)
    assert free_slab.atoms.constraints == []


def test_vacancy_slabs_vs_and_vs2() -> None:
    config = load_config()
    slab_vs = build_mos2_slab(config, supercell=(4, 4), defect_type=DEFECT_VS)
    assert slab_vs.surface_id == "V_S_4x4"
    assert len(slab_vs.atoms) == 47
    assert len(slab_vs.defect_positions_A) == 1
    tags_vs = slab_vs.atoms.get_tags()
    assert int(np.sum(tags_vs == 2)) == 15  # 1 top S removed
    assert int(np.sum(tags_vs == 0)) == 16  # bottom S intact

    slab_vs2 = build_mos2_slab(config, supercell=(4, 4), defect_type=DEFECT_VS2)
    assert slab_vs2.surface_id == "V_S2_4x4"
    assert len(slab_vs2.atoms) == 46
    assert len(slab_vs2.defect_positions_A) == 1
    tags_vs2 = slab_vs2.atoms.get_tags()
    assert int(np.sum(tags_vs2 == 2)) == 15  # 1 top S removed
    assert int(np.sum(tags_vs2 == 0)) == 15  # 1 bottom S directly underneath removed


def test_preset_molecules_and_tma_geometry() -> None:
    config = load_config()
    presets = config.text_list("molecules.presets")
    for name in presets:
        mol = build_preset_molecule(name, config)
        assert mol.molecule_id == name
        assert mol.source == "preset"
        assert tuple(mol.atoms.pbc) == (True, True, True)
        assert mol.atoms.cell[0, 0] == pytest.approx(20.0)
        assert len(mol.reference_bonds) >= 1

    tma = build_preset_molecule("TMA", config)
    assert tma.formula == "C3H9Al"
    assert len(tma.atoms) == 13
    assert tma.atoms.get_chemical_symbols()[tma.anchor_index] == "Al"
    assert len(tma.reference_bonds) == 12  # 3 Al-C + 9 C-H

    # Check Al-C distances in TMA match config (1.96 A)
    pos = tma.atoms.get_positions()
    al_pos = pos[tma.anchor_index]
    c_indices = [i for i, s in enumerate(tma.atoms.get_chemical_symbols()) if s == "C"]
    for idx in c_indices:
        assert np.linalg.norm(pos[idx] - al_pos) == pytest.approx(1.96, abs=1e-4)


def test_load_external_xyz_molecule_and_overlap_check(tmp_path: Path) -> None:
    config = load_config()
    valid_xyz = tmp_path / "pyridine_frag.xyz"
    ase_write(valid_xyz, Atoms("NH3", positions=[[0, 0, 0], [0, 0.9, 0.4], [0.8, -0.4, 0.4], [-0.8, -0.4, 0.4]]))

    mol = load_molecule_file(valid_xyz, config)
    assert mol.molecule_id == "pyridine_frag"
    assert mol.source == "file"
    assert mol.atoms.get_chemical_symbols()[mol.anchor_index] == "N"

    bad_xyz = tmp_path / "clashing.xyz"
    ase_write(bad_xyz, Atoms("H2", positions=[[0, 0, 0], [0.2, 0, 0]]))
    with pytest.raises(ValueError, match="overlapping"):
        load_molecule_file(bad_xyz, config)


def test_pymatgen_site_discovery_pristine_and_defect() -> None:
    config = load_config()
    pristine = build_mos2_slab(config, defect_type=DEFECT_PRISTINE)
    sites = find_adsorption_sites(pristine, config)
    site_map = {s.site_type: s for s in sites}
    assert set(site_map.keys()) == {SITE_MO_TOP, SITE_S_TOP, SITE_HOLLOW, SITE_BRIDGE}

    # Verify Mo_top really sits above a Mo atom and S_top really sits above a top-S atom
    tags = pristine.atoms.get_tags()
    pos = pristine.atoms.get_positions()
    mo_xy = pos[tags == 1, :2]
    top_s_xy = pos[tags == 2, :2]
    assert np.min(np.linalg.norm(mo_xy - np.array(site_map[SITE_MO_TOP].xy_A), axis=1)) < 0.1
    assert np.min(np.linalg.norm(top_s_xy - np.array(site_map[SITE_S_TOP].xy_A), axis=1)) < 0.1

    # Defect slab must expose V_S at the exact removed S coordinate
    vs_slab = build_mos2_slab(config, defect_type=DEFECT_VS)
    vs_sites = find_adsorption_sites(vs_slab, config)
    vs_site = [s for s in vs_sites if s.site_type == SITE_VS]
    assert len(vs_site) == 1
    assert vs_site[0].xy_A == pytest.approx(vs_slab.defect_positions_A[0][:2], abs=1e-6)

    vs2_slab = build_mos2_slab(config, defect_type=DEFECT_VS2)
    vs2_sites = find_adsorption_sites(vs2_slab, config)
    assert any(s.site_type == SITE_VS2 for s in vs2_sites)


def test_orientation_and_pose_building_with_collision_lift() -> None:
    config = load_config()
    slab = build_mos2_slab(config, defect_type=DEFECT_PRISTINE)
    h2o = build_preset_molecule("H2O", config)

    pos_down = orient_molecule_positions(h2o, ORIENTATION_ANCHOR_DOWN, 0.0)
    pos_up = orient_molecule_positions(h2o, ORIENTATION_ANCHOR_UP, 0.0)
    pos_flat = orient_molecule_positions(h2o, ORIENTATION_FLAT, 0.0)

    # In H2O, O is anchor (index 0): anchor_down puts O below H, anchor_up puts O above H
    assert pos_down[h2o.anchor_index, 2] < np.mean(pos_down[:, 2])
    assert pos_up[h2o.anchor_index, 2] > np.mean(pos_up[:, 2])
    # Flat orientation minimizes z spread of the planar H2O molecule
    assert np.ptp(pos_flat[:, 2]) < 0.1

    # Build poses across all sites & orientations
    built = build_poses(slab, h2o, config)
    # 4 sites x 3 orientations x 2 azimuths x 1 height = 24 poses
    assert len(built.poses) == 24
    for pose in built.poses:
        assert len(pose.atoms) == len(slab.atoms) + len(h2o.atoms)
        assert len(pose.atoms.constraints) == 1
        assert len(pose.atoms.constraints[0].index) == 16
        assert pose.atoms.info["pose_id"] == pose.pose_id

    # Very low initial height (0.5 A) must be automatically lifted to >= min_initial_distance_A (1.6 A)
    low_built = build_poses(
        slab,
        h2o,
        config,
        site_types=[SITE_S_TOP],
        orientations=[ORIENTATION_ANCHOR_DOWN],
        azimuth_angles_deg=[0.0],
        heights_A=[0.5],
    )
    assert len(low_built.poses) == 1
    assert any(w.code == "initial_height_adjusted" for w in low_built.warnings)
    pose = low_built.poses[0]
    _, dists = get_distances(
        pose.atoms.positions[list(pose.slab_indices)],
        pose.atoms.positions[list(pose.mol_indices)],
        cell=pose.atoms.cell,
        pbc=pose.atoms.pbc,
    )
    assert float(np.min(dists)) >= 1.6 - 1e-6
