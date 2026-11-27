# MoS2_adsorption_sim 작업 기록

## 0단계: 프로젝트 뼈대 및 과학적 보완 계획 수립 (2026-11-14)

- 범위: 프로그램 규칙(`AGENTS.md`), 과학적 보완 설계 및 로드맵(`docs/PLAN.md`), 환경 구축 안내(`README.md`) 작성.
- 주요 설계 결정:
  - 계산기: ASE `SumCalculator`로 uMLIP(MACE/MatterSim) + DFT-D3(`torch-dftd`)를 결합하고, 이완 후 uMLIP/D3 기여분과 변형 에너지($E_{\text{def}}$)를 분리한다.
  - 시각화: 직접 구현을 최소화하고 역할별로 검증된 도구를 조합한다 — `pymatgen`(`AdsorbateSiteFinder`, `plot_slab`), `py3Dmol`(대화형 3D 구조·이완 궤적 애니메이션), `ase.visualize.plot.plot_atoms`(2D Top/Side 정투영), `labkit`(논문 스타일 Plotly 수렴·결합·통계 그래프).

## 1단계: 설정, 표준 내부 모델, 슬랩·분자·다중 포즈 생성기 (2026-11-14)

- 범위: `config.yaml` 엄격 접근, 표준 내부 모델(`SlabSpec`, `MoleculeSpec`, `PoseSpec`), 2H-$\text{MoS}_2$ 슬랩/결함 생성기, 프리셋·외부 분자 빌더, `pymatgen` `AdsorbateSiteFinder` 기반 다중 포즈 생성기 및 단위 테스트.
- 파일:
  - `.gitignore`, `requirements.txt`, `config.yaml`
  - `ads_core/__init__.py`, `ads_core/config.py`, `ads_core/model.py`
  - `ads_core/builders/__init__.py`, `slab.py`, `molecule.py`, `poses.py`
  - `tests/test_config.py`, `tests/test_builders.py`
- 구현 확인 사항:
  - `ase.build.mx2(..., kind="2H")`로 4×4×1 2H-$\text{MoS}_2$ 슬랩(48원자, 두께 $3.17\text{ \AA}$, 전체 진공 $20.0\text{ \AA}$)을 만들고, 하부 S 16원자에 `FixAtoms` 제약을 적용한다.
  - 황 공공 `V_S`(상부 S 1원자 제거, 47원자)와 `V_S2`(수직 쌍 S 2원자 제거, 46원자) 생성 및 결함 좌표 기록.
  - 내장 프리셋 6종(`H2O`, `NH3`, `CO`, `O2`, `CH4`, `TMA`) 및 외부 `.xyz`/`.mol` 파일 로더(`load_molecule_file`), 공유결합 목록(`reference_bonds`) 자동 추출, 원자 겹침 검증.
  - `pymatgen.analysis.adsorption.AdsorbateSiteFinder`가 2H-$\text{MoS}_2$ 위에서 찾은 사이트를 주기적 최단거리 기준으로 `Mo_top`, `S_top`, `Hollow`, `Bridge`로 분류하고, 결함 슬랩에서는 `V_S`/`V_S2`를 함께 포함한다.
  - 분자 주축(PCA) 기반 `flat` / `anchor_down` / `anchor_up` 배향 + 방위각 회전 + 최소 거리(`min_initial_distance_A`) 미달 시 자동 수직 상승(`initial_height_adjusted` 경고)을 구현했다.
- 검증:
  - `.\.venv\Scripts\python.exe -m pytest -v`: **10 passed** (2.20s). `config.yaml`의 모든 키가 실제로 읽히며 죽은 키가 없음(`unread_keys == set()`)을 확인했다.
- 아직 없는 것 (3~5단계 예정):
  - 배치 파이프라인, `review.json`, 요약·내보내기, CLI, Streamlit GUI.

## 2단계: 계산기 팩토리, 합성 포텐셜, 이완·에너지 분해·품질 판정 (2026-11-14)

- 범위: uMLIP + DFT-D3 `SumCalculator` 팩토리, 해석적 합성 계산기(`synth_calc.py`), 기준 에너지 캐시, 구조 이완 및 궤적·1D 결합 곡선 스캔, uMLIP/D3 및 변형 에너지 분해, 3단계 품질 판정.
- 파일:
  - `config.yaml` (`calculator`, `relaxation`, `quality` 항목 추가)
  - `ads_core/model.py` (`CalculatorSettings`, `RelaxationSettings`, `QualitySettings`, `PoseResult`)
  - `ads_core/calculators/__init__.py`, `synth_calc.py`, `factory.py`
  - `ads_core/simulation/__init__.py`, `reference.py`, `relax.py`, `metrics.py`, `quality.py`
  - `tests/test_config.py`, `tests/test_simulation.py`
- 구현 및 시험 결과 확인 사항:
  1. `SynthUmlipCalculator` + `SynthD3Calculator`: `ase.neighborlist.neighbor_list`와 $C^2$ 5차 다항식 스무딩으로 주기적 경계 조건에서 정확한 해석적 힘을 구현했다. 유한차분 힘과 오차가 $10^{-5}\text{ eV/\AA}$ 미만임을 확인했다.
  2. 결함 사이트 초기 높이(`defect_initial_height_A`): 처음 $2.0\text{ \AA}$에서는 주변 상부 S 원자의 반발벽에 막혀 분자가 황 공공(`V_S`) 포켓으로 내려가지 못했다. `0.8 Å`로 조정하고 `S–adsorbate` 반발 컷오프를 `[2.9, 3.5] Å`로 현실화한 뒤, 기저면+D3는 물리흡착($E_{\text{ads}} = -0.129\text{ eV}$, `valid`), 기저면 D3 미적용은 비결합 반발($E_{\text{ads}} = +0.001\text{ eV}$, `attention`), `V_S` 결함은 노출된 Mo와 화학흡착($E_{\text{ads}} = -1.822\text{ eV}$, `O-Mo` 최단거리 $2.34\text{ \AA}$, `valid`)을 각각 재현했다.
  3. 1D 결합 곡선 스캔(`scan_binding_curve`): 이완된 기준 분자(`ref_mol`)를 Kabsch(SVD) 회전으로 포즈 배향에 맞춰 정렬한 뒤 수직 스캔해, 내부 구조 차이로 인한 에너지 오프셋 없이 $\Delta z \to \infty$에서 $E_{\text{ads}} \to 0$이 되도록 했다.
- 검증:
  - `.\.venv\Scripts\python.exe -m pytest -v`: **15 passed** (4.58s). `config.yaml` 미사용 키 0개(`unread_keys == set()`).

## 3단계: 배치 파이프라인, 검토 상태, 볼츠만 요약, 내보내기, CLI (2026-11-14)

- 범위: 메모리 내 배치 실행(`run_batch`), 비파괴적 검토 상태(`review.json`), `(표면, 분자, 계산기)`별 최안정 포즈 및 볼츠만 가중 평균 요약, Origin 호환 CSV·extended XYZ·메타데이터 내보내기 및 디스크 복원(`load_batch_run`), CLI 진입점(`python -m ads_core`).
- 파일:
  - `config.yaml` (`report.boltzmann_temp_K: 300.0` 추가)
  - `ads_core/model.py` (`ReportSettings`)
  - `ads_core/review.py`, `ads_core/pipeline.py`
  - `ads_core/report/__init__.py`, `summary.py`, `export.py`
  - `ads_core/cli.py`, `ads_core/__main__.py`
  - `tests/test_config.py`, `tests/test_pipeline.py`
- 구현 확인 사항:
  - `run_batch`는 디스크에 쓰지 않고 메모리에서 기준 에너지 캐시(`ReferenceCache`), 포즈별 이완, 선택적 1D $E(z)$ 결합 곡선 스캔을 수행한다.
  - `export_run`은 UTF-8(BOM) 기반 `poses_summary.csv`, `molecule_summary.csv`, `warnings.csv`, `relaxation_curves/*.csv`, `binding_curves/*.csv`, `structures/*_relaxed.xyz`, `run_metadata.json`을 출력하고, GUI에서 재계산 없이 즉시 불러올 수 있도록 `batch_state.json` + 초기·궤적 `.xyz`도 함께 저장한다.
  - `molecule_summary`는 `included == True`(`status != "invalid"` 및 `decision != "rejected"`)인 포즈만 집계해 최안정 에너지(`e_ads_min_eV`, `best_site`), 300 K 볼츠만 평균(`e_ads_boltzmann_eV`), 에너지 요철 폭(`e_ads_corrugation_eV`)을 계산한다.
- 검증:
  - `.\.venv\Scripts\python.exe -m pytest -v`: **18 passed**. `config.yaml` 미사용 키 0개, CLI `run`/`export` 및 디스크 복원(`load_batch_run`) 일치 확인.

## 4단계: Streamlit GUI, 3D/2D 시각화 연동, GUI 자동 테스트 (2026-11-14)

- 범위: `labkit` 및 `FET_analysis` UI 규칙을 따르는 Streamlit 4페이지(`Run`, `1_Poses`, `2_Compare`, `3_Finalize`), `py3Dmol` 3D 구조·궤적 뷰어, `ase.visualize.plot.plot_atoms` Top/Side 2D 정투영, `pymatgen` `plot_slab` 흡착 사이트 지도, `AppTest` 기반 GUI 자동 테스트.
- 파일:
  - `requirements.txt` (`streamlit>=1.40`, `py3Dmol>=2.1` 활성화)
  - `ads_core/simulation/quality.py`, `ads_core/simulation/__init__.py` (`REASON_MESSAGES` 추가)
  - `gui/__init__.py`, `gui/state.py`
  - `gui/components/__init__.py`, `values.py`, `viewer3d.py`, `atoms2d.py`, `figures.py`
  - `gui/Run.py`, `gui/pages/1_Poses.py`, `gui/pages/2_Compare.py`, `gui/pages/3_Finalize.py`
  - `tests/test_gui.py`
- 구현 확인 사항:
  - 모든 GUI 페이지가 번호 붙은 사이드바 구획(`1) Batch`, `2) Filters`, `3) Figure size`)과 `labkit.figure_size.show_figure` / `labkit.plot_theme`만 사용하도록 제한했다.
  - `ads_core/` 및 `gui/components/` 어디에도 `streamlit` import가 없음을 자동 테스트로 검증했다.
  - 모든 페이지 파일이 400줄 미만임을 테스트로 검증했다.
  - `viewer3d.py`는 이완된 구조(CIF 단위셀 포함) + 이완 전 분자 Ghost + 주기적 최단거리(`d_min`) 주황 점선 실린더/라벨 보기와 Step $0 \to N$ 이완 궤적 애니메이션 보기를 제공한다.
  - `atoms2d.py`는 `ase.visualize.plot.plot_atoms` 기반 Top/Side 2D 정투영과 `pymatgen.analysis.adsorption.plot_slab` 흡착 사이트 지도를 제공한다.

## 5단계: 1D 결합 곡선 평형점 추출, `V_S_rim` 확장, D3 비교 모드 및 물리 벤치마크 검증 (2026-11-14)

- 범위: 1D $E(z)$ 결합 곡선 정량 평형점 추출, 결함 림 사이트(`V_S_rim`) 추가, `TMA` 분자 내·결함 상호작용 보정, `--compare-no-d3` / `--scan-all-sites` 비교 실행 모드, `ads_core/benchmark.py` 벤치마크 스위트 및 조건부 실제 uMLIP 테스트(`tests/test_benchmark.py`).
- 파일:
  - `config.yaml`, `ads_core/model.py`, `ads_core/builders/poses.py` (`poses.defect_rim_radius_A: 2.3`, `SITE_VS_RIM = "V_S_rim"`)
  - `ads_core/calculators/synth_calc.py` (`TMA` geminal `Al···H`/`C···C` 비결합 반발 분리, `Al–Mo` 배위 상호작용, `H–S`/`H–Mo` 반발 조정)
  - `ads_core/simulation/reference.py` (기준 에너지 `E_slab`/`E_mol` 정밀 이완으로 비결합 시 `E_def >= 0` 변분 보장)
  - `ads_core/simulation/relax.py` (`_extract_curve_equilibrium` 3점 포물선 보간 기반 `dz_eq_A`, `e_min_total_eV`, `e_min_umlip_eV`, `e_min_d3_eV`, `has_attractive_well` 추가)
  - `ads_core/pipeline.py`, `ads_core/report/export.py`, `ads_core/cli.py`, `ads_core/benchmark.py` (`compare_no_d3`, `scan_all_sites`, `binding_curves_summary.csv`, `benchmark` 부명령)
  - `gui/Run.py`, `gui/components/figures.py`, `gui/pages/2_Compare.py` (비교 체크박스, 1D $E(z)$ 평형 우물 마커, `binding_curves_summary_table` 표시)
  - `tests/test_benchmark.py`, `AGENTS.md`, `README.md`, `docs/DEV_LOG.md`
- 구현 및 시험 결과 확인 사항:
  1. `TMA` 안정화 및 기준 에너지 수렴 바닥 정리: 1-3 geminal `Al···H`/`C···C`가 Morse 인력 범위에 들어가던 문제를 분리하고, 고립 기준 구조(`ref_slab`, `ref_mol`)를 더 촘촘한 힘 기준(`min(fmax * 0.1, 0.003)`)으로 이완해 무분산력(`no-D3`) 기저면 포즈가 수치 잡음 없이 정확히 `repulsive_adsorption`(`attention`)으로 판정되도록 했다.
  2. `V_S_rim` 사이트: 황 공공 인접 반경(`defect_rim_radius_A`) 내 노출 Mo 원자를 탐색해 `V_S_rim` 후보 사이트를 추가했고, 벤치마크에서 `TMA` on `V_S_2x2`가 `V_S_rim`($E_{\text{ads}} = -1.336\text{ eV}$)에서 안정 화학흡착됨을 확인했다.
  3. 1D $E(z)$ 정량 추출 및 D3 대조: 기저면 +D3 곡선에서는 내부 인력 우물(`has_attractive_well=True`, $\Delta z_{\text{eq}}$ 추출)이 확인되고 `no-D3`에서는 우물이 사라짐(`False`)을 검증했다.
  4. 실제 uMLIP(`mace-torch`, `mattersim`, `torch-dftd`): 현재 Windows `.venv`에는 미설치 상태이므로 `@pytest.mark.skipif`로 건너뛰고 WSL2 `umlip` 환경에서 즉시 활성화되도록 구성했다.
- 검증:
  - `.\.venv\Scripts\python.exe -m pytest -v`: **43 passed, 2 skipped** (81.78s, 라이브 `mace_mp`/`mattersim` 2건 skip).
  - `.\.venv\Scripts\python.exe -m ads_core benchmark --fast --backend synth_morse`: **all_passed=True** (`H2O_pristine=-0.174 eV`, `H2O_V_S=-2.005 eV`, `NH3_pristine=-0.215 eV`, `NH3_V_S=-1.616 eV`, `TMA_pristine=-0.614 eV`, `TMA_V_S=-1.336 eV`).

## 6단계: 다분자·다층·벌크·MD·안정성 공용 엔진 및 뷰어 확장 + 연구 공간 분리

- 범위: 공용 다분자/다층 피복 엔진(`ads_core/builders/multimol.py`, `ads_core/simulation/coverage.py`), 벌크 결정·공간군 패킹/CIF 로더(`ads_core/simulation/bulk_crystal.py`), 유한 온도 다분자 MD(`ads_core/simulation/multimol_md.py`), 국소 안정성·응력·이중 공석 검증(`ads_core/simulation/stability.py`), 및 `ads_gui/pages/4_Coverage_Dimer.py` 뷰어를 공용 패키지에 구현했다.
- 특정 연구 주제 전용 YAML·러너·스크립트·연구 모듈·보고서·산출물은 공용 코드/테스트와 완전히 분리해 git-ignored `research/<topic>/`로 격리했고, 공용 `tests/`는 `tests/conftest.py`의 100% 합성 YAML/구조 fixture만 사용한다 (`data/` 및 `research/` 비의존).
- `ads_core/config.py`에 `infer_project_root`를 추가해 공용 모듈이 `research/<topic>/configs/*.yaml`과 임시 테스트 YAML 모두에서 프로젝트 루트를 일관되게 해석하도록 정리했다.
