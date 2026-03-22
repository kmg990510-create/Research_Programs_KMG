"""PL smoke run entrypoint under fitting layout."""

from __future__ import annotations

from pathlib import Path

from fitting.mos2_core.core.default_stages import build_default_context, build_default_stages
from fitting.mos2_core.core.pipeline import run_pipeline
from fitting.mos2_pl.sample_data import generate_dummy_pl_spectra


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_dir = Path(__file__).resolve().parent / "config"
    raw_spectra = generate_dummy_pl_spectra(count=8)

    context = build_default_context(
        run_id="pl_dummy_e2e",
        artifact_dir=project_root,
        config_dir=config_dir,
    )
    stages = build_default_stages(config=context.config)
    result = run_pipeline(raw_spectra=raw_spectra, stages=stages, context=context)

    print("PL dummy pipeline run completed.")
    print(f"Configured PL models: {context.config.get('pl', {}).get('models')}")
    print(f"Accepted results: {len(result.accepted)}")
    if result.reports:
        print(f"Summary report: {result.reports[0].path}")


if __name__ == "__main__":
    main()
