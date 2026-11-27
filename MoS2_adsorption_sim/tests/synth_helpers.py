"""Synthetic YAML dict builders for MoS2_adsorption_sim public tests (no private data)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def make_synthetic_study_dict(
    molecule_path: Path,
    output_dir: Path,
    *,
    study_name: str = "synth_study",
    supercell: tuple[int, int] = (6, 6),
    vacuum_A: float = 26.0,
    disulfide_enabled: bool = True,
) -> dict[str, Any]:
    """Return a complete generic StudySettings dictionary for synthetic tests."""
    return {
        "study": {
            "name": study_name,
            "base_config_path": str(BASE_CONFIG_PATH),
            "output_dir": str(output_dir),
        },
        "substrate": {
            "supercell_nx": supercell[0],
            "supercell_ny": supercell[1],
            "defect_type": "pristine",
            "vacuum_A": vacuum_A,
            "fix_bottom_layer": True,
        },
        "adsorbate": {
            "molecule_id": "SYNTH_THIOL",
            "molecule_path": str(molecule_path),
            "anchor_element": "S",
            "initial_height_A": 3.1,
            "min_initial_distance_A": 1.6,
            "interlayer_gap_A": 3.3,
        },
        "relaxation": {
            "optimizer": "BFGS",
            "fmax_eV_per_A": 0.03,
            "max_steps": 50,
        },
        "cluster_motifs": {
            "dimer_head_to_tail": (
                [[-4.20, -2.42, 30.0, 0.0], [4.20, 2.42, 30.0, 0.0]]
                if supercell == (5, 5)
                else [[-4.75, 0.0, 0.0, 0.0], [4.75, 0.0, 0.0, 0.0]]
            ),
            "dimer_side_by_side": [[0.0, -3.5, 0.0, 0.0], [0.0, 3.5, 0.0, 0.0]],
        },
        "cluster_cases": {
            "N2_dimer_head_to_tail": {
                "base_case": "",
                "layer_index": 1,
                "motif": "dimer_head_to_tail",
                "center_frac": [0.50, 0.50],
                "rotation_deg": 0.0,
            },
            "N2_dimer_side_by_side": {
                "base_case": "",
                "layer_index": 1,
                "motif": "dimer_side_by_side",
                "center_frac": [0.50, 0.50],
                "rotation_deg": 0.0,
            },
        },
        "grid_cases": {
            "N1_monomer_flat": {
                "base_case": "",
                "layer_index": 1,
                "grid_nx": 1,
                "grid_ny": 1,
                "pattern": "parallel",
                "tilt_deg": 0.0,
                "azimuth_deg": 30.0,
                "stagger_frac": 0.0,
                "row_azimuth_step_deg": 0.0,
                "offset_frac": [0.50, 0.50],
            },
            "N4_parallel_flat": {
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
            "N4_brick_flat": {
                "base_case": "",
                "layer_index": 1,
                "grid_nx": 2,
                "grid_ny": 2,
                "pattern": "parallel",
                "tilt_deg": 0.0,
                "azimuth_deg": 30.0,
                "stagger_frac": 0.5,
                "row_azimuth_step_deg": 0.0,
                "offset_frac": [0.25, 0.25],
            },
            "N4_antiparallel_brick_flat": {
                "base_case": "",
                "layer_index": 1,
                "grid_nx": 2,
                "grid_ny": 2,
                "pattern": "antiparallel",
                "tilt_deg": 0.0,
                "azimuth_deg": 30.0,
                "stagger_frac": 0.5,
                "row_azimuth_step_deg": 0.0,
                "offset_frac": [0.25, 0.25],
            },
        },
        "vacancy_desorption": {
            "source_cases": ["N4_parallel_flat"],
            "remove_mol_index": 0,
            "sequential_pairs": {"N2_dimer_head_to_tail": "N1_monomer_flat"},
        },
        "disulfide_check": {
            "enabled": disulfide_enabled,
            "s_s_bond_A": 2.05,
            "c_s_s_angle_deg": 103.0,
            "dihedral_deg": 85.0,
            "h_h_bond_A": 0.74,
            "o_o_bond_A": 1.21,
            "h2o_oh_bond_A": 0.96,
            "h2o_angle_deg": 104.5,
            "initial_height_A": 3.1,
            "azimuth_deg": 0.0,
        },
        "thermal_analysis": {
            "temperatures_C": [60.0, 150.0],
            "prefactors_hz": [1.0e12, 1.0e13],
            "anneal_duration_s": 3600.0,
            "min_intermol_hbond_cutoff_A": 3.5,
        },
    }


def make_synthetic_multilayer_dict(molecule_path: Path, output_dir: Path) -> dict[str, Any]:
    """Return a generic multilayer StudySettings dictionary for synthetic tests."""
    raw = make_synthetic_study_dict(
        molecule_path,
        output_dir,
        study_name="synth_multilayer",
        supercell=(6, 5),
        vacuum_A=38.0,
        disulfide_enabled=False,
    )
    raw["cluster_motifs"] = {}
    raw["cluster_cases"] = {}
    raw["grid_cases"] = {
        "L1_N4_parallel": {
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
        "L2_N4_AA_par": {
            "base_case": "L1_N4_parallel",
            "layer_index": 2,
            "grid_nx": 2,
            "grid_ny": 2,
            "pattern": "parallel",
            "tilt_deg": 0.0,
            "azimuth_deg": 150.0,
            "stagger_frac": 0.0,
            "row_azimuth_step_deg": 0.0,
            "offset_frac": [0.25, 0.25],
        },
        "L2_N4_AB_diag_anti": {
            "base_case": "L1_N4_parallel",
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
        "L3_N4_ABA_anti": {
            "base_case": "best_of:L2_N4_AA_par,L2_N4_AB_diag_anti",
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
    raw["vacancy_desorption"] = {
        "source_cases": ["L1_N4_parallel", "best_of:L2_N4_AA_par,L2_N4_AB_diag_anti", "L3_N4_ABA_anti"],
        "remove_mol_index": 0,
        "sequential_pairs": {},
    }
    return raw


def make_synthetic_bulk_dict(
    molecule_path: Path,
    output_dir: Path,
    *,
    space_group: str = "Pca2_1",
    cell_abc: tuple[float, float, float] = (11.226, 6.101, 8.282),
    cell_angles: tuple[float, float, float] = (90.0, 90.0, 90.0),
    cif_path: str = "",
    source: str = "DEPRECATED synthetic packing test cell",
) -> dict[str, Any]:
    """Return a generic BulkCrystalSettings dictionary for synthetic tests."""
    return {
        "study": {
            "name": f"synth_bulk_{space_group.lower()}",
            "base_config_path": str(BASE_CONFIG_PATH),
            "output_dir": str(output_dir),
        },
        "adsorbate": {
            "molecule_id": "SYNTH_THIOL",
            "molecule_path": str(molecule_path),
            "anchor_element": "S",
        },
        "crystal": {
            "space_group": space_group,
            "a_A": cell_abc[0],
            "b_A": cell_abc[1],
            "c_A": cell_abc[2],
            "alpha_deg": cell_angles[0],
            "beta_deg": cell_angles[1],
            "gamma_deg": cell_angles[2],
            "cif_path": cif_path,
            "source": source,
            "min_intermol_dist_A": 1.75,
        },
        "candidates": {
            "tautomers": ["neutral", "zwitterion"],
            "n_rot_trials": 200,
            "n_per_tautomer": 2,
            "seed": 42,
        },
        "relaxation": {
            "relax_cell": True,
            "optimizer": "BFGS",
            "fmax_eV_per_A": 0.03,
            "max_steps": 50,
            "cell_max_steps": 25,
        },
        "vacancy_and_surface": {
            "bulk_supercell": [1, 1, 1],
            "slab_repeat_xy": [1, 1],
            "slab_vacuum_A": 18.0,
        },
    }


def make_synthetic_md_dict(
    study_yaml_path: Path,
    output_dir: Path,
    runs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return a generic MultiMolMdSettings dictionary for synthetic tests."""
    return {
        "study": {
            "study_yaml": str(study_yaml_path),
            "output_dir": str(output_dir),
        },
        "md": {
            "mace_dtype": "float32",
            "quench_mace_dtype": "float64",
            "timestep_fs": 0.5,
            "friction_per_fs": 0.01,
            "trajectory_stride": 5,
            "hbond_cutoff_A": 3.5,
            "adsorption_cutoff_A": 5.0,
            "seed": 42,
        },
        "quench": {
            "optimizer": "BFGS",
            "fmax_eV_per_A": 0.03,
            "max_steps": 10,
        },
        "runs": runs,
    }


def make_synthetic_stability_dict(study_yaml_path: Path, results_dir: Path) -> dict[str, Any]:
    """Return a generic StabilitySettings dictionary for synthetic tests."""
    return {
        "source_study": {
            "study_yaml": str(study_yaml_path),
            "results_dir": str(results_dir),
        },
        "perturbation_check": {
            "target_cases": ["N4_brick_flat", "N4_parallel_flat", "N4_antiparallel_brick_flat"],
            "amplitudes_A": [0.05, 0.10],
            "seed": 42,
            "basin_energy_tol_eV": 0.02,
            "basin_rmsd_tol_A": 0.30,
        },
        "sheet_strain_check": {
            "target_cases": ["N4_brick_flat", "N4_parallel_flat"],
            "scale_factors": [0.95, 1.00, 1.05],
        },
        "double_vacancy_check": {
            "source_cases": ["N4_brick_flat", "N4_parallel_flat"],
            "second_remove_mol_indices": [0, 1, 2],
        },
    }
