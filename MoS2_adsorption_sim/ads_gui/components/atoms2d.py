"""ASE plot_atoms 2D Top/Side projections and pymatgen plot_slab site map. No Streamlit import."""

from __future__ import annotations

import io

from ase import Atoms
from ase.visualize.plot import plot_atoms
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from pymatgen.analysis.adsorption import plot_slab
from pymatgen.io.ase import AseAtomsAdaptor

from ads_core.config import Config
from ads_core.model import SlabSpec
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
