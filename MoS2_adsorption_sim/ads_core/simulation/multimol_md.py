"""Finite-temperature NVT Langevin MD and post-MD quench analysis for multi-molecule layers."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms, units
from ase.geometry import find_mic, get_distances
from ase.io import read as ase_read
from ase.io import write as ase_write
from ase.md.langevin import Langevin
from ase.optimize import BFGS, FIRE, LBFGS

from ads_core.builders.molecule import load_molecule_file
from ads_core.builders.multimol import StudySettings
from ads_core.builders.slab import build_mos2_slab
from ads_core.calculators.factory import CalculatorBundle, build_calculator_bundle
from ads_core.config import Config, infer_project_root, load_config
from ads_core.simulation.md import _init_momenta

_OPTIMIZERS = {
    "BFGS": BFGS,
    "LBFGS": LBFGS,
    "FIRE": FIRE,
}


@dataclass(frozen=True)
class MdRunCase:
    """One YAML-configured finite-temperature MD trajectory specification."""

    run_id: str
    results_dir: Path
    source_case: str
    temperature_K: float
    steps: int
    quench_after_md: bool


@dataclass(frozen=True)
class MultiMolMdSettings:
    """Settings for finite-temperature multi-molecule MD stability verification."""

    study_yaml_path: Path
    output_dir: Path
    md_mace_dtype: str
    quench_mace_dtype: str
    timestep_fs: float
    friction_per_fs: float
    trajectory_stride: int
    hbond_cutoff_A: float
    adsorption_cutoff_A: float
    seed: int
    quench_optimizer: str
    quench_fmax_eV_per_A: float
    quench_max_steps: int
    runs: tuple[MdRunCase, ...]

    @classmethod
    def from_config(cls, cfg: Config, *, project_root: Path) -> "MultiMolMdSettings":
        runs: list[MdRunCase] = []
        for rid in cfg.section_keys("runs"):
            pfx = f"runs.{rid}"
            runs.append(
                MdRunCase(
                    run_id=rid,
                    results_dir=(project_root / cfg.text(f"{pfx}.results_dir")).resolve(),
                    source_case=cfg.text(f"{pfx}.source_case"),
                    temperature_K=cfg.number(f"{pfx}.temperature_K"),
                    steps=cfg.integer(f"{pfx}.steps"),
                    quench_after_md=cfg.boolean(f"{pfx}.quench_after_md"),
                )
            )
        return cls(
            study_yaml_path=(project_root / cfg.text("study.study_yaml")).resolve(),
            output_dir=(project_root / cfg.text("study.output_dir")).resolve(),
            md_mace_dtype=cfg.text("md.mace_dtype"),
            quench_mace_dtype=cfg.text("md.quench_mace_dtype"),
            timestep_fs=cfg.number("md.timestep_fs"),
            friction_per_fs=cfg.number("md.friction_per_fs"),
            trajectory_stride=cfg.integer("md.trajectory_stride"),
            hbond_cutoff_A=cfg.number("md.hbond_cutoff_A"),
            adsorption_cutoff_A=cfg.number("md.adsorption_cutoff_A"),
            seed=cfg.integer("md.seed"),
            quench_optimizer=cfg.text("quench.optimizer"),
            quench_fmax_eV_per_A=cfg.number("quench.fmax_eV_per_A"),
            quench_max_steps=cfg.integer("quench.max_steps"),
            runs=tuple(runs),
        )


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _resolve_md_source_case(source_case: str, results_dir: Path) -> str:
    if not source_case.startswith("best_of:"):
        return source_case
    cands = [c.strip() for c in source_case[len("best_of:") :].split(",") if c.strip()]
    if not cands:
        raise ValueError(f"Empty candidate list in MD source_case {source_case!r}")
    summary_csv = results_dir / "coverage_summary.csv"
    if not summary_csv.is_file():
        raise FileNotFoundError(f"Cannot resolve {source_case!r}: missing {summary_csv}")
    energies: dict[str, float] = {}
    with summary_csv.open("r", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            energies[row["case_id"]] = float(row["energy_total_eV"])
    missing = [c for c in cands if c not in energies]
    if missing:
        raise KeyError(f"Candidates missing from {summary_csv}: {missing}")
    return min(cands, key=lambda cid: energies[cid])


def _partition_layers_by_z(init_dzs: np.ndarray, gap_threshold_A: float = 2.0) -> list[list[int]]:
    """Group molecule indices into bottom-to-top layers using initial vertical COM heights."""
    order = np.argsort(init_dzs)
    layers: list[list[int]] = [[int(order[0])]]
    for idx in order[1:]:
        prev_z = float(init_dzs[layers[-1][-1]])
        cur_z = float(init_dzs[idx])
        if cur_z - prev_z > gap_threshold_A:
            layers.append([int(idx)])
        else:
            layers[-1].append(int(idx))
    return layers


def _mol_groups(n_atoms: int, slab_count: int, mol_n: int) -> list[list[int]]:
    n_mol = (n_atoms - slab_count) // mol_n
    return [list(range(slab_count + k * mol_n, slab_count + (k + 1) * mol_n)) for k in range(n_mol)]


def _polar_azimuth_deg(atoms: Atoms, group: list[int], anchor_element: str) -> float:
    """In-plane angle (deg) from anchor S end to opposite end using minimum-image unwrapped coords."""
    pos = atoms.positions[group]
    # Unwrap molecule internal coordinates relative to first atom under PBC
    rel, _ = find_mic(pos - pos[0], cell=atoms.cell, pbc=atoms.pbc)
    symbols = [atoms[idx].symbol for idx in group]
    anchor_local = [k for k, s in enumerate(symbols) if s == anchor_element]
    heavy_other = [k for k, s in enumerate(symbols) if s != "H" and k not in anchor_local]
    if anchor_local and heavy_other:
        v = np.mean(rel[heavy_other], axis=0) - np.mean(rel[anchor_local], axis=0)
    else:
        centered = rel - np.mean(rel, axis=0)
        _, _, vt = np.linalg.svd(centered)
        v = vt[0]
    return float(math.degrees(math.atan2(float(v[1]), float(v[0]))))


def _mol_tilt_deg(atoms: Atoms, group: list[int]) -> float:
    pos = atoms.positions[group]
    rel, _ = find_mic(pos - pos[0], cell=atoms.cell, pbc=atoms.pbc)
    centered = rel - np.mean(rel, axis=0)
    _, _, vt = np.linalg.svd(centered)
    cos_t = min(1.0, max(0.0, float(abs(vt[-1][2]))))
    return float(math.degrees(math.acos(cos_t)))


def _circular_spread_deg(angles_deg: list[float]) -> float:
    """1 - R circular dispersion indicator mapped to [0, 180] deg: 0=aligned, larger=disordered."""
    if len(angles_deg) < 2:
        return 0.0
    rad = np.radians(angles_deg)
    r = float(np.hypot(np.mean(np.cos(rad)), np.mean(np.sin(rad))))
    r = max(1e-8, min(1.0, r))
    return float(math.degrees(math.sqrt(-2.0 * math.log(r)))) if r < 1.0 else 0.0


def _angle_diff_deg(a_deg: float, b_deg: float) -> float:
    return float(((a_deg - b_deg + 180.0) % 360.0) - 180.0)


def _intermol_contacts(
    atoms: Atoms,
    groups: list[list[int]],
    hbond_cutoff_A: float,
) -> tuple[float | None, float | None, int]:
    if len(groups) < 2:
        return None, None, 0
    symbols = atoms.get_chemical_symbols()
    min_heavy = float("inf")
    min_hsn = float("inf")
    hb_count = 0
    for i in range(len(groups)):
        hi = [idx for idx in groups[i] if symbols[idx] != "H"]
        sni = [idx for idx in groups[i] if symbols[idx] in ("N", "S")]
        hhi = [idx for idx in groups[i] if symbols[idx] == "H"]
        for j in range(i + 1, len(groups)):
            hj = [idx for idx in groups[j] if symbols[idx] != "H"]
            snj = [idx for idx in groups[j] if symbols[idx] in ("N", "S")]
            hhj = [idx for idx in groups[j] if symbols[idx] == "H"]
            if hi and hj:
                _, dmat = get_distances(atoms.positions[hi], atoms.positions[hj], cell=atoms.cell, pbc=atoms.pbc)
                min_heavy = min(min_heavy, float(np.min(dmat)))
            if sni and snj:
                _, d_ns = get_distances(atoms.positions[sni], atoms.positions[snj], cell=atoms.cell, pbc=atoms.pbc)
                if float(np.min(d_ns)) <= hbond_cutoff_A:
                    hb_count += 1
            if hhi and snj:
                _, d_hs = get_distances(atoms.positions[hhi], atoms.positions[snj], cell=atoms.cell, pbc=atoms.pbc)
                min_hsn = min(min_hsn, float(np.min(d_hs)))
            if hhj and sni:
                _, d_hs2 = get_distances(atoms.positions[hhj], atoms.positions[sni], cell=atoms.cell, pbc=atoms.pbc)
                min_hsn = min(min_hsn, float(np.min(d_hs2)))
    return (
        None if math.isinf(min_heavy) else min_heavy,
        None if math.isinf(min_hsn) else min_hsn,
        hb_count,
    )


def _with_mace_dtype(base_cfg: Config, dtype: str) -> Config:
    raw = base_cfg.as_dict()
    raw["calculator"]["mace_dtype"] = dtype
    return Config(raw)


def _calc_for_dtype(
    base_cfg: Config,
    dtype: str,
    *,
    backend_override: str | None,
    device_override: str | None,
) -> CalculatorBundle:
    cfg = _with_mace_dtype(base_cfg, dtype)
    return build_calculator_bundle(cfg, backend=backend_override, device=device_override)


def run_multimol_md_suite(
    md_yaml: Path | str,
    *,
    backend_override: str | None = None,
    device_override: str | None = None,
) -> dict[str, Any]:
    """Run YAML-configured finite-temperature MD and post-MD quenches."""
    yaml_path = Path(md_yaml).resolve()
    project_root = infer_project_root(yaml_path)
    md_cfg = load_config(yaml_path)
    settings = MultiMolMdSettings.from_config(md_cfg, project_root=project_root)

    study_cfg = load_config(settings.study_yaml_path)
    study_root = infer_project_root(settings.study_yaml_path)
    study = StudySettings.from_config(study_cfg, project_root=study_root)
    base_cfg = load_config(study.base_config_path)

    slab_spec = build_mos2_slab(
        base_cfg,
        supercell=(study.supercell_nx, study.supercell_ny),
        defect_type=study.defect_type,
        vacuum_A=study.vacuum_A,
        fix_bottom_layer=study.fix_bottom_layer,
    )
    slab_count = len(slab_spec.atoms)
    mol_spec = load_molecule_file(study.molecule_path, base_cfg, molecule_id=study.molecule_id)
    mol_n = len(mol_spec.atoms)

    md_bundle = _calc_for_dtype(
        base_cfg,
        settings.md_mace_dtype,
        backend_override=backend_override,
        device_override=device_override,
    )
    need_quench = any(r.quench_after_md for r in settings.runs)
    quench_bundle = (
        md_bundle
        if not need_quench or settings.quench_mace_dtype == settings.md_mace_dtype
        else _calc_for_dtype(
            base_cfg,
            settings.quench_mace_dtype,
            backend_override=backend_override,
            device_override=device_override,
        )
    )

    out_dir = settings.output_dir
    traj_dir = out_dir / "trajectories"
    struct_dir = out_dir / "structures"
    traj_dir.mkdir(parents=True, exist_ok=True)
    struct_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []
    ts_rows: list[dict[str, Any]] = []

    for run_case in settings.runs:
        resolved_source = _resolve_md_source_case(run_case.source_case, run_case.results_dir)
        src_xyz = run_case.results_dir / "structures" / f"{resolved_source}_relaxed.xyz"
        init_atoms = ase_read(src_xyz)
        groups = _mol_groups(len(init_atoms), slab_count, mol_n)
        n_mol = len(groups)

        # Evaluate initial reference energy with quench calculator if quenching enabled
        e_init_quench_calc: float | None = None
        if run_case.quench_after_md:
            ref_eval = init_atoms.copy()
            ref_eval.calc = quench_bundle.total_calc
            e_init_quench_calc = float(ref_eval.get_potential_energy())

        work = init_atoms.copy()
        work.calc = md_bundle.total_calc
        rng = np.random.default_rng(settings.seed)
        _init_momenta(work, run_case.temperature_K, rng)

        slab_top_z0 = float(np.max(work.positions[:slab_count, 2]))
        init_coms = np.array([np.mean(work.positions[g], axis=0) for g in groups])
        init_dzs = init_coms[:, 2] - slab_top_z0
        layer_mol_indices = _partition_layers_by_z(init_dzs)
        top_layer_idx = layer_mol_indices[-1]
        prev_coms = init_coms.copy()
        unwrapped_xy = np.zeros((n_mol, 2), dtype=float)
        init_az = [_polar_azimuth_deg(work, g, study.anchor_element) for g in groups]

        frames: list[Atoms] = []
        run_ts: list[dict[str, Any]] = []

        def _sample(step_idx: int) -> None:
            nonlocal prev_coms
            cur_coms = np.array([np.mean(work.positions[g], axis=0) for g in groups])
            if step_idx > 0:
                step_delta, _ = find_mic(cur_coms - prev_coms, cell=work.cell, pbc=work.pbc)
                unwrapped_xy[:] += step_delta[:, :2]
                prev_coms = cur_coms

            msd_xy = float(np.mean(np.sum(unwrapped_xy ** 2, axis=1)))
            max_disp_xy = float(np.max(np.linalg.norm(unwrapped_xy, axis=1)))

            slab_top_z = float(np.max(work.positions[:slab_count, 2]))
            mol_dzs = [float(cur_coms[k, 2] - slab_top_z) for k in range(n_mol)]
            mol_dz_drifts = [float(mol_dzs[k] - init_dzs[k]) for k in range(n_mol)]
            mol_tilts = [_mol_tilt_deg(work, g) for g in groups]
            mol_azs = [_polar_azimuth_deg(work, g, study.anchor_element) for g in groups]
            rot_drifts = [abs(_angle_diff_deg(mol_azs[k], init_az[k])) for k in range(n_mol)]
            min_heavy, min_hsn, hb_cnt = _intermol_contacts(work, groups, settings.hbond_cutoff_A)

            top_dzs = [mol_dzs[k] for k in top_layer_idx]
            top_tilts = [mol_tilts[k] for k in top_layer_idx]
            top_msd_xy = float(np.mean(np.sum(unwrapped_xy[top_layer_idx] ** 2, axis=1)))

            epot = float(work.get_potential_energy())
            ekin = float(work.get_kinetic_energy())
            temp_inst = float(work.get_temperature())

            row = {
                "run_id": run_case.run_id,
                "step": step_idx,
                "time_fs": step_idx * settings.timestep_fs,
                "temperature_K": temp_inst,
                "epot_eV": epot,
                "ekin_eV": ekin,
                "mean_dz_A": float(np.mean(mol_dzs)),
                "max_dz_A": float(np.max(mol_dzs)),
                "max_dz_drift_A": float(np.max(mol_dz_drifts)),
                "top_layer_mean_dz_A": float(np.mean(top_dzs)),
                "top_layer_mean_tilt_deg": float(np.mean(top_tilts)),
                "top_layer_msd_xy_A2": top_msd_xy,
                "mean_tilt_deg": float(np.mean(mol_tilts)),
                "max_tilt_deg": float(np.max(mol_tilts)),
                "msd_xy_A2": msd_xy,
                "max_disp_xy_A": max_disp_xy,
                "mean_rot_drift_deg": float(np.mean(rot_drifts)),
                "azimuth_spread_deg": _circular_spread_deg(mol_azs),
                "min_heavy_A": "" if min_heavy is None else min_heavy,
                "min_H_SN_A": "" if min_hsn is None else min_hsn,
                "hbond_pair_count": hb_cnt,
            }
            run_ts.append(row)
            ts_rows.append(row)

            snap = work.copy()
            snap.calc = None
            snap.info["step"] = step_idx
            snap.info["time_fs"] = step_idx * settings.timestep_fs
            frames.append(snap)

        _sample(0)
        dyn = Langevin(
            work,
            timestep=settings.timestep_fs * units.fs,
            temperature_K=run_case.temperature_K,
            friction=settings.friction_per_fs / units.fs,
            fixcm=False,
            rng=rng,
        )

        def _on_step() -> None:
            idx = int(dyn.nsteps)
            if idx > 0 and idx % settings.trajectory_stride == 0:
                _sample(idx)

        dyn.attach(_on_step, interval=1)
        dyn.run(run_case.steps)
        if not frames or frames[-1].info.get("step") != run_case.steps:
            _sample(run_case.steps)

        ase_write(traj_dir / f"{run_case.run_id}_traj.extxyz", frames, format="extxyz")
        final_snap = work.copy()
        final_snap.calc = None
        ase_write(struct_dir / f"{run_case.run_id}_final.xyz", final_snap)

        # Post-MD quench back to 0 K on float64 calculator to test symmetry breaking / basin transition
        q_delta_e: float | str = ""
        q_conv: bool | str = ""
        q_tilt: float | str = ""
        q_spread: float | str = ""
        q_hb: int | str = ""
        if run_case.quench_after_md:
            q_atoms = final_snap.copy()
            q_atoms.calc = quench_bundle.total_calc
            opt = _OPTIMIZERS[settings.quench_optimizer](q_atoms, logfile=None)
            conv = bool(opt.run(fmax=settings.quench_fmax_eV_per_A, steps=settings.quench_max_steps))
            e_q = float(q_atoms.get_potential_energy())
            q_atoms_save = q_atoms.copy()
            q_atoms_save.calc = None
            ase_write(struct_dir / f"{run_case.run_id}_quenched.xyz", q_atoms_save)
            q_tilts = [_mol_tilt_deg(q_atoms, g) for g in groups]
            q_azs = [_polar_azimuth_deg(q_atoms, g, study.anchor_element) for g in groups]
            _, _, q_hb_cnt = _intermol_contacts(q_atoms, groups, settings.hbond_cutoff_A)
            assert e_init_quench_calc is not None
            q_delta_e = e_q - e_init_quench_calc
            q_conv = conv
            q_tilt = float(np.mean(q_tilts))
            q_spread = _circular_spread_deg(q_azs)
            q_hb = q_hb_cnt

        all_dz = [float(r["mean_dz_A"]) for r in run_ts]
        all_max_dz = [float(r["max_dz_A"]) for r in run_ts]
        all_max_drift = [float(r["max_dz_drift_A"]) for r in run_ts]
        if len(layer_mol_indices) == 1:
            res_frac = sum(1 for dz in all_max_dz if -1.5 <= dz <= settings.adsorption_cutoff_A) / len(all_max_dz)
        else:
            res_frac = sum(1 for dr in all_max_drift if -1.5 <= dr <= settings.adsorption_cutoff_A) / len(all_max_drift)
        # Skip initial 20% equilibration for steady-state averages
        eq_idx = max(1, len(run_ts) // 5)
        steady = run_ts[eq_idx:]
        summary_rows.append(
            {
                "run_id": run_case.run_id,
                "source_case": resolved_source,
                "layer_count": len(layer_mol_indices),
                "n_molecules": n_mol,
                "target_temp_K": run_case.temperature_K,
                "total_ps": run_case.steps * settings.timestep_fs / 1000.0,
                "mean_temp_K": float(np.mean([r["temperature_K"] for r in steady])),
                "slab_top_z0_A": slab_top_z0,
                "mean_dz_A": float(np.mean(all_dz[eq_idx:])),
                "max_dz_A": float(np.max(all_max_dz)),
                "max_dz_drift_A": float(np.max(all_max_drift)),
                "top_layer_mean_dz_A": float(np.mean([float(r["top_layer_mean_dz_A"]) for r in steady])),
                "top_layer_mean_tilt_deg": float(np.mean([float(r["top_layer_mean_tilt_deg"]) for r in steady])),
                "top_layer_msd_xy_A2": float(run_ts[-1]["top_layer_msd_xy_A2"]),
                "residence_fraction": res_frac,
                "mean_tilt_deg": float(np.mean([r["mean_tilt_deg"] for r in steady])),
                "max_tilt_deg": float(np.max([r["max_tilt_deg"] for r in run_ts])),
                "final_msd_xy_A2": float(run_ts[-1]["msd_xy_A2"]),
                "final_max_disp_xy_A": float(run_ts[-1]["max_disp_xy_A"]),
                "mean_rot_drift_deg": float(np.mean([r["mean_rot_drift_deg"] for r in steady])),
                "final_azimuth_spread_deg": float(run_ts[-1]["azimuth_spread_deg"]),
                "mean_hbonds": float(np.mean([r["hbond_pair_count"] for r in steady])),
                "quench_delta_E_eV": q_delta_e,
                "quench_converged": q_conv,
                "quench_tilt_deg": q_tilt,
                "quench_azimuth_spread_deg": q_spread,
                "quench_hbonds": q_hb,
            }
        )

    if summary_rows:
        _write_csv(out_dir / "md_runs_summary.csv", list(summary_rows[0].keys()), summary_rows)
    if ts_rows:
        _write_csv(out_dir / "md_timeseries.csv", list(ts_rows[0].keys()), ts_rows)

    meta = {
        "study_yaml": str(settings.study_yaml_path),
        "md_mace_dtype": settings.md_mace_dtype,
        "quench_mace_dtype": settings.quench_mace_dtype,
        "timestep_fs": settings.timestep_fs,
        "friction_per_fs": settings.friction_per_fs,
    }
    (out_dir / "md_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"output_dir": str(out_dir), "summary": summary_rows, "timeseries": ts_rows}
