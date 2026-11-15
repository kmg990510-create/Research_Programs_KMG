"""Stage 5 tests: V_S_rim sites, 1D E(z) well extraction, D3 ablation, TMA, and benchmark suite."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ads_core.benchmark import BENCHMARK_CASES, run_benchmark_suite
from ads_core.builders.poses import find_adsorption_sites
from ads_core.builders.slab import build_mos2_slab
from ads_core.cli import main as cli_main
from ads_core.config import load_config
from ads_core.model import (
    DEFECT_PRISTINE,
    DEFECT_VS,
    ORIENTATION_FLAT,
    SITE_HOLLOW,
    SITE_S_TOP,
    SITE_VS,
    SITE_VS_RIM,
    STATUS_INVALID,
)
from ads_core.pipeline import run_batch
from ads_core.report.export import BINDING_CURVES_SUMMARY_FILE, binding_curves_summary_table, export_run, load_batch_run
from ads_core.simulation.quality import counts_in_summary

_HAS_MACE_D3 = find_spec("mace") is not None and find_spec("torch_dftd") is not None
_HAS_MATTERSIM_D3 = find_spec("mattersim") is not None and find_spec("torch_dftd") is not None


def test_defect_rim_site_generated_on_vs_slab() -> None:
    cfg = load_config()
    pristine = build_mos2_slab(cfg, supercell=(3, 3), defect_type=DEFECT_PRISTINE)
    vs_slab = build_mos2_slab(cfg, supercell=(3, 3), defect_type=DEFECT_VS)

    pristine_sites = find_adsorption_sites(pristine, cfg)
    vs_sites = find_adsorption_sites(vs_slab, cfg)

    assert not any(s.site_type == SITE_VS_RIM for s in pristine_sites)
    rim_sites = [s for s in vs_sites if s.site_type == SITE_VS_RIM]
    assert len(rim_sites) == 1
    assert rim_sites[0].source == "defect_rim"

    # Rim site must coincide horizontally with one of the Mo atoms near the vacancy
    tags = vs_slab.atoms.get_tags()
    mo_xy = vs_slab.atoms.get_positions()[tags == 1, :2]
    assert float(np.min(np.linalg.norm(mo_xy - np.array(rim_sites[0].xy_A), axis=1))) < 1.0e-5


def test_binding_curve_equilibrium_extraction_d3_vs_nod3(tmp_path: Path) -> None:
    cfg = load_config()
    run = run_batch(
        "curve_well_check",
        cfg,
        surfaces=["pristine_2x2"],
        molecules=["H2O"],
        backend="synth_morse",
        d3_enabled=True,
        site_types=[SITE_HOLLOW],
        orientations=[ORIENTATION_FLAT],
        azimuth_angles_deg=[0.0],
        scan_binding_curves=True,
        compare_no_d3=True,
    )

    assert len(run.binding_curves) == 2
    d3_curve = next(c for c in run.binding_curves if c.d3_enabled)
    nod3_curve = next(c for c in run.binding_curves if not c.d3_enabled)

    assert d3_curve.has_attractive_well is True
    assert d3_curve.dz_eq_A is not None and 2.0 <= d3_curve.dz_eq_A <= 4.0
    assert d3_curve.e_min_total_eV is not None and d3_curve.e_min_total_eV < -0.05
    assert nod3_curve.has_attractive_well is False
    assert nod3_curve.dz_eq_A is None

    # Verify persistence + reload preserves equilibrium well descriptors and writes CSV summary
    out_dir = tmp_path / "out"
    export_run(run, None, out_dir)
    assert (out_dir / BINDING_CURVES_SUMMARY_FILE).is_file()
    summary_df = binding_curves_summary_table(run.binding_curves)
    assert len(summary_df) == 2

    reloaded = load_batch_run(out_dir)
    reloaded_d3 = next(c for c in reloaded.binding_curves if c.d3_enabled)
    assert reloaded_d3.has_attractive_well is True
    assert reloaded_d3.dz_eq_A == pytest.approx(d3_curve.dz_eq_A)
    assert reloaded_d3.e_min_total_eV == pytest.approx(d3_curve.e_min_total_eV)


def test_run_batch_compare_no_d3_and_scan_all_sites() -> None:
    cfg = load_config()
    run = run_batch(
        "ablation_multisite",
        cfg,
        surfaces=["V_S_2x2"],
        molecules=["H2O"],
        backend="synth_morse",
        d3_enabled=True,
        site_types=[SITE_VS, SITE_VS_RIM, SITE_HOLLOW, SITE_S_TOP],
        orientations=[ORIENTATION_FLAT],
        azimuth_angles_deg=[0.0],
        scan_binding_curves=True,
        scan_all_sites=True,
        compare_no_d3=True,
    )

    # 4 sites x 1 orientation x 2 calculator modes (+D3 and __nod3) = 8 pose results and 8 1D curves
    assert len(run.results) == 8
    assert any(r.pose_id.endswith("__nod3") and not r.d3_enabled for r in run.results)
    assert any((not r.pose_id.endswith("__nod3")) and r.d3_enabled for r in run.results)
    assert len(run.binding_curves) == 8
    assert {c.site_type for c in run.binding_curves if c.d3_enabled} == {SITE_VS, SITE_VS_RIM, SITE_HOLLOW, SITE_S_TOP}


def test_tma_intact_on_pristine_and_vs() -> None:
    cfg = load_config()
    run = run_batch(
        "tma_check",
        cfg,
        surfaces=["pristine_2x2", "V_S_2x2"],
        molecules=["TMA"],
        backend="synth_morse",
        d3_enabled=True,
        site_types=[SITE_HOLLOW, SITE_VS],
        orientations=[ORIENTATION_FLAT],
        azimuth_angles_deg=[0.0],
        scan_binding_curves=False,
    )

    pristine_res = [r for r in run.results if r.defect_type == DEFECT_PRISTINE]
    vs_res = [r for r in run.results if r.defect_type == DEFECT_VS and counts_in_summary(r.status)]
    assert len(pristine_res) == 1
    assert len(vs_res) >= 1

    r_pr = pristine_res[0]
    r_vs = min(vs_res, key=lambda r: float(r.e_ads_eV or 0.0))
    assert r_pr.converged and r_pr.status != STATUS_INVALID
    assert "unexpected_dissociation" not in r_pr.reasons
    assert r_pr.e_ads_eV is not None and -1.2 <= r_pr.e_ads_eV <= -0.1
    assert r_pr.vdw_fraction is not None and r_pr.vdw_fraction >= 0.70

    assert r_vs.converged and r_vs.status != STATUS_INVALID
    assert "dissociation_candidate" not in r_vs.reasons
    assert r_vs.e_ads_eV is not None and r_vs.e_ads_eV < r_pr.e_ads_eV - 0.15


def test_benchmark_suite_passes_on_synth_morse() -> None:
    cfg = load_config()
    report = run_benchmark_suite(cfg, backend="synth_morse", repeat_2x2=True)
    assert report.all_passed is True
    assert len(report.cases) == len(BENCHMARK_CASES)
    for case_res in report.cases:
        assert case_res.passed is True, f"{case_res.case_id} failed: {case_res.notes}"
    for mol, delta in report.defect_deltas_eV.items():
        assert delta < -0.15, f"{mol} V_S stabilization too weak: {delta:+.3f} eV"


def test_cli_benchmark_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_csv = tmp_path / "bench.csv"
    rc = cli_main(["benchmark", "--backend", "synth_morse", "--fast", "--out-csv", str(out_csv)])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "all_passed=True" in captured
    assert out_csv.is_file()
    df = pd.read_csv(out_csv, encoding="utf-8-sig")
    assert len(df) == len(BENCHMARK_CASES)
    assert bool(df["passed"].all())


@pytest.mark.skipif(not _HAS_MACE_D3, reason="mace-torch and torch-dftd are not installed in this environment")
def test_live_mace_mp_if_installed() -> None:  # pragma: no cover
    cfg = load_config()
    report = run_benchmark_suite(cfg, backend="mace_mp", repeat_2x2=True)
    assert report.all_passed is True


@pytest.mark.skipif(not _HAS_MATTERSIM_D3, reason="mattersim and torch-dftd are not installed in this environment")
def test_live_mattersim_if_installed() -> None:  # pragma: no cover
    cfg = load_config()
    report = run_benchmark_suite(cfg, backend="mattersim", repeat_2x2=True)
    assert report.all_passed is True
