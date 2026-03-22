"""Run an end-to-end dummy pipeline with synthetic spectra."""

from __future__ import annotations

from pathlib import Path

from ..io import generate_dummy_spectra
from .default_stages import build_default_context, build_default_stages
from .pipeline import run_pipeline


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    raw_spectra = generate_dummy_spectra(count=8)
    context = build_default_context(
        run_id="dummy_e2e",
        artifact_dir=project_root,
        config_dir=project_root / "config",
    )
    stages = build_default_stages(config=context.config)

    result = run_pipeline(raw_spectra=raw_spectra, stages=stages, context=context)

    print("Dummy pipeline run completed.")
    print(f"Configured Raman models: {context.config.get('raman', {}).get('models')}")
    print(f"Configured review threshold: {context.config.get('review', {}).get('confidence_threshold')}")
    print(f"QC total: {len(result.qc)}")
    print(f"Flagged for review: {len(result.flagged)}")
    print(f"Accepted results: {len(result.accepted)}")
    print(f"Extracted parameter sets: {len(result.parameters)}")
    print(f"Map results: {len(result.maps)}")
    if result.reports:
        print(f"Summary report: {result.reports[0].path}")


if __name__ == "__main__":
    main()
