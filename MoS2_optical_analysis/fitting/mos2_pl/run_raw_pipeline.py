"""PL raw TXT run entrypoint under fitting layout."""

from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path
from typing import NamedTuple

from fitting.mos2_core.core.default_stages import build_default_context, build_default_stages
from fitting.mos2_core.core.pipeline import run_pipeline
from fitting.mos2_core.core.types import SpectrumRecord
from fitting.mos2_core.core.runtime_paths import runtime_project_root
from fitting.mos2_core.io import config_access as cfgx
from fitting.mos2_core.io import load_pipeline_config, load_raman_txt_directory


NM_TO_EV = 1239.8419843320026


class RunSummary(NamedTuple):
    raw_dir: Path
    run_id: str
    input_total: int
    accepted_total: int
    flagged_total: int
    report_json_path: str | None
    report_csv_path: str | None


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run PL pipeline on raw spectra.")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/pl"), help="Directory containing raw spectra")
    parser.add_argument("--pattern", type=str, default="*.asc", help="Glob pattern for spectra files")
    parser.add_argument("--run-id", type=str, default="pl_raw_e2e", help="Run identifier used for report filename")
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
        "--workers",
        type=int,
        default=1,
        help="Number of spectrum-level fit worker processes (1 = sequential).",
    )
    parser.add_argument(
        "--peak-n-mode",
        type=str,
        default="auto",
        choices=["auto", "pl_single_pvoigt", "pl_a_doublet_pvoigt", "pl_5_component_pvoigt"],
        help="Override PL model ensemble list. 'auto' keeps config defaults.",
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


def _infer_temperature_k(source_file: object) -> int | None:
    name = Path(str(source_file or "")).name
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*K(?![A-Za-z])", name, flags=re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    return int(value) if value.is_integer() else int(round(value))


def _infer_treatment_label(metadata: dict[str, object]) -> str:
    source = str(metadata.get("source_file", ""))
    dataset = str(metadata.get("dataset", ""))
    haystack = f"{dataset} {source}".lower()
    if "pristine" in haystack:
        return "Pristine"
    if "treatment" in haystack:
        return "Treatment"
    if "4atp" in haystack or "atp" in haystack:
        return "4ATP"
    return dataset.strip() or "unknown"


def _convert_nm_to_ev_if_needed(
    spectrum: SpectrumRecord,
    *,
    intensity_density_correction: bool = False,
) -> tuple[list[float], list[float], dict[str, object]]:
    x_values = [float(v) for v in spectrum.x]
    y_values = [float(v) for v in spectrum.y]
    metadata = dict(spectrum.metadata)
    header = metadata.get("header", {})
    x_unit = ""
    if isinstance(header, dict):
        x_unit = str(header.get("X_UNIT", "")).strip().lower()

    looks_like_nm = bool(x_values) and max(x_values) > 100.0
    if x_unit == "nm" or looks_like_nm:
        converted = [NM_TO_EV / value for value in x_values if value > 0.0]
        if len(converted) != len(x_values):
            raise ValueError(f"Cannot convert non-positive wavelength values to eV: {spectrum.spectrum_id}")
        if intensity_density_correction:
            y_values = [
                intensity * (NM_TO_EV / (energy_ev * energy_ev))
                for intensity, energy_ev in zip(y_values, converted)
            ]
        paired = sorted(zip(converted, y_values), key=lambda item: item[0])
        x_ev = [x for x, _ in paired]
        y_sorted = [y for _, y in paired]
        metadata["original_x_unit"] = x_unit or "nm"
        metadata["x_unit"] = "eV"
        metadata["x_conversion"] = "eV = 1239.8419843320026 / nm"
        metadata["intensity_density_correction"] = bool(intensity_density_correction)
        if intensity_density_correction:
            metadata["intensity_conversion"] = "I_eV = I_nm * abs(d_nm/d_eV)"
        if paired:
            metadata["original_x_min_nm"] = min(x_values)
            metadata["original_x_max_nm"] = max(x_values)
        return x_ev, y_sorted, metadata

    metadata["x_unit"] = x_unit or "eV"
    return x_values, y_values, metadata


def _pl_intensity_density_correction_enabled(config: dict) -> bool:
    correction_cfg = cfgx.section(cfgx.section(config, "pl", ""), "intensity_density_correction", "pl")
    return cfgx.flag(correction_cfg, "enabled", "pl.intensity_density_correction")


def _force_pl_modality(records: list[SpectrumRecord], *, intensity_density_correction: bool = False) -> list[SpectrumRecord]:
    patched: list[SpectrumRecord] = []
    for spectrum in records:
        x_values, y_values, metadata = _convert_nm_to_ev_if_needed(
            spectrum,
            intensity_density_correction=intensity_density_correction,
        )
        metadata["temperature_k"] = _infer_temperature_k(metadata.get("source_file"))
        metadata["treatment_label"] = _infer_treatment_label(metadata)
        patched.append(
            SpectrumRecord(
                spectrum_id=spectrum.spectrum_id,
                x=x_values,
                y=y_values,
                modality="pl",
                metadata={**metadata, "modality": "pl"},
            )
        )
    return patched


def _run_single(
    raw_dir: Path,
    run_id: str,
    pattern: str,
    project_root: Path,
    runtime_config: dict,
    progress_every: int,
    fit_workers: int,
) -> RunSummary:
    raw_spectra = load_raman_txt_directory(raw_dir, pattern=pattern)
    if not raw_spectra:
        raise FileNotFoundError(f"No spectra found. raw_dir={raw_dir} | pattern={pattern}")

    patched = _force_pl_modality(
        raw_spectra,
        intensity_density_correction=_pl_intensity_density_correction_enabled(runtime_config),
    )
    context = build_default_context(
        run_id=run_id,
        artifact_dir=project_root,
        config=runtime_config,
    )
    context.state["progress_enabled"] = True
    context.state["progress_every"] = max(int(progress_every), 1)
    context.state["fit_workers"] = max(int(fit_workers), 1)
    stages = build_default_stages(config=context.config)
    result = run_pipeline(raw_spectra=patched, stages=stages, context=context)

    return RunSummary(
        raw_dir=raw_dir,
        run_id=run_id,
        input_total=len(patched),
        accepted_total=len(result.accepted),
        flagged_total=len(result.flagged),
        report_json_path=str(result.reports[0].path) if result.reports else None,
        report_csv_path=str(result.reports[1].path) if len(result.reports) > 1 else None,
    )


def _print_run_summary(summary: RunSummary) -> None:
    print("PL raw pipeline run completed.", flush=True)
    print(f"Run ID: {summary.run_id}", flush=True)
    print(f"Resolved raw dir: {summary.raw_dir}", flush=True)
    print(f"Input files: {summary.input_total}", flush=True)
    print(f"Accepted results: {summary.accepted_total}", flush=True)
    print(f"Flagged queue size: {summary.flagged_total}", flush=True)
    if summary.report_json_path:
        print(f"Fit report (JSON): {summary.report_json_path}", flush=True)
    if summary.report_csv_path:
        print(f"Fit report (CSV): {summary.report_csv_path}", flush=True)


def _apply_runtime_overrides(
    base_config: dict,
    *,
    peak_n_mode: str,
    distance_outlier: str,
    delta_outlier: str,
    si_calibration: str,
) -> dict:
    config = copy.deepcopy(base_config)
    pl_cfg = config.get("pl")
    if not isinstance(pl_cfg, dict):
        return config

    if peak_n_mode != "auto":
        pl_cfg["models"] = [peak_n_mode]

    raman_cfg = config.get("raman")
    if not isinstance(raman_cfg, dict):
        config["pl"] = pl_cfg
        return config

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
    config["pl"] = pl_cfg
    return config


def main() -> None:
    args = _build_arg_parser().parse_args()
    project_root = runtime_project_root(__file__, 2)
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
                print("No direct TXT files in --raw-dir. Auto-switching to subdirectory batch mode.", flush=True)
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
            print("", flush=True)
            print(f"[Batch {index}/{total_targets}] run_id={run_id} | raw_dir={target_dir}", flush=True)
        summary = _run_single(
            raw_dir=target_dir,
            run_id=run_id,
            pattern=args.pattern,
            project_root=project_root,
            runtime_config=runtime_config,
            progress_every=args.progress_every,
            fit_workers=args.workers,
        )
        _print_run_summary(summary)
        summaries.append(summary)

    if len(summaries) > 1:
        total_input = sum(s.input_total for s in summaries)
        total_accepted = sum(s.accepted_total for s in summaries)
        total_flagged = sum(s.flagged_total for s in summaries)
        print("", flush=True)
        print("Batch run summary:", flush=True)
        print(f"Runs: {len(summaries)}", flush=True)
        print(f"Input files: {total_input}", flush=True)
        print(f"Accepted results: {total_accepted}", flush=True)
        print(f"Flagged queue size: {total_flagged}", flush=True)


if __name__ == "__main__":
    main()
