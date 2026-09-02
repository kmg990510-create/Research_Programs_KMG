from __future__ import annotations

from pathlib import Path

import numpy as np

from fitting.mos2_core.core.types import PipelineContext, SpectrumRecord
from fitting.mos2_core.fitting.raman_lmfit import LmfitRamanModelEnsembleFitting
from fitting.mos2_core.io import load_pipeline_config
from fitting.mos2_core.review.refit_api import _synthesize_fitted_y
from fitting.mos2_pl.run_raw_pipeline import NM_TO_EV, _convert_nm_to_ev_if_needed


def test_pl_nm_input_is_converted_to_ev_and_sorted() -> None:
    spectrum = SpectrumRecord(
        spectrum_id="pl_nm",
        x=[900.0, 800.0, 700.0],
        y=[9.0, 8.0, 7.0],
        modality="pl",
        metadata={"header": {"X_UNIT": "nm"}},
    )

    x_ev, y_sorted, metadata = _convert_nm_to_ev_if_needed(spectrum)

    assert x_ev == sorted(x_ev)
    assert np.allclose(x_ev, sorted([NM_TO_EV / 900.0, NM_TO_EV / 800.0, NM_TO_EV / 700.0]))
    assert y_sorted == [9.0, 8.0, 7.0]
    assert metadata["x_unit"] == "eV"
    assert metadata["original_x_unit"] == "nm"
    assert metadata["intensity_density_correction"] is False


def test_pl_nm_input_can_apply_intensity_density_correction() -> None:
    spectrum = SpectrumRecord(
        spectrum_id="pl_nm_density",
        x=[800.0],
        y=[2.0],
        modality="pl",
        metadata={"header": {"X_UNIT": "nm"}},
    )

    x_ev, y_ev, metadata = _convert_nm_to_ev_if_needed(
        spectrum,
        intensity_density_correction=True,
    )

    expected_energy = NM_TO_EV / 800.0
    assert np.allclose(x_ev, [expected_energy])
    assert np.allclose(y_ev, [2.0 * NM_TO_EV / (expected_energy * expected_energy)])
    assert metadata["intensity_density_correction"] is True


def test_pl_yaml_components_resolve_to_model_specs() -> None:
    config = load_pipeline_config(Path("fitting/mos2_pl/config"))
    fitter = LmfitRamanModelEnsembleFitting(enable_pl=True)
    cfg = fitter._resolve_fit_config(PipelineContext(config=config), "pl")  # noqa: SLF001

    assert cfg.models == ["pl_single_pvoigt", "pl_a_doublet_pvoigt", "pl_5_component_pvoigt"]
    assert cfg.pl_model_components["pl_a_doublet_pvoigt"] == ["a_minus", "a0"]
    assert cfg.pl_model_components["pl_5_component_pvoigt"] == ["i1", "i2", "a_minus", "a0", "b"]

    a_minus = cfg.pl_components["a_minus"]
    assert a_minus.profile == "pvoigt"
    assert 1.78 <= a_minus.center_init <= 1.90
    assert a_minus.center_min < a_minus.center_init < a_minus.center_max
    assert a_minus.sigma_min < a_minus.sigma_init < a_minus.sigma_max


def test_synthetic_five_component_pl_fit_recovers_key_centers() -> None:
    config = load_pipeline_config(Path("fitting/mos2_pl/config"))
    fitter = LmfitRamanModelEnsembleFitting(enable_pl=True)
    cfg = fitter._resolve_fit_config(PipelineContext(config=config), "pl")  # noqa: SLF001

    x = np.linspace(1.38, 2.33, 900)
    components = {
        "i1": (1.510, 0.060, 0.10),
        "i2": (1.610, 0.080, 0.14),
        "a_minus": (1.855, 0.035, 0.70),
        "a0": (1.882, 0.025, 0.55),
        "b": (2.022, 0.050, 0.30),
    }
    y = np.full_like(x, 0.02)
    for center, sigma, height in components.values():
        y += height * np.exp(-0.5 * ((x - center) / sigma) ** 2)

    candidate = fitter._fit_pl_model("pl_5_component_pvoigt", x, y, cfg)  # noqa: SLF001

    assert candidate.model_name == "pl_5_component_pvoigt"
    for key, (center, _, _) in components.items():
        assert abs(candidate.params[f"{key}_position"] - center) < 0.035
        assert candidate.params[f"{key}_area"] > 0

    assert candidate.params["a_minus_a0_energy_split"] > 0
    assert candidate.params["a_minus_a0_area_ratio"] > 0
    assert candidate.params["defect_to_a_total_area_ratio"] > 0


def test_pl_summary_alias_is_not_double_counted_in_refit_synthesis() -> None:
    x = np.linspace(1.7, 1.95, 200)
    params = {
        "line_profile": "pvoigt",
        "bg_slope": 0.0,
        "bg_intercept": 1.0,
        "a_minus_position": 1.84,
        "a_minus_area": 2.0,
        "a_minus_sigma": 0.04,
        "a_minus_fraction": 0.5,
        "a_minus_line_profile": "pvoigt",
        "pl_position": 1.84,
        "pl_area": 2.0,
        "pl_sigma": 0.04,
        "pl_fraction": 0.5,
        "pl_line_profile": "pvoigt",
    }

    with_alias = dict(params)
    without_alias = dict(params)
    for key in ("pl_position", "pl_area", "pl_sigma", "pl_fraction", "pl_line_profile"):
        without_alias.pop(key)

    assert np.allclose(_synthesize_fitted_y(x, with_alias), _synthesize_fitted_y(x, without_alias))
