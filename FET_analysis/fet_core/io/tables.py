"""Shared steps that turn a vendor table into the standard measurement table."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from fet_core.config import Config
from fet_core.model import (
    CURVE_OUTPUT,
    CURVE_TRANSFER,
    CURVE_UNKNOWN,
    STANDARD_COLUMNS,
)


def match_columns(source_columns: Sequence[str], aliases: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """Internal column -> source column. Aliases are tried in order, ignoring case and spaces."""
    by_folded = {str(name).strip().casefold(): str(name) for name in source_columns}
    matched: dict[str, str] = {}
    for internal, candidates in aliases.items():
        for candidate in candidates:
            hit = by_folded.get(candidate.strip().casefold())
            if hit is not None:
                matched[internal] = hit
                break
    return matched


def standard_frame(raw: pd.DataFrame, column_map: Mapping[str, str]) -> tuple[pd.DataFrame, int]:
    """Build the STANDARD_COLUMNS table and count cells that were not numbers.

    Row order and row count are preserved. A cell that is not a number becomes
    NaN in place; an unrecorded quantity is an all-NaN column.
    """
    frame = pd.DataFrame(index=range(len(raw)), columns=list(STANDARD_COLUMNS), dtype=float)
    non_numeric = 0
    for internal in STANDARD_COLUMNS:
        source = column_map.get(internal)
        if source is None:
            continue
        cells = raw[source].reset_index(drop=True)
        numeric = pd.to_numeric(cells, errors="coerce").astype(float)
        numeric = numeric.where(np.isfinite(numeric))
        blank = cells.isna() | (cells.astype(str).str.strip() == "")
        non_numeric += int((numeric.isna() & ~blank).sum())
        frame[internal] = numeric.to_numpy()
    return frame, non_numeric


def _change_fraction(values: pd.Series, tolerance: float) -> float | None:
    finite = values.dropna().to_numpy()
    if finite.size < 2:
        return None
    return float(np.mean(np.abs(np.diff(finite)) > tolerance))


def classify_curve(frame: pd.DataFrame, config: Config) -> str:
    """Transfer when Vg is the swept voltage, output when Vd is.

    The swept voltage changes at almost every point; a stepped or constant one
    rarely does. When neither or both look swept the answer is ``unknown``:
    the caller decides, nothing is guessed here.
    """
    threshold = config.number("classification.swept_min_change_fraction")
    tolerance = config.number("classification.voltage_change_tolerance_V")
    gate = _change_fraction(frame["Vg"], tolerance)
    drain = _change_fraction(frame["Vd"], tolerance)
    gate_swept = gate is not None and gate >= threshold
    drain_swept = drain is not None and drain >= threshold
    if gate_swept and not drain_swept:
        return CURVE_TRANSFER
    if drain_swept and not gate_swept:
        return CURVE_OUTPUT
    return CURVE_UNKNOWN


def _median_or_none(values: pd.Series) -> float | None:
    finite = values.dropna()
    return float(finite.median()) if not finite.empty else None


def resolve_vds(frame: pd.DataFrame, vd_bias: float | None, vs_bias: float | None) -> dict[str, Any]:
    """Drain-source voltage of a transfer run and where each term came from.

    Measured columns win over header values. A source voltage that is neither
    measured nor in the header is taken as 0 V and reported as ``assumed_zero``.
    """
    vd = _median_or_none(frame["Vd"])
    vd_source = "measured"
    if vd is None:
        vd, vd_source = vd_bias, "header"
    vs = _median_or_none(frame["Vs"])
    vs_source = "measured"
    if vs is None:
        vs, vs_source = (vs_bias, "header") if vs_bias is not None else (0.0, "assumed_zero")
    if vd is None:
        return {"vds_V": None, "vd_source": "missing", "vs_source": vs_source}
    return {"vds_V": float(vd - vs), "vd_source": vd_source, "vs_source": vs_source}


def to_float(value: Any) -> float | None:
    """A header cell as a finite number, or None (``"N/A"``, blank, text)."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None
