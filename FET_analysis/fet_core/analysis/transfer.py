"""Parameter extraction from transfer (Id-Vg) curves.

Everything is computed in "turn-on" coordinates: ``u = Vg`` for n-type and
``u = -Vg`` for p-type, with ``I = |Id|``, so the device always turns on as
``u`` increases. Reported voltages are converted back to real gate voltages.

Raw currents are used throughout. Gate leakage is assessed, never used to
remove points.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from fet_core.analysis.numeric import lagged_median_slope, running_median, sliding_linear_fit, window_end_indices
from fet_core.analysis.results import (
    POLARITY_N,
    POLARITY_P,
    POLARITY_UNKNOWN,
    REASONS,
    STATUS_ATTENTION,
    STATUS_INVALID,
    STATUS_VALID,
    SweepResult,
    TransferAnalysis,
)
from fet_core.analysis.settings import AnalysisSettings
from fet_core.analysis.sweeps import BACKWARD, FORWARD, Branch, split_branches
from fet_core.model import (
    CURVE_TRANSFER,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    DeviceGeometry,
    Measurement,
    WarningRecord,
)

logger = logging.getLogger(__name__)

OFF_METHOD_PLATEAU = "stable_plateau"
OFF_METHOD_LOWEST = "lowest_window"
VTH_METHOD = "linear_extrapolation_at_gm_peak"
VTH_METHOD_HALF_VDS = "linear_extrapolation_at_gm_peak_minus_half_vds"
MOBILITY_METHOD = "linear_regime_gm_peak"
_SEVERITY_OF_STATUS = {STATUS_VALID: SEVERITY_INFO, STATUS_ATTENTION: SEVERITY_WARNING, STATUS_INVALID: SEVERITY_ERROR}


def detect_polarity(frame: pd.DataFrame, settings: AnalysisSettings) -> str:
    """n when |Id| rises with Vg, p when it falls, unknown when it does neither clearly."""
    vg = frame["Vg"].to_numpy(dtype=float)
    current = np.abs(frame["Id"].to_numpy(dtype=float))
    usable = np.isfinite(vg) & np.isfinite(current) & (current > 0)
    if int(usable.sum()) < settings.min_points:
        return POLARITY_UNKNOWN
    order = np.argsort(vg[usable], kind="stable")
    log_current = np.log10(current[usable][order])
    edge = max(1, int(log_current.size * settings.polarity_edge_fraction))
    rise = float(np.median(log_current[-edge:]) - np.median(log_current[:edge]))
    if rise >= settings.polarity_min_decades:
        return POLARITY_N
    if rise <= -settings.polarity_min_decades:
        return POLARITY_P
    return POLARITY_UNKNOWN


def _turn_on_arrays(data: pd.DataFrame, sign: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(u, |Id|, |Ig|) sorted by u, repeated gate voltages averaged."""
    table = pd.DataFrame(
        {
            "u": sign * data["Vg"].to_numpy(dtype=float),
            "i": np.abs(data["Id"].to_numpy(dtype=float)),
            "g": np.abs(data["Ig"].to_numpy(dtype=float)),
        }
    )
    table = table[np.isfinite(table["u"]) & np.isfinite(table["i"])]
    merged = table.groupby("u", sort=True).mean()
    return merged.index.to_numpy(dtype=float), merged["i"].to_numpy(), merged["g"].to_numpy()


def _blank_result(measurement: Measurement, sweep: str, polarity: str, n_points: int) -> SweepResult:
    return SweepResult(
        source_file=measurement.source_file.name,
        run_id=measurement.run_id,
        label=measurement.label,
        group=measurement.group,
        position=measurement.position,
        sweep=sweep,
        polarity=polarity,
        vds_V=measurement.conditions.get("vds_V"),
        n_points=n_points,
    )


def _off_current(u: np.ndarray, current: np.ndarray, log_current: np.ndarray, last_off: int, width: int, s: AnalysisSettings):
    """(start index, method) of the representative off window, or (None, None).

    Among windows before the transition that are flat and quiet, the one with
    the lowest level wins; early settling and rising tails are passed over.
    """
    view = np.lib.stride_tricks.sliding_window_view
    if last_off + 1 >= width:
        windows = view(log_current[: last_off + 1], width)
        level = np.median(windows, axis=1)
        spread = np.std(windows, axis=1)
        slope, _ = sliding_linear_fit(u[: last_off + 1], log_current[: last_off + 1], width)
        with np.errstate(invalid="ignore"):
            stable = (spread <= s.off_max_std_decades) & (np.abs(slope) <= s.off_max_slope_decades_per_V)
        if stable.any():
            score = np.where(stable, level + s.off_noise_weight * spread, np.inf)
            return int(np.argmin(score)), OFF_METHOD_PLATEAU
    if current.size >= width:
        level = np.median(view(current, width), axis=1)
        return int(np.argmin(level)), OFF_METHOD_LOWEST
    return None, None


def _gm_curve(u: np.ndarray, current: np.ndarray, window_V: float, s: AnalysisSettings):
    """Smoothed gm of every sliding window: (smooth, window ends, neighbours, relative slope error near the top)."""
    ends = window_end_indices(u, window_V, s.gm_window_min_points)
    starts = np.flatnonzero(ends >= 0)
    if starts.size == 0:
        return None
    slopes = np.full(u.size, np.nan)
    errors = np.full(u.size, np.nan)
    for start in starts:
        slopes[start], _, errors[start] = lagged_median_slope(
            u[start : ends[start] + 1], current[start : ends[start] + 1]
        )
    neighbours = int(np.median(ends[starts] - starts + 1)) | 1  # odd
    smooth = running_median(slopes, neighbours)
    smooth[ends < 0] = np.nan
    if not np.isfinite(smooth).any() or not np.nanmax(smooth) > 0:
        return None
    top = float(np.nanmax(smooth))
    with np.errstate(invalid="ignore"):
        near_top = errors[smooth >= 0.5 * top]
    near_top = near_top[np.isfinite(near_top)]
    noise = float(np.median(near_top)) / top if near_top.size else 0.0
    return smooth, ends, neighbours, noise


def _gm_peak(u: np.ndarray, current: np.ndarray, s: AnalysisSettings) -> tuple[float, float, int, int, int, float] | None:
    """Peak transconductance: (gm, tangent intercept, first index, last index, window end index, relative slope error).

    1. Lagged median slope in every sliding window: one current jump cannot fake a peak.
    2. Running median over neighbouring windows: the maximum of a noisy curve
       is biased high, the maximum of its median much less.
    3. While the gm curve is still noisy near its top, the window is doubled
       (up to a fraction of the sweep range): a slope needs a longer baseline
       when the current is noisy.
    4. The peak is the maximum of that curve. Among windows within the plateau
       tolerance of the maximum the first one is taken, so a flat top gives the
       point nearest the threshold.
    """
    window_V = s.gm_window_V
    widest = s.gm_max_window_fraction * float(u[-1] - u[0])
    curve = _gm_curve(u, current, window_V, s)
    while curve is not None and curve[3] > s.gm_max_relative_noise and 2.0 * window_V <= widest:
        wider = _gm_curve(u, current, 2.0 * window_V, s)
        if wider is None:
            break
        window_V, curve = 2.0 * window_V, wider
    if curve is None:
        return None
    smooth, ends, neighbours, noise = curve
    starts = np.flatnonzero(ends >= 0)
    top = float(np.nanmax(smooth))
    with np.errstate(invalid="ignore"):
        start = int(np.flatnonzero(smooth >= (1.0 - s.gm_peak_plateau_tolerance) * top)[0])
    gm = float(smooth[start])
    half = neighbours // 2
    first = max(start - half, int(starts[0]))
    last = int(ends[min(start + half, int(starts[-1]))])
    intercept = float(np.median(current[first : last + 1] - gm * u[first : last + 1]))
    return gm, intercept, first, last, int(ends[start]), noise


def _near_sweep_end(u: np.ndarray, window_end: int, s: AnalysisSettings) -> bool:
    """True when fewer than one base gm window of data lies beyond the peak window."""
    beyond_points = u.size - 1 - window_end
    beyond_V = float(u[-1] - u[window_end])
    return beyond_points < s.gm_window_min_points or beyond_V < s.gm_window_V


def _analyze_branch(
    measurement: Measurement,
    branch: Branch,
    polarity: str,
    geometry: DeviceGeometry,
    s: AnalysisSettings,
    compute_mobility: bool,
) -> SweepResult:
    sign = -1.0 if polarity == POLARITY_P else 1.0
    u, current, gate = _turn_on_arrays(branch.data, sign)
    n = u.size
    result = _blank_result(measurement, branch.direction, polarity, n)
    positive = current > 0
    if n < s.min_points or int(positive.sum()) < s.min_points:
        result.add_reason("insufficient_points")
        return result
    if polarity == POLARITY_UNKNOWN:
        result.add_reason("no_gate_modulation")
        return result

    log_current = np.full(n, np.nan)
    log_current[positive] = np.log10(current[positive])
    smooth = running_median(log_current, s.transition_smooth_window_points)

    # ---- transition region ---------------------------------------------------
    low, high = np.nanpercentile(log_current, [s.transition_low_percentile, s.transition_high_percentile])
    span = float(high - low)
    if not span >= s.transition_min_span_decades:
        result.add_reason("no_gate_modulation")
        return result
    lower = low + s.transition_lower_fraction * span
    upper = low + s.transition_upper_fraction * span
    reached = np.flatnonzero(smooth >= upper)
    on_start = int(reached[0]) if reached.size else int(np.nanargmax(smooth))
    still_off = np.flatnonzero(smooth[:on_start] < lower)
    last_off = int(still_off[-1]) if still_off.size else -1
    if last_off < 0:
        result.add_reason("off_state_not_reached")
    result.transition_start_V = sign * float(u[max(last_off, 0)])
    result.transition_end_V = sign * float(u[on_start])
    result.transition_span_decades = span

    # ---- off and on current --------------------------------------------------
    step = float(np.median(np.diff(u)))
    width = max(s.off_window_min_points, int(np.ceil(s.off_window_V / step)) + 1)
    off_start, off_method = _off_current(u, current, log_current, last_off, width, s)
    if off_start is not None:
        result.i_off_A = float(np.median(current[off_start : off_start + width]))
        result.i_off_window_start_V = sign * float(u[off_start])
        result.i_off_window_end_V = sign * float(u[off_start + width - 1])
        result.i_off_n_points = width
        result.i_off_method = off_method
    if off_method != OFF_METHOD_PLATEAU:
        result.add_reason("off_plateau_not_found")

    on_points = min(s.on_window_points, n)
    result.i_on_A = float(np.median(current[-on_points:]))
    result.i_on_window_start_V = sign * float(u[-on_points])
    result.i_on_window_end_V = sign * float(u[-1])
    if result.i_off_A and result.i_off_A > 0 and result.i_on_A > 0:
        result.on_off_ratio = result.i_on_A / result.i_off_A
        result.on_off_decades = float(np.log10(result.on_off_ratio))
        if result.on_off_decades < s.quality_min_on_off_decades:
            result.add_reason("low_on_off_ratio")

    # ---- transconductance and linear-extrapolation Vth ---------------------------
    gm_fit = _gm_peak(u, current, s)
    vth_u = peak_u = None
    if gm_fit is not None:
        gm, intercept, start, end, window_end, gm_noise = gm_fit
        peak_u = 0.5 * float(u[start] + u[end])
        vth_u = -intercept / gm
        result.gm_peak_S = gm
        result.gm_peak_Vg_V = sign * peak_u
        result.gm_window_start_V = sign * float(u[start])
        result.gm_window_end_V = sign * float(u[end])
        result.gm_tangent_current_A = gm * peak_u + intercept
        result.gm_relative_error = gm_noise
        result.gm_method = s.gm_method
        # Less than one base window of data beyond the peak window: gm may still be rising.
        if _near_sweep_end(u, window_end, s):
            result.add_reason("gm_peak_at_sweep_edge")
        if gm_noise > s.gm_max_relative_noise:
            result.add_reason("gm_noisy")
        vds = result.vds_V
        if s.vth_subtract_half_vds and vds is not None:
            result.vth_linear_V = sign * (vth_u - abs(vds) / 2.0)
            result.vth_linear_method = VTH_METHOD_HALF_VDS
        elif s.vth_subtract_half_vds:
            result.add_reason("vds_missing")
        else:
            result.vth_linear_V = sign * vth_u
            result.vth_linear_method = VTH_METHOD
    else:
        result.add_reason("gm_not_extracted")

    # ---- constant-current Vth ---------------------------------------------------
    level = s.vth_const_current_nA_per_um * 1e-9 * geometry.W_um
    result.vth_const_current_level_A = level
    below = np.flatnonzero(current < level)
    if below.size and below[-1] < n - 1:
        i = int(below[-1])
        lo_i, hi_i = current[i], current[i + 1]
        if lo_i > 0:
            fraction = (np.log10(level) - np.log10(lo_i)) / (np.log10(hi_i) - np.log10(lo_i))
        else:
            fraction = (level - lo_i) / (hi_i - lo_i)
        result.vth_const_current_V = sign * float(u[i] + fraction * (u[i + 1] - u[i]))
    else:
        result.add_reason("vth_const_current_not_found")

    # ---- subthreshold swing -----------------------------------------------------
    region_start = max(last_off - s.ss_window_min_points + 1, 0)
    region_u = u[region_start : on_start + 1]
    region_log = log_current[region_start : on_start + 1]
    best: tuple[float, float, int, int, float] | None = None
    for points in range(s.ss_window_min_points, s.ss_window_max_points + 1):
        slope, r2 = sliding_linear_fit(region_u, region_log, points)
        if slope.size == 0:
            break
        covered = slope * (region_u[points - 1 :] - region_u[: slope.size])
        with np.errstate(invalid="ignore"):
            good = (slope > 0) & (r2 >= s.ss_min_r2) & (covered >= s.ss_min_span_decades)
        if good.any():
            k = int(np.argmax(np.where(good, slope, -np.inf)))
            if best is None or slope[k] > best[0]:
                best = (float(slope[k]), float(r2[k]), region_start + k, points, float(covered[k]))
    if best is not None:
        slope, r2, start, points, covered = best
        result.ss_mV_per_dec = 1000.0 / slope
        result.ss_window_start_V = sign * float(u[start])
        result.ss_window_end_V = sign * float(u[start + points - 1])
        result.ss_r2 = r2
        result.ss_n_points = points
        result.ss_span_decades = covered
        with np.errstate(divide="ignore", invalid="ignore"):
            window_leak = gate[start : start + points] / current[start : start + points]
        window_leak = window_leak[np.isfinite(window_leak)]
        if window_leak.size:
            result.ss_window_leak_median = float(np.median(window_leak))
    else:
        result.add_reason("ss_not_extracted")

    # ---- mobility (linear regime) ------------------------------------------------
    if result.gm_peak_S is not None:
        vds = result.vds_V
        if vds is None or vds == 0:
            result.add_reason("vds_missing")
        elif not compute_mobility:
            result.mobility_note = "not_lowest_vds"
        else:
            mobility_m2 = result.gm_peak_S / (geometry.width_over_length * geometry.cox_F_per_m2 * abs(vds))
            result.mobility_cm2_per_Vs = mobility_m2 * 1e4
            result.mobility_method = MOBILITY_METHOD
            overdrive = peak_u - vth_u
            if abs(vds) > s.mobility_max_vds_over_overdrive * overdrive:
                result.add_reason("mobility_outside_linear_regime")

    # ---- gate leakage, assessed per region ---------------------------------------
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(positive & np.isfinite(gate), gate / current, np.nan)
    index = np.arange(n)
    regions = {
        "off": index <= last_off,
        "transition": (index > last_off) & (index <= on_start),
        "on": index > on_start,
    }
    stats: dict[str, tuple[float, float, float] | None] = {}
    for name, mask in regions.items():
        values = ratio[mask]
        values = values[np.isfinite(values)]
        stats[name] = (float(np.median(values)), float(values.max()), float(np.mean(values > 1.0))) if values.size else None
    if stats["off"]:
        result.leak_off_median, result.leak_off_max, _ = stats["off"]
    if stats["transition"]:
        result.leak_transition_median, result.leak_transition_max, result.leak_transition_fraction_above_1 = stats["transition"]
        if result.leak_transition_median >= s.leakage_transition_ratio_warn:
            result.add_reason("leakage_dominated_transition")
    if stats["on"]:
        result.leak_on_median, result.leak_on_max, _ = stats["on"]
        if result.leak_on_median >= s.leakage_on_ratio_warn:
            result.add_reason("on_state_leakage")
    return result


def _difference(backward: float | None, forward: float | None) -> float | None:
    return None if backward is None or forward is None else backward - forward


def analyze_measurement(
    measurement: Measurement,
    geometry: DeviceGeometry,
    settings: AnalysisSettings,
    compute_mobility: bool = True,
) -> tuple[list[SweepResult], list[WarningRecord]]:
    """One result per sweep direction of a transfer run, plus the matching warnings."""
    if measurement.curve_type != CURVE_TRANSFER:
        raise ValueError(f"not a transfer curve: {measurement.key} is '{measurement.curve_type}'")
    polarity = detect_polarity(measurement.data, settings)
    branches, issues = split_branches(measurement.data, settings)

    results: list[SweepResult] = []
    if not branches:
        result = _blank_result(measurement, FORWARD, polarity, len(measurement.data))
        for code, _ in issues:
            result.add_reason(code)
        results.append(result)
    else:
        for branch in branches:
            results.append(_analyze_branch(measurement, branch, polarity, geometry, settings, compute_mobility))
        for code, context in issues:
            targets = [r for r in results if r.sweep == context.get("sweep")] or results[:1]
            for target in targets:
                target.add_reason(code)

    by_sweep = {r.sweep: r for r in results}
    if FORWARD in by_sweep and BACKWARD in by_sweep:
        forward, backward = by_sweep[FORWARD], by_sweep[BACKWARD]
        linear = _difference(backward.vth_linear_V, forward.vth_linear_V)
        constant = _difference(backward.vth_const_current_V, forward.vth_const_current_V)
        for result in results:
            result.hysteresis_vth_linear_V = linear
            result.hysteresis_vth_const_current_V = constant

    warnings = [
        WarningRecord(
            code=code,
            message=REASONS[code][1],
            source_file=result.source_file,
            run_id=result.run_id,
            severity=_SEVERITY_OF_STATUS[REASONS[code][0]],
            context={"sweep": result.sweep},
        )
        for result in results
        for code in result.reasons
    ]
    return results, warnings


def _device_key(measurement: Measurement) -> tuple[str, str]:
    return (measurement.source_file.name, measurement.label)


def analyze_transfer_batch(
    measurements: Iterable[Measurement],
    default_geometry: DeviceGeometry,
    settings: AnalysisSettings,
    geometry_overrides: Mapping[tuple[str, str], DeviceGeometry] | None = None,
) -> TransferAnalysis:
    """Analyse every transfer run. Nothing is written to disk.

    ``geometry_overrides`` maps ``Measurement.key`` to that device's geometry.
    Mobility is reported only for the run(s) at the lowest ``|Vds|`` of each
    device, where the linear-regime formula applies best.
    """
    overrides: Mapping[tuple[str, str], DeviceGeometry] = geometry_overrides or {}
    items = list(measurements)
    analysis = TransferAnalysis()

    lowest_vds: dict[tuple[str, str], float] = {}
    for item in items:
        vds = item.conditions.get("vds_V")
        if item.curve_type == CURVE_TRANSFER and vds:
            key = _device_key(item)
            lowest_vds[key] = min(lowest_vds.get(key, np.inf), abs(vds))

    for item in items:
        if item.curve_type != CURVE_TRANSFER:
            analysis.warnings.append(
                WarningRecord(
                    "curve_not_analysed",
                    f"'{item.curve_type}' curve: only transfer curves are analysed.",
                    item.source_file.name,
                    item.run_id,
                    SEVERITY_INFO,
                )
            )
            continue
        vds = item.conditions.get("vds_V")
        lowest = lowest_vds.get(_device_key(item))
        at_lowest = bool(vds) and lowest is not None and abs(vds) <= lowest * (1.0 + settings.mobility_vds_relative_tolerance)
        results, warnings = analyze_measurement(item, overrides.get(item.key, default_geometry), settings, at_lowest)
        analysis.results.extend(results)
        analysis.warnings.extend(warnings)
    logger.info(
        "Analysed %d sweep(s): %s",
        len(analysis.results),
        {status: sum(r.status == status for r in analysis.results) for status in ("valid", "attention", "invalid")},
    )
    return analysis


def results_table(results: Iterable[SweepResult]) -> pd.DataFrame:
    """One row per sweep result, columns in ``SweepResult`` field order."""
    rows: list[dict[str, Any]] = [result.to_row() for result in results]
    return pd.DataFrame(rows)
