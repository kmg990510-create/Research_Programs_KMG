"""Pure data loader and intermolecular distance analyzer for coverage/multilayer studies.

No Streamlit imports allowed (enforced by tests).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from ase import Atoms
from ase.geometry import find_mic, get_distances
from ase.io import read as ase_read

COVERAGE_SUMMARY_FILE = "coverage_summary.csv"
DESORPTION_SUMMARY_FILE = "desorption_summary.csv"
DISULFIDE_SUMMARY_FILE = "disulfide_summary.csv"
THERMAL_LIFETIMES_FILE = "thermal_lifetimes.csv"
STUDY_METADATA_FILE = "study_metadata.json"

MOLECULE_COLORS: tuple[str, ...] = (
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#9467bd",
    "#ff7f0e",
    "#17becf",
    "#8c564b",
    "#e377c2",
)


@dataclass(frozen=True)
class ContactLine:
    """3D contact or bond vector in Å between two atoms (or centers) for display."""

    kind: str
    label: str
    distance_A: float
    mol_i: int
    mol_j: int
    atom_i: int | None
    atom_j: int | None
    start_xyz: tuple[float, float, float]
    end_xyz: tuple[float, float, float]
    crosses_pbc: bool = False


@dataclass(frozen=True)
class MultimolGeometryReport:
    """Intermolecular contact distances, per-molecule metrics, and pairwise matrices."""

    n_molecules: int
    per_molecule: pd.DataFrame
    contacts: dict[str, ContactLine]
    matrices: dict[str, np.ndarray]


@dataclass(frozen=True)
class DisulfideGeometryReport:
    """Geometric metrics characterizing Ar-S-S-Ar disulfide bond & surface configuration."""

    d_ss_gas_A: float | None
    d_ss_initial_A: float | None
    d_ss_relaxed_A: float | None
    angle_css_gas_deg: tuple[float, float] | None
    angle_css_relaxed_deg: tuple[float, float] | None
    dihedral_cssc_gas_deg: float | None
    dihedral_cssc_relaxed_deg: float | None
    ring_tilts_relaxed_deg: tuple[float, float] | None
    s_heights_above_slab_A: tuple[float, float] | None
    n_heights_above_slab_A: tuple[float, float] | None
    n_to_n_span_A: float | None
    com_shift_initial_to_relaxed_A: float | None
    ss_bond_line: ContactLine | None
    n_span_line: ContactLine | None


@dataclass(frozen=True)
class CoverageStudyBundle:
    """Loaded coverage/multilayer study directory with tables and ASE structures."""

    study_name: str
    folder: Path
    metadata: dict[str, Any]
    coverage_df: pd.DataFrame
    desorption_df: pd.DataFrame
    disulfide_df: pd.DataFrame
    thermal_df: pd.DataFrame
    slab_count: int
    mol_count: int
    structures: dict[str, Atoms]


def is_coverage_study_dir(folder: Path) -> bool:
    """Return True if ``folder`` looks like a coverage/multilayer study output directory."""
    return (
        folder.is_dir()
        and (folder / COVERAGE_SUMMARY_FILE).is_file()
        and (folder / STUDY_METADATA_FILE).is_file()
    )


def list_coverage_studies(results_dir: Path | str) -> list[str]:
    """List subfolders under ``results_dir`` that hold a completed coverage study."""
    root = Path(results_dir)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if is_coverage_study_dir(p))


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def load_coverage_study(folder: Path | str) -> CoverageStudyBundle:
    """Load tables, metadata, and relaxed/initial XYZ structures from a coverage study directory."""
    root = Path(folder)
    metadata = json.loads((root / STUDY_METADATA_FILE).read_text(encoding="utf-8"))
    coverage_df = _read_csv_if_exists(root / COVERAGE_SUMMARY_FILE)
    desorption_df = _read_csv_if_exists(root / DESORPTION_SUMMARY_FILE)
    disulfide_df = _read_csv_if_exists(root / DISULFIDE_SUMMARY_FILE)
    thermal_df = _read_csv_if_exists(root / THERMAL_LIFETIMES_FILE)

    structures: dict[str, Atoms] = {}
    struct_dir = root / "structures"
    if struct_dir.is_dir():
        for xyz in sorted(struct_dir.glob("*.xyz")):
            structures[xyz.stem] = ase_read(xyz, index=0)

    slab_ref = structures.get("reference_slab_relaxed")
    mol_ref = structures.get("reference_mol_relaxed")
    slab_count = len(slab_ref) if slab_ref is not None else 0
    mol_count = len(mol_ref) if mol_ref is not None else 0

    return CoverageStudyBundle(
        study_name=str(metadata.get("study_name", root.name)),
        folder=root,
        metadata=metadata,
        coverage_df=coverage_df,
        desorption_df=desorption_df,
        disulfide_df=disulfide_df,
        thermal_df=thermal_df,
        slab_count=slab_count,
        mol_count=mol_count,
        structures=structures,
    )


def unwrap_molecule_groups(atoms: Atoms, slab_count: int, mol_count: int) -> list[Atoms]:
    """Split adsorbate portion into per-molecule ``Atoms`` unwrapped into the primary cell."""
    if mol_count <= 0 or len(atoms) <= slab_count:
        return []
    adsorbate_len = len(atoms) - slab_count
    n_mol = adsorbate_len // mol_count
    if n_mol <= 0 or n_mol * mol_count != adsorbate_len:
        # Irregular atom count (e.g. disulfide 28 atoms): return single unwrapped group
        mol = atoms[slab_count:].copy()
        return [unwrap_single_group(mol, atoms.cell, atoms.pbc)]

    groups: list[Atoms] = []
    slab_xy = (
        np.mean(atoms.positions[:slab_count, :2], axis=0)
        if slab_count > 0
        else np.zeros(2, dtype=float)
    )
    for idx in range(n_mol):
        start = slab_count + idx * mol_count
        mol = atoms[start : start + mol_count].copy()
        groups.append(unwrap_single_group(mol, atoms.cell, atoms.pbc, target_xy=slab_xy))
    return groups


def unwrap_single_group(
    mol: Atoms,
    cell: Any,
    pbc: Any,
    target_xy: np.ndarray | None = None,
) -> Atoms:
    """Unwrap one connected molecule around atom 0 and wrap its COM cleanly into the cell."""
    out = mol.copy()
    if len(out) == 0:
        return out
    pos = out.get_positions()
    if len(out) > 1 and any(bool(x) for x in pbc):
        rel, _ = find_mic(pos - pos[0], cell=cell, pbc=pbc)
        pos = pos[0] + rel
    if target_xy is not None and any(bool(x) for x in pbc[:2]):
        com = np.mean(pos, axis=0)
        delta_xy, _ = find_mic(
            np.array([[com[0] - target_xy[0], com[1] - target_xy[1], 0.0]]),
            cell=cell,
            pbc=pbc,
        )
        shift = np.array([target_xy[0] + delta_xy[0, 0] - com[0], target_xy[1] + delta_xy[0, 1] - com[1], 0.0])
        pos = pos + shift
    out.set_positions(pos)
    return out


def _tilt_deg(positions: np.ndarray) -> float:
    if len(positions) < 3:
        return 0.0
    centered = positions - np.mean(positions, axis=0)
    _, _, vt = np.linalg.svd(centered)
    normal = vt[-1]
    cos_t = min(1.0, max(0.0, float(abs(normal[2]))))
    return float(math.degrees(math.acos(cos_t)))


def _closest_pair_between(
    pos_i: np.ndarray,
    pos_j: np.ndarray,
    idx_i: list[int],
    idx_j: list[int],
    cell: Any,
    pbc: Any,
) -> tuple[float, int, int, np.ndarray, np.ndarray, bool] | None:
    """Return ``(dist, atom_i, atom_j, start_xyz, end_xyz, crosses_pbc)`` for two subsets."""
    if not idx_i or not idx_j:
        return None
    sub_i = pos_i[idx_i]
    sub_j = pos_j[idx_j]
    vec, dmat = get_distances(sub_i, sub_j, cell=cell, pbc=pbc)
    flat = int(np.argmin(dmat))
    a_loc, b_loc = divmod(flat, len(idx_j))
    dist = float(dmat[a_loc, b_loc])
    start = sub_i[a_loc]
    end_mic = start + vec[a_loc, b_loc]
    crosses = float(np.linalg.norm(sub_j[b_loc] - end_mic)) > 0.15
    return dist, idx_i[a_loc], idx_j[b_loc], start, end_mic, crosses


def analyze_multimol_contacts(atoms: Atoms, slab_count: int, mol_count: int) -> MultimolGeometryReport:
    """Compute per-molecule geometry, shortest MIC contact vectors, and N x N distance matrices."""
    groups = unwrap_molecule_groups(atoms, slab_count, mol_count)
    n_mol = len(groups)
    slab_top_z = float(np.max(atoms.positions[:slab_count, 2])) if slab_count > 0 else 0.0
    cell = atoms.cell
    pbc = atoms.pbc

    metric_names = ("Heavy···Heavy", "S···S", "N···S", "N···N", "COM···COM")
    matrices: dict[str, np.ndarray] = {name: np.full((n_mol, n_mol), np.nan, dtype=float) for name in metric_names}
    for name in metric_names:
        np.fill_diagonal(matrices[name], 0.0)

    best_contacts: dict[str, ContactLine] = {}

    def _consider(kind: str, cand: tuple[float, int, int, np.ndarray, np.ndarray, bool] | None, mi: int, mj: int) -> None:
        if cand is None:
            return
        dist, ai, aj, start, end, crosses = cand
        prev = best_contacts.get(kind)
        if prev is None or dist < prev.distance_A:
            suffix = " (PBC)" if crosses else ""
            best_contacts[kind] = ContactLine(
                kind=kind,
                label=f"{kind}: {dist:.2f} A{suffix}",
                distance_A=dist,
                mol_i=mi,
                mol_j=mj,
                atom_i=ai,
                atom_j=aj,
                start_xyz=(float(start[0]), float(start[1]), float(start[2])),
                end_xyz=(float(end[0]), float(end[1]), float(end[2])),
                crosses_pbc=crosses,
            )

    sym_lists = [g.get_chemical_symbols() for g in groups]
    pos_lists = [g.get_positions() for g in groups]
    coms = [np.mean(p, axis=0) for p in pos_lists]

    for i in range(n_mol):
        si, pi = sym_lists[i], pos_lists[i]
        heavy_i = [k for k, s in enumerate(si) if s != "H"]
        s_i = [k for k, s in enumerate(si) if s == "S"]
        n_i = [k for k, s in enumerate(si) if s == "N"]
        h_i = [k for k, s in enumerate(si) if s == "H"]
        sn_i = [k for k, s in enumerate(si) if s in ("S", "N")]

        for j in range(i + 1, n_mol):
            sj, pj = sym_lists[j], pos_lists[j]
            heavy_j = [k for k, s in enumerate(sj) if s != "H"]
            s_j = [k for k, s in enumerate(sj) if s == "S"]
            n_j = [k for k, s in enumerate(sj) if s == "N"]
            h_j = [k for k, s in enumerate(sj) if s == "H"]
            sn_j = [k for k, s in enumerate(sj) if s in ("S", "N")]

            c_heavy = _closest_pair_between(pi, pj, heavy_i, heavy_j, cell, pbc)
            if c_heavy is not None:
                matrices["Heavy···Heavy"][i, j] = matrices["Heavy···Heavy"][j, i] = c_heavy[0]
                _consider("Heavy···Heavy", c_heavy, i, j)

            c_ss = _closest_pair_between(pi, pj, s_i, s_j, cell, pbc)
            if c_ss is not None:
                matrices["S···S"][i, j] = matrices["S···S"][j, i] = c_ss[0]
                _consider("S···S", c_ss, i, j)

            c_ns_1 = _closest_pair_between(pi, pj, n_i, s_j, cell, pbc)
            c_ns_2 = _closest_pair_between(pi, pj, s_i, n_j, cell, pbc)
            c_ns = min([x for x in (c_ns_1, c_ns_2) if x is not None], key=lambda x: x[0], default=None)
            if c_ns is not None:
                matrices["N···S"][i, j] = matrices["N···S"][j, i] = c_ns[0]
                _consider("N···S", c_ns, i, j)

            c_nn = _closest_pair_between(pi, pj, n_i, n_j, cell, pbc)
            if c_nn is not None:
                matrices["N···N"][i, j] = matrices["N···N"][j, i] = c_nn[0]
                _consider("N···N", c_nn, i, j)

            c_h1 = _closest_pair_between(pi, pj, h_i, sn_j, cell, pbc)
            c_h2 = _closest_pair_between(pi, pj, sn_i, h_j, cell, pbc)
            c_h = min([x for x in (c_h1, c_h2) if x is not None], key=lambda x: x[0], default=None)
            _consider("H···S/N", c_h, i, j)

            vec_com, d_com = get_distances(np.array([coms[i]]), np.array([coms[j]]), cell=cell, pbc=pbc)
            dist_com = float(d_com[0, 0])
            matrices["COM···COM"][i, j] = matrices["COM···COM"][j, i] = dist_com
            end_com = coms[i] + vec_com[0, 0]
            crosses_com = float(np.linalg.norm(coms[j] - end_com)) > 0.15
            _consider(
                "COM···COM",
                (dist_com, 0, 0, coms[i], end_com, crosses_com),
                i,
                j,
            )

    # Periodic self-image contact for isolated N=1 monomer
    if n_mol == 1 and any(bool(x) for x in pbc[:2]):
        p0 = pos_lists[0]
        s0 = sym_lists[0]
        heavy0 = [k for k, s in enumerate(s0) if s != "H"]
        if heavy0:
            best_img: tuple[float, np.ndarray, np.ndarray] | None = None
            for sx in (-1, 0, 1):
                for sy in (-1, 0, 1):
                    if sx == 0 and sy == 0:
                        continue
                    shift = sx * np.asarray(cell[0]) + sy * np.asarray(cell[1])
                    p_img = p0[heavy0] + shift
                    dmat = np.linalg.norm(p0[heavy0][:, None, :] - p_img[None, :, :], axis=2)
                    flat = int(np.argmin(dmat))
                    ai, aj = divmod(flat, len(heavy0))
                    d = float(dmat[ai, aj])
                    if best_img is None or d < best_img[0]:
                        best_img = (d, p0[heavy0[ai]], p_img[aj])
            if best_img is not None:
                d_self, st, en = best_img
                best_contacts["Heavy···Heavy"] = ContactLine(
                    kind="Heavy···Heavy",
                    label=f"PBC self: {d_self:.2f} A",
                    distance_A=d_self,
                    mol_i=0,
                    mol_j=0,
                    atom_i=None,
                    atom_j=None,
                    start_xyz=(float(st[0]), float(st[1]), float(st[2])),
                    end_xyz=(float(en[0]), float(en[1]), float(en[2])),
                    crosses_pbc=True,
                )

    rows = []
    for i in range(n_mol):
        com = coms[i]

        def _row_min(mat_name: str) -> float | None:
            if n_mol < 2:
                return None
            vals = [matrices[mat_name][i, j] for j in range(n_mol) if j != i and not math.isnan(matrices[mat_name][i, j])]
            return min(vals) if vals else None

        rows.append(
            {
                "mol_idx": i + 1,
                "com_x_A": round(float(com[0]), 2),
                "com_y_A": round(float(com[1]), 2),
                "com_z_A": round(float(com[2]), 2),
                "dz_slab_top_A": round(float(com[2] - slab_top_z), 2) if slab_count > 0 else None,
                "tilt_deg": round(_tilt_deg(pos_lists[i]), 1),
                "min_heavy_neighbor_A": _row_min("Heavy···Heavy"),
                "min_S_S_neighbor_A": _row_min("S···S"),
                "min_N_S_neighbor_A": _row_min("N···S"),
                "min_COM_neighbor_A": _row_min("COM···COM"),
            }
        )

    return MultimolGeometryReport(
        n_molecules=n_mol,
        per_molecule=pd.DataFrame(rows),
        contacts=best_contacts,
        matrices=matrices,
    )


def _extract_disulfide_metrics(dimer: Atoms) -> tuple[float | None, tuple[float, float] | None, float | None]:
    """Compute (d_SS, (angle1, angle2), dihedral_CSSC) from an unwrapped 2-half disulfide."""
    syms = dimer.get_chemical_symbols()
    s_indices = [i for i, sym in enumerate(syms) if sym == "S"]
    if len(s_indices) != 2:
        return None, None, None
    s1, s2 = s_indices[0], s_indices[1]
    d_ss = float(dimer.get_distance(s1, s2, mic=True))

    half = len(dimer) // 2
    c_candidates_1 = [i for i in range(half) if syms[i] == "C"]
    c_candidates_2 = [i for i in range(half, len(dimer)) if syms[i] == "C"]
    if not c_candidates_1 or not c_candidates_2:
        return d_ss, None, None
    c1 = min(c_candidates_1, key=lambda i: float(dimer.get_distance(i, s1, mic=True)))
    c2 = min(c_candidates_2, key=lambda i: float(dimer.get_distance(i, s2, mic=True)))

    ang1 = float(dimer.get_angle(c1, s1, s2, mic=True))
    ang2 = float(dimer.get_angle(c2, s2, s1, mic=True))
    dih = float(dimer.get_dihedral(c1, s1, s2, c2, mic=True))
    if dih > 180.0:
        dih -= 360.0
    return d_ss, (ang1, ang2), dih


def analyze_disulfide_geometry(
    slab_atoms: Atoms | None,
    gas_relaxed: Atoms | None,
    ads_initial: Atoms | None,
    ads_relaxed: Atoms | None,
    slab_count: int,
) -> DisulfideGeometryReport:
    """Analyze S-S bond, C-S-S bond angle, C-S-S-C dihedral, and heights of 4-ATP-S-S-4-ATP."""
    d_ss_gas = ang_gas = dih_gas = None
    if gas_relaxed is not None:
        g_unwrapped = unwrap_single_group(gas_relaxed, gas_relaxed.cell, gas_relaxed.pbc)
        d_ss_gas, ang_gas, dih_gas = _extract_disulfide_metrics(g_unwrapped)

    d_ss_init = None
    com_init = None
    if ads_initial is not None and len(ads_initial) > slab_count:
        target_xy = np.mean(ads_initial.positions[:slab_count, :2], axis=0) if slab_count > 0 else None
        init_dim = unwrap_single_group(ads_initial[slab_count:], ads_initial.cell, ads_initial.pbc, target_xy=target_xy)
        d_ss_init, _, _ = _extract_disulfide_metrics(init_dim)
        com_init = np.mean(init_dim.get_positions(), axis=0)

    d_ss_rel = ang_rel = dih_rel = None
    ring_tilts = s_heights = n_heights = n_span = com_shift = ss_line = n_line = None
    if ads_relaxed is not None and len(ads_relaxed) > slab_count:
        slab_top_z = (
            float(np.max(ads_relaxed.positions[:slab_count, 2]))
            if slab_count > 0
            else (float(np.max(slab_atoms.positions[:, 2])) if slab_atoms is not None else 0.0)
        )
        target_xy = np.mean(ads_relaxed.positions[:slab_count, :2], axis=0) if slab_count > 0 else None
        rel_dim = unwrap_single_group(ads_relaxed[slab_count:], ads_relaxed.cell, ads_relaxed.pbc, target_xy=target_xy)
        d_ss_rel, ang_rel, dih_rel = _extract_disulfide_metrics(rel_dim)

        half = len(rel_dim) // 2
        syms = rel_dim.get_chemical_symbols()
        pos = rel_dim.get_positions()
        ring_tilts = (_tilt_deg(pos[:half]), _tilt_deg(pos[half:]))

        s_indices = [i for i, s in enumerate(syms) if s == "S"]
        n_indices = [i for i, s in enumerate(syms) if s == "N"]
        if len(s_indices) == 2:
            s1, s2 = s_indices
            s_heights = (float(pos[s1, 2] - slab_top_z), float(pos[s2, 2] - slab_top_z))
            ss_dist = float(np.linalg.norm(pos[s2] - pos[s1]))
            ss_line = ContactLine(
                kind="S–S bond",
                label=f"S–S = {ss_dist:.2f} A",
                distance_A=ss_dist,
                mol_i=0,
                mol_j=1,
                atom_i=s1,
                atom_j=s2,
                start_xyz=(float(pos[s1, 0]), float(pos[s1, 1]), float(pos[s1, 2])),
                end_xyz=(float(pos[s2, 0]), float(pos[s2, 1]), float(pos[s2, 2])),
            )
        if len(n_indices) == 2:
            n1, n2 = n_indices
            n_heights = (float(pos[n1, 2] - slab_top_z), float(pos[n2, 2] - slab_top_z))
            n_span = float(np.linalg.norm(pos[n2] - pos[n1]))
            n_line = ContactLine(
                kind="N···N span",
                label=f"N···N = {n_span:.2f} A",
                distance_A=n_span,
                mol_i=0,
                mol_j=1,
                atom_i=n1,
                atom_j=n2,
                start_xyz=(float(pos[n1, 0]), float(pos[n1, 1]), float(pos[n1, 2])),
                end_xyz=(float(pos[n2, 0]), float(pos[n2, 1]), float(pos[n2, 2])),
            )
        if com_init is not None:
            com_rel = np.mean(pos, axis=0)
            com_shift = float(np.linalg.norm(com_rel - com_init))

    return DisulfideGeometryReport(
        d_ss_gas_A=d_ss_gas,
        d_ss_initial_A=d_ss_init,
        d_ss_relaxed_A=d_ss_rel,
        angle_css_gas_deg=ang_gas,
        angle_css_relaxed_deg=ang_rel,
        dihedral_cssc_gas_deg=dih_gas,
        dihedral_cssc_relaxed_deg=dih_rel,
        ring_tilts_relaxed_deg=ring_tilts,
        s_heights_above_slab_A=s_heights,
        n_heights_above_slab_A=n_heights,
        n_to_n_span_A=n_span,
        com_shift_initial_to_relaxed_A=com_shift,
        ss_bond_line=ss_line,
        n_span_line=n_line,
    )


def overview_distances_df(bundle: CoverageStudyBundle) -> pd.DataFrame:
    """Build combined N=1..4 energetics + intermolecular distance comparison table."""
    if bundle.coverage_df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for row in bundle.coverage_df.itertuples():
        cid = str(row.case_id)
        atoms = bundle.structures.get(f"{cid}_relaxed")
        rep = analyze_multimol_contacts(atoms, bundle.slab_count, bundle.mol_count) if atoms is not None else None
        contacts = rep.contacts if rep is not None else {}

        def _cdist(key: str) -> float | None:
            c = contacts.get(key)
            return None if c is None else round(float(c.distance_A), 3)

        rows.append(
            {
                "case_id": cid,
                "N": int(row.n_molecules),
                "layer": int(row.layer_index),
                "area_per_mol_A2": round(float(row.area_per_mol_A2), 2),
                "e_ads_per_mol_eV": round(float(row.e_ads_per_mol_eV), 3),
                "e_sub_per_mol_eV": round(float(row.e_sub_per_mol_eV), 3),
                "e_lat_per_mol_eV": round(float(row.e_lat_per_mol_eV), 3),
                "e_ads_d3_per_mol_eV": None if pd.isna(row.e_ads_d3_per_mol_eV) else round(float(row.e_ads_d3_per_mol_eV), 3),
                "mean_tilt_deg": round(float(row.mean_tilt_deg), 1),
                "dz_above_slab_top_A": round(float(row.dz_above_slab_top_A), 2),
                "min_heavy_A": _cdist("Heavy···Heavy"),
                "min_S_S_A": _cdist("S···S"),
                "min_N_S_A": _cdist("N···S"),
                "min_N_N_A": _cdist("N···N"),
                "min_H_SN_A": _cdist("H···S/N"),
                "min_COM_A": _cdist("COM···COM"),
                "hbond_pair_count": int(row.hbond_pair_count),
            }
        )
    return pd.DataFrame(rows).sort_values(["layer", "N", "e_ads_per_mol_eV"], kind="stable").reset_index(drop=True)
