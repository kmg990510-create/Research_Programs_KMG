"""Command line entry point for MoS2_adsorption_sim.

Examples:
Examples:
    python -m ads_core run --batch my_screening --molecules H2O TMA --surface pristine_4x4
    python -m ads_core export --batch-dir data/results/my_screening
    python -m ads_core benchmark --fast --backend synth_morse
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ads_core.benchmark import benchmark_report_table, run_benchmark_suite
from ads_core.config import load_config
from ads_core.pipeline import md_results_table, poses_frame, run_batch, status_counts
from ads_core.report.export import export_run, load_batch_run
from ads_core.review import load_review

REVIEW_FILE = "review.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ads_core", description="MoS2 surface-molecule adsorption screening (uMLIP + DFT-D3).")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run a new adsorption simulation batch and export results.")
    run_p.add_argument("--batch", required=True, help="Batch name (outputs to data/results/<batch> unless --output-dir is set)")
    run_p.add_argument("--surfaces", "--surface", nargs="+", dest="surfaces", default=None, help="Surface specs e.g. pristine_4x4 V_S_4x4")
    run_p.add_argument("--molecules", "--molecule", nargs="+", dest="molecules", default=None, help="Preset names or .xyz paths")
    run_p.add_argument("--supercell", nargs=2, type=int, metavar=("NX", "NY"), default=None, help="Default supercell dimensions")
    run_p.add_argument("--backend", choices=["mace_mp", "mattersim", "synth_morse"], default=None, help="Calculator backend")
    run_p.add_argument("--no-d3", action="store_true", help="Disable DFT-D3 dispersion correction")
    run_p.add_argument("--device", default=None, help="Compute device (auto, cpu, cuda)")
    run_p.add_argument("--sites", nargs="+", default=None, help="Restrict adsorption site types")
    run_p.add_argument("--orientations", nargs="+", default=None, help="Restrict initial orientations")
    run_p.add_argument("--scan-binding-curves", action="store_true", help="Also scan 1D E(z) binding curves")
    run_p.add_argument("--scan-all-sites", action="store_true", help="Scan one 1D E(z) curve per selected site type")
    run_p.add_argument("--compare-no-d3", action="store_true", help="Also run a baseline pass without DFT-D3")
    run_p.add_argument("--md", action="store_true", help="Also run finite-temperature Langevin MD per pose")
    run_p.add_argument("--md-temp", type=float, default=None, help="MD target temperature in K")
    run_p.add_argument("--md-steps", type=int, default=None, help="MD total integration steps")
    run_p.add_argument("--md-dt", type=float, default=None, help="MD timestep in fs")
    run_p.add_argument("--md-seed", type=int, default=None, help="MD random seed")
    run_p.add_argument("--output-dir", type=Path, default=None, help="Explicit output directory")
    run_p.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    run_p.add_argument("--quiet", action="store_true", help="Only print warnings and summary")

    md_p = sub.add_parser("md", help="Run finite-temperature Langevin MD directly without BFGS relaxation.")
    md_p.add_argument("--batch", required=True, help="Batch name (outputs to data/results/<batch> unless --output-dir is set)")
    md_p.add_argument("--surfaces", "--surface", nargs="+", dest="surfaces", default=None, help="Surface specs e.g. pristine_4x4 V_S_4x4")
    md_p.add_argument("--molecules", "--molecule", nargs="+", dest="molecules", default=None, help="Preset names or .xyz paths")
    md_p.add_argument("--supercell", nargs=2, type=int, metavar=("NX", "NY"), default=None, help="Default supercell dimensions")
    md_p.add_argument("--backend", choices=["mace_mp", "mattersim", "synth_morse"], default=None, help="Calculator backend")
    md_p.add_argument("--no-d3", action="store_true", help="Disable DFT-D3 dispersion correction")
    md_p.add_argument("--device", default=None, help="Compute device (auto, cpu, cuda)")
    md_p.add_argument("--sites", nargs="+", default=None, help="Restrict adsorption site types")
    md_p.add_argument("--orientations", nargs="+", default=None, help="Restrict initial orientations")
    md_p.add_argument("--temp", type=float, default=None, help="MD target temperature in K")
    md_p.add_argument("--steps", type=int, default=None, help="MD total integration steps")
    md_p.add_argument("--dt", type=float, default=None, help="MD timestep in fs")
    md_p.add_argument("--seed", type=int, default=None, help="MD random seed")
    md_p.add_argument("--output-dir", type=Path, default=None, help="Explicit output directory")
    md_p.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    md_p.add_argument("--quiet", action="store_true", help="Only print warnings and summary")

    exp_p = sub.add_parser("export", help="Re-export CSVs and metadata from an existing batch folder with review.json.")
    exp_p.add_argument("--batch-dir", required=True, type=Path, help="Existing batch results directory containing batch_state.json")
    exp_p.add_argument("--review", type=Path, default=None, help="Optional review.json override")
    exp_p.add_argument("--quiet", action="store_true", help="Only print summary")

    bench_p = sub.add_parser(
        "benchmark",
        help="Run physical adsorption benchmark suite (H2O, NH3, TMA on pristine vs V_S).",
    )
    bench_p.add_argument("--backend", choices=["mace_mp", "mattersim", "synth_morse"], default="synth_morse", help="Calculator backend")
    bench_p.add_argument("--fast", action="store_true", help="Use a 2x2 supercell instead of the configured default")
    bench_p.add_argument("--out-csv", type=Path, default=None, help="Optional path to save benchmark summary CSV")
    bench_p.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    bench_p.add_argument("--quiet", action="store_true", help="Only print summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "run":
        config = load_config(args.config)
        output_dir = args.output_dir or (Path(__file__).resolve().parents[1] / "data" / "results" / args.batch)
        review = load_review(output_dir / REVIEW_FILE)
        supercell = (args.supercell[0], args.supercell[1]) if args.supercell else None

        run = run_batch(
            args.batch,
            config,
            surfaces=args.surfaces,
            molecules=args.molecules,
            supercell=supercell,
            backend=args.backend,
            d3_enabled=False if args.no_d3 else None,
            device=args.device,
            site_types=args.sites,
            orientations=args.orientations,
            scan_binding_curves=args.scan_binding_curves,
            scan_all_sites=args.scan_all_sites,
            compare_no_d3=args.compare_no_d3,
            run_md=True if args.md else None,
            md_temperature_K=args.md_temp,
            md_steps=args.md_steps,
            md_timestep_fs=args.md_dt,
            md_seed=args.md_seed,
        )
        files = export_run(run, review, output_dir)
        frame = poses_frame(run, review)
        print(f"Batch: {run.name}  calculator: {run.calculator_id}")
        print(f"Poses: {len(frame)}  status: {status_counts(frame)}")
        if run.md_results:
            adsorbed_count = sum(1 for m in run.md_results if m.stayed_adsorbed)
            print(f"MD runs: {len(run.md_results)}  stayed_adsorbed: {adsorbed_count}/{len(run.md_results)}")
        print(f"Wrote {len(files)} file(s) to {output_dir}")
        return 0 if (not frame.empty or run.md_results) else 1

    if args.command == "md":
        config = load_config(args.config)
        output_dir = args.output_dir or (Path(__file__).resolve().parents[1] / "data" / "results" / args.batch)
        review = load_review(output_dir / REVIEW_FILE)
        supercell = (args.supercell[0], args.supercell[1]) if args.supercell else None

        run = run_batch(
            args.batch,
            config,
            surfaces=args.surfaces,
            molecules=args.molecules,
            supercell=supercell,
            backend=args.backend,
            d3_enabled=False if args.no_d3 else None,
            device=args.device,
            site_types=args.sites,
            orientations=args.orientations,
            run_md=True,
            md_temperature_K=args.temp,
            md_steps=args.steps,
            md_timestep_fs=args.dt,
            md_seed=args.seed,
            skip_relax=True,
        )
        files = export_run(run, review, output_dir)
        md_df = md_results_table(run.md_results)
        adsorbed_count = int(md_df["stayed_adsorbed"].sum()) if not md_df.empty else 0
        print(f"MD Batch: {run.name}  calculator: {run.calculator_id}")
        print(f"MD runs: {len(md_df)}  stayed_adsorbed: {adsorbed_count}/{len(md_df)}")
        if not args.quiet:
            for m in run.md_results:
                dz_str = f"{m.final_dz_com_A:.2f} A" if m.final_dz_com_A is not None else "None"
                res_str = f"{m.residence_fraction:.2f}" if m.residence_fraction is not None else "None"
                print(f"  {m.pose_id}: stayed={m.stayed_adsorbed} residence={res_str} final_dz={dz_str}")
        print(f"Wrote {len(files)} file(s) to {output_dir}")
        return 0 if not md_df.empty else 1

    if args.command == "export":
        batch_dir: Path = args.batch_dir
        if not batch_dir.is_dir():
            print(f"Batch folder not found: {batch_dir}", file=sys.stderr)
            return 2
        run = load_batch_run(batch_dir)
        review = load_review(args.review or batch_dir / REVIEW_FILE)
        files = export_run(run, review, batch_dir)
        frame = poses_frame(run, review)
        print(f"Re-exported {len(files)} file(s) for {run.name} ({len(frame)} poses) to {batch_dir}")
        return 0

    if args.command == "benchmark":
        config = load_config(args.config)
        report = run_benchmark_suite(config, backend=args.backend, repeat_2x2=args.fast)
        table = benchmark_report_table(report)
        if args.out_csv is not None:
            args.out_csv.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(args.out_csv, index=False, encoding="utf-8-sig")
        print(f"Benchmark: backend={report.calculator_id} supercell={report.supercell} all_passed={report.all_passed}")
        if not args.quiet:
            for c in report.cases:
                e_str = f"{c.e_ads_eV:+.3f} eV" if c.e_ads_eV is not None else "None"
                print(f"  {c.case_id:14s} [{c.best_site:7s}] E_ads={e_str} vdw={c.vdw_fraction} passed={c.passed} ({c.notes})")
        return 0 if report.all_passed else 1

    return 2
