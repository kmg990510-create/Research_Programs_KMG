"""Interactive py3Dmol 3D structure viewer (relaxed + initial Ghost, d_min cylinder, trajectory animation). No Streamlit import."""

from __future__ import annotations

import io

import numpy as np
import py3Dmol
from ase import Atoms
from ase.geometry import find_mic, get_distances
from ase.io import write as ase_write

from ads_core.model import PoseResult
from ads_core.pipeline import PoseArtifact
from labkit.plot_theme import MARK, SURFACE


def atoms_to_xyz_str(atoms: Atoms, comment: str = "") -> str:
    """Serialize ``Atoms`` into an in-memory standard XYZ block."""
    symbols = atoms.get_chemical_symbols()
    pos = atoms.get_positions()
    lines = [str(len(atoms)), comment or "MoS2_adsorption_sim"]
    for sym, xyz in zip(symbols, pos):
        lines.append(f"{sym:<4s} {xyz[0]:15.8f} {xyz[1]:15.8f} {xyz[2]:15.8f}")
    return "\n".join(lines) + "\n"


def atoms_to_cif_str(atoms: Atoms) -> str:
    """Serialize periodic ``Atoms`` to CIF text so py3Dmol draws the exact unit cell box."""
    buf = io.BytesIO()
    clean = atoms.copy()
    clean.set_constraint()
    ase_write(buf, clean, format="cif")
    return buf.getvalue().decode("utf-8")


def _unwrap_mol_near_slab(atoms: Atoms, slab_indices: tuple[int, ...], mol_indices: tuple[int, ...]) -> Atoms:
    """Unwrap adsorbate atoms around their first atom and shift MIC closest to slab center."""
    mol = atoms[list(mol_indices)].copy()
    if len(mol) == 0:
        return mol
    pos = mol.get_positions()
    if len(mol) > 1:
        rel, _ = find_mic(pos - pos[0], cell=atoms.cell, pbc=atoms.pbc)
        pos = pos[0] + rel
    # Shift unwrapped COM into the primary periodic image near the slab XY center
    slab_xy = np.mean(atoms.positions[list(slab_indices), :2], axis=0) if slab_indices else np.zeros(2)
    com = np.mean(pos, axis=0)
    delta_xy, _ = find_mic(np.array([[com[0] - slab_xy[0], com[1] - slab_xy[1], 0.0]]), cell=atoms.cell, pbc=atoms.pbc)
    shift = np.array([slab_xy[0] + delta_xy[0, 0] - com[0], slab_xy[1] + delta_xy[0, 1] - com[1], 0.0])
    mol.set_positions(pos + shift)
    return mol


def _closest_pair_coords(
    relaxed_slab: Atoms,
    relaxed_mol: Atoms,
) -> tuple[dict[str, float], dict[str, float], float] | None:
    """Find Euclidean closest slab-to-unwrapped-molecule pair for drawing the d_min cylinder."""
    if len(relaxed_slab) == 0 or len(relaxed_mol) == 0:
        return None
    p_s = relaxed_slab.get_positions()
    p_m = relaxed_mol.get_positions()
    # Consider periodic images of slab atoms in xy so the drawn cylinder connects visible atoms cleanly.
    vec, dist_mat = get_distances(p_s, p_m, cell=relaxed_slab.cell, pbc=relaxed_slab.pbc)
    flat_idx = int(np.argmin(dist_mat))
    i_s, i_m = divmod(flat_idx, len(p_m))
    d_min = float(dist_mat[i_s, i_m])
    end = p_m[i_m]
    start = end - vec[i_s, i_m]
    return (
        {"x": float(start[0]), "y": float(start[1]), "z": float(start[2])},
        {"x": float(end[0]), "y": float(end[1]), "z": float(end[2])},
        d_min,
    )


def pose_3d_html(
    artifact: PoseArtifact,
    result: PoseResult,
    mode: str = "relaxed_with_ghost",
    width: int = 560,
    height: int = 420,
) -> str:
    """Render interactive py3Dmol HTML for either Ghost comparison or relaxation trajectory animation."""
    view = py3Dmol.view(width=width, height=height)
    view.setBackgroundColor(SURFACE)

    if mode == "trajectory" and len(artifact.trajectory_frames) > 1:
        multi_xyz = "".join(
            atoms_to_xyz_str(frame, comment=f"{result.pose_id} step {idx}")
            for idx, frame in enumerate(artifact.trajectory_frames)
        )
        slab_cif = atoms_to_cif_str(artifact.relaxed_atoms[list(artifact.slab_indices)])
        view.addModel(slab_cif, "cif")
        view.addUnitCell({"model": 0}, {"box": {"color": "#8a8a8a"}})
        view.setStyle({"model": 0}, {})  # keep unit-cell box without double-drawing static slab atoms

        view.addModelsAsFrames(multi_xyz, "xyz")
        view.setStyle({"model": 1}, {"stick": {"radius": 0.14}, "sphere": {"scale": 0.34}, "colorscheme": "Jmol"})
        view.animate({"loop": "forward", "interval": 160})
        view.zoomTo()
        return view._make_html()

    slab_atoms = artifact.relaxed_atoms[list(artifact.slab_indices)]
    mol_relaxed = _unwrap_mol_near_slab(artifact.relaxed_atoms, artifact.slab_indices, artifact.mol_indices)
    mol_initial = _unwrap_mol_near_slab(artifact.initial_atoms, artifact.slab_indices, artifact.mol_indices)

    # Model 0: Relaxed MoS2 slab (CIF provides exact triclinic unit cell for addUnitCell)
    view.addModel(atoms_to_cif_str(slab_atoms), "cif")
    view.setStyle(
        {"model": 0},
        {"stick": {"radius": 0.11, "opacity": 0.72}, "sphere": {"scale": 0.34, "opacity": 0.72}, "colorscheme": "Jmol"},
    )
    view.addUnitCell({"model": 0}, {"box": {"color": "#8a8a8a"}})

    # Model 1: Relaxed adsorbate molecule (opaque Jmol Ball-and-Stick)
    view.addModel(atoms_to_xyz_str(mol_relaxed, comment="relaxed_adsorbate"), "xyz")
    view.setStyle({"model": 1}, {"stick": {"radius": 0.16}, "sphere": {"scale": 0.36}, "colorscheme": "Jmol"})

    # Model 2: Initial unrelaxed adsorbate Ghost overlay (translucent grey)
    view.addModel(atoms_to_xyz_str(mol_initial, comment="initial_ghost"), "xyz")
    view.setStyle(
        {"model": 2},
        {"stick": {"radius": 0.09, "color": "#888888", "opacity": 0.32}, "sphere": {"scale": 0.22, "color": "#888888", "opacity": 0.32}},
    )

    pair = _closest_pair_coords(slab_atoms, mol_relaxed)
    if pair is not None:
        start, end, d_min = pair
        view.addCylinder(
            {
                "start": start,
                "end": end,
                "radius": 0.05,
                "color": MARK,
                "dashed": True,
                "fromCap": 1,
                "toCap": 1,
            }
        )
        mid = {k: 0.5 * (start[k] + end[k]) for k in ("x", "y", "z")}
        label_val = result.d_min_A if result.d_min_A is not None else d_min
        view.addLabel(
            f"d_min = {label_val:.2f} A",
            {
                "position": mid,
                "backgroundColor": SURFACE,
                "fontColor": "#111111",
                "fontSize": 12,
                "backgroundOpacity": 0.85,
                "borderColor": MARK,
                "borderThickness": 1,
            },
        )

    view.zoomTo()
    return view._make_html()
