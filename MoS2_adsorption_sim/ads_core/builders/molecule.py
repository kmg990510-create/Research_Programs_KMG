"""Adsorbate molecule builder: built-in presets and external structure files."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.build import molecule as ase_molecule
from ase.data import atomic_numbers, covalent_radii
from ase.io import read as ase_read

from ads_core.config import Config
from ads_core.model import MoleculeSettings, MoleculeSpec

_PRESET_ANCHOR_ELEMENT = {
    "H2O": "O",
    "NH3": "N",
    "CO": "C",
    "O2": "O",
    "CH4": "C",
    "TMA": "Al",
}


def detect_covalent_bonds(atoms: Atoms, scale: float) -> tuple[tuple[int, int, float], ...]:
    """Identify intramolecular covalent bond pairs using scaled covalent radii."""
    n = len(atoms)
    if n < 2:
        return ()
    numbers = atoms.get_atomic_numbers()
    pos = atoms.get_positions()
    bonds: list[tuple[int, int, float]] = []
    for i in range(n):
        r_i = covalent_radii[numbers[i]]
        for j in range(i + 1, n):
            r_j = covalent_radii[numbers[j]]
            dist = float(np.linalg.norm(pos[i] - pos[j]))
            if dist <= scale * float(r_i + r_j):
                bonds.append((i, j, dist))
    return tuple(bonds)


def _validate_internal_distances(atoms: Atoms, min_dist_A: float, name: str) -> None:
    if len(atoms) == 0:
        raise ValueError(f"Molecule {name!r} has no atoms")
    pos = atoms.get_positions()
    if len(atoms) == 1:
        return
    dists = np.linalg.norm(pos[:, None, :] - pos[None, :, :], axis=-1)
    np.fill_diagonal(dists, np.inf)
    shortest = float(np.min(dists))
    if shortest < min_dist_A:
        raise ValueError(f"Molecule {name!r} has overlapping atoms (min distance {shortest:.3f} A < {min_dist_A:.3f} A)")


def _build_tma(settings: MoleculeSettings) -> Atoms:
    """Build trigonal-planar D3h trimethylaluminum Al(CH3)3."""
    al_c = settings.tma_al_c_bond_A
    c_h = settings.tma_c_h_bond_A
    # Angle between C-Al bond axis and each C-H bond: 180 - H-C-Al, where tetrahedral ~ 109.5 deg
    cone_angle = math.radians(180.0 - settings.tma_h_c_h_angle_deg)
    sin_a = math.sin(cone_angle)
    cos_a = math.cos(cone_angle)

    symbols = ["Al"]
    positions = [[0.0, 0.0, 0.0]]

    for k in range(3):
        phi = 2.0 * math.pi * k / 3.0
        ux, uy = math.cos(phi), math.sin(phi)
        tx, ty = -math.sin(phi), math.cos(phi)  # in-plane tangent perpendicular to radial axis
        cx, cy = al_c * ux, al_c * uy
        symbols.append("C")
        positions.append([cx, cy, 0.0])

        for m in range(3):
            gamma = 2.0 * math.pi * m / 3.0
            # Outward along radial axis u, plus circle in (tangent, z) plane
            hx = cx + c_h * (cos_a * ux + sin_a * math.cos(gamma) * tx)
            hy = cy + c_h * (cos_a * uy + sin_a * math.cos(gamma) * ty)
            hz = 0.0 + c_h * sin_a * math.sin(gamma)
            symbols.append("H")
            positions.append([hx, hy, hz])

    return Atoms(symbols=symbols, positions=positions)


def _choose_anchor_index(atoms: Atoms, preferred_element: str | None = None) -> int:
    symbols = atoms.get_chemical_symbols()
    if preferred_element and preferred_element in symbols:
        return symbols.index(preferred_element)
    # Fallback for external files: heaviest atom closest to geometric center
    numbers = np.array([atomic_numbers[s] for s in symbols], dtype=int)
    max_z = int(np.max(numbers))
    candidates = [i for i, z in enumerate(numbers) if z == max_z]
    if len(candidates) == 1:
        return candidates[0]
    com = atoms.get_center_of_mass()
    pos = atoms.get_positions()
    return min(candidates, key=lambda idx: float(np.linalg.norm(pos[idx] - com)))


def _prepare_molecule_spec(
    atoms: Atoms,
    molecule_id: str,
    source: str,
    settings: MoleculeSettings,
    preferred_anchor: str | None = None,
) -> MoleculeSpec:
    atoms = atoms.copy()
    _validate_internal_distances(atoms, settings.min_internal_distance_A, molecule_id)

    box = settings.vacuum_box_A
    atoms.set_cell([box, box, box])
    atoms.pbc = (True, True, True)
    atoms.center()

    anchor_index = _choose_anchor_index(atoms, preferred_anchor)
    bonds = detect_covalent_bonds(atoms, settings.covalent_bond_scale)
    formula = atoms.get_chemical_formula()
    atoms.info["molecule_id"] = molecule_id
    atoms.info["anchor_index"] = anchor_index

    return MoleculeSpec(
        molecule_id=molecule_id,
        formula=formula,
        source=source,
        box_size_A=box,
        anchor_index=anchor_index,
        reference_bonds=bonds,
        atoms=atoms,
    )


def build_preset_molecule(name: str, config: Config) -> MoleculeSpec:
    """Build one of the built-in adsorbate presets configured in ``config.yaml``."""
    settings = MoleculeSettings.from_config(config)
    if name not in settings.presets:
        raise ValueError(f"Unknown preset molecule {name!r}; available presets: {settings.presets}")

    if name == "TMA":
        raw = _build_tma(settings)
    else:
        raw = ase_molecule(name)

    return _prepare_molecule_spec(
        raw,
        molecule_id=name,
        source="preset",
        settings=settings,
        preferred_anchor=_PRESET_ANCHOR_ELEMENT.get(name),
    )


def load_molecule_file(path: Path | str, config: Config, *, molecule_id: str | None = None) -> MoleculeSpec:
    """Load an external molecule file (.xyz, .mol, .sdf, .cif, etc.) via ASE."""
    settings = MoleculeSettings.from_config(config)
    src_path = Path(path)
    if not src_path.is_file():
        raise FileNotFoundError(f"Molecule file not found: {src_path}")

    raw = ase_read(str(src_path))
    chosen_id = molecule_id or src_path.stem
    return _prepare_molecule_spec(raw, molecule_id=chosen_id, source="file", settings=settings)
