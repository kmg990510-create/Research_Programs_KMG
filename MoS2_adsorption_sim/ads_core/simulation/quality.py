"""Quality classification (valid / attention / invalid) and reason codes for poses."""

from __future__ import annotations

from ads_core.calculators.factory import CalculatorBundle
from ads_core.config import Config
from ads_core.model import (
    DEFECT_PRISTINE,
    MoleculeSpec,
    PoseResult,
    PoseSpec,
    QualitySettings,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    STATUS_ATTENTION,
    STATUS_INVALID,
    STATUS_VALID,
    SlabSpec,
    WarningRecord,
)
from ads_core.simulation.metrics import compute_pose_metrics
from ads_core.simulation.reference import ReferenceResult
from ads_core.simulation.relax import RelaxationResult

# Authoritative registry of quality reason codes -> status level (AGENTS.md Section 5).
REASONS: dict[str, str] = {
    "calculator_failed": STATUS_INVALID,
    "reference_not_converged": STATUS_INVALID,
    "not_converged": STATUS_INVALID,
    "atomic_overlap": STATUS_INVALID,
    "slab_disrupted": STATUS_INVALID,
    "unexpected_dissociation": STATUS_INVALID,
    "repulsive_adsorption": STATUS_ATTENTION,
    "desorbed_to_vacuum": STATUS_ATTENTION,
    "dissociation_candidate": STATUS_ATTENTION,
    "large_slab_distortion": STATUS_ATTENTION,
    "migrated_to_other_site": STATUS_VALID,
    "physisorption_regime": STATUS_VALID,
    "chemisorption_regime": STATUS_VALID,
}

# Human-readable explanation for every registered quality reason code.
REASON_MESSAGES: dict[str, str] = {
    "calculator_failed": "Calculator raised an error or returned non-finite energy/forces.",
    "reference_not_converged": "Isolated slab or gas-phase molecule reference relaxation did not converge.",
    "not_converged": "Geometry optimization reached max_steps without satisfying the fmax convergence criterion.",
    "atomic_overlap": "Minimum slab-molecule distance fell below min_allowed_distance_A (severe atomic overlap).",
    "slab_disrupted": "Slab RMSD exceeded max_slab_rmsd_invalid_A (2D MoS2 lattice disrupted).",
    "unexpected_dissociation": "Adsorbate covalent bond stretched beyond bond_stretch_warn_pct on pristine basal plane.",
    "repulsive_adsorption": "Optimization converged with non-binding E_ads >= 0.0 eV.",
    "desorbed_to_vacuum": "Adsorbate drifted beyond max_adsorption_distance_A from the slab surface.",
    "dissociation_candidate": "Adsorbate bond stretched beyond bond_stretch_warn_pct near a defect site (possible dissociative chemisorption).",
    "large_slab_distortion": "Local slab RMSD or deformation energy exceeded the warning threshold.",
    "migrated_to_other_site": "Adsorbate migrated laterally beyond migration_threshold_A from its initial site.",
    "physisorption_regime": "Exothermic physisorption regime (dispersive van der Waals dominated).",
    "chemisorption_regime": "Strong exothermic chemisorption regime.",
}


def counts_in_summary(status: str, decision: str = "auto") -> bool:
    """Single source of truth for whether a pose enters summary statistics and Boltzmann averages."""
    return status != STATUS_INVALID and decision != "rejected"


def evaluate_pose(
    pose: PoseSpec,
    relaxation: RelaxationResult,
    ref_slab: ReferenceResult,
    ref_mol: ReferenceResult,
    molecule: MoleculeSpec,
    slab: SlabSpec,
    calc_bundle: CalculatorBundle,
    config: Config,
) -> PoseResult:
    """Combine relaxation, reference energies, metrics, and quality rules into ``PoseResult``."""
    q_settings = QualitySettings.from_config(config)
    metrics = compute_pose_metrics(pose, relaxation, ref_slab, ref_mol, molecule, calc_bundle)

    reasons: list[str] = []
    warnings: list[WarningRecord] = list(ref_slab.warnings) + list(ref_mol.warnings)

    def _add(code: str, message: str) -> None:
        if code not in REASONS:
            raise ValueError(f"Unregistered reason code: {code!r}")
        if code not in reasons:
            reasons.append(code)
        level = REASONS[code]
        severity = (
            SEVERITY_ERROR
            if level == STATUS_INVALID
            else (SEVERITY_WARNING if level == STATUS_ATTENTION else SEVERITY_INFO)
        )
        warnings.append(WarningRecord(code=code, message=message, target_id=pose.pose_id, severity=severity))

    if relaxation.failed:
        _add("calculator_failed", f"Calculator failed: {relaxation.failure_message}")
    if not ref_slab.converged or not ref_mol.converged:
        _add("reference_not_converged", "Reference slab or molecule did not converge cleanly.")
    if not relaxation.failed and not relaxation.converged:
        _add(
            "not_converged",
            f"Pose did not converge within {relaxation.n_steps} steps (fmax={relaxation.fmax_final_eV_per_A}).",
        )

    if metrics.d_min_A is not None:
        if metrics.d_min_A < q_settings.min_allowed_distance_A:
            _add(
                "atomic_overlap",
                f"Minimum slab-molecule distance {metrics.d_min_A:.3f} A < {q_settings.min_allowed_distance_A:.2f} A.",
            )
        elif metrics.d_min_A > q_settings.max_adsorption_distance_A:
            _add(
                "desorbed_to_vacuum",
                f"Molecule drifted to d_min={metrics.d_min_A:.2f} A > {q_settings.max_adsorption_distance_A:.2f} A.",
            )

    if metrics.slab_rmsd_A is not None:
        if metrics.slab_rmsd_A > q_settings.max_slab_rmsd_invalid_A:
            _add(
                "slab_disrupted",
                f"Slab RMSD {metrics.slab_rmsd_A:.3f} A exceeded invalid limit {q_settings.max_slab_rmsd_invalid_A:.2f} A.",
            )
        elif metrics.slab_rmsd_A > q_settings.max_slab_rmsd_warn_A:
            _add(
                "large_slab_distortion",
                f"Slab RMSD {metrics.slab_rmsd_A:.3f} A exceeded warning limit {q_settings.max_slab_rmsd_warn_A:.2f} A.",
            )

    if metrics.e_def_slab_eV is not None and metrics.e_def_slab_eV > q_settings.max_slab_def_warn_eV:
        _add(
            "large_slab_distortion",
            f"Slab deformation energy {metrics.e_def_slab_eV:.3f} eV > {q_settings.max_slab_def_warn_eV:.2f} eV.",
        )

    if metrics.max_bond_stretch_pct is not None and metrics.max_bond_stretch_pct > q_settings.bond_stretch_warn_pct:
        if slab.defect_type == DEFECT_PRISTINE:
            _add(
                "unexpected_dissociation",
                f"Bond stretch {metrics.max_bond_stretch_pct:.1f}% on pristine basal plane.",
            )
        else:
            _add(
                "dissociation_candidate",
                f"Bond stretch {metrics.max_bond_stretch_pct:.1f}% on defective {slab.defect_type} surface.",
            )

    if metrics.e_ads_eV is not None:
        if metrics.e_ads_eV >= 0.0:
            _add("repulsive_adsorption", f"Non-binding E_ads = {metrics.e_ads_eV:+.3f} eV >= 0.")
        elif metrics.e_ads_eV <= q_settings.chemisorption_threshold_eV:
            _add("chemisorption_regime", f"Strong chemisorption regime (E_ads = {metrics.e_ads_eV:.3f} eV).")
        elif metrics.e_ads_eV <= q_settings.physisorption_threshold_eV:
            _add("physisorption_regime", f"Physisorption regime (E_ads = {metrics.e_ads_eV:.3f} eV).")

    if metrics.lateral_shift_A is not None and metrics.lateral_shift_A > q_settings.migration_threshold_A:
        _add(
            "migrated_to_other_site",
            f"Molecule migrated laterally by {metrics.lateral_shift_A:.2f} A from initial site {pose.site_type}.",
        )

    statuses = [REASONS[r] for r in reasons]
    if STATUS_INVALID in statuses:
        overall_status = STATUS_INVALID
    elif STATUS_ATTENTION in statuses:
        overall_status = STATUS_ATTENTION
    else:
        overall_status = STATUS_VALID

    return PoseResult(
        pose_id=pose.pose_id,
        surface_id=pose.surface_id,
        defect_type=slab.defect_type,
        molecule_id=pose.molecule_id,
        site_type=pose.site_type,
        orientation=pose.orientation,
        azimuth_deg=pose.azimuth_deg,
        initial_height_A=pose.initial_height_A,
        calculator_id=calc_bundle.calculator_id,
        d3_enabled=calc_bundle.d3_enabled,
        converged=relaxation.converged,
        n_steps=relaxation.n_steps,
        fmax_final_eV_per_A=relaxation.fmax_final_eV_per_A,
        e_ads_eV=metrics.e_ads_eV,
        e_ads_umlip_eV=metrics.e_ads_umlip_eV,
        e_ads_d3_eV=metrics.e_ads_d3_eV,
        vdw_fraction=metrics.vdw_fraction,
        e_int_eV=metrics.e_int_eV,
        e_def_slab_eV=metrics.e_def_slab_eV,
        e_def_mol_eV=metrics.e_def_mol_eV,
        d_min_A=metrics.d_min_A,
        d_min_pair=metrics.d_min_pair,
        dz_com_A=metrics.dz_com_A,
        lateral_shift_A=metrics.lateral_shift_A,
        tilt_deg=metrics.tilt_deg,
        max_bond_stretch_pct=metrics.max_bond_stretch_pct,
        slab_rmsd_A=metrics.slab_rmsd_A,
        status=overall_status,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )
