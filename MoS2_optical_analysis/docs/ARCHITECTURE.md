# MoS2 Fit Architecture

This document describes the current workspace architecture after TASK-006~008 migration.

## Top-Level Layout

- `fitting/`
  - `mos2_core/`: shared pipeline contracts and stage implementations
  - `mos2_raman/`: Raman entrypoints + Raman config
  - `mos2_pl/`: PL entrypoints + PL config
- `gui/`: Streamlit UI package
- `config.yaml`: single source of scientific settings
- `packaging/`: PyInstaller spec, exe entry scripts, end-user `DIST_README.md`
- `tests/`: pytest suite
- `docs/`: this file, `PACKAGING.md`, `DEV_LOG.md`
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
- Raman mapping CSV pre-conversion (standalone, not called by the pipeline or GUI):
  - `python -m fitting.mos2_raman.split_mapping_csv <map.CSV> [--out-dir ...] [--overwrite]`
  - splits a one-row-per-point mapping CSV into `Y###-X###.txt` files that `raw_loader.parse_raman_txt` reads with `map_y`/`map_x`
  - truncated rows are skipped and missing grid points are reported
- PL ASC input:
  - default PL pattern is `*.asc`
  - simple numeric `wavelength_nm,intensity` ASC files are parsed
  - nm x-values are converted to eV before PL fitting with `eV = 1239.8419843320026 / nm`
  - optional intensity density conversion is available behind `pl.intensity_density_correction.enabled` and defaults off
- PL multi-component fitting:
  - default model ensemble is `pl_single_pvoigt`, `pl_a_doublet_pvoigt`, and `pl_5_component_pvoigt`
  - component seeds/bounds are configured in `fitting/mos2_pl/config/pl.yaml`
  - default components are `I1`, `I2`, `A_minus`, `A0`, and `B`
  - A-/A0, B/A-total, and defect/A-total area ratios are emitted for Pristine/Treatment comparison
- GUI:
  - `python -m streamlit run gui/Main.py`
- Experimental TASK-021 least-squares guardrail:
  - `python -m fitting.mos2_raman.compare_lsq_guardrail --raw-dir data/raw/raman/...`
  - compares current lmfit Raman n-peak candidates with the proposed scipy least-squares path without changing production pipeline defaults

## Current Fitting Engine Status

- Production Raman/PL fitting remains lmfit-based via `fitting/mos2_core/fitting/raman_lmfit.py`.
- TASK-021 least-squares code is guardrail-only and is not used by `run_raw_pipeline`, Streamlit Run Analysis, report generation, or manual refit defaults.
- The least-squares guardrail currently mirrors Raman n-peak first-pass candidate math and writes comparison CSVs with:
  - candidate timing
  - RMSE/AIC/BIC deltas
  - selected-model agreement
  - peak center deltas
- Broader guardrail results on 2026-05-20 show strong speedup but insufficient parity:
  - `80` spectra across four 20-spectrum sets: selected-model agreement `54/80` (`67.5%`)
  - `sample_A` full grid (`81` spectra): selected-model agreement `57/81` (`70.4%`)
  - common transition: lmfit `peak_4_model` selected, least-squares `peak_5_model` selected
- Interpretation:
  - lmfit is the current compatibility baseline, not proven universally more accurate.
  - least-squares often finds lower RMSE/AIC, but that may change peak-count selection and downstream maps.
  - Before any default switch, TASK-021 must validate whether extra `peak_5_model` selections are physically meaningful, especially LA/side-peak behavior.

## Packaging Entry Points (PyInstaller)

- Top-level app launcher:
  - `mos2-analysis` -> runs Streamlit (`gui/Main.py`)
- Worker executables used by GUI subprocess calls in frozen mode:
  - `mos2-run-raman` -> `fitting.mos2_raman.run_raw_pipeline`
  - `mos2-run-pl` -> `fitting.mos2_pl.run_raw_pipeline`
  - `mos2-desktop-editor` -> `gui.desktop_editor.app`
- Spec file:
  - `packaging/mos2_optical_analysis.spec`
- Frozen path split (`fitting/mos2_core/core/runtime_paths.py`):
  - user data (`data/raw`, `data/results`, `data/bin`): `runtime_project_root()` = exe folder
  - bundled config YAML: `runtime_resource_root()` / `raman_config_dir()` = `sys._MEIPASS` (`_internal`)
- Build identification: `core/build_info.py`; the spec bundles `build_info.json` (commit, dates) and the GUI home
  page shows it (see `docs/PACKAGING.md` "Build Identification").
- `mos2-run-raman` / `mos2-run-pl` entry scripts call `multiprocessing.freeze_support()` so `--workers > 1` works in the exe.
- If the fit process pool breaks (`BrokenExecutor`), remaining spectra fall back to the sequential fit path instead of being marked `invalid` (`fit_worker_exception`).

## Data and Report Routing

- Pipeline reports are written under `data/results/{modality}/reports`.
- GUI report loader reads from `data/results/{raman,pl}/reports`.
- Graph config is loaded from `raman_config_dir()` (`fitting/mos2_raman/config` in source runs, `_internal/...` when frozen).
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
- PL report rows include x-axis unit conversion metadata when nm input is converted (`x_unit`, `original_x_unit`, `x_conversion`).
- PL report rows include intensity-conversion metadata when optional density correction is enabled.
- PL report rows include inferred `temperature_k` and `treatment_label` metadata when file/folder names contain values such as `77K`, `Pristine`, `Treatment`, or `4ATP`.
- PL report rows flatten the selected model's component metrics, while JSON `all_candidates` keeps the full candidate ensemble for later inspection.
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

## Modality Separation and Delta Outlier (2026-10-23)

- `pl_*` summary columns (`pl_position`, `pl_fwhm`, `pl_area`, `pl_height`) are written only for PL runs/models; Raman reports no longer contain them.
- Peak review (`extract_peak_rows_from_row`, `_synthesize_fitted_y`, spectrum viewer, desktop editor) picks PL peaks (`i1,i2,a_minus,a0,b,pl`) or Raman peaks (`lo,e2g,a1g,zo,la`) by the row `modality`.
- Raman delta outlier loosened in both `raman.yaml` files: `absolute_range` 15.0-27.0, `sigma_k` 6.0, `fallback_abs` 3.0 (was 16-25, 4.0, 1.2).

## Raman Baseline Slope Bounds (2026-10-23)

- Raman n-peak fits (`peak_2..5_model`) now search `bg_slope` in `estimate +/- max(2.0, 3*|estimate|)` instead of a fixed `[-2, 2]`. Steep fluorescence backgrounds (slope ~2, e.g. sample_G) were clamped at the bound and the optimizer stalled at the initial E2g=384 / A1g=403.
- PL fits and the legacy `mos2_double_*` models keep the fixed bound.

## Unified Scientific Config (2026-10-30)

- Root `config.yaml` (next to the exe when packaged) is the single source of every scientifically meaningful value:
  model lists and selection metric/weights, peak initial positions/offsets, center/sigma bounds, height priors,
  model windows and baseline windows, anchor/offset bounds, prefit SNR gate, Si calibration, PL components,
  despike/spike check, quality flags, post-selection QC, review thresholds, strain/doping coefficients.
- `load_pipeline_config` deep-merges it over `fitting/{mos2_raman,mos2_pl}/config/*.yaml` before required-key
  validation. Section files keep only non-scientific settings (`report_export`, GUI style, baseline method).
- Path: `runtime_paths.user_config_path()` -> source: workspace root; frozen: exe folder, falling back to the bundled
  `_internal/config.yaml` if the user deleted it.
- Formerly hardcoded constants, now config keys with identical defaults:
  - `raman_lmfit`: `fit.sigma_init_by_peak`, `fit.fraction_init`, `fit.offset_bounds.*`,
    `fit.two_stage_anchor.fallback_half_window`, `fit.baseline.{lock_by_model,locked_rel_tol,slope_bounds,
    manual_refit_slope_bound,default_edge_fraction,default_edge_min}`, `fit.min_roi_points`,
    `fit.min_spectrum_points`, `fit.prefit.min_points`, `pl.fit.seed.*`, `pl.fit.spike_check.*`
  - `preprocess/basic.py`: `raman.si_calibration.{width_min,min_initial_width}`
  - `model_selection.py`: `{raman,pl}.hybrid_weights`
  - `reporting.py`: `{raman,pl}.quality_flags.*` incl. `pl.quality_flags.fwhm_check_components`
  - `confidence.py`: `review.high_rmse_threshold`
  - `refit_api.py`: shares `min_roi_points`, `locked_rel_tol`, `fraction_init`, `manual_refit_slope_bound`
  - GUI: `raman_graph.all_spectra_viewer.fwhm_warn`, `raman_graph.sample_comparison.absolute_isolines.{eps_range,n_range}`
- Kept in code on purpose: math/stat constants (FWHM<->sigma 2.3548/2.0, MAD 1.4826, h*c 1239.84 eV nm),
  numerical epsilons, unreachable legacy paths (`mos2_double_*`, `_fit_pl_model` single path), display-only GUI
  windows, the nm-vs-eV axis guess (`max(x) > 100`).
- `mos2_pl/config/raman.yaml` previously differed (`selection_metric: hybrid`, E2g/A1g sigma max 5.0); the shared
  config now uses the Raman values. PL runs do not fit with the `raman` section, so PL results are unchanged.
- Verification: 47 Raman + 8 PL real spectra re-fitted before/after; all per-spectrum values, statuses and reasons
  identical (only the embedded config dump, timestamps and paths differ).
- Known issues found while surveying (not changed here):
  - PL default baseline windows: `default_edge_min` 1.0 is in eV for PL, so both edge windows span the whole
    1.38-2.33 eV ROI.
  - `post_selection_qc` reads `raman.post_selection_qc` without a modality check; PL fallback candidates
    (`delta_e2g_a1g = 0`) get marked `invalid` by the delta absolute-range rule.
  - `reporting._fwhm_normal_band_by_peak` uses `2*sigma` for gaussian PL components too (should be 2.3548).

## Raman Prefit E2g SNR Gate (2026-10-26)

- E2g SNR below `prefit.e2g_snr_hard_min` (now 2.0, was 3.0) no longer invalidates the spectrum: it is fitted normally and flagged `attention` with reason `prefit_e2g_snr_below_hard` (soft band keeps `prefit_e2g_snr_below_soft`).
- A1g SNR below `a1g_snr_hard_min` still routes to the `prefit_gate_invalid` fallback.
