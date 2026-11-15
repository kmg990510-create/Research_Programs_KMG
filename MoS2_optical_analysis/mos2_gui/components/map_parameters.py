"""Which parameters the Map Viewer can colour by, and the user-defined ratio column."""

from __future__ import annotations

import pandas as pd
import streamlit as st

MIN_DENOMINATOR = 1.0e-12  # numerical guard against division by zero
COORDINATE_COLUMNS = {"map_x", "map_y"}

# Offered first, in this order, when the report has them. Other numeric columns follow.
PREFERRED_PARAMS = (
    "delta_e2g_a1g",
    "strain_eps_pct",
    "doping_n_1e13_cm2",
    "e2g_a1g_area_ratio",
    "e2g_position",
    "a1g_position",
    "e2g_fwhm",
    "a1g_fwhm",
    "lo_position",
    "zo_position",
    "la_position",
    "lo_fwhm",
    "zo_fwhm",
    "la_fwhm",
    "si_area",
    "pl_position",
    "pl_height",
    "pl_fwhm",
    "pl_area",
    "a_minus_position",
    "a0_position",
    "a_minus_a0_energy_split",
    "a_minus_a0_area_ratio",
    "a0_fraction_of_a_total",
    "b_to_a_total_area_ratio",
    "defect_to_a_total_area_ratio",
    "a_minus_fwhm",
    "a0_fwhm",
    "b_position",
    "i1_position",
    "i2_position",
    "rmse",
    "r2",
    "aic",
    "bic",
)


def numeric_parameters(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c]) and c not in COORDINATE_COLUMNS]


def parameter_candidates(frame: pd.DataFrame, first: tuple[str, ...] = ()) -> list[str]:
    """Columns to colour the map by: ``first``, then the preferred ones, then every other numeric column."""
    numeric = numeric_parameters(frame)
    ordered: list[str] = []
    for name in (*first, *PREFERRED_PARAMS, *numeric):
        if name in numeric and name not in ordered:
            ordered.append(name)
    return ordered


def add_ratio_column(frame: pd.DataFrame, numerator: str, denominator: str, name: str) -> pd.DataFrame:
    """Copy of ``frame`` with ``name = numerator / denominator``; empty where the ratio is not defined."""
    out = frame.copy()
    top = pd.to_numeric(out[numerator], errors="coerce")
    bottom = pd.to_numeric(out[denominator], errors="coerce")
    usable = top.notna() & bottom.notna() & (bottom.abs() > MIN_DENOMINATOR)
    ratio = pd.Series(float("nan"), index=out.index, dtype=float)
    ratio.loc[usable] = top.loc[usable] / bottom.loc[usable]
    out[name] = ratio
    return out


def ratio_builder(frame: pd.DataFrame, key: str) -> tuple[pd.DataFrame, str | None]:
    """Inputs for a ratio of two numeric columns, drawn where this is called.

    Returns the frame (with the ratio column when it is switched on) and the column name.
    """
    numeric = numeric_parameters(frame)
    enough = len(numeric) >= 2
    enabled = st.checkbox(
        "Enable custom ratio (numerator / denominator)", value=False, key=f"{key}_enable", disabled=not enough
    )
    off = not (enabled and enough)
    numerator = st.selectbox("Numerator", numeric if enough else ["-"], key=f"{key}_num", disabled=off)
    denominator = st.selectbox(
        "Denominator", [c for c in numeric if c != numerator] if enough else ["-"], key=f"{key}_den", disabled=off
    )
    default_name = f"{numerator}_over_{denominator}" if enough else "custom_ratio"
    name = st.text_input("Ratio name", value=default_name, key=f"{key}_name", disabled=off).strip() or default_name
    if off:
        return frame, None
    st.caption(f"Added ratio column: {name} = {numerator} / {denominator}")
    return add_ratio_column(frame, numerator, denominator, name), name
