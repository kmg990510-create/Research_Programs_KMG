"""Compare lmfit and least_squares Raman n-peak candidates.

This is a TASK-021 guardrail utility. It does not change production pipeline
behavior; it runs both solvers side by side and writes candidate-level parity
and timing data.
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from typing import Any

import numpy as np

from fitting.mos2_core.core.default_stages import build_default_context
from fitting.mos2_core.core.runtime_paths import runtime_project_root
from fitting.mos2_core.core.types import FitCandidate
from fitting.mos2_core.baseline.basic import ZeroBaselineEnsemble
from fitting.mos2_core.fitting import LmfitRamanModelEnsembleFitting
from fitting.mos2_core.fitting.least_squares_hotpath import fit_raman_n_peak_least_squares
from fitting.mos2_core.fitting.raman_lmfit import _finite
from fitting.mos2_core.io import load_pipeline_config, load_raman_txt_directory
from fitting.mos2_core.preprocess.basic import IdentityPreprocessing


N_PEAK_MODELS = ("peak_2_model", "peak_3_model", "peak_4_model", "peak_5_model")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare lmfit vs scipy least_squares Raman hot path.")
    parser.add_argument("--raw-dir", type=Path, required=True, help="Directory containing raw Raman TXT files")
    parser.add_argument("--pattern", type=str, default="*.txt", help="Glob pattern for spectra")
    parser.add_argument("--max-files", type=int, default=5, help="Limit spectra for quick guardrail runs")
    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        choices=N_PEAK_MODELS,
        help="Subset of n-peak models to compare. Defaults to configured n-peak models.",
    )
    parser.add_argument("--max-nfev", type=int, default=2000, help="least_squares max_nfev per candidate")
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("data/results/raman/reports/task021_lsq_guardrail.csv"),
        help="CSV artifact path for candidate-level comparison rows",
    )
    return parser


def _resolve_raw_dir(raw_dir: Path, project_root: Path) -> Path:
    if raw_dir.is_absolute():
        return raw_dir
    cwd_candidate = (Path.cwd() / raw_dir).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return (project_root / raw_dir).resolve()


def _metric(candidate: FitCandidate | None, key: str) -> float:
    if candidate is None:
        return float("nan")
    return _finite(candidate.metrics.get(key), default=float("nan"))


def _param(candidate: FitCandidate | None, key: str) -> float:
    if candidate is None:
        return float("nan")
    return _finite(candidate.params.get(key), default=float("nan"))


def _fit_legacy_candidate(
    *,
    fitter: LmfitRamanModelEnsembleFitting,
    model_name: str,
    x_full: np.ndarray,
    y_corr: np.ndarray,
    cfg: Any,
    anchor_centers: dict[str, float] | None,
) -> tuple[FitCandidate, float]:
    t0 = time.perf_counter()
    candidate = fitter._fit_candidate(  # noqa: SLF001
        model_name=model_name,
        x_full=x_full,
        y_corr=y_corr,
        cfg=cfg,
        anchor_centers=anchor_centers,
        modality="raman",
    )
    fitter._recompute_metrics_on_window(  # noqa: SLF001
        candidate,
        x_full=x_full,
        y_true=y_corr,
        x_min=cfg.compare_x_min,
        x_max=cfg.compare_x_max,
    )
    return candidate, time.perf_counter() - t0


def _fit_lsq_candidate(
    *,
    fitter: LmfitRamanModelEnsembleFitting,
    model_name: str,
    x_full: np.ndarray,
    y_corr: np.ndarray,
    cfg: Any,
    anchor_centers: dict[str, float] | None,
    max_nfev: int,
) -> tuple[FitCandidate, float]:
    t0 = time.perf_counter()
    candidate = fit_raman_n_peak_least_squares(
        model_name=model_name,
        x_full=x_full,
        y_corr=y_corr,
        cfg=cfg,
        anchor_centers=anchor_centers,
        max_nfev=max_nfev,
    )
    fitter._recompute_metrics_on_window(  # noqa: SLF001
        candidate,
        x_full=x_full,
        y_true=y_corr,
        x_min=cfg.compare_x_min,
        x_max=cfg.compare_x_max,
    )
    return candidate, time.perf_counter() - t0


def _anchor_centers(candidate: FitCandidate | None) -> dict[str, float] | None:
    if candidate is None:
        return None
    e2g = _param(candidate, "e2g_position")
    a1g = _param(candidate, "a1g_position")
    if not (np.isfinite(e2g) and np.isfinite(a1g)):
        return None
    return {"e2g": float(e2g), "a1g": float(a1g)}


def _selected_by_aic(candidates: dict[str, FitCandidate]) -> str:
    if not candidates:
        return ""
    return min(candidates.items(), key=lambda item: _metric(item[1], "aic"))[0]


def _compare_rows_for_spectrum(
    *,
    spectrum_id: str,
    x_full: np.ndarray,
    y_corr: np.ndarray,
    models: list[str],
    fitter: LmfitRamanModelEnsembleFitting,
    cfg: Any,
    max_nfev: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    legacy_candidates: dict[str, FitCandidate] = {}
    lsq_candidates: dict[str, FitCandidate] = {}
    legacy_times: dict[str, float] = {}
    lsq_times: dict[str, float] = {}
    failures: list[str] = []

    needs_anchor = bool(cfg.two_stage_anchor_enabled and any(model != "peak_2_model" for model in models))
    legacy_anchor: FitCandidate | None = None
    lsq_anchor: FitCandidate | None = None
    legacy_anchor_time = 0.0
    lsq_anchor_time = 0.0
    if needs_anchor:
        try:
            legacy_anchor, legacy_anchor_time = _fit_legacy_candidate(
                fitter=fitter,
                model_name="peak_2_model",
                x_full=x_full,
                y_corr=y_corr,
                cfg=cfg,
                anchor_centers=None,
            )
        except Exception as exc:
            failures.append(f"legacy_anchor:{exc}")
        try:
            lsq_anchor, lsq_anchor_time = _fit_lsq_candidate(
                fitter=fitter,
                model_name="peak_2_model",
                x_full=x_full,
                y_corr=y_corr,
                cfg=cfg,
                anchor_centers=None,
                max_nfev=max_nfev,
            )
        except Exception as exc:
            failures.append(f"lsq_anchor:{exc}")

    legacy_anchor_centers = _anchor_centers(legacy_anchor)
    lsq_anchor_centers = _anchor_centers(lsq_anchor)

    for model_name in models:
        try:
            if model_name == "peak_2_model" and legacy_anchor is not None:
                legacy_candidates[model_name] = legacy_anchor
                legacy_times[model_name] = legacy_anchor_time
            else:
                candidate, elapsed = _fit_legacy_candidate(
                    fitter=fitter,
                    model_name=model_name,
                    x_full=x_full,
                    y_corr=y_corr,
                    cfg=cfg,
                    anchor_centers=legacy_anchor_centers if model_name != "peak_2_model" else None,
                )
                legacy_candidates[model_name] = candidate
                legacy_times[model_name] = elapsed
        except Exception as exc:
            failures.append(f"legacy_{model_name}:{exc}")

        try:
            if model_name == "peak_2_model" and lsq_anchor is not None:
                lsq_candidates[model_name] = lsq_anchor
                lsq_times[model_name] = lsq_anchor_time
            else:
                candidate, elapsed = _fit_lsq_candidate(
                    fitter=fitter,
                    model_name=model_name,
                    x_full=x_full,
                    y_corr=y_corr,
                    cfg=cfg,
                    anchor_centers=lsq_anchor_centers if model_name != "peak_2_model" else None,
                    max_nfev=max_nfev,
                )
                lsq_candidates[model_name] = candidate
                lsq_times[model_name] = elapsed
        except Exception as exc:
            failures.append(f"lsq_{model_name}:{exc}")

    legacy_selected = _selected_by_aic(legacy_candidates)
    lsq_selected = _selected_by_aic(lsq_candidates)
    rows: list[dict[str, Any]] = []
    for model_name in models:
        legacy = legacy_candidates.get(model_name)
        lsq = lsq_candidates.get(model_name)
        legacy_ms = 1000.0 * legacy_times.get(model_name, float("nan"))
        lsq_ms = 1000.0 * lsq_times.get(model_name, float("nan"))
        rows.append(
            {
                "spectrum_id": spectrum_id,
                "model_name": model_name,
                "legacy_ok": legacy is not None,
                "least_squares_ok": lsq is not None,
                "legacy_time_ms": legacy_ms,
                "least_squares_time_ms": lsq_ms,
                "speedup": legacy_ms / lsq_ms if np.isfinite(legacy_ms) and np.isfinite(lsq_ms) and lsq_ms > 0 else "",
                "legacy_rmse": _metric(legacy, "rmse"),
                "least_squares_rmse": _metric(lsq, "rmse"),
                "rmse_delta": _metric(lsq, "rmse") - _metric(legacy, "rmse"),
                "legacy_aic": _metric(legacy, "aic"),
                "least_squares_aic": _metric(lsq, "aic"),
                "aic_delta": _metric(lsq, "aic") - _metric(legacy, "aic"),
                "legacy_bic": _metric(legacy, "bic"),
                "least_squares_bic": _metric(lsq, "bic"),
                "bic_delta": _metric(lsq, "bic") - _metric(legacy, "bic"),
                "legacy_nfev": _metric(legacy, "nfev"),
                "least_squares_nfev": _metric(lsq, "nfev"),
                "legacy_e2g": _param(legacy, "e2g_position"),
                "least_squares_e2g": _param(lsq, "e2g_position"),
                "e2g_delta": _param(lsq, "e2g_position") - _param(legacy, "e2g_position"),
                "legacy_a1g": _param(legacy, "a1g_position"),
                "least_squares_a1g": _param(lsq, "a1g_position"),
                "a1g_delta": _param(lsq, "a1g_position") - _param(legacy, "a1g_position"),
                "legacy_selected_by_aic": legacy_selected,
                "least_squares_selected_by_aic": lsq_selected,
                "selected_agree": legacy_selected == lsq_selected,
                "failures": ";".join(failures),
            }
        )

    summary = {
        "legacy_selected": legacy_selected,
        "least_squares_selected": lsq_selected,
        "selected_agree": legacy_selected == lsq_selected,
        "failures": failures,
    }
    return rows, summary


def main() -> None:
    args = _build_arg_parser().parse_args()
    project_root = runtime_project_root(__file__, 2)
    config_dir = Path(__file__).resolve().parent / "config"
    config = load_pipeline_config(config_dir)
    raw_dir = _resolve_raw_dir(args.raw_dir, project_root)
    raw_spectra = load_raman_txt_directory(raw_dir, pattern=args.pattern)
    if args.max_files > 0:
        raw_spectra = raw_spectra[: args.max_files]
    if not raw_spectra:
        raise FileNotFoundError(f"No spectra found: raw_dir={raw_dir} pattern={args.pattern}")

    context = build_default_context(
        run_id="task021_lsq_guardrail",
        artifact_dir=project_root,
        config=config,
    )
    preprocessed = IdentityPreprocessing().run(raw_spectra, context)
    baselines = ZeroBaselineEnsemble().run(preprocessed, context)
    fitter = LmfitRamanModelEnsembleFitting(enable_pl=True)
    cfg = fitter._resolve_fit_config(context, modality="raman")  # noqa: SLF001
    models = [model for model in (args.models or cfg.models) if model in N_PEAK_MODELS]
    if not models:
        raise ValueError("No Raman n-peak models selected for comparison.")

    all_rows: list[dict[str, Any]] = []
    spectrum_summaries: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for index, spectrum in enumerate(preprocessed, start=1):
        x_full = np.asarray(spectrum.x, dtype=float)
        y_full = np.asarray(spectrum.y, dtype=float)
        baseline = np.asarray(baselines[spectrum.spectrum_id].selected.baseline_y, dtype=float)
        y_corr = y_full - baseline
        rows, summary = _compare_rows_for_spectrum(
            spectrum_id=spectrum.spectrum_id,
            x_full=x_full,
            y_corr=y_corr,
            models=models,
            fitter=fitter,
            cfg=cfg,
            max_nfev=int(args.max_nfev),
        )
        all_rows.extend(rows)
        spectrum_summaries.append({"spectrum_id": spectrum.spectrum_id, **summary})
        print(
            f"[guardrail] {index}/{len(preprocessed)} {spectrum.spectrum_id} "
            f"legacy={summary['legacy_selected']} lsq={summary['least_squares_selected']} "
            f"agree={summary['selected_agree']}",
            flush=True,
        )

    output_csv = args.output_csv if args.output_csv.is_absolute() else (project_root / args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(all_rows[0].keys()) if all_rows else []
    with output_csv.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    valid_speedups = [
        float(row["speedup"])
        for row in all_rows
        if str(row.get("speedup", "")).strip()
    ]
    rmse_abs = [
        abs(float(row["rmse_delta"]))
        for row in all_rows
        if np.isfinite(float(row["rmse_delta"]))
    ]
    selected_agree_count = sum(1 for item in spectrum_summaries if bool(item["selected_agree"]))
    elapsed = time.perf_counter() - t0

    print("")
    print("TASK-021 least_squares guardrail completed.", flush=True)
    print(f"Spectra compared: {len(preprocessed)}", flush=True)
    print(f"Candidate rows: {len(all_rows)}", flush=True)
    print(f"Selected-model agreement: {selected_agree_count}/{len(spectrum_summaries)}", flush=True)
    if valid_speedups:
        print(f"Mean candidate speedup (legacy_ms / lsq_ms): {float(np.mean(valid_speedups)):.3f}x", flush=True)
        print(f"Median candidate speedup: {float(np.median(valid_speedups)):.3f}x", flush=True)
    if rmse_abs:
        print(f"Mean absolute RMSE delta: {float(np.mean(rmse_abs)):.6g}", flush=True)
        print(f"Max absolute RMSE delta: {float(np.max(rmse_abs)):.6g}", flush=True)
    print(f"Elapsed wall time: {elapsed:.2f}s", flush=True)
    print(f"Output CSV: {output_csv}", flush=True)


if __name__ == "__main__":
    main()
