"""Per-(surface, molecule, calculator) summary with lowest-energy pose and Boltzmann average."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd
from ase.units import kB

# column -> (label, unit). Single source of truth for tables and compare plots.
METRICS: dict[str, tuple[str, str]] = {
    "e_ads_eV": ("Adsorption energy", "eV"),
    "e_ads_umlip_eV": ("uMLIP contribution", "eV"),
    "e_ads_d3_eV": ("DFT-D3 contribution", "eV"),
    "vdw_fraction": ("vdW fraction", ""),
    "e_int_eV": ("Interaction energy", "eV"),
    "e_def_slab_eV": ("Slab deformation", "eV"),
    "e_def_mol_eV": ("Molecule deformation", "eV"),
    "d_min_A": ("Min distance", "Å"),
    "dz_com_A": ("COM height", "Å"),
    "lateral_shift_A": ("Lateral shift", "Å"),
    "tilt_deg": ("Tilt change", "deg"),
    "max_bond_stretch_pct": ("Max bond stretch", "%"),
    "slab_rmsd_A": ("Slab RMSD", "Å"),
}


def metric_label(column: str) -> str:
    label, unit = METRICS[column]
    return f"{label} ({unit})" if unit else label


def boltzmann_weights(energies_eV: Sequence[float], temp_K: float) -> np.ndarray:
    """Normalized Boltzmann occupation probabilities w_i ~ exp(-(E_i - E_min) / kB T)."""
    if not temp_K > 0:
        raise ValueError(f"temp_K must be positive, got {temp_K!r}")
    arr = np.asarray(energies_eV, dtype=float)
    if arr.size == 0:
        return arr
    e_min = float(np.min(arr))
    exponent = np.clip(-(arr - e_min) / (float(kB) * float(temp_K)), -700.0, 0.0)
    weights = np.exp(exponent)
    return weights / np.sum(weights)


def molecule_summary(
    frame: pd.DataFrame,
    temp_K: float,
    groups: list[str] | None = None,
) -> pd.DataFrame:
    """Summarize each ``(surface, molecule, calculator)`` group over ``included`` poses."""
    columns = [
        "group_display",
        "surface_id",
        "defect_type",
        "molecule_id",
        "calculator_id",
        "n_poses",
        "n_included",
        "best_pose_id",
        "best_site",
        "e_ads_min_eV",
        "e_ads_boltzmann_eV",
        "boltzmann_temp_K",
        "e_ads_corrugation_eV",
        "e_ads_mean_eV",
        "e_ads_median_eV",
        "e_ads_std_eV",
        "e_ads_umlip_at_best_eV",
        "e_ads_d3_at_best_eV",
        "vdw_fraction_at_best",
        "e_int_at_best_eV",
        "e_def_slab_at_best_eV",
        "e_def_mol_at_best_eV",
        "d_min_at_best_A",
        "dz_com_at_best_A",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    names = groups if groups is not None else list(dict.fromkeys(frame["group_display"]))
    rows: list[dict[str, object]] = []
    for group in names:
        part = frame[frame["group_display"] == group]
        if part.empty:
            continue
        first = part.iloc[0]
        used = part[part["included"]].copy()
        used["e_ads_num"] = pd.to_numeric(used["e_ads_eV"], errors="coerce")
        valid_e = used.dropna(subset=["e_ads_num"])

        row: dict[str, object] = {
            "group_display": group,
            "surface_id": str(first["surface_id"]),
            "defect_type": str(first["defect_type"]),
            "molecule_id": str(first["molecule_id"]),
            "calculator_id": str(first["calculator_id"]),
            "n_poses": int(len(part)),
            "n_included": int(len(used)),
            "best_pose_id": None,
            "best_site": None,
            "e_ads_min_eV": None,
            "e_ads_boltzmann_eV": None,
            "boltzmann_temp_K": float(temp_K),
            "e_ads_corrugation_eV": None,
            "e_ads_mean_eV": None,
            "e_ads_median_eV": None,
            "e_ads_std_eV": None,
            "e_ads_umlip_at_best_eV": None,
            "e_ads_d3_at_best_eV": None,
            "vdw_fraction_at_best": None,
            "e_int_at_best_eV": None,
            "e_def_slab_at_best_eV": None,
            "e_def_mol_at_best_eV": None,
            "d_min_at_best_A": None,
            "dz_com_at_best_A": None,
        }

        if not valid_e.empty:
            energies = valid_e["e_ads_num"].to_numpy(dtype=float)
            best_idx = valid_e["e_ads_num"].idxmin()
            best = valid_e.loc[best_idx]
            probs = boltzmann_weights(energies, temp_K)

            def _opt_float(val: object) -> float | None:
                if val is None or pd.isna(val):
                    return None
                return float(val)

            row.update(
                {
                    "best_pose_id": str(best["pose_id"]),
                    "best_site": str(best["site_type"]),
                    "e_ads_min_eV": float(best["e_ads_num"]),
                    "e_ads_boltzmann_eV": float(np.sum(probs * energies)),
                    "e_ads_corrugation_eV": float(np.max(energies) - np.min(energies)),
                    "e_ads_mean_eV": float(np.mean(energies)),
                    "e_ads_median_eV": float(np.median(energies)),
                    "e_ads_std_eV": float(np.std(energies, ddof=1)) if len(energies) >= 2 else None,
                    "e_ads_umlip_at_best_eV": _opt_float(best["e_ads_umlip_eV"]),
                    "e_ads_d3_at_best_eV": _opt_float(best["e_ads_d3_eV"]),
                    "vdw_fraction_at_best": _opt_float(best["vdw_fraction"]),
                    "e_int_at_best_eV": _opt_float(best["e_int_eV"]),
                    "e_def_slab_at_best_eV": _opt_float(best["e_def_slab_eV"]),
                    "e_def_mol_at_best_eV": _opt_float(best["e_def_mol_eV"]),
                    "d_min_at_best_A": _opt_float(best["d_min_A"]),
                    "dz_com_at_best_A": _opt_float(best["dz_com_A"]),
                }
            )
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)
