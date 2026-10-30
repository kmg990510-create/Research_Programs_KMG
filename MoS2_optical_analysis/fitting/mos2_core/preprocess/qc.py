"""Default QC stage implementations."""

from __future__ import annotations

from typing import Mapping, Sequence

from ..core.interfaces import QCStage
from ..core.types import PipelineContext, QCSummary, SpectrumRecord
from ..io import config_access as cfgx


class PassThroughQC(QCStage):
    """
    Lightweight QC that passes spectra unless shape is clearly invalid.

    This keeps the pipeline moving during early development while still
    catching malformed inputs. The minimum point count is `{modality}.input_qc.min_points`.
    """

    def run(
        self,
        spectra: Sequence[SpectrumRecord],
        context: PipelineContext,
    ) -> tuple[list[SpectrumRecord], Mapping[str, QCSummary]]:
        passed: list[SpectrumRecord] = []
        summaries: dict[str, QCSummary] = {}
        min_points_by_modality: dict[str, int] = {}

        for record in spectra:
            modality = str(record.modality).strip().lower()
            if modality not in min_points_by_modality:
                qc_cfg = cfgx.section(cfgx.section(context.config, modality, ""), "input_qc", modality)
                min_points_by_modality[modality] = cfgx.integer(qc_cfg, "min_points", f"{modality}.input_qc")
            n_x = len(record.x)
            n_y = len(record.y)
            issues: list[str] = []

            if n_x != n_y:
                issues.append("x_y_length_mismatch")
            if n_x < min_points_by_modality[modality]:
                issues.append("too_few_points")

            qc = QCSummary(
                passed=not issues,
                issues=issues,
                metrics={"n_points": float(n_x)},
            )
            summaries[record.spectrum_id] = qc

            if qc.passed:
                passed.append(record)

        context.state["qc_total"] = len(spectra)
        context.state["qc_passed"] = len(passed)
        context.state["qc_failed"] = len(spectra) - len(passed)
        return passed, summaries

