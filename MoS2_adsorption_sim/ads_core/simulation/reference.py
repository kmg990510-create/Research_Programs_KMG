"""Self-consistent reference relaxations (isolated slab and gas-phase molecule)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from ase import Atoms
from ase.calculators.calculator import Calculator
from ase.optimize import BFGS, FIRE, LBFGS

from ads_core.calculators.factory import CalculatorBundle
from ads_core.config import Config
from ads_core.model import (
    MoleculeSpec,
    RelaxationSettings,
    SEVERITY_ERROR,
    SlabSpec,
    WarningRecord,
)

LOGGER = logging.getLogger(__name__)

_OPTIMIZERS = {
    "BFGS": BFGS,
    "LBFGS": LBFGS,
    "FIRE": FIRE,
}


@dataclass(frozen=True, eq=False)
class ReferenceResult:
    """Relaxed reference energy and structure for an isolated slab or molecule."""

    kind: str  # "slab" or "molecule"
    item_id: str
    calculator_id: str
    converged: bool
    energy_total_eV: float | None
    energy_umlip_eV: float | None
    energy_d3_eV: float | None
    fmax_final_eV_per_A: float | None
    n_steps: int
    relaxed_atoms: Atoms
    warnings: tuple[WarningRecord, ...] = ()


def single_point_components(
    atoms: Atoms,
    calc_bundle: CalculatorBundle,
) -> tuple[float, float, float | None]:
    """Evaluate total, uMLIP-only, and D3-only energies on a fixed geometry."""
    u_atoms = atoms.copy()
    u_atoms.calc = calc_bundle.umlip_calc
    e_umlip = float(u_atoms.get_potential_energy())

    if calc_bundle.d3_calc is not None:
        d_atoms = atoms.copy()
        d_atoms.calc = calc_bundle.d3_calc
        e_d3 = float(d_atoms.get_potential_energy())
        e_total = e_umlip + e_d3
    else:
        e_d3 = None
        e_total = e_umlip

    return e_total, e_umlip, e_d3


def _relax_isolated(
    atoms: Atoms,
    kind: str,
    item_id: str,
    calc_bundle: CalculatorBundle,
    settings: RelaxationSettings,
) -> ReferenceResult:
    work = atoms.copy()
    work.calc = calc_bundle.total_calc
    opt_cls = _OPTIMIZERS[settings.optimizer]
    warnings: list[WarningRecord] = []

    try:
        # Relax isolated references tightly so deformation energies E_def >= 0 are variational,
        # while grading convergence against the configured fmax_eV_per_A threshold.
        ref_fmax = min(settings.fmax_eV_per_A * 0.1, 0.003)
        opt = opt_cls(work, logfile=None)
        opt_converged = bool(opt.run(fmax=ref_fmax, steps=settings.max_steps))
        n_steps = int(opt.nsteps)
        forces = work.get_forces()
        fmax_final = float(np.max(np.linalg.norm(forces, axis=1))) if len(forces) else 0.0
        converged = bool(opt_converged or fmax_final <= settings.fmax_eV_per_A)
        e_total, e_umlip, e_d3 = single_point_components(work, calc_bundle)
        if not converged:
            warnings.append(
                WarningRecord(
                    code="reference_not_converged",
                    message=(
                        f"Reference {kind} {item_id!r} did not converge within {settings.max_steps} steps "
                        f"(fmax={fmax_final:.4f} eV/A)."
                    ),
                    target_id=item_id,
                    severity=SEVERITY_ERROR,
                )
            )
    except Exception as exc:  # pragma: no cover - defensive guard for external MLIP backends
        LOGGER.exception("Reference relaxation failed for %s %s", kind, item_id)
        warnings.append(
            WarningRecord(
                code="calculator_failed",
                message=f"Reference {kind} {item_id!r} calculation failed: {exc}",
                target_id=item_id,
                severity=SEVERITY_ERROR,
            )
        )
        return ReferenceResult(
            kind=kind,
            item_id=item_id,
            calculator_id=calc_bundle.calculator_id,
            converged=False,
            energy_total_eV=None,
            energy_umlip_eV=None,
            energy_d3_eV=None,
            fmax_final_eV_per_A=None,
            n_steps=0,
            relaxed_atoms=work,
            warnings=tuple(warnings),
        )

    work.calc = None
    return ReferenceResult(
        kind=kind,
        item_id=item_id,
        calculator_id=calc_bundle.calculator_id,
        converged=converged,
        energy_total_eV=e_total,
        energy_umlip_eV=e_umlip,
        energy_d3_eV=e_d3,
        fmax_final_eV_per_A=fmax_final,
        n_steps=n_steps,
        relaxed_atoms=work,
        warnings=tuple(warnings),
    )


def relax_reference_slab(
    slab: SlabSpec,
    calc_bundle: CalculatorBundle,
    config: Config,
) -> ReferenceResult:
    """Relax the isolated 2H-MoS2 slab with the same calculator and fmax as adsorption poses."""
    settings = RelaxationSettings.from_config(config)
    return _relax_isolated(slab.atoms, "slab", slab.surface_id, calc_bundle, settings)


def relax_reference_molecule(
    molecule: MoleculeSpec,
    calc_bundle: CalculatorBundle,
    config: Config,
) -> ReferenceResult:
    """Relax the isolated gas-phase molecule inside its cubic vacuum box."""
    settings = RelaxationSettings.from_config(config)
    return _relax_isolated(molecule.atoms, "molecule", molecule.molecule_id, calc_bundle, settings)


@dataclass
class ReferenceCache:
    """In-memory cache of relaxed slab and molecule references keyed by (kind, id, calc_id)."""

    _store: dict[tuple[str, str, str], ReferenceResult] = field(default_factory=dict)

    def get_slab(
        self,
        slab: SlabSpec,
        calc_bundle: CalculatorBundle,
        config: Config,
    ) -> ReferenceResult:
        key = ("slab", slab.surface_id, calc_bundle.calculator_id)
        if key not in self._store:
            self._store[key] = relax_reference_slab(slab, calc_bundle, config)
        return self._store[key]

    def get_molecule(
        self,
        molecule: MoleculeSpec,
        calc_bundle: CalculatorBundle,
        config: Config,
    ) -> ReferenceResult:
        key = ("molecule", molecule.molecule_id, calc_bundle.calculator_id)
        if key not in self._store:
            self._store[key] = relax_reference_molecule(molecule, calc_bundle, config)
        return self._store[key]
