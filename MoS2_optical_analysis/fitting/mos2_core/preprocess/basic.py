"""Default preprocessing stage implementations."""

from __future__ import annotations

import warnings
import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit
from typing import Sequence

from ..core.interfaces import PreprocessingStage
from ..core.types import PipelineContext, PreprocessedSpectrum, SpectrumRecord


def lorentzian(x: np.ndarray, amp: float, cen: float, wid: float) -> np.ndarray:
    return amp * (wid**2 / ((x - cen) ** 2 + wid**2))


def get_si_calibration_offset(
    x: Sequence[float],
    y: Sequence[float],
    window_min: float = 510.0,
    window_max: float = 530.0,
    target_peak: float = 520.0,
    min_points: int = 5,
    initial_width: float = 3.0,
    max_abs_offset: float = 5.0,
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
    p0 = [0.0, y_min, max(y_max - y_min, 1.0), target_peak, max(initial_width, 0.3)]

    def _offset_from_center(center: float) -> tuple[float, bool]:
        if not np.isfinite(center):
            return 0.0, False
        offset = float(target_peak - center)
        if abs(offset) > float(max_abs_offset):
            return 0.0, False
        return offset, True

    lower_bounds = [-np.inf, -np.inf, 0.0, float(window_min), 0.1]
    upper_bounds = [np.inf, np.inf, np.inf, float(window_max), float(max(window_max - window_min, 0.3))]
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


class IdentityPreprocessing(PreprocessingStage):
    """Pass-through preprocessing with float casting."""

    def run(
        self,
        spectra: Sequence[SpectrumRecord],
        context: PipelineContext,
    ) -> list[PreprocessedSpectrum]:
        raman_cfg = context.config.get("raman", {}) if isinstance(context.config, dict) else {}
        if not isinstance(raman_cfg, dict):
            raman_cfg = {}
        cal_cfg = raman_cfg.get("si_calibration", {})
        if not isinstance(cal_cfg, dict):
            cal_cfg = {}

        calibration_enabled = bool(cal_cfg.get("enabled", True))
        window_min = float(cal_cfg.get("window_min", 510.0))
        window_max = float(cal_cfg.get("window_max", 530.0))
        target_peak = float(cal_cfg.get("target_peak", 520.0))
        min_points = int(cal_cfg.get("min_points", 5))
        initial_width = float(cal_cfg.get("initial_width", 3.0))
        max_abs_offset = float(cal_cfg.get("max_abs_offset", 5.0))

        offsets: list[float] = []
        success_count = 0

        def _metadata(record: SpectrumRecord, offset: float, success: bool) -> dict[str, object]:
            meta = dict(record.metadata)
            meta.setdefault("modality", record.modality)
            meta["calibration_offset"] = float(offset)
            meta["calibration_success"] = bool(success)
            meta["si_target_peak"] = float(target_peak)
            return meta

        output: list[PreprocessedSpectrum] = []
        for s in spectra:
            x = [float(v) for v in s.x]
            y = [float(v) for v in s.y]

            offset = 0.0
            success = False
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
                    metadata=_metadata(s, offset=offset, success=success),
                )
            )
        
        context.state["preprocessed_count"] = len(output)
        context.state["si_calibration_enabled"] = calibration_enabled
        context.state["si_calibration_success_count"] = success_count
        context.state["si_calibration_mean_offset"] = float(np.mean(offsets)) if offsets else 0.0
        return output
