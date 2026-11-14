"""Logic the viewer pages share: derived parameters and the spectrum view range."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import gui  # noqa: F401  (puts the repository root on sys.path)
from fitting.mos2_pl.run_raw_pipeline import NM_TO_EV
from gui.components import graph_style
from gui.components.derived_parameters import add_derived_map_parameters, strain_doping
from gui.components.spectrum_view import ViewWindow, default_view_range, si_check_range, to_plot_axis, view_window
from gui.components.spectrum_viewer import _PEAKS, _resolve_fit_curve_cfg, _resolve_overlay_style

GUI_DIR = Path(__file__).resolve().parents[1] / "gui"
COEFFICIENTS = {"s_e": -6.48, "s_a": -1.21, "d_e": -0.33, "d_a": -2.22}


def _window() -> ViewWindow:
    return view_window(graph_style.load_raman_graph_config_file())


def test_strain_doping_inverts_the_linear_model() -> None:
    strain, doping = 0.3, -0.5
    e2g = 385.0 + COEFFICIENTS["s_e"] * strain + COEFFICIENTS["d_e"] * doping
    a1g = 404.0 + COEFFICIENTS["s_a"] * strain + COEFFICIENTS["d_a"] * doping
    got = strain_doping(np.array([e2g]), np.array([a1g]), 385.0, 404.0, COEFFICIENTS)
    assert np.allclose(got, [[strain], [doping]])
    with pytest.raises(ValueError):
        strain_doping(np.array([e2g]), np.array([a1g]), 385.0, 404.0, {"s_e": 1.0, "s_a": 2.0, "d_e": 2.0, "d_a": 4.0})


def test_map_parameters_use_points_that_are_not_invalid_or_rejected_as_reference() -> None:
    frame = pd.DataFrame(
        {
            "e2g_position": [384.0, 386.0, 400.0, 390.0],
            "a1g_position": [403.0, 405.0, 420.0, 410.0],
            "e2g_area": [1.0, 2.0, 3.0, 4.0],
            "a1g_area": [2.0, 0.0, 6.0, 8.0],
            "fit_status": ["valid", "attention", "invalid", "valid"],
            "review_decision": ["", "", "", "rejected"],
        }
    )
    out = add_derived_map_parameters(frame, COEFFICIENTS)
    assert out["e2g_a1g_area_ratio"].tolist()[0] == 0.5 and np.isnan(out["e2g_a1g_area_ratio"].iloc[1])  # no division by zero
    expected = strain_doping(frame["e2g_position"], frame["a1g_position"], 385.0, 404.0, COEFFICIENTS)  # mean of rows 0 and 1
    assert np.allclose(out["strain_eps_pct"], expected[0]) and np.allclose(out["doping_n_1e13_cm2"], expected[1])
    assert "strain_eps_pct" not in add_derived_map_parameters(frame, {"s_e": 1.0, "s_a": 2.0, "d_e": 2.0, "d_a": 4.0})
    assert list(frame.columns) == ["e2g_position", "a1g_position", "e2g_area", "a1g_area", "fit_status", "review_decision"]


def test_pl_wavelength_axis_becomes_sorted_energy() -> None:
    window = _window()
    x, y = to_plot_axis([700.0, 800.0], [1.0, 2.0], {"x_unit": "eV"}, "pl", window)
    assert np.allclose(x, [NM_TO_EV / 800.0, NM_TO_EV / 700.0]) and y == [2.0, 1.0]
    x, y = to_plot_axis([1.7, 1.9], [1.0, 2.0], {"x_unit": "eV"}, "pl", window)  # already energy
    assert x == [1.7, 1.9]
    x, _ = to_plot_axis([380.0, 400.0], [1.0, 2.0], {"calibration_offset": 0.5}, "raman", window)
    assert x == [380.5, 400.5]


def test_default_view_range() -> None:
    window = _window()
    raman = np.linspace(100.0, 600.0, 501)
    assert default_view_range(raman, {"e2g_position": 384.0, "a1g_position": 403.0}, "raman", window) == (
        384.0 - window.peak_padding,
        403.0 + window.peak_padding,
    )
    assert default_view_range(raman, {}, "raman", window) == (window.fallback_min, window.fallback_max)

    energy = np.linspace(1.2, 2.2, 201)  # span 1 eV: padding is limited to pl_padding_max_ev
    low, high = default_view_range(energy, {"pl_position": 1.85}, "pl", window)
    assert low == window.pl_view_min_ev and high == pytest.approx(1.85 + window.pl_padding_max_ev)
    low, high = default_view_range(energy, {"a0_position": 1.85}, "pl", window)  # multi-component PL has no pl_position
    assert high == pytest.approx(1.85 + window.pl_padding_max_ev)
    assert default_view_range(energy, {}, "pl", window) == (1.2, 2.2)
    assert si_check_range(raman, window) == (window.si_check_min, window.si_check_max)


def test_view_and_style_settings_have_no_code_side_default() -> None:
    with pytest.raises(KeyError, match="x_window"):
        view_window({"all_spectra_viewer": {}})
    with pytest.raises(KeyError, match="pl_view_min_ev"):
        view_window({"all_spectra_viewer": {"x_window": {"fallback_min": 1, "fallback_max": 2, "peak_padding": 3}}})
    with pytest.raises(KeyError, match="fit_line_color"):
        _resolve_overlay_style({"raw_marker_color": "#000000"})
    with pytest.raises(KeyError, match="max_points"):
        _resolve_fit_curve_cfg({"smooth_factor": 5})
    style = _resolve_overlay_style(None)  # read from raman_graph.yaml
    assert set(style["component_colors"]) == set(_PEAKS)  # every peak, Raman and PL, has a colour in the YAML


def test_pages_do_not_repeat_the_shared_logic() -> None:
    for path in GUI_DIR.glob("pages/*.py"):
        text = path.read_text(encoding="utf-8-sig")
        assert "det_k" not in text, path.name  # strain / doping: gui/components/derived_parameters.py
        assert not re.search(r"1239\.8", text), path.name  # nm -> eV: gui/components/spectrum_view.py


def test_progress_is_logged_and_only_the_cli_prints_it(capsys) -> None:
    from fitting.mos2_core.core import progress_log

    progress_log.progress.info("[fit] silent")  # no handler yet: library use prints nothing
    assert capsys.readouterr().out == ""
    progress_log.configure_cli_logging()
    try:
        progress_log.progress.info("[fit] 1/2 | valid=1")
        assert capsys.readouterr().out == "[fit] 1/2 | valid=1\n"
    finally:
        for handler in list(progress_log.progress.handlers):
            progress_log.progress.removeHandler(handler)

    library = Path(__file__).resolve().parents[1] / "fitting" / "mos2_core"
    for path in [library / "fitting" / "model_selection.py", library / "fitting" / "raman_lmfit.py", library / "review" / "queue.py"]:
        assert "print(" not in path.read_text(encoding="utf-8-sig"), path.name


def test_every_name_a_page_uses_from_the_shared_modules_is_imported() -> None:
    names = ("view_window", "to_plot_axis", "default_view_range", "si_check_range", "add_derived_map_parameters", "strain_doping")
    for path in GUI_DIR.glob("pages/*.py"):
        text = path.read_text(encoding="utf-8-sig")
        imports = "\n".join(line for line in text.splitlines() if line.startswith(("from ", "import ")))
        for name in names:
            if re.search(rf"\b{name}\(", text):
                assert re.search(rf"\b{name}\b", imports), (path.name, name)
