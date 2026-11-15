from __future__ import annotations

import numpy as np
import pytest
from ase.calculators.mixing import SumCalculator

from ads_core.builders.molecule import build_preset_molecule
from ads_core.builders.poses import build_poses
from ads_core.builders.slab import build_mos2_slab
from ads_core.calculators.factory import build_calculator_bundle
from ads_core.calculators.synth_calc import SynthD3Calculator, SynthUmlipCalculator
from ads_core.config import Config, load_config
from ads_core.model import (
    DEFECT_PRISTINE,
    DEFECT_VS,
    ORIENTATION_ANCHOR_DOWN,
    ORIENTATION_FLAT,
    SITE_HOLLOW,
    SITE_S_TOP,
    SITE_VS,
    STATUS_ATTENTION,
    STATUS_INVALID,
    STATUS_VALID,
)
from ads_core.simulation.reference import ReferenceCache
from ads_core.simulation.relax import RelaxationResult, relax_pose, scan_binding_curve
from ads_core.simulation.quality import counts_in_summary, evaluate_pose


def _numerical_forces(atoms, calc, eps: float = 1e-5) -> np.ndarray:
    work = atoms.copy()
    work.calc = calc
    forces = np.zeros((len(work), 3), dtype=float)
    pos0 = work.get_positions().copy()
    for i in range(len(work)):
        for c in range(3):
            p_plus = pos0.copy()
            p_plus[i, c] += eps
            work.set_positions(p_plus)
            e_plus = float(work.get_potential_energy())

            p_minus = pos0.copy()
            p_minus[i, c] -= eps
            work.set_positions(p_minus)
            e_minus = float(work.get_potential_energy())

            forces[i, c] = -(e_plus - e_minus) / (2.0 * eps)
    return forces


def test_synth_analytical_forces_match_finite_difference() -> None:
    config = load_config()
    slab = build_mos2_slab(config, supercell=(2, 2), defect_type=DEFECT_PRISTINE)
    h2o = build_preset_molecule("H2O", config)
    pose = build_poses(
        slab,
        h2o,
        config,
        site_types=[SITE_HOLLOW],
        orientations=[ORIENTATION_FLAT],
        azimuth_angles_deg=[0.0],
        heights_A=[2.5],
    ).poses[0]

    # Perturb slightly so all force components are non-zero
    rng = np.random.default_rng(7)
    atoms = pose.atoms.copy()
    atoms.positions += rng.normal(scale=0.04, size=atoms.positions.shape)

    for calc in (SynthUmlipCalculator(), SynthD3Calculator()):
        check = atoms.copy()
        check.calc = calc
        f_analytic = check.get_forces()
        f_numeric = _numerical_forces(atoms, calc)
        assert np.max(np.abs(f_analytic - f_numeric)) < 1e-5


def test_calculator_factory_builds_sum_calculator_and_rejects_invalid_backend() -> None:
    config = load_config()
    with_d3 = build_calculator_bundle(config, backend="synth_morse", d3_enabled=True)
    assert with_d3.calculator_id == "synth_morse+d3"
    assert isinstance(with_d3.total_calc, SumCalculator)
    assert with_d3.d3_calc is not None

    no_d3 = build_calculator_bundle(config, backend="synth_morse", d3_enabled=False)
    assert no_d3.calculator_id == "synth_morse_no_d3"
    assert no_d3.d3_calc is None

    with pytest.raises(ValueError, match="Unsupported backend"):
        build_calculator_bundle(config, backend="unknown_mlip")


def test_reference_cache_and_physical_regimes() -> None:
    config = load_config()
    h2o = build_preset_molecule("H2O", config)
    slab_p = build_mos2_slab(config, defect_type=DEFECT_PRISTINE)
    slab_v = build_mos2_slab(config, defect_type=DEFECT_VS)

    # 1. Pristine + D3 -> Physisorption dominated by dispersion
    bundle_d3 = build_calculator_bundle(config, backend="synth_morse", d3_enabled=True)
    cache = ReferenceCache()
    ref_s = cache.get_slab(slab_p, bundle_d3, config)
    ref_m = cache.get_molecule(h2o, bundle_d3, config)
    assert cache.get_slab(slab_p, bundle_d3, config) is ref_s
    assert ref_s.converged and ref_m.converged

    pose_p = build_poses(
        slab_p, h2o, config, site_types=[SITE_HOLLOW], orientations=[ORIENTATION_FLAT], azimuth_angles_deg=[0.0]
    ).poses[0]
    rel_p = relax_pose(pose_p, bundle_d3, config)
    res_p = evaluate_pose(pose_p, rel_p, ref_s, ref_m, h2o, slab_p, bundle_d3, config)

    assert res_p.converged
    assert res_p.status == STATUS_VALID
    assert "physisorption_regime" in res_p.reasons
    assert counts_in_summary(res_p.status)
    assert res_p.e_ads_eV is not None and res_p.e_ads_eV < -0.05
    assert res_p.e_ads_d3_eV is not None and res_p.e_ads_d3_eV < 0.0
    assert res_p.vdw_fraction is not None and res_p.vdw_fraction > 0.8
    # Exact energy decompositions
    assert res_p.e_ads_eV == pytest.approx(res_p.e_ads_umlip_eV + res_p.e_ads_d3_eV, abs=1e-6)
    assert res_p.e_ads_eV == pytest.approx(res_p.e_int_eV + res_p.e_def_slab_eV + res_p.e_def_mol_eV, abs=1e-6)
    assert len(rel_p.trajectory_steps) == rel_p.n_steps + 1
    assert len(rel_p.trajectory_frames) >= 2

    # 2. Pristine WITHOUT D3 -> Repulsive/non-binding -> attention
    bundle_nod3 = build_calculator_bundle(config, backend="synth_morse", d3_enabled=False)
    cache_nod3 = ReferenceCache()
    ref_s_no = cache_nod3.get_slab(slab_p, bundle_nod3, config)
    ref_m_no = cache_nod3.get_molecule(h2o, bundle_nod3, config)
    rel_no = relax_pose(pose_p, bundle_nod3, config)
    res_no = evaluate_pose(pose_p, rel_no, ref_s_no, ref_m_no, h2o, slab_p, bundle_nod3, config)

    assert res_no.e_ads_d3_eV is None
    assert res_no.vdw_fraction is None
    assert res_no.e_ads_eV is not None and res_no.e_ads_eV >= 0.0
    assert res_no.status == STATUS_ATTENTION
    assert "repulsive_adsorption" in res_no.reasons

    # 3. V_S vacancy + D3 -> Strong chemisorption onto exposed Mo
    ref_sv = cache.get_slab(slab_v, bundle_d3, config)
    pose_v = build_poses(
        slab_v, h2o, config, site_types=[SITE_VS], orientations=[ORIENTATION_ANCHOR_DOWN], azimuth_angles_deg=[0.0]
    ).poses[0]
    rel_v = relax_pose(pose_v, bundle_d3, config)
    res_v = evaluate_pose(pose_v, rel_v, ref_sv, ref_m, h2o, slab_v, bundle_d3, config)

    assert res_v.converged
    assert res_v.status == STATUS_VALID
    assert "chemisorption_regime" in res_v.reasons
    assert res_v.e_ads_eV is not None and res_v.e_ads_eV <= -1.0
    assert res_v.d_min_pair == "O-Mo"


def test_1d_binding_curve_shows_d3_well() -> None:
    config = load_config()
    h2o = build_preset_molecule("H2O", config)
    slab = build_mos2_slab(config, defect_type=DEFECT_PRISTINE)
    pose = build_poses(
        slab, h2o, config, site_types=[SITE_HOLLOW], orientations=[ORIENTATION_FLAT], azimuth_angles_deg=[0.0]
    ).poses[0]

    bundle = build_calculator_bundle(config, backend="synth_morse", d3_enabled=True)
    cache = ReferenceCache()
    ref_s = cache.get_slab(slab, bundle, config)
    ref_m = cache.get_molecule(h2o, bundle, config)

    curve = scan_binding_curve(pose, ref_s, ref_m, bundle, config)
    assert len(curve.points) == len(config.number_list("relaxation.scan_heights_A"))
    min_total = min(p.e_ads_total_eV for p in curve.points)
    min_umlip = min(p.e_ads_umlip_eV for p in curve.points)
    assert min_total < -0.05
    assert min_umlip >= -1e-4  # uMLIP alone shows no physisorption well
    for p in curve.points:
        assert p.e_ads_d3_eV is not None
        assert p.e_ads_total_eV == pytest.approx(p.e_ads_umlip_eV + p.e_ads_d3_eV, abs=1e-8)


def test_quality_flags_not_converged_desorbed_overlap_and_failure() -> None:
    config = load_config()
    h2o = build_preset_molecule("H2O", config)
    slab_p = build_mos2_slab(config, defect_type=DEFECT_PRISTINE)
    slab_v = build_mos2_slab(config, defect_type=DEFECT_VS)
    bundle = build_calculator_bundle(config, backend="synth_morse", d3_enabled=True)
    cache = ReferenceCache()
    ref_s = cache.get_slab(slab_p, bundle, config)
    ref_m = cache.get_molecule(h2o, bundle, config)

    pose = build_poses(
        slab_p, h2o, config, site_types=[SITE_S_TOP], orientations=[ORIENTATION_FLAT], azimuth_angles_deg=[0.0]
    ).poses[0]

    # A. Not converged (max_steps = 1) -> invalid
    data_short = config.as_dict()
    data_short["relaxation"]["max_steps"] = 1
    data_short["relaxation"]["fmax_eV_per_A"] = 1e-6
    rel_short = relax_pose(pose, bundle, Config(data_short))
    res_short = evaluate_pose(pose, rel_short, ref_s, ref_m, h2o, slab_p, bundle, config)
    assert not res_short.converged
    assert res_short.status == STATUS_INVALID
    assert "not_converged" in res_short.reasons
    assert not counts_in_summary(res_short.status)

    # B. Desorbed to vacuum (molecule placed at dz = 6.5 A, converged with 0 steps / tiny force) -> attention
    far_atoms = pose.atoms.copy()
    far_atoms.positions[list(pose.mol_indices), 2] += 4.5
    rel_far = RelaxationResult(
        pose_id=pose.pose_id,
        calculator_id=bundle.calculator_id,
        converged=True,
        failed=False,
        failure_message="",
        n_steps=1,
        fmax_final_eV_per_A=0.005,
        energy_total_eV=0.0,
        initial_atoms=pose.atoms.copy(),
        relaxed_atoms=far_atoms,
    )
    res_far = evaluate_pose(pose, rel_far, ref_s, ref_m, h2o, slab_p, bundle, config)
    assert res_far.status == STATUS_ATTENTION
    assert "desorbed_to_vacuum" in res_far.reasons
    assert counts_in_summary(res_far.status)

    # C. Atomic overlap (< 1.1 A) -> invalid
    overlap_atoms = pose.atoms.copy()
    # Move molecule atom 0 within 0.7 A of top S atom
    top_s_idx = [i for i in pose.slab_indices if overlap_atoms.get_tags()[i] == 2][0]
    overlap_atoms.positions[pose.mol_indices[0]] = overlap_atoms.positions[top_s_idx] + np.array([0.0, 0.0, 0.7])
    rel_overlap = RelaxationResult(
        pose_id=pose.pose_id,
        calculator_id=bundle.calculator_id,
        converged=True,
        failed=False,
        failure_message="",
        n_steps=1,
        fmax_final_eV_per_A=0.01,
        energy_total_eV=0.0,
        initial_atoms=pose.atoms.copy(),
        relaxed_atoms=overlap_atoms,
    )
    res_overlap = evaluate_pose(pose, rel_overlap, ref_s, ref_m, h2o, slab_p, bundle, config)
    assert res_overlap.status == STATUS_INVALID
    assert "atomic_overlap" in res_overlap.reasons

    # D. Bond stretch: pristine -> invalid (unexpected_dissociation), defect -> attention (dissociation_candidate)
    stretched_atoms = pose.atoms.copy()
    stretched_atoms.positions[pose.mol_indices[1], 0] += 0.45  # >20% stretch of O-H
    rel_stretch = RelaxationResult(
        pose_id=pose.pose_id,
        calculator_id=bundle.calculator_id,
        converged=True,
        failed=False,
        failure_message="",
        n_steps=1,
        fmax_final_eV_per_A=0.01,
        energy_total_eV=0.0,
        initial_atoms=pose.atoms.copy(),
        relaxed_atoms=stretched_atoms,
    )
    res_stretch_p = evaluate_pose(pose, rel_stretch, ref_s, ref_m, h2o, slab_p, bundle, config)
    assert res_stretch_p.status == STATUS_INVALID
    assert "unexpected_dissociation" in res_stretch_p.reasons

    ref_sv = cache.get_slab(slab_v, bundle, config)
    pose_v = build_poses(
        slab_v, h2o, config, site_types=[SITE_VS], orientations=[ORIENTATION_FLAT], azimuth_angles_deg=[0.0]
    ).poses[0]
    stretched_v = pose_v.atoms.copy()
    stretched_v.positions[pose_v.mol_indices[1], 0] += 0.45
    rel_stretch_v = RelaxationResult(
        pose_id=pose_v.pose_id,
        calculator_id=bundle.calculator_id,
        converged=True,
        failed=False,
        failure_message="",
        n_steps=1,
        fmax_final_eV_per_A=0.01,
        energy_total_eV=0.0,
        initial_atoms=pose_v.atoms.copy(),
        relaxed_atoms=stretched_v,
    )
    res_stretch_v = evaluate_pose(pose_v, rel_stretch_v, ref_sv, ref_m, h2o, slab_v, bundle, config)
    assert res_stretch_v.status == STATUS_ATTENTION
    assert "dissociation_candidate" in res_stretch_v.reasons

    # E. Calculator failed -> invalid, metrics must be None (never 0)
    rel_fail = RelaxationResult(
        pose_id=pose.pose_id,
        calculator_id=bundle.calculator_id,
        converged=False,
        failed=True,
        failure_message="boom",
        n_steps=0,
        fmax_final_eV_per_A=None,
        energy_total_eV=None,
        initial_atoms=pose.atoms.copy(),
        relaxed_atoms=pose.atoms.copy(),
    )
    res_fail = evaluate_pose(pose, rel_fail, ref_s, ref_m, h2o, slab_p, bundle, config)
    assert res_fail.status == STATUS_INVALID
    assert "calculator_failed" in res_fail.reasons
    assert res_fail.e_ads_eV is None
    assert res_fail.d_min_A is None
