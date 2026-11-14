"""Command line: analyse one batch folder and write the result files.

    python -m fet_core --input-dir data/raw/my_batch --output-dir data/results/my_batch
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from fet_core.config import load_config
from fet_core.pipeline import results_frame, run_folder, status_counts
from fet_core.report.export import export_run
from fet_core.review import load_review

REVIEW_FILE = "review.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fet_core", description="Analyse FET transfer measurements in a folder.")
    parser.add_argument("--input-dir", required=True, type=Path, help="folder with the instrument files of one batch")
    parser.add_argument("--output-dir", type=Path, help="results folder (default: data/results/<batch name>)")
    parser.add_argument("--config", type=Path, help="config file (default: FET_analysis/config.yaml)")
    parser.add_argument("--review", type=Path, help="review.json to apply (default: <output-dir>/review.json when present)")
    parser.add_argument("--quiet", action="store_true", help="only print warnings and the final summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not args.input_dir.is_dir():
        print(f"Input folder not found: {args.input_dir}", file=sys.stderr)
        return 2
    config = load_config(args.config)
    output_dir = args.output_dir or Path(__file__).resolve().parents[1] / "data" / "results" / args.input_dir.name
    review = load_review(args.review or output_dir / REVIEW_FILE)
    run = run_folder(args.input_dir, config, review)
    files = export_run(run, review, output_dir)
    frame = results_frame(run, review)
    read = sum(1 for item in run.loaded.files if item.status == "read")
    print(f"Files read: {read} of {len(run.loaded.files)}")
    print(f"Measurements: {len(run.loaded.measurements)}  sweeps: {len(frame)}  status: {status_counts(frame)}")
    print(f"Wrote {len(files)} file(s) to {output_dir}")
    return 0 if run.loaded.measurements else 1


if __name__ == "__main__":
    raise SystemExit(main())
