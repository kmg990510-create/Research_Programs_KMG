"""Run pipeline on real TXT spectra from data/raw."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import NamedTuple

from ..io import load_raman_txt_directory
from .default_stages import build_default_context, build_default_stages
from .pipeline import run_pipeline


class RunSummary(NamedTuple):
    raw_dir: Path
    run_id: str
    input_total: int
    processed_count: int
    valid_count: int
    attention_count: int
    invalid_count: int
    flagged_valid_count: int
    qc_passed: int
    flagged_total: int
    accepted_total: int
    selection_metric_usage: object
    report_json_path: str | None
    report_csv_path: str | None


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MoS2 pipeline on raw TXT spectra.")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw/raman/sample_A"),
        help="Directory containing raw *.txt spectra",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="*.txt",
        help="Glob pattern for spectra files",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="raw_e2e",
        help="Run identifier used for report filename",
    )
    parser.add_argument(
        "--batch-subdirs",
        action="store_true",
        help=(
            "Treat --raw-dir as a parent directory and run pipeline for each immediate subdirectory "
            "(run_id will be each subdirectory name)."
        ),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=5,
        help="Print real-time progress every N spectra",
    )
    return parser


def _resolve_raw_dir(raw_dir: Path, project_root: Path) -> Path:
    """
    Resolve raw-dir robustly:
    - absolute path: as-is
    - relative path: try CWD first, then project root
    """
    if raw_dir.is_absolute():
        return raw_dir

    cwd_candidate = (Path.cwd() / raw_dir).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    project_candidate = (project_root / raw_dir).resolve()
    return project_candidate


def _discover_subdir_targets(parent_dir: Path, pattern: str) -> list[tuple[Path, str]]:
    targets: list[tuple[Path, str]] = []
    for subdir in sorted([p for p in parent_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
        has_txt = any(subdir.glob(pattern))
        if has_txt:
            targets.append((subdir, subdir.name))
    return targets


def _run_single(
    raw_dir: Path,
    run_id: str,
    pattern: str,
    project_root: Path,
    progress_every: int,
) -> RunSummary:
    raw_spectra = load_raman_txt_directory(raw_dir, pattern=pattern)
    if not raw_spectra:
        raise FileNotFoundError(
            "No spectra found. "
            f"raw_dir={raw_dir} | pattern={pattern}"
        )

    context = build_default_context(
        run_id=run_id,
        artifact_dir=project_root,
        config_dir=project_root / "config",
    )
    stages = build_default_stages(config=context.config)
    context.state["progress_enabled"] = True
    context.state["progress_every"] = max(int(progress_every), 1)
    result = run_pipeline(raw_spectra=raw_spectra, stages=stages, context=context)

    input_total = len(raw_spectra)
    selected_status_counts = context.state.get("selected_fit_status_counts", {})
    valid_count = int(selected_status_counts.get("valid", 0))
    attention_count = int(selected_status_counts.get("attention", 0))
    invalid_count = int(selected_status_counts.get("invalid", 0))
    processed_count = valid_count + attention_count + invalid_count
    flagged_valid_count = int(context.state.get("flagged_valid_count", 0))

    report_json_path = str(result.reports[0].path) if result.reports else None
    report_csv_path = str(result.reports[1].path) if len(result.reports) > 1 else None

    return RunSummary(
        raw_dir=raw_dir,
        run_id=run_id,
        input_total=input_total,
        processed_count=processed_count,
        valid_count=valid_count,
        attention_count=attention_count,
        invalid_count=invalid_count,
        flagged_valid_count=flagged_valid_count,
        qc_passed=int(context.state.get("qc_passed", 0)),
        flagged_total=len(result.flagged),
        accepted_total=len(result.accepted),
        selection_metric_usage=context.state.get("selection_metric_usage"),
        report_json_path=report_json_path,
        report_csv_path=report_csv_path,
    )


def _print_run_summary(summary: RunSummary) -> None:
    print("Raw pipeline run completed.")
    print(f"Run ID: {summary.run_id}")
    print(f"Resolved raw dir: {summary.raw_dir}")
    print(f"Input files: {summary.processed_count} / {summary.input_total}")
    print(f"Valid fitting: {summary.valid_count} / {summary.processed_count}")
    print(f"Attention fitting: {summary.attention_count} / {summary.processed_count}")
    print(f"Invalid fitting: {summary.invalid_count} / {summary.processed_count}")
    print(f"Flagged for review: {summary.flagged_valid_count} / {summary.valid_count}")
    print(f"QC passed: {summary.qc_passed}")
    print(f"Flagged total queue: {summary.flagged_total}")
    print(f"Accepted results: {summary.accepted_total}")
    print(f"Selection metric usage: {summary.selection_metric_usage}")
    if summary.report_json_path:
        print(f"Fit report (JSON): {summary.report_json_path}")
    if summary.report_csv_path:
        print(f"Fit report (CSV): {summary.report_csv_path}")


def main() -> None:
    args = _build_arg_parser().parse_args()
    project_root = Path(__file__).resolve().parents[2]
    resolved_raw_dir = _resolve_raw_dir(args.raw_dir, project_root)

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
                print(
                    "No direct TXT files in --raw-dir. "
                    "Auto-switching to subdirectory batch mode."
                )
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
            progress_every=args.progress_every,
        )
        _print_run_summary(summary)
        summaries.append(summary)

    if len(summaries) > 1:
        total_input = sum(s.input_total for s in summaries)
        total_processed = sum(s.processed_count for s in summaries)
        total_valid = sum(s.valid_count for s in summaries)
        total_attention = sum(s.attention_count for s in summaries)
        total_invalid = sum(s.invalid_count for s in summaries)
        total_flagged = sum(s.flagged_total for s in summaries)
        total_accepted = sum(s.accepted_total for s in summaries)
        print("")
        print("Batch run summary:")
        print(f"Runs: {len(summaries)}")
        print(f"Input files: {total_processed} / {total_input}")
        print(f"Valid fitting: {total_valid} / {total_processed}")
        print(f"Attention fitting: {total_attention} / {total_processed}")
        print(f"Invalid fitting: {total_invalid} / {total_processed}")
        print(f"Flagged total queue: {total_flagged}")
        print(f"Accepted results: {total_accepted}")


if __name__ == "__main__":
    main()
