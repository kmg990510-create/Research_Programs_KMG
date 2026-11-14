"""Run one batch folder in memory: load, analyse, apply the review.

Nothing here writes to disk. ``fet_core.report.export`` does that, after a
person has looked at the result.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from fet_core.analysis.results import STATUS_INVALID, TransferAnalysis, counts_in_summary
from fet_core.analysis.settings import AnalysisSettings
from fet_core.analysis.transfer import analyze_transfer_batch, results_table
from fet_core.config import Config
from fet_core.io.loader import load_folder
from fet_core.model import DeviceGeometry, LoadResult, Measurement
from fet_core.review import DECISION_REJECTED, ReviewState


@dataclass
class Run:
    """Everything known about one analysed batch."""

    name: str
    input_dir: Path
    config: Config
    settings: AnalysisSettings
    geometry: DeviceGeometry
    loaded: LoadResult
    analysis: TransferAnalysis

    def measurement(self, source_file: str, run_id: str) -> Measurement:
        for item in self.loaded.measurements:
            if item.key == (source_file, run_id):
                return item
        raise KeyError((source_file, run_id))


def effective_geometry(config: Config, review: ReviewState) -> DeviceGeometry:
    """Batch default geometry: the review's value when set, else ``config.yaml``."""
    return DeviceGeometry(**review.geometry) if review.geometry else DeviceGeometry.from_config(config)


def effective_settings(config: Config, review: ReviewState) -> AnalysisSettings:
    settings = AnalysisSettings.from_config(config)
    if review.vth_subtract_half_vds is not None:
        settings = replace(settings, vth_subtract_half_vds=bool(review.vth_subtract_half_vds))
    if review.vth_const_current_nA_per_um is not None:
        settings = replace(settings, vth_const_current_nA_per_um=float(review.vth_const_current_nA_per_um))
    return settings


def run_folder(input_dir: Path | str, config: Config, review: ReviewState | None = None) -> Run:
    """Load ``input_dir`` and analyse its transfer curves with the review's inputs."""
    review = review or ReviewState()
    directory = Path(input_dir)
    settings = effective_settings(config, review)
    geometry = effective_geometry(config, review)
    loaded = load_folder(directory, config)
    overrides = {}
    for item in loaded.measurements:
        device = review.device_geometry(item.source_file.name, item.run_id)
        if device is not None:
            overrides[item.key] = device
    analysis = analyze_transfer_batch(loaded.measurements, geometry, settings, overrides)
    return Run(directory.name, directory, config, settings, geometry, loaded, analysis)


def results_frame(run: Run, review: ReviewState | None = None) -> pd.DataFrame:
    """Result table with the review applied.

    Adds ``decision``, ``note``, ``group_display``, ``included`` (counts in the
    statistics: not invalid and not rejected) and width-normalised currents.
    """
    review = review or ReviewState()
    frame = results_table(run.analysis.results)
    if frame.empty:
        return frame
    decisions, notes, included = [], [], []
    for result in run.analysis.results:
        decision = review.decision(result.source_file, result.run_id, result.sweep)
        decisions.append(decision)
        notes.append(review.notes.get(f"{result.source_file}|{result.run_id}|{result.sweep}", ""))
        included.append(counts_in_summary(result) and decision != DECISION_REJECTED)
    frame["decision"] = decisions
    frame["note"] = notes
    frame["included"] = included
    frame["group_display"] = [review.display_group(group) for group in frame["group"]]
    frame["i_on_uA_per_um"] = frame["i_on_A"] * 1e6 / frame["W_um"]
    frame["gm_peak_uS_per_um"] = frame["gm_peak_S"] * 1e6 / frame["W_um"]
    return frame


def ordered_groups(frame: pd.DataFrame, review: ReviewState | None = None) -> list[str]:
    """Display groups in the review's order, then the rest in order of appearance."""
    present = list(dict.fromkeys(frame["group_display"])) if not frame.empty else []
    preferred = [name for name in (review.group_order if review else []) if name in present]
    return preferred + [name for name in present if name not in preferred]


def status_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts = {"valid": 0, "attention": 0, STATUS_INVALID: 0}
    if not frame.empty:
        counts.update({str(k): int(v) for k, v in frame["status"].value_counts().items()})
    return counts
