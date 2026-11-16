"""Finite-temperature NVT (Langevin) molecular dynamics for adsorption residence checks."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from ase import Atoms, units
from ase.md import velocitydistribution as ase_vd
from ase.md.langevin import Langevin

from ads_core.calculators.factory import CalculatorBundle
from ads_core.config import Config
from ads_core.model import MdSettings, PoseSpec
from ads_core.simulation.relax import _compute_dz_com_A

LOGGER = logging.getLogger(__name__)

# Lower bound allows a small molecule to sit inside a sulfur vacancy pocket while excluding
# periodic images wrapped near the bottom S face (-3.17 A).
_MIN_ADSORBED_DZ_A = -1.5


@dataclass(frozen=True)
class MdStep:
    """One sampled MD step recorded for time-series height and temperature plots."""

    step: int
    time_fs: float
    potential_energy_eV: float
    kinetic_energy_eV: float
    temperature_K: float
    dz_com_A: float | None


@dataclass(frozen=True, eq=False)
class MdResult:
    """Output of a finite-temperature Langevin MD run on one slab + molecule pose."""

    pose_id: str
    surface_id: str
    molecule_id: str
    site_type: str
    orientation: str
    calculator_id: str
    failed: bool
    failure_message: str
    n_steps: int
    temperature_K: float
    timestep_fs: float
    final_dz_com_A: float | None
    mean_dz_com_A: float | None
    min_dz_com_A: float | None
    max_dz_com_A: float | None
    residence_fraction: float | None
    stayed_adsorbed: bool
    initial_atoms: Atoms
    final_atoms: Atoms
    trajectory_steps: tuple[MdStep, ...] = ()
    trajectory_frames: tuple[Atoms, ...] = ()


def _init_momenta(atoms: Atoms, temperature_K: float, rng: np.random.Generator) -> None:
    if hasattr(ase_vd, "thermalize_momenta"):
        ase_vd.thermalize_momenta(atoms, temperature_K=temperature_K, rng=rng)
    else:  # pragma: no cover - ASE < 3.29 fallback
        ase_vd.MaxwellBoltzmannDistribution(atoms, temperature_K=temperature_K, rng=rng)


def _is_in_adsorption_zone(dz_com_A: float | None, cutoff_A: float) -> bool:
    return dz_com_A is not None and _MIN_ADSORBED_DZ_A <= dz_com_A <= cutoff_A


def run_pose_md(
    pose: PoseSpec,
    calc_bundle: CalculatorBundle,
    config: Config,
    *,
    temperature_K: float | None = None,
    steps: int | None = None,
    timestep_fs: float | None = None,
    seed: int | None = None,
    initial_atoms: Atoms | None = None,
) -> MdResult:
    """Run finite-temperature Langevin NVT MD on a pose and measure surface residence."""
    settings = MdSettings.from_config(config)
    chosen_temp = settings.temperature_K if temperature_K is None else float(temperature_K)
    chosen_steps = settings.steps if steps is None else int(steps)
    chosen_dt = settings.timestep_fs if timestep_fs is None else float(timestep_fs)
    chosen_seed = settings.seed if seed is None else int(seed)

    if not chosen_temp > 0:
        raise ValueError(f"temperature_K must be positive, got {chosen_temp!r}")
    if chosen_steps < 1:
        raise ValueError(f"steps must be >= 1, got {chosen_steps!r}")
    if not chosen_dt > 0:
        raise ValueError(f"timestep_fs must be positive, got {chosen_dt!r}")
    if chosen_seed < 0:
        raise ValueError(f"seed must be >= 0, got {chosen_seed!r}")

    source_atoms = initial_atoms if initial_atoms is not None else pose.atoms
    initial = source_atoms.copy()
    work = source_atoms.copy()
    work.calc = calc_bundle.total_calc

    steps_log: list[MdStep] = []
    frames: list[Atoms] = []

    def _record_step(step_idx: int) -> None:
        epot = float(work.get_potential_energy())
        ekin = float(work.get_kinetic_energy())
        temp = float(work.get_temperature())
        dz = _compute_dz_com_A(work, pose.slab_indices, pose.mol_indices)
        time_fs = step_idx * chosen_dt
        steps_log.append(
            MdStep(
                step=step_idx,
                time_fs=time_fs,
                potential_energy_eV=epot,
                kinetic_energy_eV=ekin,
                temperature_K=temp,
                dz_com_A=dz,
            )
        )
        snap = work.copy()
        snap.calc = None
        snap.info["step"] = step_idx
        snap.info["time_fs"] = time_fs
        frames.append(snap)

    try:
        rng = np.random.default_rng(chosen_seed)
        _init_momenta(work, chosen_temp, rng)
        _record_step(0)

        dyn = Langevin(
            work,
            timestep=chosen_dt * units.fs,
            temperature_K=chosen_temp,
            friction=settings.friction_per_fs / units.fs,
            fixcm=False,
            rng=rng,
        )

        def _on_step() -> None:
            step_idx = int(dyn.nsteps)
            if step_idx > 0 and step_idx % settings.trajectory_stride == 0:
                _record_step(step_idx)

        dyn.attach(_on_step)
        dyn.run(chosen_steps)

        final_step = int(dyn.nsteps)
        if not steps_log or steps_log[-1].step != final_step:
            _record_step(final_step)
    except Exception as exc:  # pragma: no cover - defensive guard for external MLIP backends
        LOGGER.exception("Pose MD failed for %s", pose.pose_id)
        work.calc = None
        return MdResult(
            pose_id=pose.pose_id,
            surface_id=pose.surface_id,
            molecule_id=pose.molecule_id,
            site_type=pose.site_type,
            orientation=pose.orientation,
            calculator_id=calc_bundle.calculator_id,
            failed=True,
            failure_message=str(exc),
            n_steps=len(steps_log),
            temperature_K=chosen_temp,
            timestep_fs=chosen_dt,
            final_dz_com_A=None,
            mean_dz_com_A=None,
            min_dz_com_A=None,
            max_dz_com_A=None,
            residence_fraction=None,
            stayed_adsorbed=False,
            initial_atoms=initial,
            final_atoms=work,
            trajectory_steps=tuple(steps_log),
            trajectory_frames=tuple(frames),
        )

    final_clean = work.copy()
    final_clean.calc = None

    dz_values = [s.dz_com_A for s in steps_log if s.dz_com_A is not None]
    final_dz = steps_log[-1].dz_com_A if steps_log else None
    if dz_values:
        mean_dz: float | None = float(np.mean(dz_values))
        min_dz: float | None = float(np.min(dz_values))
        max_dz: float | None = float(np.max(dz_values))
        in_zone = sum(1 for s in steps_log if _is_in_adsorption_zone(s.dz_com_A, settings.adsorption_cutoff_A))
        residence_fraction: float | None = float(in_zone / len(steps_log))
    else:
        mean_dz = min_dz = max_dz = residence_fraction = None

    return MdResult(
        pose_id=pose.pose_id,
        surface_id=pose.surface_id,
        molecule_id=pose.molecule_id,
        site_type=pose.site_type,
        orientation=pose.orientation,
        calculator_id=calc_bundle.calculator_id,
        failed=False,
        failure_message="",
        n_steps=int(dyn.nsteps),
        temperature_K=chosen_temp,
        timestep_fs=chosen_dt,
        final_dz_com_A=final_dz,
        mean_dz_com_A=mean_dz,
        min_dz_com_A=min_dz,
        max_dz_com_A=max_dz,
        residence_fraction=residence_fraction,
        stayed_adsorbed=_is_in_adsorption_zone(final_dz, settings.adsorption_cutoff_A),
        initial_atoms=initial,
        final_atoms=final_clean,
        trajectory_steps=tuple(steps_log),
        trajectory_frames=tuple(frames),
    )
