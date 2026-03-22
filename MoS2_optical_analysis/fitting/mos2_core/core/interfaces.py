"""Abstract stage interfaces for the MoS2 spectra pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping, Sequence

from .types import (
    AcceptedResult,
    BaselineResult,
    ConfidenceResult,
    FitEnsembleResult,
    MapAnalysisResult,
    ParameterSet,
    PipelineContext,
    PipelineResult,
    PreprocessedSpectrum,
    QCSummary,
    ReportArtifact,
    ReviewDecision,
    ReviewItem,
    SelectionResult,
    SpectrumRecord,
)


class QCStage(ABC):
    """Validate raw spectra and return pass/fail details per spectrum."""

    @abstractmethod
    def run(
        self,
        spectra: Sequence[SpectrumRecord],
        context: PipelineContext,
    ) -> tuple[list[SpectrumRecord], Mapping[str, QCSummary]]:
        raise NotImplementedError


class PreprocessingStage(ABC):
    """Transform QC-passed raw spectra into analysis-ready spectra."""

    @abstractmethod
    def run(
        self,
        spectra: Sequence[SpectrumRecord],
        context: PipelineContext,
    ) -> list[PreprocessedSpectrum]:
        raise NotImplementedError


class BaselineEnsembleStage(ABC):
    """Run baseline ensemble and pick a baseline per spectrum."""

    @abstractmethod
    def run(
        self,
        spectra: Sequence[PreprocessedSpectrum],
        context: PipelineContext,
    ) -> Mapping[str, BaselineResult]:
        raise NotImplementedError


class ModelEnsembleFittingStage(ABC):
    """Fit candidate models on baseline-corrected spectra."""

    @abstractmethod
    def run(
        self,
        spectra: Sequence[PreprocessedSpectrum],
        baselines: Mapping[str, BaselineResult],
        context: PipelineContext,
    ) -> Mapping[str, FitEnsembleResult]:
        raise NotImplementedError


class ModelSelectionStage(ABC):
    """Select the best model candidate for each spectrum."""

    @abstractmethod
    def run(
        self,
        fit_results: Mapping[str, FitEnsembleResult],
        context: PipelineContext,
    ) -> Mapping[str, SelectionResult]:
        raise NotImplementedError


class PostSelectionQCStage(ABC):
    """Run dataset-level QC rules on selected models before confidence scoring."""

    @abstractmethod
    def run(
        self,
        selections: Mapping[str, SelectionResult],
        context: PipelineContext,
    ) -> Mapping[str, SelectionResult]:
        raise NotImplementedError


class ConfidenceScoringStage(ABC):
    """Score fit quality/confidence and decide review eligibility."""

    @abstractmethod
    def run(
        self,
        selections: Mapping[str, SelectionResult],
        context: PipelineContext,
    ) -> Mapping[str, ConfidenceResult]:
        raise NotImplementedError


class ReviewQueueStage(ABC):
    """Create manual review queue from low-confidence selections."""

    @abstractmethod
    def run(
        self,
        selections: Mapping[str, SelectionResult],
        confidence: Mapping[str, ConfidenceResult],
        context: PipelineContext,
    ) -> list[ReviewItem]:
        raise NotImplementedError


class ManualReviewStage(ABC):
    """Apply reviewer decisions, manual refits, and final acceptance."""

    @abstractmethod
    def run(
        self,
        selections: Mapping[str, SelectionResult],
        baselines: Mapping[str, BaselineResult],
        review_items: Sequence[ReviewItem],
        context: PipelineContext,
    ) -> tuple[list[AcceptedResult], list[ReviewDecision]]:
        raise NotImplementedError


class ParameterExtractionStage(ABC):
    """Extract final scientific parameters from accepted results."""

    @abstractmethod
    def run(
        self,
        accepted: Sequence[AcceptedResult],
        context: PipelineContext,
    ) -> list[ParameterSet]:
        raise NotImplementedError


class MapAnalysisStage(ABC):
    """Build and analyze spatial maps from extracted parameters."""

    @abstractmethod
    def run(
        self,
        parameters: Sequence[ParameterSet],
        context: PipelineContext,
    ) -> list[MapAnalysisResult]:
        raise NotImplementedError


class ReportGenerationStage(ABC):
    """Generate final artifacts and reports from pipeline outputs."""

    @abstractmethod
    def run(
        self,
        result: PipelineResult,
        context: PipelineContext,
    ) -> list[ReportArtifact]:
        raise NotImplementedError
