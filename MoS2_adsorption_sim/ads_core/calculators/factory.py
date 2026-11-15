"""Calculator factory assembling uMLIP + DFT-D3 SumCalculator or synthetic test backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import ase
from ase.calculators.calculator import Calculator
from ase.calculators.mixing import SumCalculator
from ase.units import Bohr

from ads_core.calculators.synth_calc import SynthD3Calculator, SynthUmlipCalculator
from ads_core.config import Config
from ads_core.model import CalculatorSettings, VALID_BACKENDS


@dataclass(frozen=True)
class CalculatorBundle:
    """Paired total, uMLIP-only, and D3-only calculators for energy decomposition."""

    calculator_id: str
    backend: str
    d3_enabled: bool
    total_calc: Calculator
    umlip_calc: Calculator
    d3_calc: Calculator | None
    metadata: dict[str, Any] = field(default_factory=dict)


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _build_mace_calculator(settings: CalculatorSettings, device: str) -> tuple[Calculator, str]:
    try:
        import mace
        from mace.calculators import mace_mp
    except ImportError as exc:
        raise RuntimeError(
            "mace-torch is not installed. Install it in your WSL2 environment "
            "(`pip install mace-torch`) or use backend='synth_morse' for testing."
        ) from exc

    calc = mace_mp(
        model=settings.mace_model,
        device=device,
        default_dtype=settings.mace_dtype,
        dispersion=False,
    )
    return calc, getattr(mace, "__version__", "unknown")


def _build_mattersim_calculator(settings: CalculatorSettings, device: str) -> tuple[Calculator, str]:
    try:
        import mattersim
        from mattersim.forcefield.potential import MatterSimCalculator
    except ImportError as exc:
        raise RuntimeError(
            "mattersim is not installed. Install it in your WSL2 environment "
            "(`pip install mattersim`) or use backend='synth_morse' for testing."
        ) from exc

    calc = MatterSimCalculator(
        load_path=settings.mattersim_load_path,
        device=device,
    )
    return calc, getattr(mattersim, "__version__", "unknown")


def _build_torch_dftd3(settings: CalculatorSettings, device: str) -> tuple[Calculator, str]:
    try:
        import torch_dftd
        from torch_dftd.torch_dftd3_calculator import TorchDFTD3Calculator
    except ImportError as exc:
        raise RuntimeError(
            "torch-dftd is not installed. Install it in your WSL2 environment "
            "(`pip install torch-dftd`) or disable D3 / use backend='synth_morse'."
        ) from exc

    calc = TorchDFTD3Calculator(
        device=device,
        damping=settings.d3_damping,
        xc=settings.d3_xc,
        cutoff=settings.d3_cutoff_bohr * Bohr,
    )
    return calc, getattr(torch_dftd, "__version__", "unknown")


def build_calculator_bundle(
    config: Config,
    *,
    backend: str | None = None,
    d3_enabled: bool | None = None,
    device: str | None = None,
) -> CalculatorBundle:
    """Build ``CalculatorBundle`` from ``config.yaml`` with optional runtime overrides."""
    settings = CalculatorSettings.from_config(config)
    chosen_backend = backend if backend is not None else settings.backend
    if chosen_backend not in VALID_BACKENDS:
        raise ValueError(f"Unsupported backend {chosen_backend!r}; expected one of {VALID_BACKENDS}")

    chosen_d3 = settings.d3_enabled if d3_enabled is None else bool(d3_enabled)
    chosen_device = _resolve_device(device if device is not None else settings.device)

    meta: dict[str, Any] = {
        "ase_version": ase.__version__,
        "backend": chosen_backend,
        "device": chosen_device,
        "d3_enabled": chosen_d3,
    }

    if chosen_backend == "synth_morse":
        umlip_calc: Calculator = SynthUmlipCalculator(
            mo_s_de_eV=settings.synth_mo_s_de_eV,
            mo_s_r0_A=settings.synth_mo_s_r0_A,
            mo_adsorbate_de_eV=settings.synth_mo_adsorbate_de_eV,
            mo_adsorbate_r0_A=settings.synth_mo_adsorbate_r0_A,
            s_repulsion_eV=settings.synth_s_repulsion_eV,
        )
        d3_calc: Calculator | None = (
            SynthD3Calculator(
                c6_eV_A6=settings.synth_d3_c6_eV_A6,
                damp_r0_A=settings.synth_d3_damp_r0_A,
            )
            if chosen_d3
            else None
        )
        meta["model"] = "synth_morse_v1"
        if chosen_d3:
            meta["d3"] = {"xc": "synth_c6", "damping": "rational", "r0_A": settings.synth_d3_damp_r0_A}
    elif chosen_backend == "mace_mp":
        umlip_calc, backend_ver = _build_mace_calculator(settings, chosen_device)
        meta["backend_version"] = backend_ver
        meta["model"] = settings.mace_model
        meta["dtype"] = settings.mace_dtype
        if chosen_d3:
            d3_calc, d3_ver = _build_torch_dftd3(settings, chosen_device)
            meta["d3"] = {
                "version": d3_ver,
                "xc": settings.d3_xc,
                "damping": settings.d3_damping,
                "cutoff_bohr": settings.d3_cutoff_bohr,
            }
        else:
            d3_calc = None
    else:  # mattersim
        umlip_calc, backend_ver = _build_mattersim_calculator(settings, chosen_device)
        meta["backend_version"] = backend_ver
        meta["model"] = settings.mattersim_load_path
        if chosen_d3:
            d3_calc, d3_ver = _build_torch_dftd3(settings, chosen_device)
            meta["d3"] = {
                "version": d3_ver,
                "xc": settings.d3_xc,
                "damping": settings.d3_damping,
                "cutoff_bohr": settings.d3_cutoff_bohr,
            }
        else:
            d3_calc = None

    total_calc: Calculator = SumCalculator([umlip_calc, d3_calc]) if d3_calc is not None else umlip_calc
    calc_id = f"{chosen_backend}+d3" if chosen_d3 else f"{chosen_backend}_no_d3"

    return CalculatorBundle(
        calculator_id=calc_id,
        backend=chosen_backend,
        d3_enabled=chosen_d3,
        total_calc=total_calc,
        umlip_calc=umlip_calc,
        d3_calc=d3_calc,
        metadata=meta,
    )
