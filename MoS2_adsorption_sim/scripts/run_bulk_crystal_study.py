"""CLI entrypoint for YAML-driven 4-ATP Pca2_1 bulk crystal & (001) surface cohesive study."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ads_core.simulation.bulk_crystal import run_bulk_crystal_study


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bulk 4-ATP Pca2_1 crystal cohesive energy study.")
    parser.add_argument("--config", required=True, help="Path to bulk crystal YAML (e.g. configs/4atp_bulk_pca21.yaml)")
    parser.add_argument("--backend", default=None, help="Optional calculator backend override")
    parser.add_argument("--device", default=None, help="Optional device override (auto/cpu/cuda)")
    args = parser.parse_args()

    t0 = time.time()
    out = run_bulk_crystal_study(args.config, backend_override=args.backend, device_override=args.device)
    print(f"Completed bulk crystal study in {time.time() - t0:.1f}s -> {out['output_dir']}", flush=True)
    print("\n=== BULK Pca2_1 4-ATP POLYMORPHS (Neutral vs Zwitterion) ===", flush=True)
    for r in out["crystals"]:
        d3 = "None" if r["e_coh_d3_per_mol_eV"] is None else f"{r['e_coh_d3_per_mol_eV']:+.3f}"
        print(
            f"{r['case_id']:24s} | {r['mode']:14s} | E_coh={r['e_coh_per_mol_eV']:+.3f} eV/mol "
            f"(u={r['e_coh_umlip_per_mol_eV']:+.3f}, d3={d3}) | "
            f"abc=({r['a_A']:.2f},{r['b_A']:.2f},{r['c_A']:.2f}) rho={r['density_g_cm3']:.2f} g/cm3 | "
            f"d_inter={r['min_intermol_A']:.2f}A d_NS={r['min_N_S_A']:.2f}A (SH={r['sh_bonds_count']}, NH={r['nh_bonds_count']}) | conv={r['converged']}",
            flush=True,
        )

    print(f"\n=== BULK VACANCY & (001) CRYSTAL SURFACE DETACHMENT (best={out['best_crystal_case']}) ===", flush=True)
    for row in out["surface_desorption"]:
        gam = "" if row["cleavage_energy_eV_per_A2"] == "" else f" | gamma={float(row['cleavage_energy_eV_per_A2']):.4f} eV/A^2"
        print(f"  {row['metric_id']:32s} | E_des={row['e_des_eV']:.3f} eV{gam} | conv={row['converged']}", flush=True)


if __name__ == "__main__":
    main()
