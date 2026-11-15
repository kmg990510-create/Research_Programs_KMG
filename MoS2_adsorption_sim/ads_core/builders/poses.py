"""Multi-pose adsorption generator using pymatgen AdsorbateSiteFinder and PCA orientation."""

from __future__ import annotations

import math

import numpy as np
from ase import Atoms
from ase.geometry import get_distances
from pymatgen.analysis.adsorption import AdsorbateSiteFinder
from pymatgen.io.ase import AseAtomsAdaptor

from ads_core.config import Config
from ads_core.model import (
    AdsorptionSite,
    MoleculeSpec,
    ORIENTATION_ANCHOR_DOWN,
    ORIENTATION_ANCHOR_UP,
    ORIENTATION_FLAT,
    PoseBuildResult,
    PoseSettings,
    PoseSpec,
    SEVERITY_INFO,
    SITE_BRIDGE,
    SITE_HOLLOW,
    SITE_MO_TOP,
    SITE_S_TOP,
    SITE_VS_RIM,
    SlabSpec,
    WarningRecord,
)


def _min_xy_distance(xy: np.ndarray, targets_xy: np.ndarray, cell_xy: np.ndarray) -> float:
    """Minimum periodic 2D distance from ``xy`` to any point in ``targets_xy``."""
    if len(targets_xy) == 0:
        return float("inf")
    # Build 3D vectors with z=0 inside a tall dummy cell so ASE handles hexagonal MIC exactly.
    cell_3d = np.eye(3)
    cell_3d[:2, :2] = cell_xy
    cell_3d[2, 2] = 50.0
    p1 = np.array([[xy[0], xy[1], 0.0]])
    p2 = np.column_stack([targets_xy, np.zeros(len(targets_xy))])
    _, dists = get_distances(p1, p2, cell=cell_3d, pbc=(True, True, False))
    return float(np.min(dists))


def _wrap_near_supercell_center(
    xy: np.ndarray,
    cell: np.ndarray,
    supercell: tuple[int, int] | None = None,
) -> np.ndarray:
    """Shift a 2D point into [0, 1) supercell fractional coords (or central primitive cell when pristine)."""
    inv = np.linalg.inv(cell[:2, :2].T)
    frac = inv @ xy
    frac_wrapped = frac % 1.0
    if supercell is not None:
        nx, ny = supercell
        # On a pristine slab, primitive vectors (1/nx, 1/ny) are exact symmetries:
        # shift into the central primitive cell around (0.5, 0.5).
        fx_prim = (frac_wrapped[0] * nx) % 1.0
        fy_prim = (frac_wrapped[1] * ny) % 1.0
        frac_wrapped = np.array([
            (nx // 2 + fx_prim) / nx,
            (ny // 2 + fy_prim) / ny,
        ])
    return cell[:2, :2].T @ frac_wrapped


def _classify_site(
    xy: np.ndarray,
    asf_kind: str,
    top_s_xy: np.ndarray,
    mo_xy: np.ndarray,
    cell: np.ndarray,
    tol_A: float,
) -> str:
    if _min_xy_distance(xy, top_s_xy, cell[:2, :2]) <= tol_A:
        return SITE_S_TOP
    if _min_xy_distance(xy, mo_xy, cell[:2, :2]) <= tol_A:
        return SITE_MO_TOP
    if asf_kind == "bridge":
        return SITE_BRIDGE
    return SITE_HOLLOW


def find_adsorption_sites(
    slab: SlabSpec,
    config: Config,
    *,
    deduplicate_by_type: bool = True,
) -> list[AdsorptionSite]:
    """Find candidate adsorption sites on the 2H-MoS2 slab using pymatgen + defect records."""
    settings = PoseSettings.from_config(config)

    clean_atoms = slab.atoms.copy()
    clean_atoms.set_constraint()  # ensure FixAtoms does not alter surface detection in pymatgen
    structure = AseAtomsAdaptor.get_structure(clean_atoms)

    asf = AdsorbateSiteFinder(structure)
    raw_sites = asf.find_adsorption_sites(
        distance=settings.site_search_height_A,
        symm_reduce=settings.site_symm_reduce,
    )

    tags = slab.atoms.get_tags()
    pos = slab.atoms.get_positions()
    top_s_xy = pos[tags == 2, :2]
    mo_xy = pos[tags == 1, :2]
    cell = np.array(slab.atoms.get_cell())
    cell_center_xy = 0.5 * (cell[0, :2] + cell[1, :2])

    candidates: list[AdsorptionSite] = []

    # Explicit vacancy defect sites and exposed rim Mo sites first
    for dpos in slab.defect_positions_A:
        candidates.append(
            AdsorptionSite(
                site_type=slab.defect_type,
                xy_A=(float(dpos[0]), float(dpos[1])),
                ref_z_A=slab.top_s_z_A,
                source="defect",
            )
        )

    if slab.defect_positions_A and len(mo_xy) > 0:
        d_ref = np.array(slab.defect_positions_A[0][:2], dtype=float)
        cell_3d = np.eye(3)
        cell_3d[:2, :2] = cell[:2, :2]
        cell_3d[2, 2] = 50.0
        p1 = np.array([[d_ref[0], d_ref[1], 0.0]])
        p2 = np.column_stack([mo_xy, np.zeros(len(mo_xy))])
        _, mo_dists = get_distances(p1, p2, cell=cell_3d, pbc=(True, True, False))
        rim_indices = [idx for idx, dist in enumerate(mo_dists[0]) if dist <= settings.defect_rim_radius_A]
        if rim_indices:
            if deduplicate_by_type:
                best_idx = min(
                    rim_indices,
                    key=lambda i: (
                        round(float(mo_dists[0][i]), 6),
                        round(float(mo_xy[i][0]), 4),
                        round(float(mo_xy[i][1]), 4),
                    ),
                )
                rim_indices = [best_idx]
            for idx in rim_indices:
                candidates.append(
                    AdsorptionSite(
                        site_type=SITE_VS_RIM,
                        xy_A=(float(mo_xy[idx][0]), float(mo_xy[idx][1])),
                        ref_z_A=slab.top_s_z_A,
                        source="defect_rim",
                    )
                )

    prim_shift = None if slab.defect_positions_A else slab.supercell
    for asf_kind in ("ontop", "hollow", "bridge"):
        for coord in raw_sites.get(asf_kind, []):
            xy = _wrap_near_supercell_center(np.array(coord[:2], dtype=float), cell, supercell=prim_shift)
            # Skip sites sitting right on top of a recorded defect (already added as defect site)
            if any(
                _min_xy_distance(xy, np.array([d[:2]]), cell[:2, :2]) <= settings.site_match_tolerance_A
                for d in slab.defect_positions_A
            ):
                continue
            site_type = _classify_site(
                xy,
                asf_kind,
                top_s_xy,
                mo_xy,
                cell,
                settings.site_match_tolerance_A,
            )
            candidates.append(
                AdsorptionSite(
                    site_type=site_type,
                    xy_A=(float(xy[0]), float(xy[1])),
                    ref_z_A=slab.top_s_z_A,
                    source="pymatgen",
                )
            )

    if not deduplicate_by_type:
        return candidates

    # Keep one representative per site_type: defect sites first, otherwise nearest to supercell center
    # (on defective slabs, pick the pristine-like site farthest from the defect if multiple exist).
    by_type: dict[str, list[AdsorptionSite]] = {}
    for site in candidates:
        by_type.setdefault(site.site_type, []).append(site)

    selected: list[AdsorptionSite] = []
    ordered_types = [slab.defect_type, SITE_VS_RIM, SITE_MO_TOP, SITE_S_TOP, SITE_HOLLOW, SITE_BRIDGE]
    seen_types: set[str] = set()
    for stype in ordered_types + sorted(by_type.keys()):
        if stype in seen_types or stype not in by_type:
            continue
        seen_types.add(stype)
        group = by_type[stype]
        if group[0].source == "defect":
            selected.extend(group)
        elif group[0].source == "defect_rim":
            selected.append(group[0])
        elif slab.defect_positions_A:
            defect_arr = np.array([d[:2] for d in slab.defect_positions_A])
            best = max(group, key=lambda s: _min_xy_distance(np.array(s.xy_A), defect_arr, cell[:2, :2]))
            selected.append(best)
        else:
            best = min(
                group,
                key=lambda s: float(np.linalg.norm(np.array(s.xy_A) - cell_center_xy)),
            )
            selected.append(best)

    return selected


def _rotation_matrix_align_vectors(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Return 3x3 rotation matrix mapping unit vector ``src`` onto unit vector ``dst``."""
    a = src / np.linalg.norm(src)
    b = dst / np.linalg.norm(dst)
    cross = np.cross(a, b)
    dot = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if np.linalg.norm(cross) < 1e-10:
        if dot > 0:
            return np.eye(3)
        # 180 degree rotation around any axis orthogonal to a
        perp = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, perp)
        axis /= np.linalg.norm(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    skew = np.array(
        [
            [0.0, -cross[2], cross[1]],
            [cross[2], 0.0, -cross[0]],
            [-cross[1], cross[0], 0.0],
        ]
    )
    return np.eye(3) + skew + (skew @ skew) * (1.0 / (1.0 + dot))


def orient_molecule_positions(
    molecule: MoleculeSpec,
    orientation: str,
    azimuth_deg: float,
) -> np.ndarray:
    """Return molecule coordinates centered at origin in the requested orientation and azimuth."""
    raw = molecule.atoms.get_positions()
    com = molecule.atoms.get_center_of_mass()
    centered = raw - com

    if len(centered) >= 2:
        cov = np.cov(centered.T)
        eigvals, eigvecs = np.linalg.eigh(cov)
        # eigvals ascending: eigvecs[:, 0] is smallest-variance axis (plane normal),
        # eigvecs[:, 2] is largest-variance axis (long axis).
        v_min = eigvecs[:, 0]
        v_max = eigvecs[:, 2]

        if orientation == ORIENTATION_FLAT:
            rot1 = _rotation_matrix_align_vectors(v_min, np.array([0.0, 0.0, 1.0]))
            pos = centered @ rot1.T
            # Align longest axis along +x for deterministic reference before azimuth
            v_long_rot = rot1 @ v_max
            v_long_xy = np.array([v_long_rot[0], v_long_rot[1], 0.0])
            if np.linalg.norm(v_long_xy) > 1e-6:
                rot_xy = _rotation_matrix_align_vectors(v_long_xy, np.array([1.0, 0.0, 0.0]))
                pos = pos @ rot_xy.T
        elif orientation in (ORIENTATION_ANCHOR_DOWN, ORIENTATION_ANCHOR_UP):
            anchor_vec = centered[molecule.anchor_index]
            axis = anchor_vec if np.linalg.norm(anchor_vec) > 1e-4 else v_max
            target = np.array([0.0, 0.0, -1.0]) if orientation == ORIENTATION_ANCHOR_DOWN else np.array([0.0, 0.0, 1.0])
            rot1 = _rotation_matrix_align_vectors(axis, target)
            pos = centered @ rot1.T
        else:
            raise ValueError(f"Unsupported orientation {orientation!r}")
    else:
        pos = centered.copy()

    theta = math.radians(azimuth_deg)
    c, s = math.cos(theta), math.sin(theta)
    rz = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    return pos @ rz.T


def _min_slab_molecule_distance(combined: Atoms, n_slab: int) -> float:
    p1 = combined.positions[:n_slab]
    p2 = combined.positions[n_slab:]
    _, dists = get_distances(p1, p2, cell=combined.cell, pbc=combined.pbc)
    return float(np.min(dists))


def build_poses(
    slab: SlabSpec,
    molecule: MoleculeSpec,
    config: Config,
    *,
    site_types: list[str] | None = None,
    orientations: list[str] | None = None,
    azimuth_angles_deg: list[float] | None = None,
    heights_A: list[float] | None = None,
) -> PoseBuildResult:
    """Generate candidate initial adsorption poses (slab + oriented molecule)."""
    settings = PoseSettings.from_config(config)
    all_sites = find_adsorption_sites(slab, config, deduplicate_by_type=True)

    if site_types is not None:
        chosen_sites = [s for s in all_sites if s.site_type in set(site_types)]
    else:
        chosen_sites = all_sites

    chosen_orientations = list(orientations) if orientations is not None else list(settings.orientations)
    chosen_azimuths = list(azimuth_angles_deg) if azimuth_angles_deg is not None else list(settings.azimuth_angles_deg)
    chosen_heights = list(heights_A) if heights_A is not None else list(settings.initial_heights_A)

    result = PoseBuildResult(sites=chosen_sites)
    n_slab = len(slab.atoms)
    n_mol = len(molecule.atoms)
    slab_indices = tuple(range(n_slab))
    mol_indices = tuple(range(n_slab, n_slab + n_mol))

    for site in chosen_sites:
        site_heights = [settings.defect_initial_height_A] if site.source == "defect" and heights_A is None else chosen_heights
        for ori in chosen_orientations:
            for az in chosen_azimuths:
                rel_pos = orient_molecule_positions(molecule, ori, az)
                # Align anchor laterally over site for anchor_down/up, or COM for flat
                if ori in (ORIENTATION_ANCHOR_DOWN, ORIENTATION_ANCHOR_UP):
                    lat_ref = rel_pos[molecule.anchor_index, :2]
                else:
                    lat_ref = np.array([0.0, 0.0])

                for h in site_heights:
                    placed_pos = rel_pos.copy()
                    placed_pos[:, 0] += site.xy_A[0] - lat_ref[0]
                    placed_pos[:, 1] += site.xy_A[1] - lat_ref[1]
                    min_z = float(np.min(placed_pos[:, 2]))
                    placed_pos[:, 2] += (site.ref_z_A + h) - min_z

                    mol_copy = molecule.atoms.copy()
                    mol_copy.set_positions(placed_pos)
                    mol_copy.set_cell(slab.atoms.cell)
                    mol_copy.set_pbc(slab.atoms.pbc)

                    combined = slab.atoms.copy() + mol_copy
                    # Preserve slab bottom-layer constraint (indices 0..n_slab-1 remain identical)
                    combined.set_constraint(slab.atoms.constraints)

                    effective_height = h
                    min_dist = _min_slab_molecule_distance(combined, n_slab)
                    pose_id = f"{slab.surface_id}__{molecule.molecule_id}__{site.site_type}__{ori}_az{int(round(az))}__z{effective_height:.2f}"

                    if min_dist < settings.min_initial_distance_A:
                        # Lift vertically until minimum distance satisfies min_initial_distance_A
                        step = 0.2
                        lifted = 0.0
                        while min_dist < settings.min_initial_distance_A and lifted < 5.0:
                            combined.positions[n_slab:, 2] += step
                            lifted += step
                            min_dist = _min_slab_molecule_distance(combined, n_slab)
                        effective_height += lifted
                        result.warnings.append(
                            WarningRecord(
                                code="initial_height_adjusted",
                                message=(
                                    f"Lifted {molecule.molecule_id} on {site.site_type} by {lifted:.2f} A "
                                    f"to keep initial distance >= {settings.min_initial_distance_A:.2f} A."
                                ),
                                target_id=pose_id,
                                severity=SEVERITY_INFO,
                            )
                        )

                    combined.info.update(
                        {
                            "pose_id": pose_id,
                            "surface_id": slab.surface_id,
                            "molecule_id": molecule.molecule_id,
                            "site_type": site.site_type,
                            "orientation": ori,
                            "azimuth_deg": float(az),
                            "initial_height_A": float(effective_height),
                            "n_slab_atoms": n_slab,
                            "n_mol_atoms": n_mol,
                        }
                    )

                    result.poses.append(
                        PoseSpec(
                            pose_id=pose_id,
                            surface_id=slab.surface_id,
                            molecule_id=molecule.molecule_id,
                            site_type=site.site_type,
                            site_xy_A=site.xy_A,
                            orientation=ori,
                            azimuth_deg=float(az),
                            initial_height_A=float(effective_height),
                            atoms=combined,
                            slab_indices=slab_indices,
                            mol_indices=mol_indices,
                        )
                    )

    return result
