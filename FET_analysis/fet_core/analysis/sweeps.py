"""Split a transfer run into its forward and backward gate sweeps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from fet_core.analysis.settings import AnalysisSettings

FORWARD = "forward"  # away from the starting gate voltage
BACKWARD = "backward"  # returning to it


@dataclass(frozen=True, eq=False)
class Branch:
    direction: str
    data: pd.DataFrame  # standard columns, acquisition order


Issue = tuple[str, dict[str, Any]]  # (reason code, context)


def _wrong_way_fraction(vg: np.ndarray, tolerance: float) -> float:
    steps = np.diff(vg[np.isfinite(vg)])
    if steps.size == 0:
        return 0.0
    direction = np.sign(steps.sum())
    return float(np.mean(steps * direction < -tolerance))


def split_branches(frame: pd.DataFrame, settings: AnalysisSettings) -> tuple[list[Branch], list[Issue]]:
    """Forward branch up to the turning point, backward branch from it.

    The turning point is the gate voltage farthest from the first one. When the
    instrument repeats it (``..., 59, 60, 60, 59, ...``) the forward branch ends
    at the first copy and the backward branch starts at the last; when it does
    not, both branches share that single point.
    """
    issues: list[Issue] = []
    vg = frame["Vg"].to_numpy(dtype=float)
    finite = np.flatnonzero(np.isfinite(vg))
    if finite.size < settings.min_points:
        return [], [("insufficient_points", {"points": int(finite.size)})]

    distance = np.abs(vg - vg[finite[0]])
    reach = np.nanmax(distance)
    if not reach > settings.voltage_tolerance_V:
        return [], [("no_gate_sweep", {})]
    at_turn = np.flatnonzero(distance >= reach - settings.voltage_tolerance_V)
    first_turn, last_turn = int(at_turn[0]), int(at_turn[-1])

    branches: list[Branch] = []
    forward = frame.iloc[: first_turn + 1]
    if int(np.isfinite(forward["Vg"]).sum()) < settings.min_points:
        return [], [("insufficient_points", {"points": int(len(forward)), "sweep": FORWARD})]
    branches.append(Branch(FORWARD, forward))

    backward = frame.iloc[last_turn:]
    backward_points = int(np.isfinite(backward["Vg"]).sum())
    if backward_points >= settings.min_points:
        branches.append(Branch(BACKWARD, backward))
    elif backward_points > 1:
        issues.append(("short_backward_sweep", {"points": backward_points}))

    for branch in branches:
        fraction = _wrong_way_fraction(branch.data["Vg"].to_numpy(dtype=float), settings.voltage_tolerance_V)
        if fraction > settings.non_monotonic_max_fraction:
            issues.append(("non_monotonic_sweep", {"sweep": branch.direction, "fraction": round(fraction, 4)}))
    return branches, issues
