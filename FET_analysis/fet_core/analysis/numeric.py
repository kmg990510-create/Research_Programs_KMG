"""Small numerical tools shared by the extraction steps."""

from __future__ import annotations

import warnings

import numpy as np


def running_median(values: np.ndarray, window: int) -> np.ndarray:
    """Centred running median that ignores NaN. The window shrinks at the ends."""
    values = np.asarray(values, dtype=float)
    half = max(int(window), 1) // 2
    out = np.full(values.size, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)  # all-NaN windows stay NaN
        for index in range(values.size):
            out[index] = np.nanmedian(values[max(0, index - half) : index + half + 1])
    return out


def lagged_median_slope(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Slope, intercept and slope standard error of a line through noisy, jumpy data.

    The slope is the median of ``(y[i+k] - y[i]) / (x[i+k] - x[i])`` with the
    lag ``k`` a quarter of the window. A single level shift (a current jump)
    sits inside at most a third of those pairs, so it cannot move the median,
    while the long lag keeps the estimate far less noisy than the median of
    point-to-point slopes. A least-squares or Theil-Sen slope is pulled up by
    such a jump.

    The standard error assumes independent noise of the size seen in the
    residuals: ``1.25 * sqrt(2) * sigma / (lag_span * sqrt(pairs))``.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    lag = max(1, x.size // 4)
    dx = x[lag:] - x[:-lag]
    usable = dx != 0
    if not usable.any():
        return float("nan"), float("nan"), float("nan")
    slope = float(np.median((y[lag:] - y[:-lag])[usable] / dx[usable]))
    intercept = float(np.median(y - slope * x))
    sigma = 1.4826 * float(np.median(np.abs(y - slope * x - intercept)))
    error = 1.25 * np.sqrt(2.0) * sigma / (float(np.median(dx[usable])) * np.sqrt(int(usable.sum())))
    return slope, intercept, float(error)


def window_end_indices(x: np.ndarray, span: float, min_points: int) -> np.ndarray:
    """For each start index, the last index of the shortest window that covers
    ``span`` in ``x`` and holds ``min_points`` points; -1 when none fits.
    ``x`` must be ascending."""
    count = x.size
    ends = np.full(count, -1, dtype=int)
    end = 0
    for start in range(count):
        end = max(end, start + min_points - 1)
        while end < count and x[end] - x[start] < span:
            end += 1
        if end >= count:
            break
        ends[start] = end
    return ends


def sliding_linear_fit(x: np.ndarray, y: np.ndarray, points: int) -> tuple[np.ndarray, np.ndarray]:
    """Least-squares slope and R^2 of every window of ``points`` consecutive samples.

    Returns arrays of length ``len(x) - points + 1``. A window containing NaN,
    or with no spread in ``x`` or ``y``, gives NaN.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if points < 2 or x.size < points:
        return np.array([]), np.array([])
    xw = np.lib.stride_tricks.sliding_window_view(x, points)
    yw = np.lib.stride_tricks.sliding_window_view(y, points)
    xc = xw - xw.mean(axis=1, keepdims=True)
    yc = yw - yw.mean(axis=1, keepdims=True)
    sxx = (xc * xc).sum(axis=1)
    sxy = (xc * yc).sum(axis=1)
    syy = (yc * yc).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(sxx > 0, sxy / sxx, np.nan)
        r2 = np.where((sxx > 0) & (syy > 0), sxy * sxy / (sxx * syy), np.nan)
    return slope, r2
