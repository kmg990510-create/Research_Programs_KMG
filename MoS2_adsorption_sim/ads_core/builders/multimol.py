"""YAML-driven multi-molecule cluster, periodic layer, and disulfide builder."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from ase import Atoms
from ase.geometry import get_distances

from ads_core.builders.poses import orient_molecule_positions
from ads_core.config import Config
from ads_core.model import MoleculeSpec, ORIENTATION_FLAT


@dataclass(frozen=True)
class MultiMolPlacement:
    """Single molecule placement target relative to a slab or lower layer."""

    dx_A: float
    dy_A: float
    xy_frac: tuple[float, float] | None
    azimuth_deg: float
    tilt_deg: float


@dataclass(frozen=True)
class MultiMolCaseSpec:
    """Configuration for one cluster or periodic-grid adsorption case."""

    case_id: str
    kind: str  # "cluster" or "grid"
    base_case: str  # "" for bare substrate, or relaxed parent case_id for multilayer stacking
    layer_index: int
    n_molecules: int
    placements: tuple[MultiMolPlacement, ...]
    pattern: str
    motif: str
    tilt_deg: float


@dataclass(frozen=True)
class DisulfideSettings:
    """Parameters for thiol -> disulfide oxidative coupling check."""

    enabled: bool
    s_s_bond_A: float
    c_s_s_angle_deg: float
    dihedral_deg: float
    h_h_bond_A: float
    o_o_bond_A: float
    h2o_oh_bond_A: float
    h2o_angle_deg: float
    initial_height_A: float
    azimuth_deg: float


@dataclass(frozen=True)
class ThermalSettings:
    """Parameters for Polanyi-Wigner desorption lifetime estimates."""

    temperatures_C: tuple[float, ...]
    prefactors_hz: tuple[float, ...]
    anneal_duration_s: float
    min_intermol_hbond_cutoff_A: float


@dataclass(frozen=True)
class StudySettings:
    """Complete YAML-backed specification for a coverage / multilayer study."""

    study_name: str
    base_config_path: Path
    output_dir: Path
    supercell_nx: int
    supercell_ny: int
    defect_type: str
    vacuum_A: float
    fix_bottom_layer: bool
    molecule_id: str
    molecule_path: Path
    anchor_element: str
    initial_height_A: float
    min_initial_distance_A: float
    interlayer_gap_A: float
    optimizer: str
    fmax_eV_per_A: float
    max_steps: int
    cases: tuple[MultiMolCaseSpec, ...]
    vacancy_source_cases: tuple[str, ...]
    vacancy_remove_mol_index: int
    sequential_pairs: dict[str, str]
    disulfide: DisulfideSettings
    thermal: ThermalSettings

    @classmethod
    def from_config(cls, cfg: Config, *, project_root: Path | None = None) -> StudySettings:
        """Read every key strictly from a study YAML ``Config`` object."""
        if project_root is None:
            if cfg.source is not None:
                project_root = cfg.source.resolve().parents[1]
            else:
                project_root = Path.cwd()

        study_name = cfg.text("study.name")
        base_cfg_rel = cfg.text("study.base_config_path")
        out_rel = cfg.text("study.output_dir")

        nx = cfg.integer("substrate.supercell_nx")
        ny = cfg.integer("substrate.supercell_ny")
        defect_type = cfg.text("substrate.defect_type")
        vacuum_A = cfg.number("substrate.vacuum_A")
        fix_bottom = cfg.boolean("substrate.fix_bottom_layer")

        mol_id = cfg.text("adsorbate.molecule_id")
        mol_rel = cfg.text("adsorbate.molecule_path")
        anchor_el = cfg.text("adsorbate.anchor_element")
        init_h = cfg.number("adsorbate.initial_height_A")
        min_d = cfg.number("adsorbate.min_initial_distance_A")
        layer_gap = cfg.number("adsorbate.interlayer_gap_A")

        optimizer = cfg.text("relaxation.optimizer")
        fmax = cfg.number("relaxation.fmax_eV_per_A")
        max_steps = cfg.integer("relaxation.max_steps")

        motifs: dict[str, list[list[float]]] = {}
        for mname in cfg.section_keys("cluster_motifs"):
            rows = cfg.number_rows(f"cluster_motifs.{mname}")
            for row in rows:
                if len(row) != 4:
                    raise ValueError(f"cluster_motifs.{mname} rows must have 4 numbers [dx, dy, az, tilt], got {row}")
            motifs[mname] = rows

        cases: list[MultiMolCaseSpec] = []
        for cid in cfg.section_keys("cluster_cases"):
            pfx = f"cluster_cases.{cid}"
            base_case = cfg.text(f"{pfx}.base_case")
            layer_idx = cfg.integer(f"{pfx}.layer_index")
            motif_name = cfg.text(f"{pfx}.motif")
            if motif_name not in motifs:
                raise KeyError(f"{pfx}.motif references unknown motif {motif_name!r}")
            center_frac = cfg.number_list(f"{pfx}.center_frac")
            if len(center_frac) != 2:
                raise ValueError(f"{pfx}.center_frac must have 2 numbers [fx, fy]")
            rot_deg = cfg.number(f"{pfx}.rotation_deg")
            rot_rad = math.radians(rot_deg)
            cos_r, sin_r = math.cos(rot_rad), math.sin(rot_rad)
            placements = []
            for dx, dy, az, tilt in motifs[motif_name]:
                rdx = cos_r * dx - sin_r * dy
                rdy = sin_r * dx + cos_r * dy
                placements.append(
                    MultiMolPlacement(
                        dx_A=rdx,
                        dy_A=rdy,
                        xy_frac=(float(center_frac[0]), float(center_frac[1])),
                        azimuth_deg=float(az + rot_deg),
                        tilt_deg=float(tilt),
                    )
                )
            cases.append(
                MultiMolCaseSpec(
                    case_id=cid,
                    kind="cluster",
                    base_case=base_case,
                    layer_index=layer_idx,
                    n_molecules=len(placements),
                    placements=tuple(placements),
                    pattern=motif_name,
                    motif=motif_name,
                    tilt_deg=float(motifs[motif_name][0][3]),
                )
            )

        for cid in cfg.section_keys("grid_cases"):
            pfx = f"grid_cases.{cid}"
            base_case = cfg.text(f"{pfx}.base_case")
            layer_idx = cfg.integer(f"{pfx}.layer_index")
            gx = cfg.integer(f"{pfx}.grid_nx")
            gy = cfg.integer(f"{pfx}.grid_ny")
            if gx < 1 or gy < 1:
                raise ValueError(f"{pfx} grid dimensions must be >= 1, got ({gx}, {gy})")
            pattern = cfg.text(f"{pfx}.pattern")
            if pattern not in ("parallel", "antiparallel", "checkerboard"):
                raise ValueError(f"{pfx}.pattern unsupported: {pattern!r}")
            tilt_deg = cfg.number(f"{pfx}.tilt_deg")
            az_deg = cfg.number(f"{pfx}.azimuth_deg")
            stagger_frac = cfg.number(f"{pfx}.stagger_frac")
            row_az_step_deg = cfg.number(f"{pfx}.row_azimuth_step_deg")
            offset_frac = cfg.number_list(f"{pfx}.offset_frac")
            if len(offset_frac) != 2:
                raise ValueError(f"{pfx}.offset_frac must have 2 numbers [fx, fy]")

            placements = []
            for ix in range(gx):
                for iy in range(gy):
                    row_shift = stagger_frac if (iy % 2 == 1) else 0.0
                    fx = (float(offset_frac[0]) + (ix + row_shift) / gx) % 1.0
                    fy = (float(offset_frac[1]) + iy / gy) % 1.0
                    if pattern == "parallel":
                        flip = 0.0
                    elif pattern == "antiparallel":
                        flip = 180.0 if (iy % 2 == 1) else 0.0
                    else:  # checkerboard
                        flip = 180.0 if ((ix + iy) % 2 == 1) else 0.0
                    row_rot = row_az_step_deg if (iy % 2 == 1) else 0.0
                    placements.append(
                        MultiMolPlacement(
                            dx_A=0.0,
                            dy_A=0.0,
                            xy_frac=(fx, fy),
                            azimuth_deg=float(az_deg + flip + row_rot),
                            tilt_deg=float(tilt_deg),
                        )
                    )
            cases.append(
                MultiMolCaseSpec(
                    case_id=cid,
                    kind="grid",
                    base_case=base_case,
                    layer_index=layer_idx,
                    n_molecules=len(placements),
                    placements=tuple(placements),
                    pattern=pattern,
                    motif="grid",
                    tilt_deg=float(tilt_deg),
                )
            )

        vac_sources = tuple(cfg.text_list("vacancy_desorption.source_cases"))
        vac_remove_idx = cfg.integer("vacancy_desorption.remove_mol_index")
        seq_pairs = {
            k: cfg.text(f"vacancy_desorption.sequential_pairs.{k}")
            for k in cfg.section_keys("vacancy_desorption.sequential_pairs")
        }

        disulfide = DisulfideSettings(
            enabled=cfg.boolean("disulfide_check.enabled"),
            s_s_bond_A=cfg.number("disulfide_check.s_s_bond_A"),
            c_s_s_angle_deg=cfg.number("disulfide_check.c_s_s_angle_deg"),
            dihedral_deg=cfg.number("disulfide_check.dihedral_deg"),
            h_h_bond_A=cfg.number("disulfide_check.h_h_bond_A"),
            o_o_bond_A=cfg.number("disulfide_check.o_o_bond_A"),
            h2o_oh_bond_A=cfg.number("disulfide_check.h2o_oh_bond_A"),
            h2o_angle_deg=cfg.number("disulfide_check.h2o_angle_deg"),
            initial_height_A=cfg.number("disulfide_check.initial_height_A"),
            azimuth_deg=cfg.number("disulfide_check.azimuth_deg"),
        )

        thermal = ThermalSettings(
            temperatures_C=tuple(cfg.number_list("thermal_analysis.temperatures_C")),
            prefactors_hz=tuple(cfg.number_list("thermal_analysis.prefactors_hz")),
            anneal_duration_s=cfg.number("thermal_analysis.anneal_duration_s"),
            min_intermol_hbond_cutoff_A=cfg.number("thermal_analysis.min_intermol_hbond_cutoff_A"),
        )

        def _res(rel: str) -> Path:
            p = Path(rel)
            return p if p.is_absolute() else (project_root / p)

        return cls(
            study_name=study_name,
            base_config_path=_res(base_cfg_rel),
            output_dir=_res(out_rel),
            supercell_nx=nx,
            supercell_ny=ny,
            defect_type=defect_type,
            vacuum_A=vacuum_A,
            fix_bottom_layer=fix_bottom,
            molecule_id=mol_id,
            molecule_path=_res(mol_rel),
            anchor_element=anchor_el,
            initial_height_A=init_h,
            min_initial_distance_A=min_d,
            interlayer_gap_A=layer_gap,
            optimizer=optimizer,
            fmax_eV_per_A=fmax,
            max_steps=max_steps,
            cases=tuple(cases),
            vacancy_source_cases=vac_sources,
            vacancy_remove_mol_index=vac_remove_idx,
            sequential_pairs=seq_pairs,
            disulfide=disulfide,
            thermal=thermal,
        )


@dataclass
class MultiMolAssembly:
    """Combined periodic substrate + N adsorbate molecules with index book-keeping."""

    case_id: str
    atoms: Atoms
    slab_count: int
    existing_mol_groups: tuple[tuple[int, ...], ...]
    new_mol_groups: tuple[tuple[int, ...], ...]

    @property
    def all_mol_groups(self) -> tuple[tuple[int, ...], ...]:
        return self.existing_mol_groups + self.new_mol_groups


def _orient_with_tilt(mol_spec: MoleculeSpec, tilt_deg: float, azimuth_deg: float) -> np.ndarray:
    """Start from flat PCA orientation, apply y-axis tilt, then z-axis azimuth."""
    pos = orient_molecule_positions(mol_spec, ORIENTATION_FLAT, 0.0)
    if abs(tilt_deg) > 1e-8:
        t = math.radians(tilt_deg)
        ct, st = math.cos(t), math.sin(t)
        ry = np.array([[ct, 0.0, st], [0.0, 1.0, 0.0], [-st, 0.0, ct]])
        pos = pos @ ry.T
    if abs(azimuth_deg) > 1e-8:
        a = math.radians(azimuth_deg)
        ca, sa = math.cos(a), math.sin(a)
        rz = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])
        pos = pos @ rz.T
    return pos


def _min_distance_between_groups(
    atoms: Atoms,
    group_a: Iterable[int],
    group_b: Iterable[int],
) -> float:
    idx_a = list(group_a)
    idx_b = list(group_b)
    if not idx_a or not idx_b:
        return float("inf")
    _, dists = get_distances(
        atoms.positions[idx_a],
        atoms.positions[idx_b],
        cell=atoms.cell,
        pbc=atoms.pbc,
    )
    return float(np.min(dists))


def _lift_until_clear(
    mol_pos: np.ndarray,
    mol_symbols: list[str],
    existing: Atoms,
    min_dist_A: float,
    *,
    step_A: float = 0.2,
    max_lifts: int = 30,
) -> np.ndarray:
    """Raise ``mol_pos`` vertically until it clears all atoms in ``existing`` by ``min_dist_A``."""
    pos = mol_pos.copy()
    existing_pos = existing.get_positions()
    for _ in range(max_lifts + 1):
        _, dists = get_distances(pos, existing_pos, cell=existing.cell, pbc=existing.pbc)
        if float(np.min(dists)) >= min_dist_A:
            return pos
        pos[:, 2] += step_A
    raise ValueError(
        f"Placed molecule ({len(mol_symbols)} atoms) still overlaps existing structure (< {min_dist_A:.2f} A) after lifting"
    )


def build_multimol_assembly(
    base_atoms: Atoms,
    slab_count: int,
    existing_mol_groups: tuple[tuple[int, ...], ...],
    mol_spec: MoleculeSpec,
    case: MultiMolCaseSpec,
    study: StudySettings,
) -> MultiMolAssembly:
    """Assemble ``case.n_molecules`` copies of ``mol_spec`` onto ``base_atoms``."""
    combined = base_atoms.copy()
    # Keep periodic cell vectors; base z reference is highest atom in base_atoms.
    base_top_z = float(np.max(combined.positions[:, 2]))
    vertical_gap = study.initial_height_A if case.layer_index == 1 else study.interlayer_gap_A
    target_z_com = base_top_z + vertical_gap

    cell_xy = combined.cell[:2, :2]
    new_groups: list[tuple[int, ...]] = []
    mol_symbols = mol_spec.atoms.get_chemical_symbols()
    n_per_mol = len(mol_symbols)

    for p in case.placements:
        fx, fy = p.xy_frac if p.xy_frac is not None else (0.5, 0.5)
        origin_xy = cell_xy.T @ np.array([fx, fy], dtype=float)
        target_xy = origin_xy + np.array([p.dx_A, p.dy_A], dtype=float)

        rel_pos = _orient_with_tilt(mol_spec, tilt_deg=p.tilt_deg, azimuth_deg=p.azimuth_deg)
        # Shift lowest atom at least above base_top_z + gap, using COM anchor if flat
        min_rel_z = float(np.min(rel_pos[:, 2]))
        base_shift_z = max(target_z_com, base_top_z + study.min_initial_distance_A - min_rel_z)
        placed_pos = rel_pos + np.array([target_xy[0], target_xy[1], base_shift_z], dtype=float)

        # Check horizontal overlap against molecules already added in THIS layer first
        for prev_group in new_groups:
            prev_pos = combined.positions[list(prev_group)]
            _, inter_d = get_distances(placed_pos, prev_pos, cell=combined.cell, pbc=combined.pbc)
            dmin = float(np.min(inter_d))
            if dmin < study.min_initial_distance_A:
                raise ValueError(
                    f"Case {case.case_id!r}: intermolecular overlap ({dmin:.2f} A < {study.min_initial_distance_A:.2f} A); "
                    "increase cluster spacing or reduce grid density in YAML."
                )

        # Lift clear of substrate (and any earlier layers) vertically if needed
        placed_pos = _lift_until_clear(placed_pos, mol_symbols, combined, study.min_initial_distance_A)

        start_idx = len(combined)
        combined += Atoms(symbols=mol_symbols, positions=placed_pos)
        new_groups.append(tuple(range(start_idx, start_idx + n_per_mol)))

    return MultiMolAssembly(
        case_id=case.case_id,
        atoms=combined,
        slab_count=slab_count,
        existing_mol_groups=existing_mol_groups,
        new_mol_groups=tuple(new_groups),
    )


def build_disulfide_dimer(
    mol_spec: MoleculeSpec,
    *,
    anchor_element: str,
    s_s_bond_A: float,
    c_s_s_angle_deg: float,
    dihedral_deg: float,
    vacuum_box_A: float,
) -> Atoms:
    """Construct a bent ``Ar-S-S-Ar`` disulfide dimer from a thiol ``MoleculeSpec``."""
    raw = mol_spec.atoms.copy()
    symbols = raw.get_chemical_symbols()
    if anchor_element not in symbols:
        raise ValueError(f"Anchor element {anchor_element!r} not found in {mol_spec.molecule_id}")

    s_idx = symbols.index(anchor_element)
    pos = raw.get_positions()
    # Find terminal H bonded to S (closest H atom)
    h_candidates = [i for i, sym in enumerate(symbols) if sym == "H"]
    if not h_candidates:
        raise ValueError(f"No H atom found in {mol_spec.molecule_id} to remove for disulfide")
    h_thiol = min(h_candidates, key=lambda i: float(np.linalg.norm(pos[i] - pos[s_idx])))

    # Remove thiol H cleanly
    del raw[h_thiol]
    new_s_idx = s_idx if h_thiol > s_idx else s_idx - 1

    # Align S at origin with (ring center -> S) pointing along +x and ring normal along +z
    p_rad = raw.get_positions()
    s_pos = p_rad[new_s_idx].copy()
    heavy = [i for i, sym in enumerate(raw.get_chemical_symbols()) if sym != "H" and i != new_s_idx]
    ring_com = np.mean(p_rad[heavy], axis=0)
    axis_cs = s_pos - ring_com
    axis_cs /= np.linalg.norm(axis_cs)

    p_shift = p_rad - s_pos
    c_pos = p_shift[heavy]
    cov = np.cov(c_pos.T)
    _, eigvecs = np.linalg.eigh(cov)
    normal = eigvecs[:, 0]
    normal = normal - np.dot(normal, axis_cs) * axis_cs
    normal /= np.linalg.norm(normal)
    binormal = np.cross(normal, axis_cs)
    rot_frame = np.vstack([axis_cs, binormal, normal])
    p_aligned = p_shift @ rot_frame.T

    # Rotate Fragment 1 around z so S1->C1 makes exact C-S-S bond angle relative to S1->S2 (+x)
    bend_rad = -math.radians(180.0 - c_s_s_angle_deg)
    cb, sb = math.cos(bend_rad), math.sin(bend_rad)
    rz = np.array([[cb, -sb, 0.0], [sb, cb, 0.0], [0.0, 0.0, 1.0]])
    p1 = p_aligned @ rz.T

    # Mirror Fragment 2 across x (keeps C2-S2-S1 = c_s_s_angle_deg), twist by dihedral around +x, shift +s_s_bond_A
    p2 = p1.copy()
    p2[:, 0] = -p2[:, 0]
    d_rad = math.radians(dihedral_deg)
    cd, sd = math.cos(d_rad), math.sin(d_rad)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cd, -sd], [0.0, sd, cd]])
    p2 = p2 @ rx.T
    p2[:, 0] += s_s_bond_A

    syms = raw.get_chemical_symbols()
    dimer = Atoms(symbols=syms + syms, positions=np.vstack([p1, p2]))
    dimer.set_cell([vacuum_box_A, vacuum_box_A, vacuum_box_A])
    dimer.pbc = (True, True, True)
    dimer.center()
    return dimer


def build_reference_gases(disulfide: DisulfideSettings, vacuum_box_A: float) -> dict[str, Atoms]:
    """Build isolated H2, O2, and H2O molecules parameterized purely from YAML."""
    theta = math.radians(disulfide.h2o_angle_deg / 2.0)
    oh = disulfide.h2o_oh_bond_A
    gases = {
        "H2": Atoms("H2", positions=[[0.0, 0.0, 0.0], [disulfide.h_h_bond_A, 0.0, 0.0]]),
        "O2": Atoms("O2", positions=[[0.0, 0.0, 0.0], [disulfide.o_o_bond_A, 0.0, 0.0]]),
        "H2O": Atoms(
            "OH2",
            positions=[
                [0.0, 0.0, 0.0],
                [oh * math.sin(theta), 0.0, oh * math.cos(theta)],
                [-oh * math.sin(theta), 0.0, oh * math.cos(theta)],
            ],
        ),
    }
    for atoms in gases.values():
        atoms.set_cell([vacuum_box_A, vacuum_box_A, vacuum_box_A])
        atoms.pbc = (True, True, True)
        atoms.center()
    return gases
