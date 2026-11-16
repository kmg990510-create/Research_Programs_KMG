"""CLI entrypoint for YAML-driven multi-molecule coverage and multilayer studies."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ads_core.simulation.coverage import run_coverage_study


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YAML-configured coverage/multilayer MoS2 study.")
    parser.add_argument("--study", required=True, help="Path to study YAML file (e.g. configs/track_a_4atp.yaml)")
    parser.add_argument("--backend", default=None, help="Optional calculator backend override")
    parser.add_argument("--device", default=None, help="Optional device override (auto/cpu/cuda)")
    args = parser.parse_args()

    t0 = time.time()
    out = run_coverage_study(
        args.study,
        backend_override=args.backend,
        device_override=args.device,
    )
    print(f"Completed study in {time.time() - t0:.1f}s -> {out['output_dir']}", flush=True)
    print("\n=== COVERAGE & LATERAL/SUBSTRATE/MULTILAYER DECOMPOSITION ===", flush=True)
    for cid, r in out["cases"].items():
        d3 = "None" if r.e_ads_d3_per_mol_eV is None else f"{r.e_ads_d3_per_mol_eV:+.3f}"
        d_int = "N/A" if r.min_intermol_heavy_A is None else f"{r.min_intermol_heavy_A:.2f}A"
        d_lay = "N/A" if r.interlayer_min_heavy_A is None else f"{r.interlayer_min_heavy_A:.2f}A"
        print(
            f"{cid:26s} | L{r.layer_index} N={r.n_molecules} | E_ads/mol={r.e_ads_per_mol_eV:+.3f} eV "
            f"(sub={r.e_sub_per_mol_eV:+.3f}, lat={r.e_lat_per_mol_eV:+.3f}, mos2={r.e_mos2_direct_per_mol_eV:+.3f}, d3={d3}) | "
            f"dz_base={r.dz_above_base_top_A:4.2f}A | tilt={r.mean_tilt_deg:4.1f} deg | "
            f"d_intra={d_int} d_inter={d_lay} | hb={r.hbond_pair_count}/{r.interlayer_hbond_count} | conv={r.converged}",
            flush=True,
        )

    print("\n=== SINGLE-MOLECULE DESORPTION ENERGIES ===", flush=True)
    for row in out["desorption"]:
        vert = "" if row["e_des_vertical_eV"] == "" else f" (vert={float(row['e_des_vertical_eV']):.3f})"
        print(f"  {row['desorption_id']:36s} | E_des={float(row['e_des_eV']):.3f} eV{vert} | conv={row['converged']}", flush=True)

    if out["disulfide"]:
        print("\n=== DISULFIDE COUPLING CHECK ===", flush=True)
        for row in out["disulfide"]:
            print(
                f"  {row['species']}: E_ads={row['e_ads_total_eV']:+.3f} eV (d3={row['e_ads_d3_eV']}) | "
                f"dE_H2(gas/ads)={row['rxn_2RSH_to_RSSR_H2_gas_eV']:+.3f}/{row['rxn_2RSH_to_RSSR_H2_ads_eV']:+.3f} eV | "
                f"dE_ox_H2O(gas/ads)={row['rxn_oxidative_H2O_gas_eV']:+.3f}/{row['rxn_oxidative_H2O_ads_eV']:+.3f} eV",
                flush=True,
            )


if __name__ == "__main__":
    main()
