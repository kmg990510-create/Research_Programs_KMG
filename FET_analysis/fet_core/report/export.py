"""Write a reviewed run to a results folder.

Tables are CSV with a header row and the unit in the column name, so they load
straight into Origin. ``run_metadata.json`` holds what is needed to reproduce
the numbers: program version, input file hashes, the whole configuration, and
every review edit.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from fet_core import __version__
from fet_core.analysis.sweeps import split_branches
from fet_core.model import CURVE_TRANSFER
from fet_core.pipeline import Run, ordered_groups, results_frame, status_counts
from fet_core.report.summary import group_summary
from fet_core.review import ReviewState

RESULTS_FILE = "results_summary.csv"
GROUPS_FILE = "group_summary.csv"
WARNINGS_FILE = "warnings.csv"
MEASUREMENTS_FILE = "measurements.csv"
METADATA_FILE = "run_metadata.json"
CURVES_DIR = "transfer_curves"
_ENCODING = "utf-8-sig"  # Excel and Origin read non-ASCII names correctly with a BOM


def git_commit() -> str | None:
    """Commit of the code that produced the results, or None outside a git checkout."""
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
    return re.sub(r'[<>:"/\\|?*\s]+', "_", text).strip("_") or "group"


def warnings_frame(run: Run) -> pd.DataFrame:
    rows = [
        {
            "source_file": w.source_file,
            "run_id": w.run_id,
            "sweep": w.context.get("sweep"),
            "severity": w.severity,
            "code": w.code,
            "message": w.message,
        }
        for w in [*run.loaded.warnings, *run.analysis.warnings]
    ]
    return pd.DataFrame(rows, columns=["source_file", "run_id", "sweep", "severity", "code", "message"])


def measurements_frame(run: Run) -> pd.DataFrame:
    """Every point of every measurement in the standard columns."""
    parts = []
    for item in run.loaded.measurements:
        part = item.data.copy()
        part.insert(0, "point", range(len(part)))
        part.insert(0, "curve_type", item.curve_type)
        part.insert(0, "label", item.label)
        part.insert(0, "run_id", item.run_id)
        part.insert(0, "source_file", item.source_file.name)
        parts.append(part)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def transfer_curve_tables(run: Run, review: ReviewState) -> dict[str, pd.DataFrame]:
    """One wide table per display group and sweep: ``Vg (V)`` and one ``Id (A)`` column per run.

    Runs rejected in the review are left out. Gate voltages of all runs are
    merged; a run that has no point at a voltage has an empty cell there.
    """
    tables: dict[str, dict[str, pd.Series]] = {}
    for item in run.loaded.measurements:
        if item.curve_type != CURVE_TRANSFER:
            continue
        branches, _ = split_branches(item.data, run.settings)
        for branch in branches:
            if review.decision(item.source_file.name, item.run_id, branch.direction) == "rejected":
                continue
            name = f"{_safe_name(review.display_group(item.group))}_{branch.direction}"
            column = f"{item.label} [{item.run_id}] Id (A)" if item.run_id != item.label else f"{item.label} Id (A)"
            data = branch.data.dropna(subset=["Vg"]).groupby("Vg")["Id"].mean()
            tables.setdefault(name, {})[column] = data
    out: dict[str, pd.DataFrame] = {}
    for name, columns in tables.items():
        table = pd.DataFrame(columns).sort_index()
        table.index.name = "Vg (V)"
        out[name] = table.reset_index()
    return out


def run_metadata(run: Run, review: ReviewState, frame: pd.DataFrame) -> dict:
    return {
        "program": "FET_analysis",
        "version": __version__,
        "git_commit": git_commit(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "batch": run.name,
        "input_dir": str(run.input_dir),
        "input_files": [
            {
                "name": f.path.name,
                "sha256": f.sha256,
                "reader": f.reader,
                "status": f.status,
                "reason": f.reason,
                "measurements": f.measurement_count,
            }
            for f in run.loaded.files
        ],
        "counts": {
            "measurements": len(run.loaded.measurements),
            "sweeps": int(len(frame)),
            "included_in_statistics": int(frame["included"].sum()) if not frame.empty else 0,
            "status": status_counts(frame),
        },
        "device_geometry_default": {
            "W_um": run.geometry.W_um,
            "L_um": run.geometry.L_um,
            "t_ox_nm": run.geometry.t_ox_nm,
            "eps_r": run.geometry.eps_r,
        },
        "analysis_settings": run.settings.as_dict(),
        "config": run.config.as_dict(),
        "config_file": str(run.config.source) if run.config.source else None,
        "review": review.to_dict(),
    }


def export_run(run: Run, review: ReviewState | None, output_dir: Path | str) -> list[Path]:
    """Write all result files into ``output_dir`` and return their paths."""
    review = review or ReviewState()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = results_frame(run, review)
    written: list[Path] = []

    def write_csv(table: pd.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(path, index=False, encoding=_ENCODING)
        written.append(path)

    write_csv(frame, out / RESULTS_FILE)
    write_csv(group_summary(frame, ordered_groups(frame, review)), out / GROUPS_FILE)
    write_csv(warnings_frame(run), out / WARNINGS_FILE)
    write_csv(measurements_frame(run), out / MEASUREMENTS_FILE)
    curves_dir = out / CURVES_DIR
    if curves_dir.exists():  # stale tables of renamed groups must not survive
        for old in curves_dir.glob("*.csv"):
            old.unlink()
    for name, table in transfer_curve_tables(run, review).items():
        write_csv(table, curves_dir / f"{name}.csv")
    metadata_path = out / METADATA_FILE
    metadata_path.write_text(json.dumps(run_metadata(run, review, frame), ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(metadata_path)
    return written
