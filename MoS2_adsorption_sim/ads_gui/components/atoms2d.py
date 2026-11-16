"""ASE plot_atoms 2D Top/Side projections and pymatgen plot_slab site map. No Streamlit import."""

from __future__ import annotations

import io

from typing import Sequence

from ase import Atoms
from ase.visualize.plot import plot_atoms
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from pymatgen.analysis.adsorption import plot_slab
from pymatgen.io.ase import AseAtomsAdaptor

from ads_core.config import Config
from ads_core.model import SlabSpec
from ads_core.report.coverage_view import ContactLine, unwrap_molecule_groups
from labkit.plot_theme import DATA, MARK, STATUS_COLORS


def pose_top_side_png(atoms: Atoms, title: str = "", status: str = "valid") -> bytes:
    """Render a 1x2 PNG image showing orthographic Top (xy) and Side (xz) views via ``ase.visualize.plot.plot_atoms``."""
    fig = Figure(figsize=(6.4, 3.1), dpi=130, facecolor="white")
    ax_top = fig.add_subplot(1, 2, 1)
    ax_side = fig.add_subplot(1, 2, 2)

    clean = atoms.copy()
    clean.set_constraint()
    plot_atoms(clean, ax_top, radii=0.55, rotation="0x,0y,0z", show_unit_cell=2)
    plot_atoms(clean, ax_side, radii=0.55, rotation="-90x,0y,0z", show_unit_cell=2)

    ax_top.set_title("Top view (xy)", fontsize=10, color=DATA)
    ax_side.set_title("Side view (xz)", fontsize=10, color=DATA)
    for ax in (ax_top, ax_side):
        ax.set_xlabel("x (Å)", fontsize=9)
        ax.set_ylabel("y (Å)" if ax is ax_top else "z (Å)", fontsize=9)
        ax.tick_params(labelsize=8)

    if title:
        fig.suptitle(title, fontsize=11, fontweight="bold", color=STATUS_COLORS.get(status, DATA))

    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.93 if title else 1.0))
    buf = io.BytesIO()
    FigureCanvasAgg(fig).print_png(buf)
    return buf.getvalue()


def slab_sites_png(slab: SlabSpec, config: Config) -> bytes:
    """Render the 2D crystallographic adsorption site diagram using ``pymatgen`` ``plot_slab``."""
    _ = config
    clean = slab.atoms.copy()
    clean.set_constraint()
    structure = AseAtomsAdaptor.get_structure(clean)

    fig = Figure(figsize=(5.0, 4.6), dpi=130, facecolor="white")
    ax = fig.add_subplot(1, 1, 1)
    plot_slab(structure, ax, repeat=2, adsorption_sites=True, decay=0.09)

    if slab.defect_positions_A:
        xs = [pos[0] for pos in slab.defect_positions_A]
        ys = [pos[1] for pos in slab.defect_positions_A]
        ax.scatter(xs, ys, marker="*", s=220, color=MARK, edgecolor="black", zorder=10, label=f"Defect ({slab.defect_type})")
        ax.legend(loc="upper right", fontsize=9, framealpha=0.9)

    ax.set_title(f"Adsorption Sites — {slab.surface_id}", fontsize=11, color=DATA)
    fig.tight_layout()
    buf = io.BytesIO()
    FigureCanvasAgg(fig).print_png(buf)
    return buf.getvalue()


def multimol_top_side_png(
    atoms: Atoms,
    *,
    slab_count: int = 0,
    mol_count: int = 15,
    title: str = "",
    repeat_xy: int = 1,
    distance_lines: Sequence[ContactLine] = (),
) -> bytes:
    """Render 2D orthographic Top (xy) and Side (xz) views with unwrapped molecules and contact lines."""
    has_slab = slab_count > 0 and len(atoms) > slab_count
    rep = max(1, min(2, int(repeat_xy))) if has_slab else 1
    slab_part = atoms[:slab_count].copy() if has_slab else Atoms(cell=atoms.cell, pbc=atoms.pbc)
    groups = unwrap_molecule_groups(atoms, slab_count if has_slab else 0, mol_count)

    combined = slab_part.repeat((rep, rep, 1)) if (has_slab and rep > 1) else slab_part.copy()
    cell = atoms.cell
    for grp in groups:
        if has_slab and rep > 1:
            for ix in range(rep):
                for iy in range(rep):
                    dup = grp.copy()
                    dup.translate(ix * cell[0] + iy * cell[1])
                    combined += dup
        else:
            combined += grp
    combined.set_constraint()

    fig = Figure(figsize=(7.2, 3.4), dpi=135, facecolor="white")
    ax_top = fig.add_subplot(1, 2, 1)
    ax_side = fig.add_subplot(1, 2, 2)
    plot_atoms(combined, ax_top, radii=0.52, rotation="0x,0y,0z", show_unit_cell=2)
    plot_atoms(combined, ax_side, radii=0.52, rotation="-90x,0y,0z", show_unit_cell=2)

    for line in distance_lines:
        x0, y0, z0 = line.start_xyz
        x1, y1, z1 = line.end_xyz
        ax_top.plot([x0, x1], [y0, y1], "--o", color=MARK, linewidth=1.6, markersize=4, zorder=12)
        ax_top.annotate(
            line.label,
            xy=(0.5 * (x0 + x1), 0.5 * (y0 + y1)),
            fontsize=7.5,
            color="#111111",
            bbox={"boxstyle": "round,pad=0.18", "fc": "white", "ec": MARK, "alpha": 0.9},
            zorder=13,
        )
        ax_side.plot([x0, x1], [z0, z1], "--o", color=MARK, linewidth=1.6, markersize=4, zorder=12)

    ax_top.set_title("Top view (xy)", fontsize=10, color=DATA)
    ax_side.set_title("Side view (xz)", fontsize=10, color=DATA)
    ax_top.set_xlabel("x (Å)", fontsize=9)
    ax_top.set_ylabel("y (Å)", fontsize=9)
    ax_side.set_xlabel("x (Å)", fontsize=9)
    ax_side.set_ylabel("z (Å)", fontsize=9)
    if title:
        fig.suptitle(title, fontsize=11, fontweight="bold", color=DATA)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.93 if title else 1.0))
    buf = io.BytesIO()
    FigureCanvasAgg(fig).print_png(buf)
    return buf.getvalue()
