"""Write reviewed simulation results, Origin-ready CSVs, XYZ structures, and metadata.

Also persists/reloads ``batch_state.json`` + initial/trajectory XYZ files so
completed simulations can be reopened in the Streamlit GUI without re-running
uMLIP geometry optimizations.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ase
import pandas as pd
import pymatgen.core
from ase.io import read as ase_read
from ase.io import write as ase_write

from ads_core import __version__
from ads_core.config import Config
from ads_core.model import (
    MoleculeSpec,
    PoseResult,
    ReportSettings,
    SlabSpec,
    WarningRecord,
)
from ads_core.pipeline import BatchRun, PoseArtifact, ordered_groups, poses_frame, status_counts
from ads_core.report.summary import molecule_summary
from ads_core.review import ReviewState
from ads_core.simulation.reference import ReferenceResult
from ads_core.simulation.relax import (
    BindingCurvePoint,
    BindingCurveResult,
    TrajectoryStep,
    _extract_curve_equilibrium,
)

POSES_FILE = "poses_summary.csv"
MOLECULES_FILE = "molecule_summary.csv"
WARNINGS_FILE = "warnings.csv"
BINDING_CURVES_SUMMARY_FILE = "binding_curves_summary.csv"
METADATA_FILE = "run_metadata.json"
BATCH_STATE_FILE = "batch_state.json"
RELAX_CURVES_DIR = "relaxation_curves"
BINDING_CURVES_DIR = "binding_curves"
STRUCTURES_DIR = "structures"
TRAJECTORIES_DIR = "trajectories"
_ENCODING = "utf-8-sig"


def git_commit() -> str | None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def _safe_name(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*\s]+', "_", text).strip("_") or "item"


def warnings_frame(run: BatchRun) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    pose_lookup = {r.pose_id: r for r in run.results}

    for w in run.build_warnings:
        key = (w.target_id, w.code, w.message)
        if key in seen:
            continue
        seen.add(key)
        pr = pose_lookup.get(w.target_id)
        rows.append(
            {
                "pose_id": w.target_id,
                "surface_id": pr.surface_id if pr else "",
                "molecule_id": pr.molecule_id if pr else "",
                "severity": w.severity,
                "code": w.code,
                "message": w.message,
            }
        )

    for r in run.results:
        for w in r.warnings:
            key = (w.target_id, w.code, w.message)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "pose_id": r.pose_id,
                    "surface_id": r.surface_id,
                    "molecule_id": r.molecule_id,
                    "severity": w.severity,
                    "code": w.code,
                    "message": w.message,
                }
            )

    return pd.DataFrame(rows, columns=["pose_id", "surface_id", "molecule_id", "severity", "code", "message"])


def relaxation_curve_table(artifact: PoseArtifact) -> pd.DataFrame:
    columns = ["step", "energy_eV", "fmax_eV_per_A", "dz_com_A"]
    if not artifact.trajectory_steps:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "step": s.step,
            "energy_eV": s.energy_eV,
            "fmax_eV_per_A": s.fmax_eV_per_A,
            "dz_com_A": s.dz_com_A,
        }
        for s in artifact.trajectory_steps
    ]
    return pd.DataFrame(rows, columns=columns)


def binding_curve_table(curve: BindingCurveResult) -> pd.DataFrame:
    columns = ["dz_A", "e_ads_total_eV", "e_ads_umlip_eV", "e_ads_d3_eV"]
    if not curve.points:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "dz_A": p.dz_A,
            "e_ads_total_eV": p.e_ads_total_eV,
            "e_ads_umlip_eV": p.e_ads_umlip_eV,
            "e_ads_d3_eV": p.e_ads_d3_eV,
        }
        for p in curve.points
    ]
    return pd.DataFrame(rows, columns=columns)


def binding_curves_summary_table(curves: list[BindingCurveResult]) -> pd.DataFrame:
    """Tabular summary of extracted 1D E(z) equilibrium height and well depth."""
    columns = [
        "pose_id",
        "surface_id",
        "molecule_id",
        "site_type",
        "calculator_id",
        "d3_enabled",
        "has_attractive_well",
        "dz_eq_A",
        "e_min_total_eV",
        "e_min_umlip_eV",
        "e_min_d3_eV",
    ]
    if not curves:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "pose_id": bc.pose_id,
            "surface_id": bc.surface_id,
            "molecule_id": bc.molecule_id,
            "site_type": bc.site_type,
            "calculator_id": bc.calculator_id,
            "d3_enabled": bc.d3_enabled,
            "has_attractive_well": bc.has_attractive_well,
            "dz_eq_A": bc.dz_eq_A,
            "e_min_total_eV": bc.e_min_total_eV,
            "e_min_umlip_eV": bc.e_min_umlip_eV,
            "e_min_d3_eV": bc.e_min_d3_eV,
        }
        for bc in curves
    ]
    return pd.DataFrame(rows, columns=columns)


def run_metadata(run: BatchRun, review: ReviewState, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "program": "MoS2_adsorption_sim",
        "version": __version__,
        "git_commit": git_commit(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "batch": run.name,
        "environment": {
            "python_version": sys.version.split()[0],
            "ase_version": ase.__version__,
            "pymatgen_version": pymatgen.core.__version__,
        },
        "calculator": {
            "calculator_id": run.calculator_id,
            "backend": run.backend,
            "d3_enabled": run.d3_enabled,
            **run.calculator_metadata,
        },
        "counts": {
            "surfaces": len(run.slabs),
            "molecules": len(run.molecules),
            "poses": int(len(frame)),
            "included_in_statistics": int(frame["included"].sum()) if not frame.empty else 0,
            "status": status_counts(frame),
        },
        "references": [
            {
                "kind": ref.kind,
                "item_id": ref.item_id,
                "calculator_id": ref.calculator_id,
                "converged": ref.converged,
                "energy_total_eV": ref.energy_total_eV,
                "energy_umlip_eV": ref.energy_umlip_eV,
                "energy_d3_eV": ref.energy_d3_eV,
                "n_steps": ref.n_steps,
                "fmax_final_eV_per_A": ref.fmax_final_eV_per_A,
            }
            for ref in run.references
        ],
        "config": run.config.as_dict(),
        "config_file": str(run.config.source) if run.config.source else None,
        "review": review.to_dict(),
    }


def _save_batch_state(run: BatchRun, out: Path) -> Path:
    """Persist machine-readable batch data + initial/trajectory XYZs for instant GUI reloading."""
    state_payload: dict[str, Any] = {
        "schema_version": "ads_batch.v1",
        "name": run.name,
        "calculator_id": run.calculator_id,
        "backend": run.backend,
        "d3_enabled": run.d3_enabled,
        "calculator_metadata": run.calculator_metadata,
        "config": run.config.as_dict(),
        "slabs": [
            {
                "surface_id": s.surface_id,
                "supercell": list(s.supercell),
                "defect_type": s.defect_type,
                "vacuum_A": s.vacuum_A,
                "fix_bottom_layer": s.fix_bottom_layer,
                "lattice_a_A": s.lattice_a_A,
                "s_s_thickness_A": s.s_s_thickness_A,
                "top_s_z_A": s.top_s_z_A,
                "mo_z_A": s.mo_z_A,
                "bottom_s_z_A": s.bottom_s_z_A,
                "defect_positions_A": [list(p) for p in s.defect_positions_A],
            }
            for s in run.slabs.values()
        ],
        "molecules": [
            {
                "molecule_id": m.molecule_id,
                "formula": m.formula,
                "source": m.source,
                "box_size_A": m.box_size_A,
                "anchor_index": m.anchor_index,
                "reference_bonds": [list(b) for b in m.reference_bonds],
            }
            for m in run.molecules.values()
        ],
        "references": [
            {
                "kind": ref.kind,
                "item_id": ref.item_id,
                "calculator_id": ref.calculator_id,
                "converged": ref.converged,
                "energy_total_eV": ref.energy_total_eV,
                "energy_umlip_eV": ref.energy_umlip_eV,
                "energy_d3_eV": ref.energy_d3_eV,
                "fmax_final_eV_per_A": ref.fmax_final_eV_per_A,
                "n_steps": ref.n_steps,
                "warnings": [
                    {
                        "code": w.code,
                        "message": w.message,
                        "target_id": w.target_id,
                        "severity": w.severity,
                    }
                    for w in ref.warnings
                ],
            }
            for ref in run.references
        ],
        "build_warnings": [
            {
                "code": w.code,
                "message": w.message,
                "target_id": w.target_id,
                "severity": w.severity,
            }
            for w in run.build_warnings
        ],
        "results": [
            {
                "pose_id": r.pose_id,
                "surface_id": r.surface_id,
                "defect_type": r.defect_type,
                "molecule_id": r.molecule_id,
                "site_type": r.site_type,
                "orientation": r.orientation,
                "azimuth_deg": r.azimuth_deg,
                "initial_height_A": r.initial_height_A,
                "calculator_id": r.calculator_id,
                "d3_enabled": r.d3_enabled,
                "converged": r.converged,
                "n_steps": r.n_steps,
                "fmax_final_eV_per_A": r.fmax_final_eV_per_A,
                "e_ads_eV": r.e_ads_eV,
                "e_ads_umlip_eV": r.e_ads_umlip_eV,
                "e_ads_d3_eV": r.e_ads_d3_eV,
                "vdw_fraction": r.vdw_fraction,
                "e_int_eV": r.e_int_eV,
                "e_def_slab_eV": r.e_def_slab_eV,
                "e_def_mol_eV": r.e_def_mol_eV,
                "d_min_A": r.d_min_A,
                "d_min_pair": r.d_min_pair,
                "dz_com_A": r.dz_com_A,
                "lateral_shift_A": r.lateral_shift_A,
                "tilt_deg": r.tilt_deg,
                "max_bond_stretch_pct": r.max_bond_stretch_pct,
                "slab_rmsd_A": r.slab_rmsd_A,
                "status": r.status,
                "reasons": list(r.reasons),
                "warnings": [
                    {
                        "code": w.code,
                        "message": w.message,
                        "target_id": w.target_id,
                        "severity": w.severity,
                    }
                    for w in r.warnings
                ],
            }
            for r in run.results
        ],
        "artifacts": {
            pid: {
                "slab_indices": list(art.slab_indices),
                "mol_indices": list(art.mol_indices),
                "site_xy_A": list(art.site_xy_A),
                "trajectory_steps": [
                    {
                        "step": s.step,
                        "energy_eV": s.energy_eV,
                        "fmax_eV_per_A": s.fmax_eV_per_A,
                        "dz_com_A": s.dz_com_A,
                    }
                    for s in art.trajectory_steps
                ],
            }
            for pid, art in run.artifacts.items()
        },
        "binding_curves": [
            {
                "pose_id": bc.pose_id,
                "surface_id": bc.surface_id,
                "molecule_id": bc.molecule_id,
                "site_type": bc.site_type,
                "calculator_id": bc.calculator_id,
                "d3_enabled": bc.d3_enabled,
                "dz_eq_A": bc.dz_eq_A,
                "e_min_total_eV": bc.e_min_total_eV,
                "e_min_umlip_eV": bc.e_min_umlip_eV,
                "e_min_d3_eV": bc.e_min_d3_eV,
                "has_attractive_well": bc.has_attractive_well,
                "points": [
                    {
                        "dz_A": p.dz_A,
                        "e_ads_total_eV": p.e_ads_total_eV,
                        "e_ads_umlip_eV": p.e_ads_umlip_eV,
                        "e_ads_d3_eV": p.e_ads_d3_eV,
                    }
                    for p in bc.points
                ],
            }
            for bc in run.binding_curves
        ],
    }

    struct_dir = out / STRUCTURES_DIR
    traj_dir = out / TRAJECTORIES_DIR
    struct_dir.mkdir(parents=True, exist_ok=True)
    traj_dir.mkdir(parents=True, exist_ok=True)

    for sid, slab in run.slabs.items():
        ase_write(struct_dir / f"ref_slab_{_safe_name(sid)}.xyz", slab.atoms, format="extxyz")
    for mid, mol in run.molecules.items():
        ase_write(struct_dir / f"ref_mol_{_safe_name(mid)}.xyz", mol.atoms, format="extxyz")

    for pid, art in run.artifacts.items():
        safe = _safe_name(pid)
        ase_write(struct_dir / f"{safe}_initial.xyz", art.initial_atoms, format="extxyz")
        if art.trajectory_frames:
            ase_write(traj_dir / f"{safe}_traj.xyz", list(art.trajectory_frames), format="extxyz")

    state_path = out / BATCH_STATE_FILE
    state_path.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return state_path


def load_batch_run(batch_dir: Path | str) -> BatchRun:
    """Reload a persisted ``BatchRun`` from disk without re-running simulations."""
    root = Path(batch_dir)
    state_path = root / BATCH_STATE_FILE
    if not state_path.is_file():
        raise FileNotFoundError(f"Batch state not found: {state_path}")
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    config = Config(payload["config"], source=None)
    struct_dir = root / STRUCTURES_DIR
    traj_dir = root / TRAJECTORIES_DIR

    slabs: dict[str, SlabSpec] = {}
    for s in payload["slabs"]:
        sid = s["surface_id"]
        atoms = ase_read(struct_dir / f"ref_slab_{_safe_name(sid)}.xyz", format="extxyz")
        slabs[sid] = SlabSpec(
            surface_id=sid,
            supercell=(int(s["supercell"][0]), int(s["supercell"][1])),
            defect_type=s["defect_type"],
            vacuum_A=float(s["vacuum_A"]),
            fix_bottom_layer=bool(s["fix_bottom_layer"]),
            lattice_a_A=float(s["lattice_a_A"]),
            s_s_thickness_A=float(s["s_s_thickness_A"]),
            top_s_z_A=float(s["top_s_z_A"]),
            mo_z_A=float(s["mo_z_A"]),
            bottom_s_z_A=float(s["bottom_s_z_A"]),
            defect_positions_A=tuple((float(p[0]), float(p[1]), float(p[2])) for p in s["defect_positions_A"]),
            atoms=atoms,
        )

    molecules: dict[str, MoleculeSpec] = {}
    for m in payload["molecules"]:
        mid = m["molecule_id"]
        atoms = ase_read(struct_dir / f"ref_mol_{_safe_name(mid)}.xyz", format="extxyz")
        molecules[mid] = MoleculeSpec(
            molecule_id=mid,
            formula=m["formula"],
            source=m["source"],
            box_size_A=float(m["box_size_A"]),
            anchor_index=int(m["anchor_index"]),
            reference_bonds=tuple((int(b[0]), int(b[1]), float(b[2])) for b in m["reference_bonds"]),
            atoms=atoms,
        )

    references = [
        ReferenceResult(
            kind=r["kind"],
            item_id=r["item_id"],
            calculator_id=r["calculator_id"],
            converged=bool(r["converged"]),
            energy_total_eV=r["energy_total_eV"],
            energy_umlip_eV=r["energy_umlip_eV"],
            energy_d3_eV=r["energy_d3_eV"],
            fmax_final_eV_per_A=r["fmax_final_eV_per_A"],
            n_steps=int(r["n_steps"]),
            relaxed_atoms=slabs[r["item_id"]].atoms if r["kind"] == "slab" else molecules[r["item_id"]].atoms,
            warnings=tuple(WarningRecord(**w) for w in r["warnings"]),
        )
        for r in payload["references"]
    ]

    results = [
        PoseResult(
            pose_id=r["pose_id"],
            surface_id=r["surface_id"],
            defect_type=r["defect_type"],
            molecule_id=r["molecule_id"],
            site_type=r["site_type"],
            orientation=r["orientation"],
            azimuth_deg=float(r["azimuth_deg"]),
            initial_height_A=float(r["initial_height_A"]),
            calculator_id=r["calculator_id"],
            d3_enabled=bool(r["d3_enabled"]),
            converged=bool(r["converged"]),
            n_steps=int(r["n_steps"]),
            fmax_final_eV_per_A=r["fmax_final_eV_per_A"],
            e_ads_eV=r["e_ads_eV"],
            e_ads_umlip_eV=r["e_ads_umlip_eV"],
            e_ads_d3_eV=r["e_ads_d3_eV"],
            vdw_fraction=r["vdw_fraction"],
            e_int_eV=r["e_int_eV"],
            e_def_slab_eV=r["e_def_slab_eV"],
            e_def_mol_eV=r["e_def_mol_eV"],
            d_min_A=r["d_min_A"],
            d_min_pair=r["d_min_pair"],
            dz_com_A=r["dz_com_A"],
            lateral_shift_A=r["lateral_shift_A"],
            tilt_deg=r["tilt_deg"],
            max_bond_stretch_pct=r["max_bond_stretch_pct"],
            slab_rmsd_A=r["slab_rmsd_A"],
            status=r["status"],
            reasons=tuple(r["reasons"]),
            warnings=tuple(WarningRecord(**w) for w in r["warnings"]),
        )
        for r in payload["results"]
    ]

    artifacts: dict[str, PoseArtifact] = {}
    for pid, a in payload["artifacts"].items():
        safe = _safe_name(pid)
        init_atoms = ase_read(struct_dir / f"{safe}_initial.xyz", format="extxyz")
        relaxed_path = struct_dir / f"{safe}_relaxed.xyz"
        relaxed_atoms = ase_read(relaxed_path, format="extxyz") if relaxed_path.is_file() else init_atoms.copy()
        traj_path = traj_dir / f"{safe}_traj.xyz"
        traj_frames = tuple(ase_read(traj_path, index=":", format="extxyz")) if traj_path.is_file() else ()
        artifacts[pid] = PoseArtifact(
            pose_id=pid,
            slab_indices=tuple(int(i) for i in a["slab_indices"]),
            mol_indices=tuple(int(i) for i in a["mol_indices"]),
            site_xy_A=(float(a["site_xy_A"][0]), float(a["site_xy_A"][1])),
            initial_atoms=init_atoms,
            relaxed_atoms=relaxed_atoms,
            trajectory_steps=tuple(TrajectoryStep(**s) for s in a["trajectory_steps"]),
            trajectory_frames=traj_frames,
        )

    binding_curves: list[BindingCurveResult] = []
    for bc in payload.get("binding_curves", []):
        pts = tuple(BindingCurvePoint(**p) for p in bc["points"])
        if "has_attractive_well" in bc:
            dz_eq = bc.get("dz_eq_A")
            e_min_tot = bc.get("e_min_total_eV")
            e_min_u = bc.get("e_min_umlip_eV")
            e_min_d3 = bc.get("e_min_d3_eV")
            has_well = bool(bc.get("has_attractive_well"))
        else:
            dz_eq, e_min_tot, e_min_u, e_min_d3, has_well = _extract_curve_equilibrium(pts)
        binding_curves.append(
            BindingCurveResult(
                pose_id=bc["pose_id"],
                surface_id=bc["surface_id"],
                molecule_id=bc["molecule_id"],
                site_type=bc["site_type"],
                calculator_id=bc["calculator_id"],
                d3_enabled=bool(bc["d3_enabled"]),
                points=pts,
                dz_eq_A=dz_eq,
                e_min_total_eV=e_min_tot,
                e_min_umlip_eV=e_min_u,
                e_min_d3_eV=e_min_d3,
                has_attractive_well=has_well,
            )
        )

    return BatchRun(
        name=payload["name"],
        config=config,
        calculator_id=payload["calculator_id"],
        backend=payload["backend"],
        d3_enabled=bool(payload["d3_enabled"]),
        calculator_metadata=payload["calculator_metadata"],
        slabs=slabs,
        molecules=molecules,
        references=references,
        results=results,
        artifacts=artifacts,
        binding_curves=binding_curves,
        build_warnings=[WarningRecord(**w) for w in payload.get("build_warnings", [])],
    )


def export_run(run: BatchRun, review: ReviewState | None, output_dir: Path | str) -> list[Path]:
    """Write all output-contract CSVs, relaxed XYZs, metadata JSON, and batch state."""
    review = review or ReviewState()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_settings = ReportSettings.from_config(run.config)
    frame = poses_frame(run, review)
    groups = ordered_groups(frame, review)
    written: list[Path] = []

    def write_csv(table: pd.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(path, index=False, encoding=_ENCODING)
        written.append(path)

    write_csv(frame, out / POSES_FILE)
    write_csv(molecule_summary(frame, report_settings.boltzmann_temp_K, groups), out / MOLECULES_FILE)
    write_csv(warnings_frame(run), out / WARNINGS_FILE)

    relax_dir = out / RELAX_CURVES_DIR
    if relax_dir.exists():
        for old in relax_dir.glob("*.csv"):
            old.unlink()
    for pid, art in run.artifacts.items():
        write_csv(relaxation_curve_table(art), relax_dir / f"{_safe_name(pid)}.csv")

    bind_dir = out / BINDING_CURVES_DIR
    if bind_dir.exists():
        for old in bind_dir.glob("*.csv"):
            old.unlink()
    for bc in run.binding_curves:
        name = _safe_name(f"{bc.surface_id}_{bc.molecule_id}_{bc.site_type}_{bc.calculator_id}")
        write_csv(binding_curve_table(bc), bind_dir / f"{name}.csv")
    if run.binding_curves:
        write_csv(binding_curves_summary_table(run.binding_curves), out / BINDING_CURVES_SUMMARY_FILE)

    struct_dir = out / STRUCTURES_DIR
    struct_dir.mkdir(parents=True, exist_ok=True)
    for pid, art in run.artifacts.items():
        xyz_path = struct_dir / f"{_safe_name(pid)}_relaxed.xyz"
        ase_write(xyz_path, art.relaxed_atoms, format="extxyz")
        written.append(xyz_path)

    written.append(_save_batch_state(run, out))

    metadata_path = out / METADATA_FILE
    metadata_path.write_text(json.dumps(run_metadata(run, review, frame), ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(metadata_path)
    return written
