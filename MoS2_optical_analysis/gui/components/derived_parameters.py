"""Quantities derived from fitted peak parameters. No Streamlit import.

One place for the strain / doping separation and the map-level derived columns,
so every page shows the same numbers.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

MIN_DETERMINANT = 1.0e-12  # numerical guard: below this the coefficient matrix cannot be inverted


def strain_doping(e2g, a1g, omega_e0: float, omega_a0: float, coefficients: Mapping[str, float]):
    """Strain (%) and doping (1e13 cm^-2) from E2g and A1g positions (cm^-1).

    Linear model with the reference positions ``omega_e0`` / ``omega_a0``:
    ``dE2g = s_e * strain + d_e * n`` and ``dA1g = s_a * strain + d_a * n``.
    Works on arrays and on pandas Series. Raises ``ValueError`` when the
    coefficients cannot be inverted.
    """
    s_e, s_a = float(coefficients["s_e"]), float(coefficients["s_a"])
    d_e, d_a = float(coefficients["d_e"]), float(coefficients["d_a"])
    det_k = s_e * d_a - s_a * d_e
    if abs(det_k) < MIN_DETERMINANT:
        raise ValueError("Invalid coefficient set: determinant is near zero.")
    d_e2g = e2g - omega_e0
    d_a1g = a1g - omega_a0
    strain = (d_a * d_e2g - d_e * d_a1g) / det_k
    doping = (-s_a * d_e2g + s_e * d_a1g) / det_k
    return strain, doping


def _not_equal(frame: pd.DataFrame, column: str, value: str) -> pd.Series:
    return frame[column].astype(str).str.strip().str.lower() != value


def add_derived_map_parameters(frame: pd.DataFrame, coefficients: Mapping[str, float]) -> pd.DataFrame:
    """Copy of ``frame`` with ``e2g_a1g_area_ratio``, ``strain_eps_pct`` and ``doping_n_1e13_cm2``.

    The strain / doping reference is the mean E2g and A1g position of the points
    of this frame that are not invalid and not rejected. A column is added only
    when its inputs exist; with unusable coefficients strain and doping are left out.
    """
    out = frame.copy()
    if {"e2g_area", "a1g_area"}.issubset(out.columns):
        e2g_area = pd.to_numeric(out["e2g_area"], errors="coerce")
        a1g_area = pd.to_numeric(out["a1g_area"], errors="coerce")
        usable = e2g_area.notna() & a1g_area.notna() & (a1g_area != 0.0)
        ratio = pd.Series(np.nan, index=out.index, dtype=float)
        ratio.loc[usable] = e2g_area.loc[usable] / a1g_area.loc[usable]
        out["e2g_a1g_area_ratio"] = ratio

    if {"e2g_position", "a1g_position"}.issubset(out.columns):
        e2g = pd.to_numeric(out["e2g_position"], errors="coerce")
        a1g = pd.to_numeric(out["a1g_position"], errors="coerce")
        reference = e2g.notna() & a1g.notna()
        if "fit_status" in out.columns:
            reference &= _not_equal(out, "fit_status", "invalid")
        if "review_decision" in out.columns:
            reference &= _not_equal(out, "review_decision", "rejected")
        if bool(reference.any()):
            try:
                strain, doping = strain_doping(
                    e2g, a1g, float(e2g.loc[reference].mean()), float(a1g.loc[reference].mean()), coefficients
                )
            except ValueError:
                return out
            out["strain_eps_pct"] = strain
            out["doping_n_1e13_cm2"] = doping
    return out
