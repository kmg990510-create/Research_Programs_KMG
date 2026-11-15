"""Tables of extracted values for the pages. No Streamlit import."""

from __future__ import annotations

import pandas as pd

from fet_core.analysis.results import SweepResult


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    return f"{value:.4g}" if isinstance(value, float) else str(value)


def extracted_values(result: SweepResult, i_on_uA_per_um: float | None) -> pd.DataFrame:
    """Every extracted value of one sweep as quantity / value / unit rows."""
    rows = [
        ("Polarity", result.polarity, ""),
        ("Vds", result.vds_V, "V"),
        ("W / L / t_ox / eps_r", f"{result.W_um:g} / {result.L_um:g} / {result.t_ox_nm:g} / {result.eps_r:g}", "µm / µm / nm / -"),
        ("Off current", result.i_off_A, "A"),
        ("Off window", f"{result.i_off_window_start_V} .. {result.i_off_window_end_V}" if result.i_off_A else None, "V"),
        ("Off method", result.i_off_method, ""),
        ("On current", result.i_on_A, "A"),
        ("On current per width", i_on_uA_per_um, "µA/µm"),
        ("Peak gm", result.gm_peak_S, "S"),
        ("gm peak position", result.gm_peak_Vg_V, "V"),
        ("gm relative error", result.gm_relative_error, ""),
        ("Vth, linear extrapolation", result.vth_linear_V, "V"),
        ("Vth method", result.vth_linear_method, ""),
        ("Vth, constant current", result.vth_const_current_V, "V"),
        ("SS", result.ss_mV_per_dec, "mV/dec"),
        ("SS window", f"{result.ss_window_start_V} .. {result.ss_window_end_V}" if result.ss_mV_per_dec else None, "V"),
        ("SS fit R²", result.ss_r2, ""),
        ("Mobility", result.mobility_cm2_per_Vs, "cm²/Vs"),
        ("Hysteresis, linear Vth", result.hysteresis_vth_linear_V, "V"),
        ("Leakage |Ig|/|Id|, transition median", result.leak_transition_median, ""),
        ("Leakage |Ig|/|Id|, on median", result.leak_on_median, ""),
    ]
    return pd.DataFrame([{"quantity": name, "value": _text(value), "unit": unit} for name, value, unit in rows])
