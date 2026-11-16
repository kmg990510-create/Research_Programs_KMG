"""CLI entrypoint for Step 1-2 local-basin, sheet-strain, and double-vacancy checks."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ads_core.simulation.stability import run_stability_checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YAML-configured monolayer stability checks.")
    parser.add_argument("--config", required=True, help="Path to stability YAML (e.g. configs/mos2_5x5_4atp_mechanical.yaml)")
    parser.add_argument("--backend", default=None, help="Optional calculator backend override")
    parser.add_argument("--device", default=None, help="Optional device override (auto/cpu/cuda)")
    parser.add_argument(
        "--only",
        nargs="+",
        default=("perturbation", "strain", "double_vacancy"),
        choices=("perturbation", "strain", "double_vacancy"),
        help="Subset of checks to run",
    )
    args = parser.parse_args()

    t0 = time.time()
    out = run_stability_checks(
        args.config,
        backend_override=args.backend,
        device_override=args.device,
        checks=tuple(args.only),
    )
    print(f"Completed stability checks in {time.time() - t0:.1f}s -> {out['results_dir']}", flush=True)

    print("\n=== PERTURBATION RE-RELAXATION CHECK ===", flush=True)
    for row in out["perturbation"]:
        print(
            f"  {row['case_id']:28s} amp={row['amplitude_A']:.2f}A | dE={row['delta_E_eV']:+.4f} eV | "
            f"RMSD={row['heavy_rmsd_A']:.3f}A | tilt={row['tilt_orig_deg']:.1f}->{row['tilt_rerelax_deg']:.1f} deg | "
            f"basin={row['returns_to_basin']}",
            flush=True,
        )

    print("\n=== STANDALONE SHEET STRAIN SCAN ===", flush=True)
    for row in out["strain"]:
        p2d = "N/A" if row["lateral_pressure_2D_N_per_m"] is None else f"{row['lateral_pressure_2D_N_per_m']:+.3f} N/m"
        print(
            f"  {row['case_id']:20s} scale={row['scale_factor']:.2f} ({row['area_per_mol_A2']:5.2f} A2/mol) | "
            f"E_lat/mol={row['e_lat_per_mol_eV']:+.4f} eV | P2D={p2d} | "
            f"tilt={row['mean_tilt_deg']:4.1f} deg | conv={row['converged']}",
            flush=True,
        )

    print("\n=== DOUBLE VACANCY (N4 -> N3_vac -> N2_2vac) ===", flush=True)
    for row in out["double_vacancy"]:
        print(
            f"  {row['source_case']:20s} idx={row['second_remove_idx']} (N->2) | "
            f"E_des,2nd={row['e_des_2nd_vac_eV']:.3f} eV | conv={row['converged']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
