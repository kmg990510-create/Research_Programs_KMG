"""Pose structure relaxation with trajectory recording and 1D binding curve scan."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from ase import Atoms
from ase.geometry import find_mic
from ase.optimize import BFGS, FIRE, LBFGS

from ads_core.calculators.factory import CalculatorBundle
from ads_core.config import Config
from ads_core.model import PoseSpec, RelaxationSettings
from ads_core.simulation.reference import ReferenceResult, single_point_components

LOGGER = logging.getLogger(__name__)

_OPTIMIZERS = {
    "BFGS": BFGS,
    "LBFGS": LBFGS,
    "FIRE": FIRE,
}


@dataclass(frozen=True)
class TrajectoryStep:
    """One optimization step recorded for convergence plots."""

    step: int
    energy_eV: float
    fmax_eV_per_A: float
    dz_com_A: float | None


@dataclass(frozen=True, eq=False)
class RelaxationResult:
    """Output of relaxing a single slab + molecule pose."""

    pose_id: str
    calculator_id: str
    converged: bool
    failed: bool
    failure_message: str
    n_steps: int
    fmax_final_eV_per_A: float | None
    energy_total_eV: float | None
    initial_atoms: Atoms
    relaxed_atoms: Atoms
    trajectory_steps: tuple[TrajectoryStep, ...] = ()
    trajectory_frames: tuple[Atoms, ...] = ()


@dataclass(frozen=True)
class BindingCurvePoint:
    """One vertical height point along a 1D E(z) binding curve scan."""

    dz_A: float
    e_ads_total_eV: float
    e_ads_umlip_eV: float
    e_ads_d3_eV: float | None


@dataclass(frozen=True)
class BindingCurveResult:
    """1D vertical binding curve E(z) for one pose/site and calculator."""

    pose_id: str
    surface_id: str
    molecule_id: str
    site_type: str
    calculator_id: str
    d3_enabled: bool
    points: tuple[BindingCurvePoint, ...] = field(default_factory=tuple)
    dz_eq_A: float | None = None
    e_min_total_eV: float | None = None
    e_min_umlip_eV: float | None = None
    e_min_d3_eV: float | None = None
    has_attractive_well: bool = False


def _extract_curve_equilibrium(
    points: tuple[BindingCurvePoint, ...],
) -> tuple[float | None, float | None, float | None, float | None, bool]:
    """Extract equilibrium height dz_eq and well depth E_min via 3-point quadratic fit."""
    if len(points) < 3:
        return (None, None, None, None, False)
    ordered = sorted(points, key=lambda p: p.dz_A)
    dz = np.array([p.dz_A for p in ordered], dtype=float)
    e_tot = np.array([p.e_ads_total_eV for p in ordered], dtype=float)
    e_u = np.array([p.e_ads_umlip_eV for p in ordered], dtype=float)
    idx = int(np.argmin(e_tot))
    if not (0 < idx < len(ordered) - 1) or not (e_tot[idx] < -0.01):
        return (None, None, None, None, False)

    if dz[idx - 1] < dz[idx] < dz[idx + 1]:
        coeffs = np.polyfit(dz[idx - 1 : idx + 2], e_tot[idx - 1 : idx + 2], 2)
        a, b, c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])
        if a > 1.0e-8:
            dz_eq = float(np.clip(-b / (2.0 * a), dz[idx - 1], dz[idx + 1]))
            e_min = float(a * dz_eq * dz_eq + b * dz_eq + c)
        else:
            dz_eq = float(dz[idx])
            e_min = float(e_tot[idx])
    else:
        dz_eq = float(dz[idx])
        e_min = float(e_tot[idx])

    e_min_u = float(np.interp(dz_eq, dz, e_u))
    if all(p.e_ads_d3_eV is not None for p in ordered):
        e_d3 = np.array([float(p.e_ads_d3_eV) for p in ordered], dtype=float)
        e_min_d3: float | None = float(np.interp(dz_eq, dz, e_d3))
    else:
        e_min_d3 = None
    return (dz_eq, e_min, e_min_u, e_min_d3, True)


def _compute_dz_com_A(atoms: Atoms, slab_indices: tuple[int, ...], mol_indices: tuple[int, ...]) -> float | None:
    if not slab_indices or not mol_indices:
        return None
    tags = atoms.get_tags()
    top_s = [i for i in slab_indices if tags[i] == 2]
    ref_indices = top_s if top_s else list(slab_indices)
    pos = atoms.get_positions()
    top_z = float(np.mean(pos[ref_indices, 2]))

    # Unwrap molecule around its first atom to stay intact across periodic boundaries
    mol_pos_raw = pos[list(mol_indices)]
    rel, _ = find_mic(mol_pos_raw - mol_pos_raw[0], cell=atoms.cell, pbc=atoms.pbc)
    mol_pos = mol_pos_raw[0] + rel
    masses = atoms.get_masses()[list(mol_indices)]
    com_z = float(np.sum(mol_pos[:, 2] * masses) / np.sum(masses))

    dz = com_z - top_z
    lz = float(atoms.cell[2, 2])
    if atoms.pbc[2] and lz > 0:
        dz -= lz * round(dz / lz)
    return dz


def relax_pose(
    pose: PoseSpec,
    calc_bundle: CalculatorBundle,
    config: Config,
) -> RelaxationResult:
    """Relax a candidate adsorption pose and record step-by-step trajectory and frames."""
    settings = RelaxationSettings.from_config(config)
    initial = pose.atoms.copy()
    work = pose.atoms.copy()
    work.calc = calc_bundle.total_calc
    opt_cls = _OPTIMIZERS[settings.optimizer]

    steps_log: list[TrajectoryStep] = []
    frames: list[Atoms] = []

    def _record_step(step_idx: int) -> None:
        energy = float(work.get_potential_energy())
        forces = work.get_forces()
        fmax = float(np.max(np.linalg.norm(forces, axis=1))) if len(forces) else 0.0
        dz = _compute_dz_com_A(work, pose.slab_indices, pose.mol_indices)
        steps_log.append(TrajectoryStep(step=step_idx, energy_eV=energy, fmax_eV_per_A=fmax, dz_com_A=dz))
        if step_idx % settings.trajectory_stride == 0:
            snap = work.copy()
            snap.calc = None
            snap.info["step"] = step_idx
            frames.append(snap)

    try:
        _record_step(0)
        opt = opt_cls(work, logfile=None)
        opt.attach(lambda: _record_step(int(opt.nsteps)) if int(opt.nsteps) > 0 else None)
        converged = bool(opt.run(fmax=settings.fmax_eV_per_A, steps=settings.max_steps))

        final_step = int(opt.nsteps)
        if not steps_log or steps_log[-1].step != final_step:
            _record_step(final_step)
        if not frames or frames[-1].info.get("step") != final_step:
            snap = work.copy()
            snap.calc = None
            snap.info["step"] = final_step
            frames.append(snap)

        final_energy = steps_log[-1].energy_eV
        final_fmax = steps_log[-1].fmax_eV_per_A
    except Exception as exc:  # pragma: no cover - defensive guard for external MLIP backends
        LOGGER.exception("Pose relaxation failed for %s", pose.pose_id)
        work.calc = None
        return RelaxationResult(
            pose_id=pose.pose_id,
            calculator_id=calc_bundle.calculator_id,
            converged=False,
            failed=True,
            failure_message=str(exc),
            n_steps=len(steps_log),
            fmax_final_eV_per_A=None,
            energy_total_eV=None,
            initial_atoms=initial,
            relaxed_atoms=work,
            trajectory_steps=tuple(steps_log),
            trajectory_frames=tuple(frames),
        )

    relaxed_clean = work.copy()
    relaxed_clean.calc = None
    return RelaxationResult(
        pose_id=pose.pose_id,
        calculator_id=calc_bundle.calculator_id,
        converged=converged,
        failed=False,
        failure_message="",
        n_steps=int(opt.nsteps),
        fmax_final_eV_per_A=final_fmax,
        energy_total_eV=final_energy,
        initial_atoms=initial,
        relaxed_atoms=relaxed_clean,
        trajectory_steps=tuple(steps_log),
        trajectory_frames=tuple(frames),
    )


def scan_binding_curve(
    pose: PoseSpec,
    ref_slab: ReferenceResult,
    ref_mol: ReferenceResult,
    calc_bundle: CalculatorBundle,
    config: Config,
    *,
    heights_A: list[float] | None = None,
) -> BindingCurveResult:
    """Evaluate single-point E_ads(dz) across vertical heights above the top S plane.

    Uses the relaxed reference slab and molecule geometries rigidly translated to each
    height so total, uMLIP-only, and DFT-D3 contributions can be plotted side by side.
    """
    if ref_slab.energy_total_eV is None or ref_mol.energy_total_eV is None:
        raise ValueError("Reference slab and molecule energies are required for binding curve scan")

    settings = RelaxationSettings.from_config(config)
    scan_z = list(heights_A) if heights_A is not None else list(settings.scan_heights_A)

    slab_atoms = ref_slab.relaxed_atoms.copy()
    tags = slab_atoms.get_tags()
    top_s = [i for i in range(len(slab_atoms)) if tags[i] == 2]
    top_s_z = float(np.mean(slab_atoms.positions[top_s, 2]))

    # Use the relaxed reference molecule rotated to match the pose's orientation
    # so E_ads(dz -> inf) converges smoothly to 0.000 eV without internal strain offset.
    pose_mol = pose.atoms[list(pose.mol_indices)].copy()
    pose_pos_raw = pose_mol.get_positions()
    rel, _ = find_mic(pose_pos_raw - pose_pos_raw[0], cell=pose.atoms.cell, pbc=pose.atoms.pbc)
    pose_unwrapped = pose_pos_raw[0] + rel
    pose_masses = pose_mol.get_masses()
    pose_com = np.sum(pose_unwrapped * pose_masses[:, None], axis=0) / np.sum(pose_masses)
    pose_centered = pose_unwrapped - pose_com

    mol_template = ref_mol.relaxed_atoms.copy()
    ref_pos_raw = mol_template.get_positions()
    ref_rel, _ = find_mic(ref_pos_raw - ref_pos_raw[0], cell=mol_template.cell, pbc=mol_template.pbc)
    ref_unwrapped = ref_pos_raw[0] + ref_rel
    ref_masses = mol_template.get_masses()
    ref_com = np.sum(ref_unwrapped * ref_masses[:, None], axis=0) / np.sum(ref_masses)
    ref_centered = ref_unwrapped - ref_com

    if len(ref_centered) >= 2 and len(ref_centered) == len(pose_centered):
        cov = ref_centered.T @ pose_centered
        u, _, vt = np.linalg.svd(cov)
        d_sign = np.sign(np.linalg.det(vt.T @ u.T))
        rot = vt.T @ np.diag([1.0, 1.0, d_sign if d_sign != 0 else 1.0]) @ u.T
        mol_centered = ref_centered @ rot.T
    else:
        mol_centered = ref_centered

    points: list[BindingCurvePoint] = []
    for dz in scan_z:
        placed = mol_centered.copy()
        placed[:, 0] += pose.site_xy_A[0]
        placed[:, 1] += pose.site_xy_A[1]
        placed[:, 2] += top_s_z + float(dz)

        mol_copy = mol_template.copy()
        mol_copy.set_positions(placed)
        mol_copy.set_cell(slab_atoms.cell)
        mol_copy.set_pbc(slab_atoms.pbc)

        combined = slab_atoms.copy() + mol_copy
        e_tot, e_umlip, e_d3 = single_point_components(combined, calc_bundle)

        e_ads_tot = e_tot - (ref_slab.energy_total_eV + ref_mol.energy_total_eV)
        e_ads_u = e_umlip - (ref_slab.energy_umlip_eV + ref_mol.energy_umlip_eV)
        e_ads_d = (
            e_d3 - (ref_slab.energy_d3_eV + ref_mol.energy_d3_eV)
            if (e_d3 is not None and ref_slab.energy_d3_eV is not None and ref_mol.energy_d3_eV is not None)
            else None
        )
        points.append(
            BindingCurvePoint(
                dz_A=float(dz),
                e_ads_total_eV=float(e_ads_tot),
                e_ads_umlip_eV=float(e_ads_u),
                e_ads_d3_eV=float(e_ads_d) if e_ads_d is not None else None,
            )
        )

    pts = tuple(points)
    dz_eq, e_min_tot, e_min_u, e_min_d3, has_well = _extract_curve_equilibrium(pts)
    return BindingCurveResult(
        pose_id=pose.pose_id,
        surface_id=pose.surface_id,
        molecule_id=pose.molecule_id,
        site_type=pose.site_type,
        calculator_id=calc_bundle.calculator_id,
        d3_enabled=calc_bundle.d3_enabled,
        points=pts,
        dz_eq_A=dz_eq,
        e_min_total_eV=e_min_tot,
        e_min_umlip_eV=e_min_u,
        e_min_d3_eV=e_min_d3,
        has_attractive_well=has_well,
    )
