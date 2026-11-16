"""CLI entrypoint for finite-temperature multi-molecule MD + post-MD quench verification."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ads_core.simulation.multimol_md import run_multimol_md_suite


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YAML-configured finite-temperature MD checks.")
    parser.add_argument("--config", required=True, help="Path to MD YAML (e.g. configs/mos2_5x5_4atp_md.yaml)")
    parser.add_argument("--backend", default=None, help="Optional calculator backend override")
    parser.add_argument("--device", default=None, help="Optional device override (auto/cpu/cuda)")
    args = parser.parse_args()

    t0 = time.time()
    out = run_multimol_md_suite(args.config, backend_override=args.backend, device_override=args.device)
    print(f"Completed MD suite in {time.time() - t0:.1f}s -> {out['output_dir']}", flush=True)
    for r in out["summary"]:
        qe = "N/A" if r["quench_delta_E_eV"] == "" else f"{float(r['quench_delta_E_eV']):+.4f} eV"
        qt = "N/A" if r["quench_tilt_deg"] == "" else f"{float(r['quench_tilt_deg']):.1f} deg"
        qs = "N/A" if r["quench_azimuth_spread_deg"] == "" else f"{float(r['quench_azimuth_spread_deg']):.1f} deg"
        print(
            f"  {r['run_id']:20s} | N={r['n_molecules']} | T={r['mean_temp_K']:5.1f}K ({r['total_ps']:.1f}ps) | "
            f"dz={r['mean_dz_A']:.2f}(max {r['max_dz_A']:.2f})A res={r['residence_fraction']:.2f} | "
            f"tilt={r['mean_tilt_deg']:4.1f}(max {r['max_tilt_deg']:4.1f})deg | "
            f"MSD_xy={r['final_msd_xy_A2']:6.2f}A^2 | rot_drift={r['mean_rot_drift_deg']:5.1f}deg | "
            f"az_spread={r['final_azimuth_spread_deg']:5.1f}deg | quench(dE={qe}, tilt={qt}, spread={qs})",
            flush=True,
        )


if __name__ == "__main__":
    main()
