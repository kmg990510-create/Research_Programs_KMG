"""Transfer extraction against synthetic curves whose parameters are known."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fet_core.analysis.numeric import lagged_median_slope, sliding_linear_fit, window_end_indices
from fet_core.analysis.results import (
    REASONS,
    STATUS_ATTENTION,
    STATUS_INVALID,
    STATUS_VALID,
    counts_in_summary,
    status_from_reasons,
)
from fet_core.analysis.settings import AnalysisSettings
from fet_core.analysis.sweeps import BACKWARD, FORWARD, split_branches
from fet_core.analysis.transfer import (
    analyze_measurement,
    analyze_transfer_batch,
    detect_polarity,
    results_table,
)
from fet_core.io.loader import load_folder
from fet_core.model import CURVE_OUTPUT, CURVE_TRANSFER, DeviceGeometry, Measurement
from fet_core.synth import SyntheticDevice, transfer_curve


@pytest.fixture
def settings(config) -> AnalysisSettings:
    return AnalysisSettings.from_config(config)


@pytest.fixture
def geometry(config) -> DeviceGeometry:
    return DeviceGeometry.from_config(config)


def measurement(frame: pd.DataFrame, vds: float | None = 1.0, label: str = "S_A1", curve_type: str = CURVE_TRANSFER, run_id: str = "1") -> Measurement:
    return Measurement(
        source_file=Path("synthetic.csv"),
        source_sha256="0" * 64,
        instrument="synthetic",
        run_id=run_id,
        label=label,
        group="S",
        position="A1",
        curve_type=curve_type,
        data=frame,
        conditions={"vds_V": vds},
    )


def analyze(device: SyntheticDevice, geometry, settings, *, step=0.5, noise=0.0, start=-40.0, stop=60.0, dual=True):
    frame = transfer_curve(device, start, stop, step, dual=dual, noise_fraction=noise, seed=1)
    return analyze_measurement(measurement(frame, device.vds_V), geometry, settings)


def const_current_vth(device: SyntheticDevice, level_A: float) -> float:
    """Gate voltage where the noise-free model crosses ``level_A`` (fine grid)."""
    sign = 1.0 if device.polarity == "n" else -1.0
    u = np.linspace(-60.0, 60.0, 240001)
    current = np.abs(device.drain_current(sign * u))
    return sign * float(np.interp(np.log10(level_A), np.log10(current), u))


# ---- ground truth -------------------------------------------------------------


@pytest.mark.parametrize(("step", "ss_tolerance"), [(0.1, 0.01), (0.5, 0.01), (1.0, 0.04)])
def test_ideal_curve_recovers_its_parameters(device, geometry, settings, step, ss_tolerance) -> None:
    results, warnings = analyze(device, geometry, settings, step=step)
    assert [r.sweep for r in results] == [FORWARD, BACKWARD]
    assert warnings == []
    for r in results:
        assert (r.status, r.reasons, r.polarity) == (STATUS_VALID, (), "n")
        assert r.vth_linear_V == pytest.approx(device.vth_V, abs=0.1)
        assert r.mobility_cm2_per_Vs == pytest.approx(device.mobility_cm2_per_Vs, rel=0.02)
        assert r.gm_peak_S == pytest.approx(device.gm_max_S, rel=0.02)
        assert r.ss_mV_per_dec == pytest.approx(device.ss_mV_per_dec, rel=ss_tolerance)
        assert r.i_off_A == pytest.approx(device.off_current_A, rel=0.01)
        assert r.i_off_method == "stable_plateau"
        assert r.i_on_A == pytest.approx(abs(device.drain_current(np.array([59.0]))[0]), rel=0.05)
        assert r.on_off_decades == pytest.approx(np.log10(r.i_on_A / r.i_off_A))
        level = 1e-9 * geometry.W_um
        assert r.vth_const_current_level_A == pytest.approx(level)
        assert r.vth_const_current_V == pytest.approx(const_current_vth(device, level), abs=0.05)
        assert r.hysteresis_vth_linear_V == pytest.approx(0.0, abs=1e-9)
        assert r.vth_linear_method == "linear_extrapolation_at_gm_peak"
        assert r.gm_method == "lagged_median_slope"


def test_steep_low_voltage_device(device, geometry, settings) -> None:
    fast = replace(device, ss_mV_per_dec=150.0, vth_V=0.5, vds_V=0.1)
    (r, _), _ = analyze(fast, geometry, settings, step=0.05, start=-3.0, stop=5.0)
    assert r.status == STATUS_VALID
    assert r.vth_linear_V == pytest.approx(0.5, abs=0.05)
    assert r.ss_mV_per_dec == pytest.approx(150.0, rel=0.02)
    assert r.mobility_cm2_per_Vs == pytest.approx(20.0, rel=0.02)


@pytest.mark.parametrize(("step", "noise"), [(0.5, 0.02), (0.1, 0.05)])
def test_noisy_curve_stays_close(device, geometry, settings, step, noise) -> None:
    results, _ = analyze(device, geometry, settings, step=step, noise=noise)
    for r in results:
        assert r.status != STATUS_INVALID
        assert r.vth_linear_V == pytest.approx(device.vth_V, abs=1.5)
        assert r.mobility_cm2_per_Vs == pytest.approx(device.mobility_cm2_per_Vs, rel=0.10)
        assert r.ss_mV_per_dec == pytest.approx(device.ss_mV_per_dec, rel=0.15)
        assert r.i_off_A == pytest.approx(device.off_current_A, rel=0.10)
        assert r.gm_relative_error is not None and r.gm_relative_error <= settings.gm_max_relative_noise


def test_p_type_gives_mirrored_voltages(device, geometry, settings) -> None:
    p_device = replace(device, polarity="p", vth_V=-5.0, vds_V=-1.0)
    (n_result, _), _ = analyze(device, geometry, settings)
    (p_result, _), _ = analyze(p_device, geometry, settings, start=40.0, stop=-60.0)
    assert p_result.polarity == "p" and p_result.status == STATUS_VALID
    assert p_result.vth_linear_V == pytest.approx(-n_result.vth_linear_V)
    assert p_result.vth_const_current_V == pytest.approx(-n_result.vth_const_current_V)
    assert p_result.gm_peak_Vg_V == pytest.approx(-n_result.gm_peak_Vg_V)
    assert p_result.ss_mV_per_dec == pytest.approx(n_result.ss_mV_per_dec)
    assert p_result.mobility_cm2_per_Vs == pytest.approx(n_result.mobility_cm2_per_Vs)
    assert p_result.i_off_window_start_V > 0  # the off state of a p-type device is at positive Vg


def test_hysteresis_is_backward_minus_forward(device, geometry, settings) -> None:
    results, _ = analyze(replace(device, hysteresis_V=3.0), geometry, settings)
    forward, backward = results
    assert backward.vth_linear_V - forward.vth_linear_V == pytest.approx(3.0, abs=0.05)
    for r in results:
        assert r.hysteresis_vth_linear_V == pytest.approx(3.0, abs=0.05)
        assert r.hysteresis_vth_const_current_V == pytest.approx(3.0, abs=0.05)


def test_single_sweep_has_one_result_and_no_hysteresis(device, geometry, settings) -> None:
    results, _ = analyze(device, geometry, settings, dual=False)
    assert [r.sweep for r in results] == [FORWARD]
    assert results[0].hysteresis_vth_linear_V is None


# ---- robustness and policies ---------------------------------------------------


def test_current_jump_does_not_fake_a_gm_peak(device, geometry, settings) -> None:
    frame = transfer_curve(device, -40.0, 60.0, 0.5, dual=False)
    jump = frame["Vg"] >= 30.0
    frame.loc[jump, "Id"] += 0.2 * frame["Id"].max()
    (r,), _ = analyze_measurement(measurement(frame), geometry, settings)
    assert r.gm_peak_S == pytest.approx(device.gm_max_S, rel=0.03)
    assert r.vth_linear_V == pytest.approx(device.vth_V, abs=0.3)


def test_gate_leakage_is_assessed_not_removed(device, geometry, settings) -> None:
    (clean, _), _ = analyze(device, geometry, settings)
    (leaky, _), warnings = analyze(replace(device, gate_leakage_A=5e-6), geometry, settings)
    assert {"leakage_dominated_transition", "on_state_leakage"} <= set(leaky.reasons)
    assert leaky.status == STATUS_ATTENTION
    assert leaky.leak_transition_median > 1.0 and leaky.leak_on_median > 0.1
    assert leaky.leak_transition_fraction_above_1 > 0.5
    # the drain current is used as measured: every extracted value is unchanged
    for name in ("vth_linear_V", "ss_mV_per_dec", "mobility_cm2_per_Vs", "i_off_A", "i_on_A", "n_points"):
        assert getattr(leaky, name) == getattr(clean, name)
    assert {w.code for w in warnings} == set(leaky.reasons) and all(w.severity == "warning" for w in warnings)


def test_flat_curve_is_invalid_and_values_are_none(device, geometry, settings) -> None:
    frame = transfer_curve(device, -40.0, 60.0, 1.0)
    frame["Id"] = 3e-12
    results, warnings = analyze_measurement(measurement(frame), geometry, settings)
    for r in results:
        assert (r.status, r.reasons, r.polarity) == (STATUS_INVALID, ("no_gate_modulation",), "unknown")
        assert r.vth_linear_V is None and r.i_off_A is None and r.mobility_cm2_per_Vs is None and r.gm_peak_S is None
        assert not counts_in_summary(r)
    assert all(w.severity == "error" for w in warnings)


def test_too_few_points(device, geometry, settings) -> None:
    frame = transfer_curve(device, 0.0, 6.0, 1.0, dual=False)
    (r,), _ = analyze_measurement(measurement(frame), geometry, settings)
    assert (r.status, r.reasons) == (STATUS_INVALID, ("insufficient_points",))


def test_sweep_that_starts_above_the_off_state(device, geometry, settings) -> None:
    (r,), _ = analyze(device, geometry, settings, start=4.0, stop=60.0, dual=False)
    assert "off_plateau_not_found" in r.reasons and r.i_off_method == "lowest_window"
    assert r.status == STATUS_ATTENTION
    assert r.vth_linear_V == pytest.approx(device.vth_V, abs=0.2)


def test_gm_still_rising_at_the_end_is_a_note(device, geometry, settings) -> None:
    (r,), _ = analyze(device, geometry, settings, start=-40.0, stop=7.0, dual=False)
    assert "gm_peak_at_sweep_edge" in r.reasons
    # a note: on its own it does not ask for a review
    assert REASONS["gm_peak_at_sweep_edge"][0] == STATUS_VALID
    assert status_from_reasons(("gm_peak_at_sweep_edge",)) == STATUS_VALID
    assert r.gm_peak_S < device.gm_max_S  # a lower bound


def test_vth_half_vds_option_is_recorded(device, geometry, settings) -> None:
    (plain, _), _ = analyze(device, geometry, settings)
    (shifted, _), _ = analyze(device, geometry, replace(settings, vth_subtract_half_vds=True))
    assert shifted.vth_linear_V == pytest.approx(plain.vth_linear_V - 0.5 * device.vds_V)
    assert shifted.vth_linear_method == "linear_extrapolation_at_gm_peak_minus_half_vds"


def test_geometry_override_and_missing_vds(device, geometry, settings) -> None:
    frame = transfer_curve(device, -40.0, 60.0, 0.5, dual=False)
    wide = replace(geometry, W_um=2 * geometry.W_um)
    first, second = measurement(frame, 1.0, run_id="a"), measurement(frame, None, label="S_B2", run_id="b")
    analysis = analyze_transfer_batch([first, second], geometry, settings, {first.key: wide})
    overridden, no_vds = analysis.results
    assert overridden.mobility_cm2_per_Vs == pytest.approx(device.mobility_cm2_per_Vs / 2, rel=0.02)
    assert overridden.vth_const_current_level_A == pytest.approx(1e-9 * wide.W_um)
    assert no_vds.mobility_cm2_per_Vs is None and "vds_missing" in no_vds.reasons
    assert no_vds.vth_linear_V == pytest.approx(device.vth_V, abs=0.1)


def test_mobility_only_at_the_lowest_vds_of_a_device(device, geometry, settings) -> None:
    low = measurement(transfer_curve(replace(device, vds_V=0.1), -40.0, 60.0, 0.5, dual=False), 0.1, run_id="low")
    high = measurement(transfer_curve(device, -40.0, 60.0, 0.5, dual=False), 1.0, run_id="high")
    other = measurement(transfer_curve(device, -40.0, 60.0, 0.5, dual=False), 1.0, label="S_B2", run_id="other")
    output = measurement(transfer_curve(device, -40.0, 60.0, 0.5, dual=False), 1.0, curve_type=CURVE_OUTPUT, run_id="out")
    analysis = analyze_transfer_batch([low, high, other, output], geometry, settings)
    by_run = {r.run_id: r for r in analysis.results}
    assert set(by_run) == {"low", "high", "other"}
    assert by_run["low"].mobility_cm2_per_Vs == pytest.approx(20.0, rel=0.02)
    assert by_run["high"].mobility_cm2_per_Vs is None and by_run["high"].mobility_note == "not_lowest_vds"
    assert by_run["other"].mobility_cm2_per_Vs == pytest.approx(20.0, rel=0.02)
    assert [w.code for w in analysis.warnings] == ["curve_not_analysed"]
    with pytest.raises(ValueError, match="not a transfer curve"):
        analyze_measurement(output, geometry, settings)


def test_results_table_has_one_row_per_sweep(device, geometry, settings) -> None:
    results, _ = analyze(device, geometry, settings)
    table = results_table(results)
    assert list(table["sweep"]) == [FORWARD, BACKWARD]
    assert {"vth_linear_V", "ss_mV_per_dec", "mobility_cm2_per_Vs", "status", "reasons"} <= set(table.columns)
    assert table["reasons"].tolist() == ["", ""]


# ---- building blocks -----------------------------------------------------------


def test_polarity_detection(device, settings) -> None:
    frame = transfer_curve(device, -40.0, 60.0, 1.0, dual=False)
    assert detect_polarity(frame, settings) == "n"
    assert detect_polarity(frame.assign(Id=frame["Id"].to_numpy()[::-1]), settings) == "p"
    assert detect_polarity(frame.assign(Id=1e-9), settings) == "unknown"


def test_split_handles_repeated_and_single_turning_point(settings) -> None:
    def frame_of(vg):
        return pd.DataFrame({"Vg": vg, "Vd": 1.0, "Vs": 0.0, "Id": 1e-9, "Ig": 0.0, "Is": np.nan, "time": np.nan})

    up = np.arange(0.0, 21.0)
    repeated, _ = split_branches(frame_of(np.concatenate([up, up[::-1]])), settings)
    single, _ = split_branches(frame_of(np.concatenate([up, up[-2::-1]])), settings)
    for branches in (repeated, single):
        assert [b.direction for b in branches] == [FORWARD, BACKWARD]
        assert list(branches[0].data["Vg"]) == list(up)
        assert list(branches[1].data["Vg"]) == list(up[::-1])

    wobble = up.copy()
    wobble[5:9] = wobble[5:9][::-1]
    _, issues = split_branches(frame_of(wobble), settings)
    assert [code for code, _ in issues] == ["non_monotonic_sweep"]
    assert split_branches(frame_of(np.zeros(30)), settings) == ([], [("no_gate_sweep", {})])
    short, issues = split_branches(frame_of(np.concatenate([up, [19.0, 18.0, 17.0]])), settings)
    assert [b.direction for b in short] == [FORWARD] and [code for code, _ in issues] == ["short_backward_sweep"]


def test_lagged_median_slope_ignores_a_step() -> None:
    x = np.linspace(0.0, 10.0, 41)
    y = 2.0 * x + 1.0
    slope, intercept, error = lagged_median_slope(x, y)
    assert (slope, intercept, error) == pytest.approx((2.0, 1.0, 0.0), abs=1e-9)
    stepped = y + np.where(x >= 5.0, 8.0, 0.0)
    assert lagged_median_slope(x, stepped)[0] == pytest.approx(2.0, abs=1e-9)
    assert np.polyfit(x, stepped, 1)[0] > 2.5  # least squares is pulled up by the step


def test_window_and_sliding_fit_helpers() -> None:
    x = np.arange(0.0, 10.0, 0.5)
    assert list(window_end_indices(x, 2.0, 3)[:3]) == [4, 5, 6]
    assert window_end_indices(x, 2.0, 3)[-1] == -1
    assert list(window_end_indices(np.arange(5.0), 0.5, 3)) == [2, 3, 4, -1, -1]
    rng = np.random.default_rng(0)
    y = 0.3 * x + rng.normal(0, 0.05, x.size)
    slope, r2 = sliding_linear_fit(x, y, 6)
    assert slope.size == x.size - 5
    assert slope[3] == pytest.approx(np.polyfit(x[3:9], y[3:9], 1)[0])
    assert r2[3] == pytest.approx(np.corrcoef(x[3:9], y[3:9])[0, 1] ** 2)


# ---- real instrument files (local only) ----------------------------------------


def _real_data_dirs() -> list[Path]:
    root = Path(os.environ.get("FET_REAL_DATA_DIR", Path(__file__).resolve().parents[1] / "data" / "raw"))
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and any(f.suffix.lower() in {".csv", ".xls"} for f in p.iterdir()))


@pytest.mark.parametrize("folder", _real_data_dirs(), ids=lambda p: p.name)
def test_real_folders_analyse_without_invalid_sweeps(folder: Path, config, geometry, settings) -> None:
    loaded = load_folder(folder, config)
    analysis = analyze_transfer_batch(loaded.measurements, geometry, settings)
    assert len(analysis.results) == 2 * len(loaded.measurements)  # every run here is a dual sweep
    assert all(r.status != STATUS_INVALID for r in analysis.results)
    for r in analysis.results:
        assert r.polarity == "n"
        assert r.vth_linear_V is not None and r.ss_mV_per_dec is not None and r.mobility_cm2_per_Vs > 0
        assert r.i_off_A < r.i_on_A
