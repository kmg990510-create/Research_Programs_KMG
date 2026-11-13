"""Standard internal data model.

Every instrument file becomes a list of ``Measurement`` objects before any
analysis. Analysis code never sees vendor sheet names or column labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from fet_core.config import Config

# Columns of every measurement table, in acquisition order, SI units (V, A, s).
# A quantity the instrument did not record is an all-NaN column.
STANDARD_COLUMNS = ("Vg", "Vd", "Vs", "Id", "Ig", "Is", "time")
REQUIRED_COLUMNS = ("Vg", "Id")

CURVE_TRANSFER = "transfer"
CURVE_OUTPUT = "output"
CURVE_UNKNOWN = "unknown"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"

VACUUM_PERMITTIVITY_F_PER_M = 8.8541878128e-12


@dataclass(frozen=True)
class WarningRecord:
    """One quality problem. ``code`` names the cause; ``message`` is for people."""

    code: str
    message: str
    source_file: str
    run_id: str | None = None
    severity: str = SEVERITY_WARNING
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeviceGeometry:
    """Channel geometry and gate dielectric. Units are in the field names."""

    W_um: float
    L_um: float
    t_ox_nm: float
    eps_r: float

    def __post_init__(self) -> None:
        for name in ("W_um", "L_um", "t_ox_nm", "eps_r"):
            value = getattr(self, name)
            if not value > 0:
                raise ValueError(f"{name} must be positive, got {value!r}")

    @classmethod
    def from_config(cls, config: Config) -> "DeviceGeometry":
        return cls(
            W_um=config.number("device.W_um"),
            L_um=config.number("device.L_um"),
            t_ox_nm=config.number("device.t_ox_nm"),
            eps_r=config.number("device.eps_r"),
        )

    @property
    def cox_F_per_m2(self) -> float:
        """Gate capacitance per area, parallel-plate: eps0 * eps_r / t_ox."""
        return VACUUM_PERMITTIVITY_F_PER_M * self.eps_r / (self.t_ox_nm * 1e-9)

    @property
    def width_over_length(self) -> float:
        return self.W_um / self.L_um


@dataclass(frozen=True, eq=False)
class Measurement:
    """One sweep run of one device, as acquired."""

    source_file: Path
    source_sha256: str
    instrument: str
    run_id: str  # unique within ``source_file`` only
    label: str  # device name as the operator wrote it
    group: str  # sample group derived from ``label``
    position: str | None  # device position such as "B3", when the label has one
    curve_type: str
    data: pd.DataFrame  # STANDARD_COLUMNS, float, rows in acquisition order
    # Sweep conditions read from the file header. A value the header does not give is None.
    conditions: dict[str, Any] = field(default_factory=dict)
    # Reader-specific facts kept for traceability (source column names, raw header values).
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        """Identity of a run: file name plus run id."""
        return (self.source_file.name, self.run_id)


@dataclass(frozen=True)
class InputFile:
    """What happened to one file in the input folder."""

    path: Path
    sha256: str
    reader: str | None
    status: str  # "read" or "skipped"
    reason: str = ""
    measurement_count: int = 0


@dataclass
class LoadResult:
    measurements: list[Measurement] = field(default_factory=list)
    warnings: list[WarningRecord] = field(default_factory=list)
    files: list[InputFile] = field(default_factory=list)
