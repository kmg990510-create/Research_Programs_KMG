"""2H-MoS2 monolayer slab builder with vacancy defects and layer constraints."""

from __future__ import annotations

import numpy as np
from ase import Atoms
from ase.build import mx2
from ase.constraints import FixAtoms

from ads_core.config import Config
from ads_core.model import (
    DEFECT_PRISTINE,
    DEFECT_VS,
    DEFECT_VS2,
    SlabSettings,
    SlabSpec,
    VALID_DEFECT_TYPES,
)


def _select_central_atom(atoms: Atoms, candidate_indices: list[int]) -> int:
    """Return the index in ``candidate_indices`` closest to fractional (0.5, 0.5) in xy."""
    if not candidate_indices:
        raise ValueError("No candidate atoms available to remove for defect")
    scaled = atoms.get_scaled_positions(wrap=True)
    best_idx = candidate_indices[0]
    best_d2 = float("inf")
    for idx in candidate_indices:
        dx = scaled[idx, 0] - 0.5
        dy = scaled[idx, 1] - 0.5
        dx -= round(dx)
        dy -= round(dy)
        d2 = dx * dx + dy * dy
        if d2 < best_d2:
            best_d2 = d2
            best_idx = idx
    return best_idx


def build_mos2_slab(
    config: Config,
    *,
    supercell: tuple[int, int] | None = None,
    defect_type: str | None = None,
    vacuum_A: float | None = None,
    fix_bottom_layer: bool | None = None,
) -> SlabSpec:
    """Build a 2H-MoS2 monolayer supercell slab with optional sulfur vacancies."""
    settings = SlabSettings.from_config(config)
    nx, ny = supercell if supercell is not None else (settings.supercell_nx, settings.supercell_ny)
    if nx < 1 or ny < 1:
        raise ValueError(f"supercell must be >= (1, 1), got {(nx, ny)!r}")

    chosen_defect = defect_type if defect_type is not None else settings.defect_type
    if chosen_defect not in VALID_DEFECT_TYPES:
        raise ValueError(f"Unsupported defect_type {chosen_defect!r}; expected one of {VALID_DEFECT_TYPES}")

    chosen_vacuum = float(vacuum_A) if vacuum_A is not None else settings.vacuum_A
    if not chosen_vacuum > 0:
        raise ValueError(f"vacuum_A must be positive, got {chosen_vacuum!r}")

    chosen_fix = settings.fix_bottom_layer if fix_bottom_layer is None else bool(fix_bottom_layer)

    atoms = mx2(
        formula="MoS2",
        kind="2H",
        a=settings.lattice_a_A,
        thickness=settings.s_s_thickness_A,
        size=(nx, ny, 1),
    )
    atoms.pbc = (True, True, True)
    # Set exact total vacuum = chosen_vacuum, with the trilayer centered in z.
    atoms.center(vacuum=chosen_vacuum / 2.0, axis=2)

    symbols = atoms.get_chemical_symbols()
    positions = atoms.get_positions()
    mo_indices = [i for i, sym in enumerate(symbols) if sym == "Mo"]
    mo_z_A = float(np.mean(positions[mo_indices, 2]))

    tol = settings.layer_tolerance_A
    top_s_indices = [i for i, sym in enumerate(symbols) if sym == "S" and positions[i, 2] > mo_z_A + tol]
    bottom_s_indices = [i for i, sym in enumerate(symbols) if sym == "S" and positions[i, 2] < mo_z_A - tol]

    if len(top_s_indices) != nx * ny or len(bottom_s_indices) != nx * ny or len(mo_indices) != nx * ny:
        raise ValueError("Unexpected 2H-MoS2 layer stoichiometry; check layer_tolerance_A")

    # Tag layers: 0 = bottom S, 1 = Mo, 2 = top S
    tags = np.ones(len(atoms), dtype=int)
    tags[bottom_s_indices] = 0
    tags[top_s_indices] = 2
    atoms.set_tags(tags)

    defect_positions: list[tuple[float, float, float]] = []
    remove_indices: list[int] = []

    if chosen_defect in (DEFECT_VS, DEFECT_VS2):
        top_idx = _select_central_atom(atoms, top_s_indices)
        top_pos = positions[top_idx]
        defect_positions.append((float(top_pos[0]), float(top_pos[1]), float(top_pos[2])))
        remove_indices.append(top_idx)

        if chosen_defect == DEFECT_VS2:
            # Remove the bottom-layer S directly beneath the top-layer vacancy (2H eclipsed column).
            bot_xy = positions[bottom_s_indices, :2]
            d2 = np.sum((bot_xy - top_pos[:2]) ** 2, axis=1)
            bot_idx = bottom_s_indices[int(np.argmin(d2))]
            remove_indices.append(bot_idx)

    if remove_indices:
        for idx in sorted(remove_indices, reverse=True):
            del atoms[idx]

    # Recompute layer summary after any defect deletion
    new_tags = atoms.get_tags()
    new_pos = atoms.get_positions()
    bottom_after = [i for i, t in enumerate(new_tags) if t == 0]
    mo_after = [i for i, t in enumerate(new_tags) if t == 1]
    top_after = [i for i, t in enumerate(new_tags) if t == 2]

    if chosen_fix and bottom_after:
        atoms.set_constraint(FixAtoms(indices=bottom_after))

    top_s_z_A = float(np.mean(new_pos[top_after, 2]))
    mo_z_final = float(np.mean(new_pos[mo_after, 2]))
    bottom_s_z_A = float(np.mean(new_pos[bottom_after, 2]))

    atoms.info["surface_id"] = f"{chosen_defect}_{nx}x{ny}"
    atoms.info["defect_type"] = chosen_defect
    atoms.info["defect_positions_A"] = defect_positions

    return SlabSpec(
        surface_id=f"{chosen_defect}_{nx}x{ny}",
        supercell=(nx, ny),
        defect_type=chosen_defect,
        vacuum_A=chosen_vacuum,
        fix_bottom_layer=chosen_fix,
        lattice_a_A=settings.lattice_a_A,
        s_s_thickness_A=settings.s_s_thickness_A,
        top_s_z_A=top_s_z_A,
        mo_z_A=mo_z_final,
        bottom_s_z_A=bottom_s_z_A,
        defect_positions_A=tuple(defect_positions),
        atoms=atoms,
    )
