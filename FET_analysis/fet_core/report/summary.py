"""Group statistics over the reviewed result table."""

from __future__ import annotations

import pandas as pd

# column -> (label, unit). The single list of metrics used by tables and plots.
METRICS: dict[str, tuple[str, str]] = {
    "mobility_cm2_per_Vs": ("Mobility", "cm²/Vs"),
    "vth_linear_V": ("Vth (linear extrapolation)", "V"),
    "vth_const_current_V": ("Vth (constant current)", "V"),
    "ss_mV_per_dec": ("SS", "mV/dec"),
    "on_off_decades": ("log10(on/off)", ""),
    "i_on_uA_per_um": ("On current", "µA/µm"),
    "i_off_A": ("Off current", "A"),
    "gm_peak_uS_per_um": ("Peak gm", "µS/µm"),
    "hysteresis_vth_linear_V": ("Hysteresis (linear Vth)", "V"),
}
STATISTICS = ("count", "median", "mean", "std", "min", "max")


def metric_label(column: str) -> str:
    label, unit = METRICS[column]
    return f"{label} ({unit})" if unit else label


def group_summary(frame: pd.DataFrame, groups: list[str] | None = None) -> pd.DataFrame:
    """Statistics of every metric per display group and sweep direction.

    Only rows with ``included`` true are counted. ``n_sweeps`` is every sweep of
    the group, ``n_included`` the ones in the statistics.
    """
    columns = ["group", "sweep", "n_sweeps", "n_included"] + [f"{m}_{s}" for m in METRICS for s in STATISTICS]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    names = groups if groups is not None else list(dict.fromkeys(frame["group_display"]))
    rows = []
    for group in names:
        for sweep in dict.fromkeys(frame["sweep"]):
            part = frame[(frame["group_display"] == group) & (frame["sweep"] == sweep)]
            if part.empty:
                continue
            used = part[part["included"]]
            row: dict[str, object] = {"group": group, "sweep": sweep, "n_sweeps": len(part), "n_included": len(used)}
            for metric in METRICS:
                values = pd.to_numeric(used[metric], errors="coerce").dropna()
                row[f"{metric}_count"] = int(values.size)
                for statistic in STATISTICS[1:]:
                    row[f"{metric}_{statistic}"] = float(getattr(values, statistic)()) if values.size else None
                if values.size < 2:
                    row[f"{metric}_std"] = None
            rows.append(row)
    return pd.DataFrame(rows, columns=columns)
