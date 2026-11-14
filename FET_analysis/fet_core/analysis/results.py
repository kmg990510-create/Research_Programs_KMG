"""Result model of the transfer analysis.

One ``SweepResult`` per measurement and sweep direction. A value that could not
be extracted is ``None`` (never 0). Voltages are real gate voltages, also for
p-type devices.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from fet_core.model import WarningRecord

STATUS_VALID = "valid"
STATUS_ATTENTION = "attention"
STATUS_INVALID = "invalid"

POLARITY_N = "n"
POLARITY_P = "p"
POLARITY_UNKNOWN = "unknown"

# Reason code -> (status it causes, message). The single list of quality findings.
# A reason mapped to STATUS_VALID is a note: recorded with the result, but it
# does not ask for a review.
REASONS: dict[str, tuple[str, str]] = {
    "insufficient_points": (STATUS_INVALID, "Too few points in the sweep."),
    "no_gate_sweep": (STATUS_INVALID, "The gate voltage does not change."),
    "no_gate_modulation": (STATUS_INVALID, "The current does not change enough with gate voltage."),
    "short_backward_sweep": (STATUS_ATTENTION, "The backward sweep is too short and was not analysed."),
    "non_monotonic_sweep": (STATUS_ATTENTION, "The gate voltage does not move in one direction."),
    "off_state_not_reached": (STATUS_ATTENTION, "The sweep does not reach the off state."),
    "off_plateau_not_found": (STATUS_ATTENTION, "No stable off-current plateau; the lowest window was used."),
    "gm_not_extracted": (STATUS_ATTENTION, "No transconductance peak could be found."),
    "gm_peak_at_sweep_edge": (
        STATUS_VALID,
        "gm is still rising at the end of the sweep: gm and mobility are lower bounds, Vth depends on the range.",
    ),
    "gm_noisy": (
        STATUS_ATTENTION,
        "The current is too noisy for a reliable gm even with the widest window: gm, Vth and mobility are uncertain.",
    ),
    "vth_const_current_not_found": (STATUS_ATTENTION, "The current never crosses the constant-current level."),
    "ss_not_extracted": (STATUS_ATTENTION, "No log-linear subthreshold window passed the quality limits."),
    "vds_missing": (STATUS_ATTENTION, "Drain-source voltage unknown: mobility not computed."),
    "mobility_outside_linear_regime": (STATUS_ATTENTION, "|Vds| is not small against the gate overdrive."),
    "leakage_dominated_transition": (STATUS_ATTENTION, "Gate leakage is as large as the drain current during turn-on."),
    "on_state_leakage": (STATUS_ATTENTION, "Gate leakage is a noticeable part of the on current."),
    "low_on_off_ratio": (STATUS_ATTENTION, "The on/off ratio is small."),
}

_RANK = {STATUS_VALID: 0, STATUS_ATTENTION: 1, STATUS_INVALID: 2}


def status_from_reasons(reasons: tuple[str, ...]) -> str:
    worst = STATUS_VALID
    for reason in reasons:
        candidate = REASONS[reason][0]
        if _RANK[candidate] > _RANK[worst]:
            worst = candidate
    return worst


@dataclass
class SweepResult:
    # identity
    source_file: str
    run_id: str
    label: str
    group: str
    position: str | None
    sweep: str
    polarity: str
    vds_V: float | None
    n_points: int
    # geometry the values below were computed with
    W_um: float
    L_um: float
    t_ox_nm: float
    eps_r: float
    # quality
    status: str = STATUS_VALID
    reasons: tuple[str, ...] = ()
    # transition region
    transition_start_V: float | None = None
    transition_end_V: float | None = None
    transition_span_decades: float | None = None
    # off / on current
    i_off_A: float | None = None
    i_off_window_start_V: float | None = None
    i_off_window_end_V: float | None = None
    i_off_n_points: int | None = None
    i_off_method: str | None = None
    i_on_A: float | None = None
    i_on_window_start_V: float | None = None
    i_on_window_end_V: float | None = None
    on_off_ratio: float | None = None
    on_off_decades: float | None = None
    # transconductance
    gm_peak_S: float | None = None
    gm_peak_Vg_V: float | None = None
    gm_window_start_V: float | None = None
    gm_window_end_V: float | None = None
    gm_tangent_current_A: float | None = None  # |Id| of the tangent line at gm_peak_Vg_V
    gm_relative_error: float | None = None  # standard error of gm divided by gm
    gm_method: str | None = None
    # threshold voltage
    vth_linear_V: float | None = None
    vth_linear_method: str | None = None
    vth_const_current_V: float | None = None
    vth_const_current_level_A: float | None = None
    # subthreshold swing
    ss_mV_per_dec: float | None = None
    ss_window_start_V: float | None = None
    ss_window_end_V: float | None = None
    ss_r2: float | None = None
    ss_n_points: int | None = None
    ss_span_decades: float | None = None
    ss_window_leak_median: float | None = None  # median |Ig| / |Id| inside the SS window
    # mobility
    mobility_cm2_per_Vs: float | None = None
    mobility_method: str | None = None
    mobility_note: str | None = None
    # gate leakage, |Ig| / |Id| per region
    leak_off_median: float | None = None
    leak_off_max: float | None = None
    leak_transition_median: float | None = None
    leak_transition_max: float | None = None
    leak_transition_fraction_above_1: float | None = None
    leak_on_median: float | None = None
    leak_on_max: float | None = None
    # hysteresis, backward minus forward (same value on both rows of a run)
    hysteresis_vth_linear_V: float | None = None
    hysteresis_vth_const_current_V: float | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source_file, self.run_id, self.sweep)

    def add_reason(self, code: str) -> None:
        if code not in REASONS:
            raise KeyError(f"unknown reason code: {code}")
        if code not in self.reasons:
            self.reasons = self.reasons + (code,)
            self.status = status_from_reasons(self.reasons)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["reasons"] = ";".join(self.reasons)
        return row


def counts_in_summary(result: SweepResult) -> bool:
    """The one rule for group statistics: every sweep that is not invalid."""
    return result.status != STATUS_INVALID


@dataclass
class TransferAnalysis:
    results: list[SweepResult] = field(default_factory=list)
    warnings: list[WarningRecord] = field(default_factory=list)
