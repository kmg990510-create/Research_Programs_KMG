"""Physical benchmark suite for validating MoS2 adsorption regimes and DFT-D3 necessity."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

import pandas as pd

from ads_core.config import Config
from ads_core.model import (
    DEFECT_PRISTINE,
    DEFECT_VS,
    ORIENTATION_ANCHOR_DOWN,
    ORIENTATION_FLAT,
    SITE_HOLLOW,
    SITE_VS,
    SITE_VS_RIM,
)
from ads_core.pipeline import run_batch
from ads_core.simulation.quality import counts_in_summary

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchmarkCase:
    """Expected physical regime and bounds for one molecule-surface benchmark."""

    case_id: str
    molecule_id: str
    defect_type: str
    expected_regime: str
    e_ads_min_bound_eV: float
    e_ads_max_bound_eV: float
    min_vdw_fraction: float | None = None
    requires_d3_well: bool = False


@dataclass(frozen=True)
class BenchmarkCaseResult:
    """Evaluated outcome of one benchmark case."""

    case_id: str
    molecule_id: str
    defect_type: str
    expected_regime: str
    best_pose_id: str
    best_site: str
    e_ads_eV: float | None
    e_ads_umlip_eV: float | None
    e_ads_d3_eV: float | None
    vdw_fraction: float | None
    d_min_A: float | None
    max_bond_stretch_pct: float | None
    d3_well_found: bool | None
    no_d3_well_found: bool | None
    passed: bool
    notes: str


@dataclass(frozen=True)
class BenchmarkSuiteReport:
    """Aggregated physical benchmark suite result."""

    backend: str
    calculator_id: str
    supercell: tuple[int, int]
    cases: tuple[BenchmarkCaseResult, ...]
    defect_deltas_eV: dict[str, float]
    all_passed: bool


BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        case_id="H2O_pristine",
        molecule_id="H2O",
        defect_type=DEFECT_PRISTINE,
        expected_regime="physisorption",
        e_ads_min_bound_eV=-0.80,
        e_ads_max_bound_eV=-0.05,
        min_vdw_fraction=0.70,
        requires_d3_well=True,
    ),
    BenchmarkCase(
        case_id="H2O_V_S",
        molecule_id="H2O",
        defect_type=DEFECT_VS,
        expected_regime="chemisorption",
        e_ads_min_bound_eV=-3.00,
        e_ads_max_bound_eV=-0.35,
    ),
    BenchmarkCase(
        case_id="NH3_pristine",
        molecule_id="NH3",
        defect_type=DEFECT_PRISTINE,
        expected_regime="physisorption",
        e_ads_min_bound_eV=-0.85,
        e_ads_max_bound_eV=-0.05,
        min_vdw_fraction=0.70,
        requires_d3_well=True,
    ),
    BenchmarkCase(
        case_id="NH3_V_S",
        molecule_id="NH3",
        defect_type=DEFECT_VS,
        expected_regime="chemisorption",
        e_ads_min_bound_eV=-3.00,
        e_ads_max_bound_eV=-0.35,
    ),
    BenchmarkCase(
        case_id="TMA_pristine",
        molecule_id="TMA",
        defect_type=DEFECT_PRISTINE,
        expected_regime="physisorption",
        e_ads_min_bound_eV=-1.20,
        e_ads_max_bound_eV=-0.10,
        min_vdw_fraction=0.70,
        requires_d3_well=True,
    ),
    BenchmarkCase(
        case_id="TMA_V_S",
        molecule_id="TMA",
        defect_type=DEFECT_VS,
        expected_regime="chemisorption",
        e_ads_min_bound_eV=-3.50,
        e_ads_max_bound_eV=-0.50,
    ),
)

_MIN_DEFECT_ENHANCEMENT_EV = 0.15


def run_benchmark_suite(
    config: Config,
    *,
    backend: str | None = None,
    repeat_2x2: bool = False,
) -> BenchmarkSuiteReport:
    """Execute standard adsorption physics checks (H2O, NH3, TMA on pristine vs V_S)."""
    sc = (2, 2) if repeat_2x2 else (config.integer("slab.supercell_nx"), config.integer("slab.supercell_ny"))
    surfaces = [f"{DEFECT_PRISTINE}_{sc[0]}x{sc[1]}", f"{DEFECT_VS}_{sc[0]}x{sc[1]}"]
    molecules = list(dict.fromkeys(c.molecule_id for c in BENCHMARK_CASES))

    LOGGER.info("Running benchmark suite on supercell %s with backend=%s", sc, backend or config.text("calculator.backend"))
    batch = run_batch(
        "benchmark",
        config,
        surfaces=surfaces,
        molecules=molecules,
        supercell=sc,
        backend=backend,
        d3_enabled=True,
        site_types=[SITE_HOLLOW, SITE_VS, SITE_VS_RIM],
        orientations=[ORIENTATION_FLAT, ORIENTATION_ANCHOR_DOWN],
        azimuth_angles_deg=[0.0],
        scan_binding_curves=True,
        compare_no_d3=True,
    )

    preliminary: list[BenchmarkCaseResult] = []
    pristine_e_by_mol: dict[str, float] = {}
    vs_e_by_mol: dict[str, float] = {}

    for case in BENCHMARK_CASES:
        valid_d3 = [
            r
            for r in batch.results
            if r.d3_enabled
            and r.defect_type == case.defect_type
            and r.molecule_id == case.molecule_id
            and counts_in_summary(r.status)
            and r.e_ads_eV is not None
        ]
        if not valid_d3:
            preliminary.append(
                BenchmarkCaseResult(
                    case_id=case.case_id,
                    molecule_id=case.molecule_id,
                    defect_type=case.defect_type,
                    expected_regime=case.expected_regime,
                    best_pose_id="",
                    best_site="",
                    e_ads_eV=None,
                    e_ads_umlip_eV=None,
                    e_ads_d3_eV=None,
                    vdw_fraction=None,
                    d_min_A=None,
                    max_bond_stretch_pct=None,
                    d3_well_found=None,
                    no_d3_well_found=None,
                    passed=False,
                    notes="no valid converged pose",
                )
            )
            continue

        best = min(valid_d3, key=lambda r: float(r.e_ads_eV))
        assert best.e_ads_eV is not None

        if case.defect_type == DEFECT_PRISTINE:
            pristine_e_by_mol[case.molecule_id] = best.e_ads_eV
        elif case.defect_type == DEFECT_VS:
            vs_e_by_mol[case.molecule_id] = best.e_ads_eV

        d3_curves = [
            c
            for c in batch.binding_curves
            if c.surface_id == best.surface_id and c.molecule_id == case.molecule_id and c.d3_enabled
        ]
        nod3_curves = [
            c
            for c in batch.binding_curves
            if c.surface_id == best.surface_id and c.molecule_id == case.molecule_id and not c.d3_enabled
        ]
        d3_well = bool(d3_curves[0].has_attractive_well) if d3_curves else None
        nod3_well = bool(nod3_curves[0].has_attractive_well) if nod3_curves else None

        failures: list[str] = []
        if not (case.e_ads_min_bound_eV <= best.e_ads_eV <= case.e_ads_max_bound_eV):
            failures.append(
                f"E_ads={best.e_ads_eV:.3f} outside [{case.e_ads_min_bound_eV:.2f}, {case.e_ads_max_bound_eV:.2f}]"
            )
        if case.min_vdw_fraction is not None:
            if best.vdw_fraction is None or best.vdw_fraction < case.min_vdw_fraction:
                failures.append(f"vdw_fraction={best.vdw_fraction} < {case.min_vdw_fraction:.2f}")
        if any(tag in best.reasons for tag in ("unexpected_dissociation", "dissociation_candidate")):
            failures.append("molecule dissociated")
        if case.requires_d3_well:
            if d3_well is not True:
                failures.append("missing +D3 1D attractive well")
            if nod3_well is not False:
                failures.append("unexpected attractive well without D3")

        preliminary.append(
            BenchmarkCaseResult(
                case_id=case.case_id,
                molecule_id=case.molecule_id,
                defect_type=case.defect_type,
                expected_regime=case.expected_regime,
                best_pose_id=best.pose_id,
                best_site=best.site_type,
                e_ads_eV=best.e_ads_eV,
                e_ads_umlip_eV=best.e_ads_umlip_eV,
                e_ads_d3_eV=best.e_ads_d3_eV,
                vdw_fraction=best.vdw_fraction,
                d_min_A=best.d_min_A,
                max_bond_stretch_pct=best.max_bond_stretch_pct,
                d3_well_found=d3_well,
                no_d3_well_found=nod3_well,
                passed=not failures,
                notes="; ".join(failures) if failures else "ok",
            )
        )

    defect_deltas_eV: dict[str, float] = {}
    final_cases: list[BenchmarkCaseResult] = []
    for item in preliminary:
        if item.defect_type == DEFECT_VS and item.molecule_id in vs_e_by_mol and item.molecule_id in pristine_e_by_mol:
            delta = float(vs_e_by_mol[item.molecule_id] - pristine_e_by_mol[item.molecule_id])
            defect_deltas_eV[item.molecule_id] = delta
            if delta >= -_MIN_DEFECT_ENHANCEMENT_EV:
                msg = f"V_S stabilization {delta:+.3f} eV weaker than -{_MIN_DEFECT_ENHANCEMENT_EV:.2f} eV"
                new_notes = msg if item.notes == "ok" else f"{item.notes}; {msg}"
                item = replace(item, passed=False, notes=new_notes)
        final_cases.append(item)

    all_passed = bool(final_cases) and all(c.passed for c in final_cases)
    return BenchmarkSuiteReport(
        backend=batch.backend,
        calculator_id=batch.calculator_id,
        supercell=sc,
        cases=tuple(final_cases),
        defect_deltas_eV=defect_deltas_eV,
        all_passed=all_passed,
    )


def benchmark_report_table(report: BenchmarkSuiteReport) -> pd.DataFrame:
    """Convert ``BenchmarkSuiteReport`` into a flat DataFrame for CLI/CSV reporting."""
    columns = [
        "case_id",
        "molecule_id",
        "defect_type",
        "expected_regime",
        "best_site",
        "e_ads_eV",
        "e_ads_umlip_eV",
        "e_ads_d3_eV",
        "vdw_fraction",
        "d_min_A",
        "max_bond_stretch_pct",
        "d3_well_found",
        "no_d3_well_found",
        "passed",
        "notes",
        "best_pose_id",
    ]
    if not report.cases:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "case_id": c.case_id,
            "molecule_id": c.molecule_id,
            "defect_type": c.defect_type,
            "expected_regime": c.expected_regime,
            "best_site": c.best_site,
            "e_ads_eV": c.e_ads_eV,
            "e_ads_umlip_eV": c.e_ads_umlip_eV,
            "e_ads_d3_eV": c.e_ads_d3_eV,
            "vdw_fraction": c.vdw_fraction,
            "d_min_A": c.d_min_A,
            "max_bond_stretch_pct": c.max_bond_stretch_pct,
            "d3_well_found": c.d3_well_found,
            "no_d3_well_found": c.no_d3_well_found,
            "passed": c.passed,
            "notes": c.notes,
            "best_pose_id": c.best_pose_id,
        }
        for c in report.cases
    ]
    return pd.DataFrame(rows, columns=columns)
