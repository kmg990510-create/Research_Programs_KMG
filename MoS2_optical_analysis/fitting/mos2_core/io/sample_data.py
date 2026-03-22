"""Synthetic data helpers for local end-to-end tests."""

from __future__ import annotations

import math
from typing import Sequence

from ..core.types import SpectrumRecord


def _gaussian(x: float, center: float, width: float, amplitude: float) -> float:
    return amplitude * math.exp(-((x - center) ** 2) / (2 * width**2))


def generate_dummy_spectra(count: int = 6) -> Sequence[SpectrumRecord]:
    """
    Generate a small synthetic dataset with Raman-like peaks.

    Returned data is deterministic, so pipeline behavior is reproducible.
    """

    x = [350.0 + i * 0.5 for i in range(500)]
    output: list[SpectrumRecord] = []

    for idx in range(count):
        center = 385.0 + (idx % 3) * 0.8
        amplitude = 80.0 + idx * 5.0
        width = 2.5 + (idx % 2) * 0.5
        baseline = 10.0 + 0.02 * idx

        y = [baseline + _gaussian(v, center, width, amplitude) for v in x]
        output.append(
            SpectrumRecord(
                spectrum_id=f"spec_{idx:03d}",
                x=x,
                y=y,
                modality="raman",
                metadata={"map_id": "default_map"},
            )
        )

    return output

