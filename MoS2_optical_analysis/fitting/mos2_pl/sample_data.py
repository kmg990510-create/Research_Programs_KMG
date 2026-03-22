"""PL synthetic data helpers."""

from __future__ import annotations

import math
from typing import Sequence

from fitting.mos2_core.core.types import SpectrumRecord


def generate_dummy_pl_spectra(count: int = 8) -> Sequence[SpectrumRecord]:
    x = [520.0 + i * 0.5 for i in range(520)]
    output: list[SpectrumRecord] = []

    for idx in range(count):
        center = 645.0 + (idx % 4) * 4.0
        amplitude = 120.0 + idx * 8.0
        width = 8.0 + (idx % 2) * 2.0
        y = [12.0 + 0.02 * i + amplitude * math.exp(-((v - center) ** 2) / (2.0 * width * width)) for i, v in enumerate(x)]
        output.append(
            SpectrumRecord(
                spectrum_id=f"pl_{idx:03d}",
                x=x,
                y=y,
                modality="pl",
                metadata={"map_id": "pl_dummy", "modality": "pl"},
            )
        )

    return output
