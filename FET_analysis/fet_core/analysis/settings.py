"""Analysis settings, read once from ``config.yaml``.

Extraction functions take an ``AnalysisSettings`` argument: no hidden globals,
no defaults in code. This is the only module that reads ``analysis.*`` keys.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from fet_core.config import Config, ConfigKeyError

GM_METHODS = ("lagged_median_slope",)


@dataclass(frozen=True)
class AnalysisSettings:
    min_points: int
    voltage_tolerance_V: float
    non_monotonic_max_fraction: float
    polarity_edge_fraction: float
    polarity_min_decades: float
    transition_low_percentile: float
    transition_high_percentile: float
    transition_lower_fraction: float
    transition_upper_fraction: float
    transition_smooth_window_points: int
    transition_min_span_decades: float
    off_window_V: float
    off_window_min_points: int
    off_max_std_decades: float
    off_max_slope_decades_per_V: float
    off_noise_weight: float
    on_window_points: int
    gm_method: str
    gm_window_V: float
    gm_window_min_points: int
    gm_peak_plateau_tolerance: float
    gm_max_relative_noise: float
    gm_noise_top_fraction: float
    gm_max_window_fraction: float
    vth_subtract_half_vds: bool
    vth_const_current_nA_per_um: float
    ss_window_min_points: int
    ss_window_max_points: int
    ss_min_r2: float
    ss_min_span_decades: float
    mobility_vds_relative_tolerance: float
    mobility_max_vds_over_overdrive: float
    leakage_transition_ratio_warn: float
    leakage_on_ratio_warn: float
    quality_min_on_off_decades: float

    @classmethod
    def from_config(cls, config: Config) -> "AnalysisSettings":
        a = "analysis"
        gm_method = config.text(f"{a}.gm.method")
        if gm_method not in GM_METHODS:
            raise ConfigKeyError(f"config key {a}.gm.method must be one of {GM_METHODS}, got {gm_method!r}")
        return cls(
            min_points=config.integer(f"{a}.min_points"),
            voltage_tolerance_V=config.number("classification.voltage_change_tolerance_V"),
            non_monotonic_max_fraction=config.number(f"{a}.sweep.non_monotonic_max_fraction"),
            polarity_edge_fraction=config.number(f"{a}.polarity.edge_fraction"),
            polarity_min_decades=config.number(f"{a}.polarity.min_decades"),
            transition_low_percentile=config.number(f"{a}.transition.low_percentile"),
            transition_high_percentile=config.number(f"{a}.transition.high_percentile"),
            transition_lower_fraction=config.number(f"{a}.transition.lower_fraction"),
            transition_upper_fraction=config.number(f"{a}.transition.upper_fraction"),
            transition_smooth_window_points=config.integer(f"{a}.transition.smooth_window_points"),
            transition_min_span_decades=config.number(f"{a}.transition.min_span_decades"),
            off_window_V=config.number(f"{a}.off_current.window_V"),
            off_window_min_points=config.integer(f"{a}.off_current.window_min_points"),
            off_max_std_decades=config.number(f"{a}.off_current.max_std_decades"),
            off_max_slope_decades_per_V=config.number(f"{a}.off_current.max_slope_decades_per_V"),
            off_noise_weight=config.number(f"{a}.off_current.noise_weight"),
            on_window_points=config.integer(f"{a}.on_current.window_points"),
            gm_method=gm_method,
            gm_window_V=config.number(f"{a}.gm.window_V"),
            gm_window_min_points=config.integer(f"{a}.gm.window_min_points"),
            gm_peak_plateau_tolerance=config.number(f"{a}.gm.peak_plateau_tolerance"),
            gm_max_relative_noise=config.number(f"{a}.gm.max_relative_noise"),
            gm_noise_top_fraction=config.number(f"{a}.gm.noise_top_fraction"),
            gm_max_window_fraction=config.number(f"{a}.gm.max_window_fraction"),
            vth_subtract_half_vds=config.boolean(f"{a}.vth.subtract_half_vds"),
            vth_const_current_nA_per_um=config.number(f"{a}.vth.const_current_nA_per_um"),
            ss_window_min_points=config.integer(f"{a}.ss.window_min_points"),
            ss_window_max_points=config.integer(f"{a}.ss.window_max_points"),
            ss_min_r2=config.number(f"{a}.ss.min_r2"),
            ss_min_span_decades=config.number(f"{a}.ss.min_span_decades"),
            mobility_vds_relative_tolerance=config.number(f"{a}.mobility.vds_relative_tolerance"),
            mobility_max_vds_over_overdrive=config.number(f"{a}.mobility.max_vds_over_overdrive"),
            leakage_transition_ratio_warn=config.number(f"{a}.leakage.transition_ratio_warn"),
            leakage_on_ratio_warn=config.number(f"{a}.leakage.on_ratio_warn"),
            quality_min_on_off_decades=config.number(f"{a}.quality.min_on_off_decades"),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
