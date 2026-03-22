"""Raman raw TXT run entrypoint under fitting layout."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import NamedTuple

from fitting.mos2_core.core.default_stages import build_default_context, build_default_stages
from fitting.mos2_core.core.pipeline import run_pipeline
from fitting.mos2_core.io import load_pipeline_config, load_raman_txt_directory


class RunSummary(NamedTuple):
    raw_dir: Path
    run_id: str
    input_total: int
    accepted_total: int
    flagged_total: int
    report_json_path: str | None
    report_csv_path: str | None


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Raman pipeline on raw TXT spectra.")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/raman"), help="Directory containing raw *.txt spectra")
    parser.add_argument("--pattern", type=str, default="*.txt", help="Glob pattern for spectra files")
    parser.add_argument("--run-id", type=str, default="raman_raw_e2e", help="Run identifier used for report filename")
    parser.add_argument(
        "--batch-subdirs",
        action="store_true",
        help=(
            "Treat --raw-dir as a parent directory and run pipeline for each immediate subdirectory "
            "(run_id is set to each subdirectory name)."
        ),
    )
    parser.add_argument("--progress-every", type=int, default=5, help="Print real-time progress every N spectra")
    parser.add_argument(
        "--peak-n-mode",
        type=str,
        default="auto",
        choices=["auto", "peak_2_model", "peak_3_model", "peak_4_model", "peak_5_model"],
        help="Override Raman peak model mode. 'auto' keeps config models list.",
    )
    parser.add_argument(
        "--distance-outlier",
        type=str,
        default="config",
        choices=["config", "enabled", "disabled"],
        help="Override post_selection_qc.mahalanobis_outlier.enabled",
    )
    parser.add_argument(
        "--delta-outlier",
        type=str,
        default="config",
        choices=["config", "enabled", "disabled"],
        help="Override post_selection_qc.delta_outlier.enabled",
    )
    parser.add_argument(
        "--si-calibration",
        type=str,
        default="config",
        choices=["config", "enabled", "disabled"],
        help="Override raman.si_calibration.enabled",
    )
    return parser


def _resolve_raw_dir(raw_dir: Path, project_root: Path) -> Path:
    if raw_dir.is_absolute():
        return raw_dir

    cwd_candidate = (Path.cwd() / raw_dir).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return (project_root / raw_dir).resolve()


def _discover_subdir_targets(parent_dir: Path, pattern: str) -> list[tuple[Path, str]]:
    if not parent_dir.exists() or not parent_dir.is_dir():
        return []

    targets: list[tuple[Path, str]] = []
    for subdir in sorted((p for p in parent_dir.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
        if any(subdir.glob(pattern)):
            targets.append((subdir, subdir.name))
    return targets


def _run_single(
    raw_dir: Path,
    run_id: str,
    pattern: str,
    project_root: Path,
    runtime_config: dict,
    progress_every: int,
) -> RunSummary:
    raw_spectra = load_raman_txt_directory(raw_dir, pattern=pattern)
    if not raw_spectra:
        raise FileNotFoundError(f"No spectra found. raw_dir={raw_dir} | pattern={pattern}")

    context = build_default_context(
        run_id=run_id,
        artifact_dir=project_root,
        config=runtime_config,
    )
    context.state["progress_enabled"] = True
    context.state["progress_every"] = max(int(progress_every), 1)
    stages = build_default_stages(config=context.config)
    result = run_pipeline(raw_spectra=raw_spectra, stages=stages, context=context)

    return RunSummary(
        raw_dir=raw_dir,
        run_id=run_id,
        input_total=len(raw_spectra),
        accepted_total=len(result.accepted),
        flagged_total=len(result.flagged),
        report_json_path=str(result.reports[0].path) if result.reports else None,
        report_csv_path=str(result.reports[1].path) if len(result.reports) > 1 else None,
    )


def _print_run_summary(summary: RunSummary) -> None:
    print("Raman raw pipeline run completed.")
    print(f"Run ID: {summary.run_id}")
    print(f"Resolved raw dir: {summary.raw_dir}")
    print(f"Input files: {summary.input_total}")
    print(f"Accepted results: {summary.accepted_total}")
    print(f"Flagged queue size: {summary.flagged_total}")
    if summary.report_json_path:
        print(f"Fit report (JSON): {summary.report_json_path}")
    if summary.report_csv_path:
        print(f"Fit report (CSV): {summary.report_csv_path}")


def _apply_runtime_overrides(
    base_config: dict,
    *,
    peak_n_mode: str,
    distance_outlier: str,
    delta_outlier: str,
    si_calibration: str,
) -> dict:
    config = copy.deepcopy(base_config)
    raman_cfg = config.get("raman")
    if not isinstance(raman_cfg, dict):
        return config

    if peak_n_mode != "auto":
        raman_cfg["models"] = [peak_n_mode]

    qc_cfg = raman_cfg.get("post_selection_qc")
    if not isinstance(qc_cfg, dict):
        qc_cfg = {}

    if distance_outlier in {"enabled", "disabled"}:
        mh_cfg = qc_cfg.get("mahalanobis_outlier")
        if not isinstance(mh_cfg, dict):
            mh_cfg = {}
        mh_cfg["enabled"] = distance_outlier == "enabled"
        qc_cfg["mahalanobis_outlier"] = mh_cfg

    if delta_outlier in {"enabled", "disabled"}:
        delta_cfg = qc_cfg.get("delta_outlier")
        if not isinstance(delta_cfg, dict):
            delta_cfg = {}
        delta_cfg["enabled"] = delta_outlier == "enabled"
        qc_cfg["delta_outlier"] = delta_cfg

    if si_calibration in {"enabled", "disabled"}:
        si_cfg = raman_cfg.get("si_calibration")
        if not isinstance(si_cfg, dict):
            si_cfg = {}
        si_cfg["enabled"] = si_calibration == "enabled"
        raman_cfg["si_calibration"] = si_cfg

    raman_cfg["post_selection_qc"] = qc_cfg
    config["raman"] = raman_cfg
    return config


def main() -> None:
    args = _build_arg_parser().parse_args()
    project_root = Path(__file__).resolve().parents[2]
    config_dir = Path(__file__).resolve().parent / "config"
    base_config = load_pipeline_config(config_dir)
    runtime_config = _apply_runtime_overrides(
        base_config,
        peak_n_mode=args.peak_n_mode,
        distance_outlier=args.distance_outlier,
        delta_outlier=args.delta_outlier,
        si_calibration=args.si_calibration,
    )
    resolved_raw_dir = _resolve_raw_dir(args.raw_dir, project_root)

    if not resolved_raw_dir.exists():
        raise FileNotFoundError(f"Raw directory does not exist: {resolved_raw_dir}")
    if not resolved_raw_dir.is_dir():
        raise NotADirectoryError(f"Raw path is not a directory: {resolved_raw_dir}")

    run_targets: list[tuple[Path, str]]
    if args.batch_subdirs:
        run_targets = _discover_subdir_targets(resolved_raw_dir, args.pattern)
        if not run_targets:
            raise FileNotFoundError(
                "No spectra found in immediate subdirectories. "
                f"raw_dir_arg={args.raw_dir} | resolved={resolved_raw_dir} | pattern={args.pattern}"
            )
    else:
        direct_files = sorted(resolved_raw_dir.glob(args.pattern))
        if direct_files:
            run_targets = [(resolved_raw_dir, args.run_id)]
        else:
            auto_targets = _discover_subdir_targets(resolved_raw_dir, args.pattern)
            if auto_targets:
                print("No direct TXT files in --raw-dir. Auto-switching to subdirectory batch mode.")
                run_targets = auto_targets
            else:
                raise FileNotFoundError(
                    "No spectra found. "
                    f"raw_dir_arg={args.raw_dir} | resolved={resolved_raw_dir} | pattern={args.pattern}"
                )

    summaries: list[RunSummary] = []
    total_targets = len(run_targets)
    for index, (target_dir, run_id) in enumerate(run_targets, start=1):
        if total_targets > 1:
            print("")
            print(f"[Batch {index}/{total_targets}] run_id={run_id} | raw_dir={target_dir}")
        summary = _run_single(
            raw_dir=target_dir,
            run_id=run_id,
            pattern=args.pattern,
            project_root=project_root,
            runtime_config=runtime_config,
            progress_every=args.progress_every,
        )
        _print_run_summary(summary)
        summaries.append(summary)

    if len(summaries) > 1:
        total_input = sum(s.input_total for s in summaries)
        total_accepted = sum(s.accepted_total for s in summaries)
        total_flagged = sum(s.flagged_total for s in summaries)
        print("")
        print("Batch run summary:")
        print(f"Runs: {len(summaries)}")
        print(f"Input files: {total_input}")
        print(f"Accepted results: {total_accepted}")
        print(f"Flagged queue size: {total_flagged}")


if __name__ == "__main__":
    main()
