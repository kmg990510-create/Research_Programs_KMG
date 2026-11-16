"""Batch simulation execution in memory and review-applied result tables.

``run_batch`` executes the simulations and returns a ``BatchRun`` without
writing to disk. ``ads_core.report.export`` writes results and artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd
from ase import Atoms

from ads_core.builders.molecule import build_preset_molecule, load_molecule_file
from ads_core.builders.poses import build_poses
from ads_core.builders.slab import build_mos2_slab
from ads_core.calculators.factory import build_calculator_bundle
from ads_core.config import Config
from ads_core.model import (
    MdSettings,
    MoleculeSettings,
    MoleculeSpec,
    PoseResult,
    PoseSpec,
    STATUS_INVALID,
    SlabSettings,
    SlabSpec,
    WarningRecord,
)
from ads_core.review import ReviewState, make_group_key
from ads_core.simulation.md import MdResult, run_pose_md
from ads_core.simulation.quality import counts_in_summary, evaluate_pose
from ads_core.simulation.reference import ReferenceCache, ReferenceResult
from ads_core.simulation.relax import (
    BindingCurveResult,
    TrajectoryStep,
    relax_pose,
    scan_binding_curve,
)


@dataclass(frozen=True, eq=False)
class PoseArtifact:
    """In-memory structural and trajectory artifacts retained for one pose."""

    pose_id: str
    slab_indices: tuple[int, ...]
    mol_indices: tuple[int, ...]
    site_xy_A: tuple[float, float]
    initial_atoms: Atoms
    relaxed_atoms: Atoms
    trajectory_steps: tuple[TrajectoryStep, ...]
    trajectory_frames: tuple[Atoms, ...]


@dataclass
class BatchRun:
    """Everything produced by one simulation batch."""

    name: str
    config: Config
    calculator_id: str
    backend: str
    d3_enabled: bool
    calculator_metadata: dict[str, Any]
    slabs: dict[str, SlabSpec]
    molecules: dict[str, MoleculeSpec]
    references: list[ReferenceResult]
    results: list[PoseResult]
    artifacts: dict[str, PoseArtifact]
    binding_curves: list[BindingCurveResult] = field(default_factory=list)
    build_warnings: list[WarningRecord] = field(default_factory=list)
    md_results: list[MdResult] = field(default_factory=list)


def _resolve_molecule(item: str | Path, config: Config) -> MoleculeSpec:
    presets = set(MoleculeSettings.from_config(config).presets)
    if isinstance(item, str) and item in presets:
        return build_preset_molecule(item, config)
    path = Path(item)
    if path.is_file():
        return load_molecule_file(path, config)
    raise ValueError(f"Unknown preset molecule and file not found: {item!r}")


def parse_surface_spec(token: str, default_supercell: tuple[int, int]) -> tuple[str, tuple[int, int]]:
    """Parse ``pristine`` / ``V_S`` or ``pristine_4x4`` / ``V_S_3x3`` into (defect_type, supercell)."""
    parts = token.rsplit("_", 1)
    if len(parts) == 2 and "x" in parts[1]:
        dim_parts = parts[1].lower().split("x")
        if len(dim_parts) == 2 and dim_parts[0].isdigit() and dim_parts[1].isdigit():
            return parts[0], (int(dim_parts[0]), int(dim_parts[1]))
    return token, default_supercell


def _select_curve_poses(poses: list[PoseSpec], scan_all_sites: bool) -> list[PoseSpec]:
    if not poses:
        return []
    if not scan_all_sites:
        return [poses[0]]
    chosen: list[PoseSpec] = []
    seen_sites: set[str] = set()
    for p in poses:
        if p.site_type not in seen_sites:
            seen_sites.add(p.site_type)
            chosen.append(p)
    return chosen


def run_batch(
    batch_name: str,
    config: Config,
    *,
    surfaces: Sequence[str] | None = None,
    molecules: Sequence[str | Path] | None = None,
    supercell: tuple[int, int] | None = None,
    backend: str | None = None,
    d3_enabled: bool | None = None,
    device: str | None = None,
    site_types: list[str] | None = None,
    orientations: list[str] | None = None,
    azimuth_angles_deg: list[float] | None = None,
    heights_A: list[float] | None = None,
    scan_binding_curves: bool = False,
    scan_all_sites: bool = False,
    compare_no_d3: bool = False,
    run_md: bool | None = None,
    md_temperature_K: float | None = None,
    md_steps: int | None = None,
    md_timestep_fs: float | None = None,
    md_seed: int | None = None,
    skip_relax: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> BatchRun:
    """Build slabs/molecules/poses, relax with uMLIP+D3 (or synth), and evaluate quality in memory."""
    slab_defaults = SlabSettings.from_config(config)
    md_defaults = MdSettings.from_config(config)
    do_md = md_defaults.enabled if run_md is None else bool(run_md)
    default_sc = supercell if supercell is not None else (slab_defaults.supercell_nx, slab_defaults.supercell_ny)
    surface_tokens = list(surfaces) if surfaces else [slab_defaults.defect_type]
    molecule_items = list(molecules) if molecules else [MoleculeSettings.from_config(config).presets[0]]

    calc_bundle = build_calculator_bundle(config, backend=backend, d3_enabled=d3_enabled, device=device)
    bundles_to_run: list[tuple[Any, str]] = [(calc_bundle, "")]
    if compare_no_d3 and calc_bundle.d3_enabled:
        bundles_to_run.append(
            (build_calculator_bundle(config, backend=backend, d3_enabled=False, device=device), "__nod3")
        )

    slabs_map: dict[str, SlabSpec] = {}
    for token in surface_tokens:
        defect_type, sc = parse_surface_spec(token, default_sc)
        slab = build_mos2_slab(config, supercell=sc, defect_type=defect_type)
        slabs_map[slab.surface_id] = slab

    mols_map: dict[str, MoleculeSpec] = {}
    for item in molecule_items:
        mol = _resolve_molecule(item, config)
        mols_map[mol.molecule_id] = mol

    # Build all candidate poses first so total count is known for progress reporting
    pose_bundles: list[tuple[SlabSpec, MoleculeSpec, list[PoseSpec]]] = []
    build_warnings: list[WarningRecord] = []
    for slab in slabs_map.values():
        for mol in mols_map.values():
            built = build_poses(
                slab,
                mol,
                config,
                site_types=site_types,
                orientations=orientations,
                azimuth_angles_deg=azimuth_angles_deg,
                heights_A=heights_A,
            )
            build_warnings.extend(built.warnings)
            pose_bundles.append((slab, mol, built.poses))

    total_poses = sum(len(poses) for _, _, poses in pose_bundles) * len(bundles_to_run)
    ref_cache = ReferenceCache()
    references_seen: dict[tuple[str, str, str], ReferenceResult] = {}
    results: list[PoseResult] = []
    artifacts: dict[str, PoseArtifact] = {}
    binding_curves: list[BindingCurveResult] = []
    md_results: list[MdResult] = []

    done_count = 0
    for active_bundle, id_suffix in bundles_to_run:
        for slab, mol, poses in pose_bundles:
            if not skip_relax:
                ref_slab = ref_cache.get_slab(slab, active_bundle, config)
                ref_mol = ref_cache.get_molecule(mol, active_bundle, config)
                references_seen[("slab", slab.surface_id, active_bundle.calculator_id)] = ref_slab
                references_seen[("molecule", mol.molecule_id, active_bundle.calculator_id)] = ref_mol

                if scan_binding_curves and poses:
                    for curve_pose in _select_curve_poses(poses, scan_all_sites):
                        tagged_curve_pose = (
                            replace(curve_pose, pose_id=f"{curve_pose.pose_id}{id_suffix}") if id_suffix else curve_pose
                        )
                        binding_curves.append(scan_binding_curve(tagged_curve_pose, ref_slab, ref_mol, active_bundle, config))

            for pose in poses:
                active_pose = replace(pose, pose_id=f"{pose.pose_id}{id_suffix}") if id_suffix else pose
                done_count += 1
                if progress_callback is not None:
                    progress_callback(done_count, total_poses, active_pose.pose_id)

                if not skip_relax:
                    relaxation = relax_pose(active_pose, active_bundle, config)
                    pose_result = evaluate_pose(active_pose, relaxation, ref_slab, ref_mol, mol, slab, active_bundle, config)
                    results.append(pose_result)
                    artifacts[active_pose.pose_id] = PoseArtifact(
                        pose_id=active_pose.pose_id,
                        slab_indices=active_pose.slab_indices,
                        mol_indices=active_pose.mol_indices,
                        site_xy_A=active_pose.site_xy_A,
                        initial_atoms=relaxation.initial_atoms,
                        relaxed_atoms=relaxation.relaxed_atoms,
                        trajectory_steps=relaxation.trajectory_steps,
                        trajectory_frames=relaxation.trajectory_frames,
                    )

                if do_md:
                    md_results.append(
                        run_pose_md(
                            active_pose,
                            active_bundle,
                            config,
                            temperature_K=md_temperature_K,
                            steps=md_steps,
                            timestep_fs=md_timestep_fs,
                            seed=md_seed,
                        )
                    )

    return BatchRun(
        name=batch_name,
        config=config,
        calculator_id=calc_bundle.calculator_id,
        backend=calc_bundle.backend,
        d3_enabled=calc_bundle.d3_enabled,
        calculator_metadata=calc_bundle.metadata,
        slabs=slabs_map,
        molecules=mols_map,
        references=list(references_seen.values()),
        results=results,
        artifacts=artifacts,
        binding_curves=binding_curves,
        build_warnings=build_warnings,
        md_results=md_results,
    )


def md_results_table(md_results: Sequence[MdResult]) -> pd.DataFrame:
    """Convert ``MdResult`` records into a flat summary DataFrame."""
    columns = [
        "pose_id",
        "surface_id",
        "molecule_id",
        "site_type",
        "orientation",
        "calculator_id",
        "failed",
        "failure_message",
        "n_steps",
        "temperature_K",
        "timestep_fs",
        "final_dz_com_A",
        "mean_dz_com_A",
        "min_dz_com_A",
        "max_dz_com_A",
        "residence_fraction",
        "stayed_adsorbed",
    ]
    if not md_results:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "pose_id": m.pose_id,
            "surface_id": m.surface_id,
            "molecule_id": m.molecule_id,
            "site_type": m.site_type,
            "orientation": m.orientation,
            "calculator_id": m.calculator_id,
            "failed": m.failed,
            "failure_message": m.failure_message,
            "n_steps": m.n_steps,
            "temperature_K": m.temperature_K,
            "timestep_fs": m.timestep_fs,
            "final_dz_com_A": m.final_dz_com_A,
            "mean_dz_com_A": m.mean_dz_com_A,
            "min_dz_com_A": m.min_dz_com_A,
            "max_dz_com_A": m.max_dz_com_A,
            "residence_fraction": m.residence_fraction,
            "stayed_adsorbed": m.stayed_adsorbed,
        }
        for m in md_results
    ]
    return pd.DataFrame(rows, columns=columns)


def results_table(results: Sequence[PoseResult]) -> pd.DataFrame:
    """Convert evaluated ``PoseResult`` records into a flat DataFrame."""
    columns = [
        "pose_id",
        "surface_id",
        "defect_type",
        "molecule_id",
        "site_type",
        "orientation",
        "azimuth_deg",
        "initial_height_A",
        "calculator_id",
        "d3_enabled",
        "converged",
        "n_steps",
        "fmax_final_eV_per_A",
        "e_ads_eV",
        "e_ads_umlip_eV",
        "e_ads_d3_eV",
        "vdw_fraction",
        "e_int_eV",
        "e_def_slab_eV",
        "e_def_mol_eV",
        "d_min_A",
        "d_min_pair",
        "dz_com_A",
        "lateral_shift_A",
        "tilt_deg",
        "max_bond_stretch_pct",
        "slab_rmsd_A",
        "status",
        "reasons",
    ]
    if not results:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "pose_id": r.pose_id,
            "surface_id": r.surface_id,
            "defect_type": r.defect_type,
            "molecule_id": r.molecule_id,
            "site_type": r.site_type,
            "orientation": r.orientation,
            "azimuth_deg": r.azimuth_deg,
            "initial_height_A": r.initial_height_A,
            "calculator_id": r.calculator_id,
            "d3_enabled": r.d3_enabled,
            "converged": r.converged,
            "n_steps": r.n_steps,
            "fmax_final_eV_per_A": r.fmax_final_eV_per_A,
            "e_ads_eV": r.e_ads_eV,
            "e_ads_umlip_eV": r.e_ads_umlip_eV,
            "e_ads_d3_eV": r.e_ads_d3_eV,
            "vdw_fraction": r.vdw_fraction,
            "e_int_eV": r.e_int_eV,
            "e_def_slab_eV": r.e_def_slab_eV,
            "e_def_mol_eV": r.e_def_mol_eV,
            "d_min_A": r.d_min_A,
            "d_min_pair": r.d_min_pair,
            "dz_com_A": r.dz_com_A,
            "lateral_shift_A": r.lateral_shift_A,
            "tilt_deg": r.tilt_deg,
            "max_bond_stretch_pct": r.max_bond_stretch_pct,
            "slab_rmsd_A": r.slab_rmsd_A,
            "status": r.status,
            "reasons": "; ".join(r.reasons),
        }
        for r in results
    ]
    return pd.DataFrame(rows, columns=columns)


def poses_frame(run: BatchRun, review: ReviewState | None = None) -> pd.DataFrame:
    """Pose result table with ``ReviewState`` applied (``decision``, ``note``, ``included``, ``group_display``)."""
    review = review or ReviewState()
    frame = results_table(run.results)
    if frame.empty:
        for col in ("decision", "note", "included", "group_key", "group_display"):
            frame[col] = pd.Series(dtype=object)
        return frame

    decisions, notes, included, group_keys, group_displays = [], [], [], [], []
    for r in run.results:
        decision = review.decision(r.pose_id)
        g_key = make_group_key(r.surface_id, r.molecule_id, r.calculator_id)
        decisions.append(decision)
        notes.append(review.note(r.pose_id))
        included.append(counts_in_summary(r.status, decision))
        group_keys.append(g_key)
        group_displays.append(review.display_group(g_key))

    frame["decision"] = decisions
    frame["note"] = notes
    frame["included"] = included
    frame["group_key"] = group_keys
    frame["group_display"] = group_displays
    return frame


def ordered_groups(frame: pd.DataFrame, review: ReviewState | None = None) -> list[str]:
    present = list(dict.fromkeys(frame["group_display"])) if not frame.empty else []
    preferred = [name for name in (review.group_order if review else []) if name in present]
    return preferred + [name for name in present if name not in preferred]


def status_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts = {"valid": 0, "attention": 0, STATUS_INVALID: 0}
    if not frame.empty:
        counts.update({str(k): int(v) for k, v in frame["status"].value_counts().items()})
    return counts
