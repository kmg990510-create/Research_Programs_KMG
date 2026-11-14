# AGENTS.md — FET_analysis

FET 측정(transfer / output) 분석 프로그램의 규칙이다. 공통 원칙은 루트 [`AGENTS.md`](../AGENTS.md)를 따르고, 이 문서는 이 프로그램만의 규칙을 담는다.

`legacy/FET device analysis/`는 참고 자료다. 정책은 가져오고 코드는 가져오지 않는다 (루트 `AGENTS.md` 8장).

## 구조

```text
FET_analysis/
  config.yaml          과학적 수치와 장비 파일 해석 규칙 (유일한 기준)
  fet_core/            분석 코어. streamlit을 import하지 않는다
    config.py          config.yaml 엄격 접근 (코드 쪽 기본값 없음)
    model.py           표준 내부 모델: Measurement, DeviceGeometry, WarningRecord, LoadResult
    naming.py          소자 이름 해석 (이름 규칙을 아는 유일한 모듈)
    synth.py           정답을 아는 합성 transfer 곡선
    analysis/
      settings.py      AnalysisSettings (analysis.* 설정 키를 읽는 유일한 모듈)
      sweeps.py        forward / backward sweep 분리
      numeric.py       이동 중앙값, 점프에 강한 기울기, 이동 직선 맞춤
      transfer.py      transfer 곡선 추출, 배치 분석 (디스크에 쓰지 않음)
      results.py       SweepResult, 상태와 사유 목록
    review.py          사람이 바꾼 것 (치수, 방법 옵션, 결정, 그룹 이름) = review.json
    pipeline.py        배치 하나를 메모리에서 실행, 검토를 적용한 결과 표
    report/
      summary.py       그룹 통계, 지표 목록 (METRICS)
      export.py        결과 파일 쓰기
    cli.py             명령줄 진입점 (python -m fet_core)
  gui/                 Streamlit 화면. 분석 로직을 두지 않는다
    Run.py             진입 페이지 (배치, 치수, 방법 옵션)
    state.py           데이터 폴더, 활성 배치, 분석 캐시, 사이드바 1) 2) 구획
    components/        figures.py (Plotly 그림), values.py (추출값 표). streamlit을 import하지 않음
    pages/             1_Devices, 2_Compare, 3_Finalize
    io/
      loader.py        reader 선택, 폴더 읽기, 중복 파일 처리
      tables.py        reader 공용: 열 매칭, 표준 표 만들기, 곡선 종류 판정, Vds 결정
      b1500_csv.py     Keysight B1500 (EasyEXPERT) CSV
      clarius_xls.py   Keithley 4200A (Clarius) XLS
  tests/               pytest. 합성 데이터만 사용
  data/raw/            측정 파일 (git 제외)
  data/results/        분석 결과 (git 제외)
  docs/DEV_LOG.md      작업 기록
```

## 명령

`FET_analysis` 폴더에서 실행한다.

```powershell
# 배치 하나 분석 후 결과 파일 쓰기 (기본 출력: data/results/<배치 이름>)
.\.venv\Scripts\python.exe -m fet_core --input-dir data/raw/my_batch
# 화면
.\.venv\Scripts\python.exe -m streamlit run gui/Run.py
# 테스트
.\.venv\Scripts\python.exe -m pytest
# 실제 측정 폴더까지 검사 (폴더 안의 각 하위 폴더가 배치 하나)
$env:FET_REAL_DATA_DIR = "..\legacy\FET device analysis\data\raw"; .\.venv\Scripts\python.exe -m pytest
```

## 표준 내부 모델

- 모든 장비 파일은 분석 전에 `Measurement` 목록이 된다. 분석 코드는 시트 이름, 열 이름, 헤더 형식을 모른다.
- `Measurement.data`는 `Vg, Vd, Vs, Id, Ig, Is, time` 열을 가진 표다. 단위는 V, A, s이고 행 순서는 측정 순서다.
- 장비가 기록하지 않은 양은 전부 NaN인 열이다. 숫자가 아닌 칸은 제자리에서 NaN이 되고 행은 지우지 않는다.
- 전류는 부호를 그대로 둔다. 절댓값 열(`absId`)은 부호 있는 열이 없을 때만 쓴다.
- 측정의 식별자는 `(파일 이름, run_id)`다. `run_id`는 파일 안에서만 유일하다.
- `conditions`는 헤더에서 읽은 sweep 조건이다. 헤더에 없는 값은 `None`이다.
  - `vds_V`와 함께 `vd_source`, `vs_source`(`measured` / `header` / `assumed_zero` / `missing`)를 기록한다.
- `group`과 `position`은 `naming.parse_label`만 만든다. 위치 토큰 후보가 둘 이상이면 추측하지 않고 `position = None`으로 둔다.

## Reader 규칙

- 장비별 지식은 `fet_core/io/<reader>.py`와 `config.yaml`의 `readers.<reader>`에만 둔다.
- reader는 내용 문제로 예외를 던지지 않는다. 문제는 원인 이름이 붙은 `WarningRecord`로 돌려준다.
- 파일 하나가 실패해도 나머지는 계속 읽는다 (`reader_failed`).
- 새 reader는 실제 예시 파일이 생겼을 때만 만든다. 범용 CSV reader는 만들지 않는다.
- 내용이 완전히 같은 파일(SHA-256)은 이름이 가장 짧은 것 하나만 읽고 나머지는 `duplicate_file`로 기록한다.
- `load_folder`는 폴더 바로 아래 파일만 읽는다. 하위 폴더는 별도 배치다.

### 경고 코드 (1단계)

| 코드 | 심각도 | 뜻 |
| --- | --- | --- |
| `reader_failed` | error | reader가 파일을 열지 못함 |
| `no_column_names` | error | B1500 파일에 열 이름 줄이 없음 |
| `no_data_rows` | error | 데이터가 없음 |
| `missing_required_column` | error | `Vg` 또는 `Id` 열을 찾지 못함 |
| `ragged_data_rows` | warning | 열 수가 맞지 않는 데이터 줄이 있음 |
| `non_numeric_cells` | warning | 숫자가 아닌 칸을 비워 둠 |
| `settings_sheet_missing` | warning | Clarius 워크북에 Settings 시트가 없음 |
| `settings_block_missing` | warning | Settings 시트에 해당 측정의 블록이 없음 |
| `unknown_curve_type` | warning | transfer / output을 판정하지 못함 |
| `timestamp_unparsed` | info | 측정 시각 형식이 예상과 다름 |
| `duplicate_file` | info | 다른 파일과 내용이 같아 건너뜀 |

## Transfer 분석 규칙 (2단계)

- 계산은 "켜지는 방향" 좌표에서 한다: n-type은 `u = Vg`, p-type은 `u = −Vg`, 전류는 `|Id|`. 결과의 전압은 실제 `Vg`로 되돌려 적는다.
- 극성은 Vg 양 끝의 `log10|Id|` 차이로 판정한다. 판정하지 못하면 추출하지 않고 `no_gate_modulation`(invalid)으로 둔다.
- 왕복 sweep은 시작 전압에서 가장 먼 점에서 나눈다. `forward`는 시작점에서 멀어지는 방향, `backward`는 돌아오는 방향이다.
- 결과는 측정 하나의 sweep 방향마다 `SweepResult` 하나다. 추출하지 못한 값은 `None`이다.

| 항목 | 방법 | 방법 이름 |
| --- | --- | --- |
| 전이 구간 | `log10|Id|`의 5·95 백분위 사이를 10%~90% 지나는 범위 | |
| off 전류 | 전이 이전에서 평평하고 조용한 구간 중 가장 낮은 것의 중앙값 | `stable_plateau` (없으면 `lowest_window`) |
| on 전류 | 가장 많이 켜진 쪽 끝 5점의 중앙값 | |
| gm | 이동 창마다 "창 길이의 1/4만큼 떨어진 두 점의 기울기"들의 중앙값, 이웃 창끼리 이동 중앙값, 그 최댓값 | `lagged_median_slope` |
| Vth (선형 외삽) | gm peak에서의 접선이 전류 0과 만나는 전압 | `linear_extrapolation_at_gm_peak` |
| Vth (정전류) | `|Id|`가 `W × 1 nA/µm`를 마지막으로 넘는 전압 (로그 보간) | |
| SS | 전이 구간에서 `log10|Id|` 대 Vg가 가장 가파른 직선 구간 (R² ≥ 0.95, 0.5 decade 이상) | |
| 이동도 | `gm·L / (W·Cox·|Vds|)`, 같은 소자의 측정 중 `|Vds|`가 가장 작은 것에서만 | `linear_regime_gm_peak` |
| 히스테리시스 | backward의 Vth − forward의 Vth (선형 외삽, 정전류 각각) | |
| 누설 | off / 전이 / on 구간과 SS 구간의 `|Ig|/|Id|` 중앙값·최댓값 (평가만) | |

- gm 창은 기본 2 V이고, peak 부근 기울기의 상대 표준오차가 5%를 넘으면 2배씩 넓힌다 (sweep 범위의 25%까지). 최종 오차는 `gm_relative_error`로 남긴다. 오차는 gm이 최댓값의 절반(`gm.noise_top_fraction`) 이상인 창들에서 잰 중앙값이다.
- gm peak이 평평하면(최댓값의 1% 이내) 가장 먼저 나오는 창을 고른다.
- 이동도는 선형 영역 식이다. `|Vds|`가 gate overdrive보다 크면 `mobility_outside_linear_regime`을 남긴다.
- 치수는 배치 기본값(`config.yaml`의 `device`)을 쓰고, `analyze_transfer_batch`의 `geometry_overrides`로 측정별 값을 덮어쓴다.

### 상태와 사유

- 상태는 `valid` / `attention` / `invalid`이고, 사유 목록(`fet_core/analysis/results.py`의 `REASONS`)에서만 정한다.
- 사유는 `SweepResult.reasons`와 `WarningRecord` 양쪽에 같은 코드로 남는다.
- 통계에 넣을지는 `counts_in_summary` 하나로 판단한다 (invalid가 아니면 포함).

| 사유 | 상태 | 뜻 |
| --- | --- | --- |
| `insufficient_points` | invalid | 점이 너무 적음 |
| `no_gate_sweep` | invalid | 게이트 전압이 변하지 않음 |
| `no_gate_modulation` | invalid | 게이트 전압에 따라 전류가 충분히 변하지 않음 |
| `short_backward_sweep` | attention | backward sweep이 너무 짧아 분석하지 않음 |
| `non_monotonic_sweep` | attention | 게이트 전압이 한 방향으로 움직이지 않음 |
| `off_state_not_reached` | attention | sweep이 off 상태까지 가지 않음 |
| `off_plateau_not_found` | attention | 안정된 off 구간이 없어 가장 낮은 구간을 씀 |
| `gm_not_extracted` | attention | gm peak을 찾지 못함 |
| `gm_noisy` | attention | 창을 최대로 넓혀도 gm 오차가 큼 |
| `vth_const_current_not_found` | attention | 전류가 정전류 기준을 넘지 않음 |
| `ss_not_extracted` | attention | 품질 기준을 만족하는 subthreshold 구간이 없음 |
| `vds_missing` | attention | Vds를 몰라 이동도를 내지 않음 |
| `mobility_outside_linear_regime` | attention | `|Vds|`가 gate overdrive에 비해 작지 않음 |
| `leakage_dominated_transition` | attention | 전이 구간에서 누설이 드레인 전류만큼 큼 |
| `on_state_leakage` | attention | on 구간에서 누설이 눈에 띔 |
| `low_on_off_ratio` | attention | on/off 비가 작음 |
| `gm_peak_at_sweep_edge` | 참고 (valid) | sweep 끝에서 gm이 아직 오르는 중: gm과 이동도는 하한 |

"참고" 사유는 결과에 기록되지만 검토 대상으로 올리지 않는다.

## 실행과 검토 (3단계)

- `pipeline.run_folder`는 디스크에 쓰지 않는다. 쓰는 것은 `report.export.export_run`뿐이다.
- 사람이 바꾼 것은 전부 `data/results/<배치>/review.json`(`ReviewState`)에 둔다. 원본 파일과 자동 결과는 고치지 않는다.
  - 분석에 영향을 주는 것: 배치 기본 치수, 소자별 치수, `vth_subtract_half_vds`, `vth_const_current_nA_per_um`. 바뀌면 다시 분석한다.
  - 분석에 영향을 주지 않는 것: sweep별 결정(`auto` / `approved` / `rejected`)과 메모, 그룹 표시 이름과 순서.
- 통계에 들어가는 sweep은 `included`가 참인 것이다: invalid가 아니고 rejected가 아니다. `pipeline.results_frame`에서만 정한다.
- 배치는 `data/raw` 바로 아래 폴더 하나다.

### 출력 계약

`data/results/<배치>/`에 쓴다. CSV는 UTF-8(BOM)이고 첫 행이 열 이름이다.

| 파일 | 내용 |
| --- | --- |
| `results_summary.csv` | sweep마다 한 행. `SweepResult`의 모든 필드와 `decision`, `note`, `included`, `group_display`, `i_on_uA_per_um`, `gm_peak_uS_per_um` |
| `group_summary.csv` | 표시 그룹과 sweep 방향별 `n_sweeps`, `n_included`, 지표별 count / median / mean / std / min / max |
| `warnings.csv` | reader와 분석의 모든 경고 (`source_file`, `run_id`, `sweep`, `severity`, `code`, `message`) |
| `measurements.csv` | 모든 측정의 모든 점 (표준 열) |
| `transfer_curves/<그룹>_<방향>.csv` | Origin용 넓은 표: `Vg (V)`와 소자별 `Id (A)` 열. rejected sweep은 뺀다 |
| `run_metadata.json` | 프로그램 버전, git commit, 입력 파일 SHA-256, 설정 전체, 분석 설정, 기본 치수, review 전체, 개수 |
| `review.json` | 검토 상태 (화면이 쓰고 CLI가 읽는다) |

그림 파일은 내보내지 않는다. 화면의 그림은 카메라 버튼으로 저장한다.

## 화면 (4단계)

- 페이지는 배치만 한다. 계산은 `fet_core`, 그림은 `gui/components/figures.py`에 둔다.
- 모든 페이지는 `gui.state.active()`로 배치, 실행 결과, review, 결과 표를 받는다. 분석은 폴더의 파일 목록과 review의 분석 입력이 바뀔 때만 다시 돈다 (`st.cache_resource`).
- 사이드바의 공통 구획은 두 개다: `1) Batch`(배치 선택), `2) Filters`(sweep 방향, 상태, 그룹, rejected 표시). 필터 선택은 모든 페이지가 공유하고, 기본값은 아무것도 숨기지 않는다.
- 그래프가 있는 페이지(Devices, Compare)는 `3) Figure size` 구획을 가진다. 그래프 종류마다 가로·세로(px)를 정하고, 그림은 `labkit.figure_size.show_figure`로만 그린다. Gallery는 패널 하나의 크기와 한 줄의 패널 수를 정한다. 가로를 고정하면 그림들이 옆으로 놓이다가 자리가 모자라면 다음 줄로 넘어간다.
- 저장 규칙: 결정, 메모, 그룹 이름·순서는 바꾸는 즉시 `review.json`에 쓴다 (저장 버튼 없음). 다시 분석해야 하는 치수와 방법 옵션만 `Apply` / `Save per-device geometry` 버튼을 쓴다.
- sweep 방향 하나가 목록의 한 행이다. 값과 결정은 그 행의 것이고, 그림에는 같은 측정의 다른 방향이 흐리게 같이 그려진다.
- 데이터 폴더는 `FET_analysis/data`이고, 환경 변수 `FET_DATA_ROOT`로 바꿀 수 있다 (테스트가 쓴다).
- 그림은 `labkit.plot_theme.apply_paper_layout`으로 모양을 맞추고 `labkit.figure_size.show_figure(fig, size, filename=...)`로 그린다. 색·선 굵기·점 크기는 `labkit.plot_theme`의 이름을 쓴다.
- 페이지 맨 위의 `sys.path` 4줄은 `fet_core`, `gui`, `labkit`을 찾기 위한 것이다.

| 페이지 | 하는 일 |
| --- | --- |
| Run | 파일 업로드로 배치 만들기, 배치 기본 치수와 방법 옵션, 소자별 치수, 파일 목록과 경고 |
| Devices | Detail: 왼쪽 sweep 목록(attention 먼저), 오른쪽에 고른 행의 log / linear 그림(off 구간, SS 직선, gm 접선, Vth 표시)과 `Approve` / `Reject` / `Clear`, 메모, 추출값 표. Gallery: 모든 소자의 작은 그림 격자(상태별 색), 패널을 누르면 Detail로 이동 |
| Compare | 지표 여러 개의 box + 점을 2열로, 그룹별 overlay(통계에 드는 sweep만), 그룹 통계 표, 그룹 이름과 순서 |
| Finalize | 그룹 요약, 결과 파일 쓰기, zip 내려받기 |

## 설정 규칙

- 과학적 수치와 파일 해석 규칙은 `config.yaml`에만 둔다. 키마다 한국어 주석을 단다.
- 코드에 기본값을 두지 않는다. 값은 `Config.number / integer / text / text_list / texts / text_lists`로 읽고, 키가 없거나 형이 다르면 `ConfigKeyError`가 키 이름과 함께 난다.
- 읽히지 않는 키를 두지 않는다. `tests/test_config.py::test_every_config_key_is_read`가 검사한다. 다음 단계에서 쓸 키를 미리 넣지 않는다.

## 물리·수치 규칙

- 변수와 열 이름에 단위를 붙인다 (`W_um`, `t_ox_nm`, `vds_V`, `cox_F_per_m2`).
- 실패한 값은 `0`이 아니라 `None` / NaN이다.
- 게이트 누설은 평가만 하고 점을 지우지 않는다. 점을 제거하는 처리는 명시적으로 고른 모드에서만 한다.
- off 전류는 고정된 점 개수가 아니라 안정된 저전류 구간에서 구한다.
- 방법에 따라 값이 달라지는 항목(Vth, 이동도, sweep 방향)은 방법 이름을 설정과 결과에 함께 남긴다.
- 극성(n / p)을 처음부터 반영한다. 판정하지 못하면 `unknown`으로 두고 추측하지 않는다.

## 테스트 규칙

- 값을 검증하는 테스트는 `data/raw/`를 읽지 않는다. `tests/conftest.py`의 합성 곡선과 장비 형식 작성 함수를 쓴다.
- 실제 파일 검사는 `data/raw`(또는 `FET_REAL_DATA_DIR`이 가리키는 폴더)에 배치 폴더가 있을 때만 돌고, 없으면 skip한다.
- 추출 방법의 기준은 합성 곡선의 정답이다. legacy 출력은 참고값이며, 차이는 설명할 수 있어야 한다.

## 진행 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 0 | 뼈대, 규칙 문서, 설정, 테스트 틀 | 완료 |
| 1 | 측정 모델, reader 2종, 합성 곡선 생성기 | 완료 |
| 2 | transfer 추출 (전처리, off/on, gm, Vth, SS, 이동도, 히스테리시스, 누설, 품질) | 완료 |
| 3 | 배치 실행, 출력 파일, CLI | 완료 |
| 4 | Streamlit 페이지 (Run, Devices, Compare, Finalize) | 완료 |
| 5 | 그래프에서 구간 수동 지정, 위치 맵 | 예정 |
| 6 | exe와 클라우드 배포 | 예정 |
