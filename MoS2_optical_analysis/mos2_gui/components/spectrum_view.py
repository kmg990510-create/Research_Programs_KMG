"""X axis and default view range of a spectrum figure. No Streamlit import.

One place for the wavelength -> energy conversion and for the range that is
shown first, so the viewer pages agree. The numbers come from
``all_spectra_viewer.x_window`` of the graph config (``raman_graph.yaml``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

NM_EV = 1239.8419843320026  # h*c in eV*nm (physical constant): E (eV) = NM_EV / wavelength (nm)

_PATH = "raman_graph.all_spectra_viewer.x_window"


@dataclass(frozen=True)
class ViewWindow:
    fallback_min: float  # cm^-1, shown when no peak position is known
    fallback_max: float  # cm^-1
    peak_padding: float  # cm^-1 around the E2g / A1g pair
    pl_view_min_ev: float  # eV, the PL view reaches down to at least here
    pl_padding_fraction: float  # of the measured span, around the PL peak
    pl_padding_min_ev: float  # eV
    pl_padding_max_ev: float  # eV
    pl_wavelength_padding_nm: float  # nm, when the PL axis is still a wavelength
    energy_axis_max_span: float  # an axis spanning less than this is in eV
    wavelength_axis_min: float  # an "eV" axis with values above this is really in nm
    si_check_min: float  # cm^-1, range of the Si peak check
    si_check_max: float  # cm^-1
    si_visible_from: float  # cm^-1, the check is offered when the spectrum reaches this


def view_window(graph_cfg: Mapping[str, Any]) -> ViewWindow:
    """Read the view settings. A missing key raises ``KeyError`` naming its full path."""
    section: Any = graph_cfg
    for part in ("all_spectra_viewer", "x_window"):
        section = section.get(part) if isinstance(section, Mapping) else None
    if not isinstance(section, Mapping):
        raise KeyError(f"{_PATH} is missing in the graph config")
    values = {}
    for name in ViewWindow.__dataclass_fields__:
        if name not in section:
            raise KeyError(f"{_PATH}.{name} is missing in the graph config")
        values[name] = float(section[name])
    return ViewWindow(**values)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def to_plot_axis(x_raw, y_raw, row: Mapping[str, Any], modality: str, window: ViewWindow) -> tuple[list[float], list[float]]:
    """Measured x and y as they are plotted: calibration offset added, PL wavelength turned into energy.

    A PL row whose unit is eV but whose axis still holds wavelengths (values above
    ``wavelength_axis_min``) is converted with ``NM_EV`` and sorted by energy.
    """
    offset = _number(row.get("calibration_offset"))
    offset = offset if np.isfinite(offset) else 0.0
    x = [float(value) + offset for value in x_raw]
    y = [float(value) for value in y_raw]
    is_energy_row = modality == "pl" and str(row.get("x_unit", "")).strip().lower() == "ev"
    if is_energy_row and x and max(x) > window.wavelength_axis_min:
        pairs = sorted((NM_EV / xv, yv) for xv, yv in zip(x, y) if xv > 0.0)
        x, y = [xv for xv, _ in pairs], [yv for _, yv in pairs]
    return x, y


def default_view_range(x, row: Mapping[str, Any], modality: str, window: ViewWindow) -> tuple[float, float]:
    """The range shown first: around the PL peak, or around the E2g / A1g pair."""
    x = np.asarray(x, dtype=float)
    data_min, data_max = float(np.min(x)), float(np.max(x))
    if modality == "pl":
        peak = _number(row.get("pl_position"))
        if not np.isfinite(peak):
            peak = _number(row.get("a0_position"))
        if not np.isfinite(peak):
            return data_min, data_max
        span = data_max - data_min
        if span <= window.energy_axis_max_span:
            padding = max(window.pl_padding_min_ev, min(window.pl_padding_max_ev, span * window.pl_padding_fraction))
            low = min(window.pl_view_min_ev, peak - padding)
        else:
            padding = max(window.peak_padding, window.pl_wavelength_padding_nm)
            low = peak - padding
        return max(data_min, low), min(data_max, peak + padding)
    e2g, a1g = _number(row.get("e2g_position")), _number(row.get("a1g_position"))
    if np.isfinite(e2g) and np.isfinite(a1g):
        return min(e2g, a1g) - window.peak_padding, max(e2g, a1g) + window.peak_padding
    return window.fallback_min, window.fallback_max


def si_check_range(x, window: ViewWindow) -> tuple[float, float]:
    """Range of the Si peak check, limited to the measured range."""
    return max(float(min(x)), window.si_check_min), min(float(max(x)), window.si_check_max)
