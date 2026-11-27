"""Shared pytest fixtures for MoS2_adsorption_sim (100% independent of local data/ and research/)."""

from __future__ import annotations

import math
from pathlib import Path
import sys

import pytest
from ase import Atoms
from ase.io import write as ase_write

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))


def build_synthetic_4atp_atoms() -> Atoms:
    """Build an idealized 15-atom molecule with S/+x and N/-x endgroups in canonical order."""
    r_cc = 1.39
    r_ch = 1.09
    angles_deg = [0.0, 60.0, 120.0, 180.0, -120.0, -60.0]
    syms: list[str] = []
    pos: list[list[float]] = []
    for idx_c, ang in enumerate(angles_deg):
        rad = math.radians(ang)
        cx, cy = r_cc * math.cos(rad), r_cc * math.sin(rad)
        syms.append("C")
        pos.append([cx, cy, 0.0])
        if idx_c in (1, 2, 4, 5):
            syms.append("H")
            pos.append([cx + r_ch * math.cos(rad), cy + r_ch * math.sin(rad), 0.0])

    # S10, H11 on C0 (+x), N12, H13, H14 on C5 (-x)
    syms.extend(["S", "H", "N", "H", "H"])
    pos.extend(
        [
            [r_cc + 1.73, 0.0, 0.0],
            [r_cc + 1.73 + 0.20, 1.33, 0.12],
            [-r_cc - 1.36, 0.0, 0.0],
            [-r_cc - 1.36 - 0.52, 0.86, 0.02],
            [-r_cc - 1.36 - 0.52, -0.86, 0.02],
        ]
    )
    atoms = Atoms(syms, positions=pos)
    atoms.center(vacuum=10.0)
    return atoms


@pytest.fixture(scope="session")
def four_atp_xyz_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Write a synthetic molecule .xyz file under pytest's temp directory."""
    out_dir = tmp_path_factory.mktemp("synth_molecules")
    xyz_path = out_dir / "synth_thiol.xyz"
    ase_write(xyz_path, build_synthetic_4atp_atoms(), format="xyz")
    return xyz_path
