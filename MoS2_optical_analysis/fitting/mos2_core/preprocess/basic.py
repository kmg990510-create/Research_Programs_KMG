"""Default preprocessing stage implementations."""

from __future__ import annotations

import warnings
import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.signal import medfilt
from typing import Sequence

from ..core.interfaces import PreprocessingStage
from ..core.types import PipelineContext, PreprocessedSpectrum, SpectrumRecord
from ..io import config_access as cfgx


def lorentzian(x: np.ndarray, amp: float, cen: float, wid: float) -> np.ndarray:
    return amp * (wid**2 / ((x - cen) ** 2 + wid**2))


def estimate_si_window_area(
    x: Sequence[float],
    y: Sequence[float],
    window_min: float,
    window_max: float,
    min_points: int,
) -> float:
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    mask = (x_arr >= window_min) & (x_arr <= window_max)
    if int(np.sum(mask)) < int(min_points):
        return 0.0

    x_fit = x_arr[mask]
    y_fit = y_arr[mask]
    if x_fit.size < 2:
        return 0.0

    # Use a local linear baseline in Si window and integrate only positive component.
    x0, x1 = float(x_fit[0]), float(x_fit[-1])
    if not np.isfinite(x0) or not np.isfinite(x1) or abs(x1 - x0) < 1.0e-12:
        return 0.0
    y0, y1 = float(y_fit[0]), float(y_fit[-1])
    slope = (y1 - y0) / (x1 - x0)
    intercept = y0 - slope * x0
    baseline = slope * x_fit + intercept
    signal = np.clip(y_fit - baseline, 0.0, None)
    area = float(np.trapezoid(signal, x_fit))
    return max(area, 0.0)


def get_si_calibration_offset(
    x: Sequence[float],
    y: Sequence[float],
    window_min: float,
    window_max: float,
    target_peak: float,
    min_points: int,
    initial_width: float,
    max_abs_offset: float,
    width_min: float,
    min_initial_width: float,
) -> tuple[float, bool]:
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)

    mask = (x_arr >= window_min) & (x_arr <= window_max)
    if int(np.sum(mask)) < int(min_points):
        return 0.0, False

    x_fit = x_arr[mask]
    y_fit = y_arr[mask]
    y_min = float(np.min(y_fit))
    y_max = float(np.max(y_fit))
    p0 = [0.0, y_min, max(y_max - y_min, 1.0), target_peak, max(initial_width, min_initial_width)]

    def _offset_from_center(center: float) -> tuple[float, bool]:
        if not np.isfinite(center):
            return 0.0, False
        offset = float(target_peak - center)
        if abs(offset) > float(max_abs_offset):
            return 0.0, False
        return offset, True

    lower_bounds = [-np.inf, -np.inf, 0.0, float(window_min), float(width_min)]
    upper_bounds = [np.inf, np.inf, np.inf, float(window_max), float(max(window_max - window_min, min_initial_width))]
    try:
        with warnings.catch_warnings():
            # Some spectra fit numerically but covariance is unstable; treat this as non-reliable fit.
            warnings.simplefilter("error", OptimizeWarning)
            popt, _ = curve_fit(
                lambda xx, a, b, amp, cen, wid: a * xx + b + lorentzian(xx, amp, cen, wid),
                x_fit,
                y_fit,
                p0=p0,
                bounds=(lower_bounds, upper_bounds),
                maxfev=20000,
            )
        return _offset_from_center(float(popt[3]))
    except Exception:
        # Fallback: use local maximum in Si window when Lorentz fit is unstable.
        peak_idx = int(np.argmax(y_fit))
        return _offset_from_center(float(x_fit[peak_idx]))


def despike_1d_spectrum(
    y: Sequence[float],
    kernel: int,
    threshold: float,
) -> tuple[list[float], int]:
    """Detect and replace sharp single-point/two-point positive spikes using rolling MAD."""
    y_arr = np.asarray(y, dtype=float)
    if y_arr.size < 5:
        return [float(v) for v in y_arr], 0
    k = max(3, int(kernel))
    if k % 2 == 0:
        k += 1
    if k > y_arr.size:
        k = y_arr.size if y_arr.size % 2 == 1 else y_arr.size - 1
    if k < 3:
        return [float(v) for v in y_arr], 0

    med = medfilt(y_arr, k)
    diff = y_arr - med
    mad = float(np.median(np.abs(diff - np.median(diff))))
    if mad < 1.0e-6:
        mad = float(np.std(diff))
    spike_mask = diff > float(threshold) * max(mad, 1.0e-6)
    n_spikes = int(np.sum(spike_mask))
    if n_spikes > 0:
        y_clean = y_arr.copy()
        y_clean[spike_mask] = med[spike_mask]
        return [float(v) for v in y_clean], n_spikes
    return [float(v) for v in y_arr], 0


class IdentityPreprocessing(PreprocessingStage):
    """Pass-through preprocessing with float casting, calibration, and PL despiking."""

    def run(
        self,
        spectra: Sequence[SpectrumRecord],
        context: PipelineContext,
    ) -> list[PreprocessedSpectrum]:
        modalities = {str(s.modality).lower() for s in spectra}

        # Only the sections for the modalities present are required.
        calibration_enabled = False
        if "raman" in modalities:
            cal_path = "raman.si_calibration"
            cal_cfg = cfgx.section(cfgx.section(context.config, "raman", ""), "si_calibration", "raman")
            calibration_enabled = cfgx.flag(cal_cfg, "enabled", cal_path)
            window_min = cfgx.number(cal_cfg, "window_min", cal_path)
            window_max = cfgx.number(cal_cfg, "window_max", cal_path)
            target_peak = cfgx.number(cal_cfg, "target_peak", cal_path)
            min_points = cfgx.integer(cal_cfg, "min_points", cal_path)
            initial_width = cfgx.number(cal_cfg, "initial_width", cal_path)
            max_abs_offset = cfgx.number(cal_cfg, "max_abs_offset", cal_path)
            width_min = cfgx.number(cal_cfg, "width_min", cal_path)
            min_initial_width = cfgx.number(cal_cfg, "min_initial_width", cal_path)
        else:
            target_peak = float("nan")

        despike_enabled = False
        if "pl" in modalities or any(str(s.metadata.get("modality", "")).lower() == "pl" for s in spectra):
            despike_cfg = cfgx.section(cfgx.section(context.config, "pl", ""), "despike", "pl")
            despike_enabled = cfgx.flag(despike_cfg, "enabled", "pl.despike")
            despike_kernel = cfgx.integer(despike_cfg, "kernel", "pl.despike")
            despike_threshold = cfgx.number(despike_cfg, "threshold", "pl.despike")

        offsets: list[float] = []
        success_count = 0
        despiked_spectra_count = 0

        def _metadata(
            record: SpectrumRecord,
            offset: float,
            success: bool,
            si_area: float,
            n_spikes: int,
        ) -> dict[str, object]:
            meta = dict(record.metadata)
            meta.setdefault("modality", record.modality)
            meta["calibration_offset"] = float(offset)
            meta["calibration_success"] = bool(success)
            if str(record.modality).lower() == "raman":
                meta["si_target_peak"] = float(target_peak)
            meta["si_area"] = float(si_area)
            if n_spikes > 0:
                meta["despiked_points"] = int(n_spikes)
            return meta

        output: list[PreprocessedSpectrum] = []
        for s in spectra:
            x = [float(v) for v in s.x]
            y = [float(v) for v in s.y]

            is_pl = str(s.modality).lower() == "pl" or str(s.metadata.get("modality", "")).lower() == "pl"
            n_spikes = 0
            if is_pl and despike_enabled:
                y, n_spikes = despike_1d_spectrum(y, kernel=despike_kernel, threshold=despike_threshold)
                if n_spikes > 0:
                    despiked_spectra_count += 1

            offset = 0.0
            success = False
            si_area = 0.0
            if str(s.modality).lower() == "raman":
                si_area = estimate_si_window_area(
                    x,
                    y,
                    window_min=window_min,
                    window_max=window_max,
                    min_points=min_points,
                )
            if calibration_enabled and str(s.modality).lower() == "raman":
                offset, success = get_si_calibration_offset(
                    x,
                    y,
                    window_min=window_min,
                    window_max=window_max,
                    target_peak=target_peak,
                    min_points=min_points,
                    initial_width=initial_width,
                    max_abs_offset=max_abs_offset,
                    width_min=width_min,
                    min_initial_width=min_initial_width,
                )

            x_shifted = [v + offset for v in x]
            offsets.append(float(offset))
            if success:
                success_count += 1

            output.append(
                PreprocessedSpectrum(
                    spectrum_id=s.spectrum_id,
                    x=x_shifted,
                    y=y,
                    metadata=_metadata(s, offset=offset, success=success, si_area=si_area, n_spikes=n_spikes),
                )
            )
        
        context.state["preprocessed_count"] = len(output)
        context.state["si_calibration_enabled"] = calibration_enabled
        context.state["si_calibration_success_count"] = success_count
        context.state["si_calibration_mean_offset"] = float(np.mean(offsets)) if offsets else 0.0
        context.state["pl_despiked_spectra_count"] = despiked_spectra_count
        return output
