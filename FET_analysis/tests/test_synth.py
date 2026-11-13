from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from fet_core.synth import gate_sweep, transfer_curve


def test_gate_sweep_dual_does_not_repeat_the_turning_point() -> None:
    assert list(gate_sweep(0.0, 2.0, 1.0, dual=True)) == [0.0, 1.0, 2.0, 1.0, 0.0]
    assert list(gate_sweep(0.0, 2.0, 1.0, dual=False)) == [0.0, 1.0, 2.0]


def test_linear_regime_recovers_vth_and_mobility(device) -> None:
    vg = np.array([50.0, 60.0])
    current = device.drain_current(vg)
    slope = (current[1] - current[0]) / 10.0
    assert slope == pytest.approx(device.gm_max_S, rel=1e-6)
    intercept = vg[0] - (current[0] - device.off_current_A) / slope
    assert intercept == pytest.approx(device.vth_V, abs=1e-6)
    k = slope / device.vds_V
    mobility_cm2 = k / (device.geometry.cox_F_per_m2 * device.geometry.width_over_length) * 1e4
    assert mobility_cm2 == pytest.approx(device.mobility_cm2_per_Vs, rel=1e-6)


def test_subthreshold_slope_is_ss(device) -> None:
    quiet = replace(device, off_current_A=1e-30)
    vg = np.array([-10.0, -9.0])
    decades = np.diff(np.log10(quiet.drain_current(vg)))[0]
    assert 1000.0 / decades == pytest.approx(quiet.ss_mV_per_dec, rel=1e-3)


def test_p_type_mirrors_n_type(device) -> None:
    p_device = replace(device, polarity="p", vth_V=-device.vth_V, vds_V=-device.vds_V)
    vg = np.linspace(-40.0, 40.0, 9)
    assert np.allclose(p_device.drain_current(-vg), -device.drain_current(vg))


def test_hysteresis_shifts_only_the_backward_branch(device) -> None:
    shifted = replace(device, hysteresis_V=3.0)
    frame = transfer_curve(shifted, -40.0, 60.0, 1.0, dual=True)
    forward, backward = frame.iloc[:101], frame.iloc[101:]
    assert len(frame) == 201
    assert np.allclose(forward["Id"], device.drain_current(forward["Vg"].to_numpy()))
    assert np.allclose(backward["Id"], device.drain_current(backward["Vg"].to_numpy() - 3.0))


def test_noise_is_reproducible(device) -> None:
    first = transfer_curve(device, -40.0, 60.0, 1.0, noise_fraction=0.05, seed=7)
    second = transfer_curve(device, -40.0, 60.0, 1.0, noise_fraction=0.05, seed=7)
    other = transfer_curve(device, -40.0, 60.0, 1.0, noise_fraction=0.05, seed=8)
    assert first.equals(second)
    assert not first["Id"].equals(other["Id"])
