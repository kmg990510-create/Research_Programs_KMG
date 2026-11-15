# AGENTS.md — MoS2_adsorption_sim

단층 $\text{MoS}_2$(기저면 및 결함 표면)와 분자(ALD 전구체, 시드 레이어 리간드, 촉매·도판트 분자 등) 사이의 흡착 에너지를 uMLIP + DFT-D3로 계산·검토·비교하는 시뮬레이션 프로그램의 규칙이다.
공통 원칙은 루트 [`AGENTS.md`](../AGENTS.md)를 따르고, 이 문서는 측정 데이터 분석 프로그램(`MoS2_optical_analysis`, `FET_analysis`)과 다른 시뮬레이션 특성과 이 프로그램만의 규칙을 담는다.

상세 과학적 보완 내용과 단계별 설계 계획은 [`docs/PLAN.md`](docs/PLAN.md)에 정리되어 있다.

## 1. 기존 분석 프로그램과의 차이 및 재사용 원칙

- **측정 파싱이 아닌 시뮬레이션 생성·분석:** 장비 파일 reader 대신 **구조 생성기**(슬랩·결함·분자·초기 포즈 배치)와 **계산기 래퍼**(ASE 기반 uMLIP + DFT-D3 `SumCalculator`)가 입력 단계를 담당한다.
- **실행과 조회의 분리:** 구조 이완은 케이스당 수 초~수 분이 걸리므로, 화면을 열 때마다 다시 계산하지 않는다. `Run` 단계(또는 WSL2 CLI)에서 시뮬레이션 배치를 실행해 궤적과 원시 결과를 `data/results/<배치>/`에 기록하고, 검토·시각화 단계(`Poses`, `Compare`, `Finalize`)는 기록된 결과와 `review.json`만 읽어 즉시 반응한다.
- **환경 분리 지원:** 무거운 GPU 계산(`torch`, `mace-torch`, `mattersim`, `torch-dftd`)은 WSL2 Ubuntu 환경에서 수행하되, 이미 계산된 배치를 검토·비교·내보내기하거나 단위 테스트(`pytest`)를 돌릴 때는 uMLIP 가중치나 GPU가 없어도 동작해야 한다.
- **UI 및 아키텍처 재사용 (`labkit` + `FET_analysis` 패턴):**
  - 그래프 테마(`labkit.plot_theme`), 번호 붙은 사이드바 구획(`labkit.sidebar.sidebar_section`), 그래프 크기·격자·이미지 저장(`labkit.figure_size.show_figure`)을 그대로 쓴다.
  - 엄격한 `config.yaml` 접근(`ConfigKeyError`, 미사용 키 금지), `review.json`(`ReviewState`)을 통한 비파괴적 검토(승인·제외·메모·그룹 이름), `counts_in_summary` 단일 판정 함수, `Run` → `Poses`(Review+Viewer 통합) → `Compare` → `Finalize` 4페이지 구성을 그대로 따른다.

## 2. 구조

```text
MoS2_adsorption_sim/
  AGENTS.md              프로그램 규칙 (이 문서)
  README.md              설치(WSL2) 및 사용 안내
  config.yaml            과학적 수치, 슬랩·포즈·이완·품질 판정 기준 (유일한 기준)
  ads_core/              시뮬레이션 및 분석 코어. streamlit을 import하지 않는다
    config.py            config.yaml 엄격 접근 (코드 쪽 기본값 없음)
    model.py             표준 내부 모델: SlabSpec, MoleculeSpec, PoseSpec, PoseResult, WarningRecord
    builders/
      slab.py            2H-MoS2 슈퍼셀 생성, 진공층 부여, 점결함(V_S, V_S2 등) 및 고정 층 설정
      molecule.py        내장 프리셋 분자 및 외부 분자 파일(.xyz, .mol, .sdf) 로드·검증
      poses.py           pymatgen AdsorbateSiteFinder 기반 대칭 사이트 탐색 + 결함 사이트 × 배향 조합 생성
    calculators/
      factory.py         uMLIP(MACE, MatterSim) + DFT-D3(torch-dftd) SumCalculator 조립 및 메타데이터 기록
      synth_calc.py      테스트용 해석적 합성 포텐셜(Morse + LJ + 2D corrugation, GPU/가중치 불필요)
    simulation/
      reference.py       슬랩 단독(E_slab) 및 진공 분자 단독(E_mol) 기준 에너지 이완·캐시
      relax.py           포즈별 구조 이완(BFGS/FIRE/LBFGS), 스텝별 에너지·최대 힘·궤적 기록, 1D 결합 곡선 스캔
      metrics.py         에너지 분해(uMLIP/D3, 상호작용/변형 에너지), 기하 지표(d_min, dz_com, tilt, 결합 변화율)
      quality.py         수렴·구조 무결성 판정 (valid / attention / invalid 및 사유 코드)
    review.py            사람이 바꾼 것 (포즈 결정, 메모, 분자·그룹 표시 이름과 순서) = review.json
    pipeline.py          배치 실행, 저장된 배치 로드, 검토를 적용한 포즈·분자 요약 표 생성
    report/
      summary.py         분자·표면별 최저 에너지 포즈, 볼츠만 가중 평균, 통계 요약
      export.py          Origin용 CSV, 이완 구조(.xyz/.cif), 메타데이터 JSON 내보내기
    benchmark.py         H2O·NH3·TMA × (pristine, V_S) 물리적 흡착·D3 우물·결함 강화 벤치마크 스위트
    cli.py               명령줄 진입점 (python -m ads_core: run / export / benchmark)
  ads_gui/               Streamlit 화면. 시뮬레이션 계산 로직을 두지 않는다
    Run.py               진입 페이지 (배치 생성·선택, 표면/분자/포즈/계산기 설정, 시뮬레이션 실행, 경고)
    state.py             데이터 폴더, 활성 배치, 결과 로드 캐시, 사이드바 1) 2) 구획
    components/
      viewer3d.py        py3Dmol 기반 대화형 3D 구조(이완 전 Ghost 비교, d_min 점선, 단위셀) 및 이완 궤적 애니메이션
      atoms2d.py         ase.visualize.plot.plot_atoms 및 pymatgen plot_slab 기반 2D Top/Side 투영 및 사이트 지도
      figures.py         labkit Plotly 그림 (이완 수렴 곡선, 1D 결합 곡선, 에너지 분해·비교 그래프). streamlit을 import하지 않음
      values.py          포즈별 추출값·에너지 분해 표. streamlit을 import하지 않음
    pages/
      1_Poses.py         Detail(포즈 목록 + 구조·수렴 그림 + 승인/제외 + 추출값) / Gallery 보기
      2_Compare.py       분자·사이트·결함·계산기별 E_ads 비교, 에너지 분해(uMLIP vs D3), 결합 곡선 overlay
      3_Finalize.py      분자별 대표값 요약, 결과 파일 내보내기, zip 내려받기
  tests/                 pytest. 합성 포텐셜(synth_calc)만 사용해 수 초 내 검증
  data/
    molecules/           사용자 추가 분자 구조 파일 (git 제외)
    results/             시뮬레이션 배치 결과, 궤적, review.json (git 제외)
  docs/
    PLAN.md              과학적 보완 설계 및 단계별 구현 계획
    DEV_LOG.md           단계별 작업 및 검증 기록
```

## 3. 명령

WSL2 Ubuntu(`conda activate umlip`) 또는 로컬 환경의 `MoS2_adsorption_sim` 폴더에서 실행한다.

```bash
# 명령줄: 설정된 배치 시뮬레이션 실행 및 결과 저장 (기본 출력: data/results/<배치 이름>)
python -m ads_core run --batch my_screening --molecules H2O TMA NH3 --surface pristine_4x4

# 물리 벤치마크 스위트 (H2O, NH3, TMA × pristine/V_S, D3 비교 포함)
python -m ads_core benchmark --fast --backend synth_morse

# 화면 실행 (단독 실행: Run_Adsorption_GUI.cmd / 통합 실행: ..\Run_Lab_GUI.cmd 또는 streamlit run ..\app.py)
python -m streamlit run ads_gui/Run.py

# 테스트 (GPU나 uMLIP 가중치 없이 합성 포텐셜로 즉시 실행)
python -m pytest
```

## 4. 물리·과학적 계산 규칙

단순히 한 위치에서 구조 이완 한 번을 돌려 에너지를 빼는 방식은 초기 위치 의존성과 기준 에너지 불일치로 인해 과학적 의미가 약하다. 모든 계산은 아래 규칙을 따른다.

### 4.1. 자체 일관적 기준 에너지 (Self-Consistent References)

$$E_{\text{ads}} = E_{\text{slab+mol}} - \left( E_{\text{slab}} + E_{\text{mol}} \right)$$

- $E_{\text{slab+mol}}$, $E_{\text{slab}}$, $E_{\text{mol}}$ 세 값은 반드시 **동일한 계산기(같은 uMLIP 모델 및 가중치 버전 + 같은 DFT-D3 파라미터)와 동일한 힘 수렴 기준(`fmax_eV_per_A`)**으로 이완된 바닥상태 에너지여야 한다.
- 기체 분자 단독 에너지($E_{\text{mol}}$)는 주기적 경계 조건 간섭이 없도록 `config.yaml`에 지정된 진공 박스(`molecule_box_A`) 안에서 자체 이완하여 구한다.
- 같은 배치 안에서 동일한 슬랩 조건과 분자에 대한 $E_{\text{slab}}$, $E_{\text{mol}}$은 한 번만 이완하고 재사용한다.

### 4.2. 반데르발스(DFT-D3) 보정 및 에너지 기여도 분해

- 기본 계산기는 ASE `SumCalculator([umlip_calc, d3_calc])`로 구성하며, D3 파라미터(`d3_xc`, `d3_damping`, `d3_cutoff_A`)는 `config.yaml`에 명시하고 결과 메타데이터에 남긴다.
- 이완이 끝난 최종 구조에서 uMLIP 단독 에너지와 DFT-D3 에너지를 분리해 기록한다:
  $$E_{\text{ads}} = E_{\text{ads}}^{\text{uMLIP}} + E_{\text{ads}}^{\text{D3}}, \quad f_{\text{vdW}} = \frac{E_{\text{ads}}^{\text{D3}}}{E_{\text{ads}}}$$
- 분산력 보정을 끄는 모드(`use_d3: false`)는 모델 비교 실험에서 명시적으로 고른 경우에만 실행하며, 결과 표의 `calculator_id`와 `d3_enabled` 열에 드러낸다.

### 4.3. 변형 에너지(Deformation Energy) 분해

흡착 과정에서 표면이나 분자가 뒤틀리는 데 쓰인 에너지 비용을 분리하기 위해, 수렴된 `slab+mol` 구조에서 분자만 떼어낸 슬랩 단점 에너지($E_{\text{slab}}^{\text{deformed}}$)와 슬랩만 떼어낸 분자 단점 에너지($E_{\text{mol}}^{\text{deformed}}$)를 구한다:

$$E_{\text{def, slab}} = E_{\text{slab}}^{\text{deformed}} - E_{\text{slab}}, \quad E_{\text{def, mol}} = E_{\text{mol}}^{\text{deformed}} - E_{\text{mol}}$$
$$E_{\text{int}} = E_{\text{slab+mol}} - \left( E_{\text{slab}}^{\text{deformed}} + E_{\text{mol}}^{\text{deformed}} \right), \quad E_{\text{ads}} = E_{\text{int}} + E_{\text{def, slab}} + E_{\text{def, mol}}$$

### 4.4. 다중 초기 포즈(Multi-Pose) 샘플링 및 대표값 산출

- 한 `(표면, 분자)` 조합은 대칭 사이트(`Mo_top`, `S_top`, `Hollow`, `Bridge`, 또는 결함 사이트 `V_S`, `V_S_rim`, `V_S2`)와 분자 초기 배향(`flat`, `anchor_down`, `anchor_up`, 방위각 회전)의 조합인 여러 초기 포즈(`PoseSpec`)로 구성된다.
- 각 초기 포즈는 독립된 1행(`PoseResult`)이 된다.
- `(표면, 분자)` 조합의 대표 흡착 에너지는 유효한(`included == True`) 포즈들로부터 두 가지를 함께 산출한다:
  1. **최안정 포즈 에너지 ($E_{\text{ads, min}}$):** 가장 낮은 $E_{\text{ads}}$와 그때의 사이트(`best_site`) 및 기하 구조.
  2. **열역학적 볼츠만 가중 평균 ($\langle E_{\text{ads}} \rangle_T$):** 기준 온도(`boltzmann_temp_K`, 기본 $300\text{ K}$)에서 $w_i \propto \exp(-E_{\text{ads}, i} / k_{\text{B}} T)$로 가중 평균한 값과 사이트 점유 확률.

### 4.5. 추출 지표 목록

모든 변수와 열 이름에는 단위를 붙인다. 추출에 실패한 값은 `0`이 아니라 `None` / NaN으로 둔다.

| 열 이름 | 단위 | 뜻 |
| --- | --- | --- |
| `e_ads_eV` | eV | 총 흡착 에너지 ($E_{\text{ads}}$) |
| `e_ads_umlip_eV` | eV | uMLIP 기여분 ($E_{\text{ads}}^{\text{uMLIP}}$) |
| `e_ads_d3_eV` | eV | DFT-D3 분산력 기여분 ($E_{\text{ads}}^{\text{D3}}$) |
| `vdw_fraction` | (무차원) | 분산력 기여 비율 ($E_{\text{ads}}^{\text{D3}} / E_{\text{ads}}$, $E_{\text{ads}} < 0$일 때) |
| `e_int_eV` | eV | 순수 상호작용 에너지 ($E_{\text{int}}$) |
| `e_def_slab_eV` | eV | 슬랩 변형 에너지 ($E_{\text{def, slab}}$) |
| `e_def_mol_eV` | eV | 분자 변형 에너지 ($E_{\text{def, mol}}$) |
| `d_min_A` | Å | 분자 원자와 슬랩 원자 사이의 최단 거리 |
| `dz_com_A` | Å | 분자 질량중심(COM)과 상부 S 원자 평균 평면 사이의 수직 거리 |
| `lateral_shift_A` | Å | 초기 지정 사이트 좌표에서 이완 후 분자 COM이 수평($xy$) 이동한 거리 |
| `tilt_deg` | deg | 분자 주축이 표면 평면과 이루는 기울기 각도 변화 |
| `max_bond_stretch_pct` | % | 이완 전후 분자 내부 공유결합 길이의 최대 변화율 |
| `slab_rmsd_A` | Å | 이완 전후 슬랩 원자 위치의 RMSD |
| `fmax_final_eV_per_A` | eV/Å | 이완 종료 시점의 최대 원자 작용력 |
| `n_steps` | (정수) | 구조 이완에 걸린 총 스텝 수 |

## 5. 상태와 사유 코드

상태는 `valid` / `attention` / `invalid` 3단계이고, 사유 목록(`ads_core/simulation/quality.py`의 `REASONS`)에서만 정한다.
요약 통계와 대표 포즈 선정에 넣을지는 `counts_in_summary` 함수 하나로만 판단한다 (`status != "invalid"` 이고 `decision != "rejected"`).

| 사유 코드 | 상태 | 뜻 |
| --- | --- | --- |
| `calculator_failed` | invalid | 계산기 실행 중 수치 오류 또는 예외 발생 |
| `reference_not_converged` | invalid | 기준 슬랩($E_{\text{slab}}$) 또는 기체 분자($E_{\text{mol}}$) 단독 이완 실패 |
| `not_converged` | invalid | `max_steps` 안에 목표 `fmax_eV_per_A`에 도달하지 못함 |
| `atomic_overlap` | invalid | 원자간 최단 거리가 비물리적 충돌 임계값(`min_allowed_distance_A`) 미만 |
| `slab_disrupted` | invalid | 슬랩 RMSD가 임계값을 넘어 2D 격자 구조가 무너짐 |
| `unexpected_dissociation` | invalid | 결함 없는 기저면에서 분자 내부 결합이 비정상적으로 끊어짐 |
| `repulsive_adsorption` | attention | 수렴했으나 $E_{\text{ads}} \ge 0\text{ eV}$로 인력이 작용하지 않음 |
| `desorbed_to_vacuum` | attention | 분자가 표면에서 멀어져($d_{\text{min}} >$ `max_adsorption_distance_A`) 진공으로 이탈 |
| `dissociation_candidate` | attention | 결함 사이트 등에서 분자 결합 변화율이 커 해리 흡착(chemisorption) 확인이 필요함 |
| `large_slab_distortion` | attention | 슬랩 국소 변형($E_{\text{def, slab}}$ 또는 RMSD)이 주의 기준을 넘음 |
| `migrated_to_other_site` | 참고 (valid) | 초기 사이트에서 다른 대칭 사이트로 수평 이동해 수렴함 (장벽 없는 이동) |
| `physisorption_regime` | 참고 (valid) | 전형적인 물리흡착 범위 |
| `chemisorption_regime` | 참고 (valid) | 강한 화학흡착 범위 |

## 6. 출력 계약

시뮬레이션 결과와 내보내기 파일은 `data/results/<배치>/`에 쓴다. CSV는 UTF-8(BOM)이고 첫 행이 열 이름이다.

| 파일 | 내용 |
| --- | --- |
| `poses_summary.csv` | 포즈마다 한 행. `PoseResult`의 모든 추출 지표, `status`, `reasons`, `decision`, `note`, `included`, `group_display` |
| `molecule_summary.csv` | `(표면, 분자, 계산기)` 그룹별 `n_poses`, `n_included`, 최안정 포즈 지표(`e_ads_min_eV`, `best_site`, `d_min_at_best_A`, `vdw_fraction_at_best`), 볼츠만 평균(`e_ads_boltzmann_eV`), 에너지·거리 통계 |
| `warnings.csv` | 구조 생성과 이완 과정의 모든 경고 (`pose_id`, `molecule`, `surface`, `severity`, `code`, `message`) |
| `relaxation_curves/<pose_id>.csv` | 스텝별 `step`, `energy_eV`, `fmax_eV_per_A`, `dz_com_A` (Origin용 수렴 곡선) |
| `binding_curves/<그룹>.csv` | 1D 스캔 수행 시 높이 `dz_A`에 따른 `e_ads_total_eV`, `e_ads_umlip_eV`, `e_ads_d3_eV` |
| `binding_curves_summary.csv` | 1D 결합 곡선별 평형 높이(`dz_eq_A`), 우물 깊이(`e_min_total_eV`, `e_min_umlip_eV`, `e_min_d3_eV`), 인력 우물 여부(`has_attractive_well`) |
| `structures/<pose_id>_relaxed.xyz` | 이완 완료된 원자 구조 파일 (VESTA / Ovito 호환 extended XYZ) |
| `run_metadata.json` | 프로그램 버전, git commit, Python/ASE/PyTorch/uMLIP 버전, 모델 가중치 이름, DFT-D3 파라미터, `config.yaml` 전체, `review.json` 전체 |
| `review.json` | 사람의 검토 상태 (`auto` / `approved` / `rejected`, 메모, 표시 이름과 순서) |

## 7. 화면 규칙

- 페이지 코드는 화면 배치만 한다. 시뮬레이션은 `ads_core`, Plotly 그림 생성은 `ads_gui/components/figures.py`에 둔다.
- 사이드바는 번호 붙은 구획만 쓴다: `1) Batch`, `2) Filters`, 그리고 그래프가 있는 페이지(`1_Poses`, `2_Compare`)의 `3) Figure size`.
- 모든 그래프는 `labkit.plot_theme`의 색·선 굵기·점 크기 이름을 쓰고 `labkit.figure_size.show_figure(fig, size, filename=...)`로만 그린다.
- 결정(`Approve` / `Reject` / `Clear`), 메모, 그룹 표시 이름·순서는 즉시 `review.json`에 저장한다.

| 페이지 | 하는 일 |
| --- | --- |
| `Run` | 배치 선택·생성, 표면(슈퍼셀 크기, 결함 종류)·분자(내장 프리셋 선택 또는 `.xyz` 업로드)·포즈 샘플링·계산기(MACE / MatterSim / 합성 포텐셜, D3 옵션) 설정 및 실행, 진행 상태와 경고 표시 |
| `1_Poses` | **Detail:** 왼쪽 포즈 목록(`attention` 먼저), 오른쪽에 고른 포즈의 **(a) `py3Dmol` 대화형 3D 뷰어(슬랩+분자 Ball-and-Stick, 단위셀 박스, 이완 전 Ghost 비교, 최단 거리 `d_min` 실린더/라벨, Step $0 \to N$ 이완 궤적 애니메이션)** + **(b) `labkit` 이완 수렴 곡선($\Delta E$, $F_{\max}$ vs step)** + `Approve` / `Reject` / `Clear` + 메모 + 에너지 분해·기하 지표 표. **Gallery:** `ase.visualize.plot.plot_atoms`로 그린 모든 포즈의 Top/Side 2D 정투영 격자(상태별 색), 클릭 시 Detail로 이동 |
| `2_Compare` | 분자별·사이트별·결함 유무별·계산기별 $E_{\text{ads}}$ 비교(`labkit` box + 점), **`pymatgen` `plot_slab` 기반 표면 사이트 지도**, **에너지 분해 막대그래프(uMLIP vs DFT-D3, 상호작용 vs 변형 에너지)**, **1D 결합 곡선($E(\Delta z)$ vs $\Delta z$) overlay**, 요약 통계 표 |
| `3_Finalize` | `(표면, 분자)`별 최안정 포즈 및 볼츠만 평균 요약, Origin용 CSV·이완 구조(`.xyz`)·메타데이터 내보내기, `.zip` 내려받기 |

## 8. 진행 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 0 | 프로젝트 폴더, 규칙(`AGENTS.md`), 과학적 보완 설계 및 구현 계획(`docs/PLAN.md`), `README.md` | 완료 |
| 1 | `config.yaml`, 표준 내부 모델(`model.py`), 슬랩·결함·분자 생성 및 `pymatgen` `AdsorbateSiteFinder` 기반 다중 포즈 생성기(`builders/`), 단위 테스트 | 완료 |
| 2 | 계산기 팩토리(`SumCalculator`: uMLIP + DFT-D3, 합성 포텐셜 `synth_calc`), 기준 에너지·이완·에너지 분해·품질 판정(`simulation/`) | 완료 |
| 3 | 배치 파이프라인(`pipeline.py`), `review.json`, 요약·내보내기(`report/`), CLI(`python -m ads_core`) | 완료 |
| 4 | Streamlit GUI (`Run`, `1_Poses`, `2_Compare`, `3_Finalize`) — `py3Dmol` 3D 뷰어 + `ase.plot_atoms` 2D 투영 + `labkit` 그래프 연동, GUI 자동 테스트 | 완료 |
| 5 | 1D 결합 곡선($E(z)$) 평형 우물 정량 추출, 결함 림 사이트(`V_S_rim`) 확장, D3 대조 실행(`--compare-no-d3`) 및 물리 벤치마크(`benchmark`, 조건부 실제 uMLIP 테스트) | 완료 |
