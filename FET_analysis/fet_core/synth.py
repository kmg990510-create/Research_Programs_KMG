"""Synthetic transfer curves with known parameters.

Used as ground truth: an extraction method is correct when it recovers the
``vth_V``, ``ss_mV_per_dec`` and ``mobility_cm2_per_Vs`` a curve was built from.

Model (n-type; p-type mirrors the gate voltage and the current sign)::

    Id = K * Vds * S * ln(1 + exp((Vg - Vth) / S)) + I_floor
    K  = mobility * Cox * W / L          S = SS / ln(10)

Far above threshold this is the linear-regime line ``K * Vds * (Vg - Vth)``, so
the tangent there extrapolates to ``Vth`` and its slope gives the mobility. Far
below threshold the current falls one decade per ``SS`` volts until it reaches
the floor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fet_core.model import STANDARD_COLUMNS, DeviceGeometry

N_TYPE = "n"
P_TYPE = "p"


@dataclass(frozen=True)
class SyntheticDevice:
    geometry: DeviceGeometry
    vth_V: float
    ss_mV_per_dec: float
    mobility_cm2_per_Vs: float
    vds_V: float = 1.0
    off_current_A: float = 1e-13
    gate_leakage_A: float = 1e-12
    hysteresis_V: float = 0.0  # backward-sweep Vth minus forward-sweep Vth
    polarity: str = N_TYPE

    def __post_init__(self) -> None:
        if self.polarity not in (N_TYPE, P_TYPE):
            raise ValueError(f"polarity must be 'n' or 'p', got {self.polarity!r}")
        if self.ss_mV_per_dec <= 0 or self.mobility_cm2_per_Vs <= 0:
            raise ValueError("ss_mV_per_dec and mobility_cm2_per_Vs must be positive")

    @property
    def transconductance_factor_A_per_V2(self) -> float:
        """K = mobility * Cox * W / L in SI units."""
        mobility_m2 = self.mobility_cm2_per_Vs * 1e-4
        return mobility_m2 * self.geometry.cox_F_per_m2 * self.geometry.width_over_length

    @property
    def gm_max_S(self) -> float:
        """Transconductance far above threshold: K * |Vds|."""
        return self.transconductance_factor_A_per_V2 * abs(self.vds_V)

    def drain_current(self, vg: np.ndarray, vth_shift_V: float = 0.0) -> np.ndarray:
        """Noise-free drain current (signed) at gate voltages ``vg``."""
        sign = 1.0 if self.polarity == N_TYPE else -1.0
        slope_V = self.ss_mV_per_dec * 1e-3 / np.log(10.0)
        overdrive = sign * (np.asarray(vg, dtype=float) - (self.vth_V + vth_shift_V))
        channel = self.gm_max_S * slope_V * np.logaddexp(0.0, overdrive / slope_V)
        return sign * (channel + self.off_current_A)


def gate_sweep(start_V: float, stop_V: float, step_V: float, dual: bool = True) -> np.ndarray:
    """Gate voltages start -> stop, and back to start when ``dual`` (turning point not repeated)."""
    count = int(round(abs(stop_V - start_V) / abs(step_V))) + 1
    forward = np.linspace(start_V, stop_V, count)
    return np.concatenate([forward, forward[-2::-1]]) if dual else forward


def transfer_curve(
    device: SyntheticDevice,
    start_V: float,
    stop_V: float,
    step_V: float,
    dual: bool = True,
    noise_fraction: float = 0.0,
    seed: int = 0,
) -> pd.DataFrame:
    """A transfer run in the standard columns, rows in acquisition order.

    ``noise_fraction`` is multiplicative Gaussian noise on Id and Ig with a
    fixed ``seed``, so the same arguments always give the same table.
    """
    vg = gate_sweep(start_V, stop_V, step_V, dual)
    forward_count = int(round(abs(stop_V - start_V) / abs(step_V))) + 1
    backward = np.arange(vg.size) >= forward_count
    drain = np.where(
        backward,
        device.drain_current(vg, device.hysteresis_V),
        device.drain_current(vg, 0.0),
    )
    gate = np.full(vg.size, -device.gate_leakage_A)
    if noise_fraction > 0:
        rng = np.random.default_rng(seed)
        drain = drain * (1.0 + noise_fraction * rng.standard_normal(vg.size))
        gate = gate * (1.0 + noise_fraction * rng.standard_normal(vg.size))
    frame = pd.DataFrame(np.nan, index=range(vg.size), columns=list(STANDARD_COLUMNS))
    frame["Vg"] = vg
    frame["Vd"] = device.vds_V
    frame["Vs"] = 0.0
    frame["Id"] = drain
    frame["Ig"] = gate
    return frame
