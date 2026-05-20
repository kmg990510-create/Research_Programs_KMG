# MoS2 Fit Architecture

This document describes the current workspace architecture after TASK-006~008 migration.

## Top-Level Layout

- `fitting/`
  - `mos2_core/`: shared pipeline contracts and stage implementations
  - `mos2_raman/`: Raman entrypoints + Raman config
  - `mos2_pl/`: PL entrypoints + PL config
- `gui/`: Streamlit UI package
- `data/`
  - `raw/raman/`, `raw/pl/`
  - `bin/results/raman/`, `bin/results/pl/` (soft-delete staging area for result files)
  - `results/raman/reports/`, `results/pl/reports/`
- `.venv/`, `.vscode/`

## Runtime Entry Points

- Raman dummy:
  - `python -m fitting.mos2_raman.run_dummy_pipeline`
- Raman raw (single):
  - `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/... --run-id ...`
- Raman raw (batch by immediate subfolders):
  - `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/... --batch-subdirs`
- PL dummy:
  - `python -m fitting.mos2_pl.run_dummy_pipeline`
- PL raw (single):
  - `python -m fitting.mos2_pl.run_raw_pipeline --raw-dir data/raw/pl/... --run-id ...`
- PL raw (batch by immediate subfolders):
  - `python -m fitting.mos2_pl.run_raw_pipeline --raw-dir data/raw/pl/... --batch-subdirs`
- GUI:
  - `python -m streamlit run gui/Main.py`
- Experimental TASK-021 least-squares guardrail:
  - `python -m fitting.mos2_raman.compare_lsq_guardrail --raw-dir data/raw/raman/...`
  - compares current lmfit Raman n-peak candidates with the proposed scipy least-squares path without changing production pipeline defaults

## Packaging Entry Points (PyInstaller)

- Top-level app launcher:
  - `mos2-analysis` -> runs Streamlit (`gui/Main.py`)
- Worker executables used by GUI subprocess calls in frozen mode:
  - `mos2-run-raman` -> `fitting.mos2_raman.run_raw_pipeline`
  - `mos2-run-pl` -> `fitting.mos2_pl.run_raw_pipeline`
  - `mos2-desktop-editor` -> `gui.desktop_editor.app`
- Spec file:
  - `mos2_optical_analysis.spec`

## Data and Report Routing

- Pipeline reports are written under `data/results/{modality}/reports`.
- GUI report loader reads from `data/results/{raman,pl}/reports`.
- Graph config is loaded from `fitting/mos2_raman/config`.
- Manual refit artifacts are stored under `data/results/{modality}/manual_refits`.
  - canonical override file per report: `{run_id}_manual_overrides.json`

## GUI Runtime Behavior

- Home navigation order follows triage-first flow: `Run Analysis -> Flagged -> All Spectra -> Finalize`.
- Run Analysis page supports two modes: `single` and `batch_subdirs`.
- In batch mode, each immediate subfolder is executed as one run and subfolder name becomes run-id.
- If `run_raw_pipeline` is called in single mode and no direct TXT files are found, it auto-switches to subdirectory batch mode.
- Run Analysis (Raman) provides runtime overrides:
  - `peak_n_mode` (`auto`, `peak_2_model`~`peak_5_model`)
  - `distance_outlier` (`config|enabled|disabled`)
  - `delta_outlier` (`config|enabled|disabled`)
  - `si_calibration` (`config|enabled|disabled`)
  - `fit_workers` (spectrum-level multiprocessing worker count)
- `run_raw_pipeline` supports `--workers`:
  - `1`: sequential fit path (baseline behavior)
  - `>1`: process-pool fit path; auto-fallback to sequential if multiprocessing is unavailable in current environment
- Live execution UI is fit-centric:
  - single mode: one `Fit Progress` card (`valid/attention/invalid`, elapsed, eta)
  - batch mode: `Overall (fit only)` and `Current Fit` cards with current batch/folder/file hints
  - raw logs remain available in advanced expander
- Run Analysis includes Result Bin workflow: move result files to `data/bin/results/{modality}`, restore later, or permanently delete from Bin.
- Result Bin selection policy shows JSON only (`*_fit_report.json`, `*_manual_overrides.json`).
- Linked result-set rule: selecting/moving/restoring/purging report JSON also processes paired CSV + matching override JSON.
- All Spectra Viewer handles single-row filtered results without slider errors.
- All Spectra Viewer uses unified sidebar coordinate navigation:
  - `Row index (Y)` for vertical movement across rows
  - `Spectrum index (X)` for horizontal movement within row
- All Spectra/Manual Refit preview graph style is config-driven from `fitting/mos2_raman/config/raman_graph.yaml`.
  - Shared raw/fitted/baseline/component colors
  - Smoother fitted-curve rendering via dense x-grid plotting
- All Spectra Viewer supports hybrid manual refit flow:
  - Streamlit creates temporary request/response JSON in a temp directory and launches external `PySide6 + pyqtgraph` desktop editor
  - editor returns overrides JSON (`fraction/center/height/fwhm/fixed`)
  - Streamlit calls `SingleSpectrumRefitAPI` for one-spectrum refit
  - UI renders before/after overlays and metrics
  - manual model-choice and manual-refit outputs are upserted into `{run_id}_manual_overrides.json`
- Desktop manual editor interaction modes:
  - Top icon-toolbar modes:
    - `Move` (drag pan)
    - `Zoom` (drag rectangle zoom)
    - `Edit`
  - `Edit` handle mapping:
    - left handle: `fraction` (`eta`)
    - top handle: `center` + `height`
    - right handle: `FWHM`
  - Fraction now has its own fixed flag (`Fix F`) alongside `Fix C/H/W`.
  - Peak-table fix toggles preserve the current zoom window.
  - `Autoscale (Main View)` is available from right-click menu and Zoom double-click.
  - Initial/autoscale x-range is aligned with All Spectra Viewer main graph rule (`all_spectra_viewer.x_window` from `raman_graph.yaml`).
  - Live preview metrics (`RMSE`, `AIC`, delta vs before) update on every edit.
  - Preview/manual synthesis is aligned to lmfit-consistent area-normalized line-shape math (`gaussian/lorentz/pvoigt`).
  - `Auto Fit (Use Current as Initial)` runs one-spectrum re-fit from current peak edits and updates editor state.

## Contracts and Invariants

- Core data contracts remain in `fitting/mos2_core/core/types.py`.
- `fit_status` values remain limited to `valid`, `attention`, `invalid`.
- Raman and PL both produce JSON/CSV report pairs.
- Batch scope is immediate subdirectories only (not recursive multi-level batch).
- Manual refit request contract:
  - `gui/components/manual_refit_contract.py` (`manual_refit_request.v1`)
- Manual refit response contract:
  - `gui/components/manual_refit_contract.py` (`manual_refit_response.v1`)
- Manual refit backend adapter:
  - `fitting/mos2_core/review/refit_api.py` (`ManualRefitRequest`, `SingleSpectrumRefitAPI`)
- Report top-level spectrum row contract:
  - `spectra[]` now stores full selected-fit details by copying selected candidate `params/metrics` into the row
  - full snapshots are also embedded as `fit_params` and `fit_metrics`
- Raman anchor/order contract:
  - `fit.two_stage_anchor` uses nested keys (`enabled`, `window`) only.
  - optional `fit.auto_refine` uses nested keys (`enabled`, `min_rmse_improvement`).
  - auto-refine runs a second-pass Raman n-peak fit on `y_corr` and adopts only if RMSE improves by threshold.
  - when anchor mode is active on n>=3 models, center coupling is anchor-centric:
    - `LO = E2g - d_lo_from_e2g`
    - `ZO = A1g + d_zo_from_a1g`
    - `LA = A1g + d_la_from_a1g`
  - in this mode, the old prev->next center chain is not used for LO/ZO/LA.
  - `fit` section layout in both Raman config files is standardized to 7 execution-order blocks:
    - ROI/comparison windows
    - ordering/anchor policy
    - anchor seeds/relative offsets
    - center bounds
    - width bounds
    - model priors
    - prefit gate

## Validation Snapshot (2026-03-20)

- `python -m fitting.mos2_raman.run_dummy_pipeline`: pass
- `python -m fitting.mos2_pl.run_dummy_pipeline`: pass
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_A --pattern Y1-X1.txt`: pass
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_set_1 --pattern Y1-X1.txt --batch-subdirs`: pass
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_set_1 --pattern Y1-X1.txt --run-id auto_switch_check`: pass (auto-switch to batch)
- `streamlit run gui/Main.py` with local HTTP check: pass (`200`)

## Validation Snapshot (2026-03-21)

- `python -m py_compile` on manual refit modules and All Spectra page: pass
- single-spectrum manual refit API smoke using latest Raman report row: pass (`status=ok`, `fit_status=attention`)
- `python -m fitting.mos2_raman.run_dummy_pipeline`: pass
- `python -m fitting.mos2_pl.run_dummy_pipeline`: pass
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_A --pattern Y1-X1.txt --run-id nav_single_smoke`: pass
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_set_1 --pattern Y1-X1.txt --batch-subdirs`: pass
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_A --pattern Y?-X?.txt --run-id nav_grid_smoke`: pass
- `streamlit run gui/Main.py` with local HTTP check: pass (`200`, port `8510`)
- All Spectra Viewer smoke (single-row report): pass (`Filtered Rows=1`, no exceptions)
- All Spectra Viewer smoke (sidebar Y/X navigation): pass (`Y1-X1 -> Y2-X1 -> Y2-X2`, no exceptions)
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_A --pattern Y1-X1.txt --run-id task14_15_single_smoke`: pass
- `streamlit run gui/Main.py` with local HTTP check: pass (`200`, port `8511`)
- All Spectra Viewer smoke (single-row report for TASK-014/015): pass (`Filtered Rows=1`, no exceptions)
- desktop editor widget smoke (`QT_QPA_PLATFORM=offscreen`, mode switch + plot render): pass
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_A --pattern Y1-X1.txt --run-id run_analysis_opts_single --peak-n-mode peak_4_model --distance-outlier disabled --delta-outlier enabled`: pass
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_set_1 --pattern Y1-X1.txt --batch-subdirs --peak-n-mode auto --distance-outlier enabled --delta-outlier disabled`: pass
- `python -m fitting.mos2_pl.run_raw_pipeline --raw-dir data/raw/raman/sample_A --pattern Y1-X1.txt --run-id pl_opts_smoke --peak-n-mode peak_3_model --distance-outlier disabled --delta-outlier enabled`: pass
- Run Analysis page AppTest check for new controls (`peak_n_mode`, `distance_outlier`, `delta_outlier`, `si_calibration`): pass
- Run Analysis page AppTest smoke (single run button flow, fit-only card): pass
- Run Analysis page AppTest smoke (batch run button flow, overall + current fit cards): pass
- `streamlit run gui/Main.py` with local HTTP check: pass (`200`, port `8513`)
- `python -m py_compile` on desktop editor + refit API updates: pass
- `python -m fitting.mos2_raman.run_dummy_pipeline`: pass
- `python -m fitting.mos2_pl.run_dummy_pipeline`: pass
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_A --pattern Y1-X1.txt --run-id manual_refit_ui_single_smoke`: pass
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_set_1 --pattern Y1-X1.txt --batch-subdirs`: pass
- `streamlit run gui/Main.py` with local HTTP check: pass (`200`, port `8515`)
- All Spectra Viewer AppTest smoke (single-row filter): pass (`Filtered Rows=1`)
- Manual refit API smoke (`submit_refit` + `submit_auto_refit`): pass (`status=ok`)
- desktop editor offscreen smoke (autoscale + metric update path): pass
- desktop editor handle-role smoke: pass (`left=>fraction`, `top=>center/height`, `right=>FWHM`)
- `python -m fitting.mos2_raman.run_raw_pipeline --raw-dir data/raw/raman/sample_A --pattern Y1-X1.txt --run-id fraction_handle_single_smoke`: pass
- `streamlit run gui/Main.py` with local HTTP check: pass (`200`, port `8516`)
