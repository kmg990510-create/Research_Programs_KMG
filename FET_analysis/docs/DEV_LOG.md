# FET_analysis 작업 기록

## 0–1단계: 뼈대, 표준 모델, reader 2종, 합성 곡선 (2026-11-13)

- 범위: 새 프로그램의 뼈대를 만들고, 측정 파일을 표준 내부 모델로 읽는 데까지 구현했다. 분석(추출)과 화면은 아직 없다.
- 방침: `legacy/FET device analysis/`의 정책만 가져왔고 코드는 새로 썼다. 파일 형식은 실제 측정 파일을 직접 열어 확인했다.
- 파일:
  - `config.yaml`, `fet_core/config.py` (엄격 접근, 읽힌 키 추적)
  - `fet_core/model.py`, `fet_core/naming.py`
  - `fet_core/io/loader.py`, `tables.py`, `b1500_csv.py`, `clarius_xls.py`
  - `fet_core/synth.py`
  - `tests/` (30개 + 실제 폴더 검사)
- legacy와 다르게 한 것:
  1. 중복 파일은 이름 규칙(`]-N`)이 아니라 내용(SHA-256)으로 판정하고, 건너뛴 사실을 경고로 남긴다.
  2. 그룹 이름은 소자 이름에서 위치 토큰만 뺀 것이다. B1500 파일은 `INTL#184_BG`가 된다 (legacy는 `#184_BG`).
  3. `Vds`는 값과 함께 출처(`measured` / `header` / `assumed_zero`)를 기록한다.
  4. 곡선 종류는 전압 범위가 아니라 "점마다 값이 바뀌는 전압"으로 판정한다.
  5. Clarius reader는 행 목록을 받는 순수 함수(`parse_workbook`)와 `xlrd` 호출(`read_sheets`)로 나눴다. 테스트에 `.xls` 파일이 필요 없다.
  6. 설정은 `config.yaml` 하나이고 코드에 기본값이 없다.
- 합성 곡선 모델: `Id = K·Vds·S·ln(1 + exp((Vg − Vth)/S)) + I_floor`, `K = μ·Cox·W/L`, `S = SS/ln 10`. 문턱 위에서는 기울기 `K·Vds`인 직선이고 외삽하면 `Vth`, 문턱 아래에서는 `SS` V마다 한 자릿수씩 줄어든다. p-type, 히스테리시스, 재현 가능한 잡음을 지원한다.
- 검증:
  - `pytest`: 30 passed, 1 skipped (실제 폴더 검사는 환경 변수가 없으면 skip).
  - `FET_REAL_DATA_DIR`을 legacy `data/raw`로 지정: 34 passed. 폴더 4개의 장비 파일 20개(xls 8, csv 12)가 모두 읽혔고 측정 44개가 전부 transfer로 판정됐으며 경고는 없었다.
  - legacy의 `normalized_measurements.csv`와 비교(배치 `260915`, `260916`): legacy 내보내기에 들어 있는 측정 19개는 `Vg`, `Id`, `Ig`가 전부 일치했다. 나머지 4개(`INTL#184_B3_BG`, `INTL#216_C9_BG`, `INTL184_D3`, `INTL184_B3`)는 legacy 내보내기 자체에 없어서 비교하지 못했다. 빠진 이유는 확인하지 못했다.
- 아직 없는 것:
  - 왕복 sweep을 forward / backward로 나누는 전처리 (2단계).
  - output 곡선은 판정만 한다. 실제 output 측정 파일이 없어 합성 데이터로만 확인했다.
  - p-type 실제 파일도 없다.
  - `labkit/` 공용 패키지는 만들지 않았다. 화면을 만드는 4단계에서 MoS2 배포 설정(Dockerfile, PyInstaller)과 함께 다룬다.

## 2단계: transfer 파라미터 추출 (2026-11-13)

- 범위: transfer 곡선에서 off/on 전류, gm, Vth 두 가지, SS, 이동도, 히스테리시스, 구간별 누설을 추출하고 상태와 사유를 매긴다. 결과 파일 저장과 화면은 없다.
- 파일:
  - `config.yaml`의 `analysis` 항목
  - `fet_core/analysis/settings.py`, `sweeps.py`, `numeric.py`, `transfer.py`, `results.py`
  - `fet_core/config.py` (`Config.boolean` 추가)
  - `tests/test_transfer.py` (24개), `tests/test_config.py`
- 방법은 `AGENTS.md`의 "Transfer 분석 규칙"에 정리했다.
- 설계하면서 바꾼 것 (시험 결과에 따른 결정):
  1. gm 기울기 추정: 처음에는 Theil-Sen을 썼으나, 창 안에 전류 계단이 있으면 절반 가까운 쌍이 계단을 걸쳐 기울기가 커졌다. "창 길이의 1/4만큼 떨어진 두 점" 기울기의 중앙값으로 바꿨다. 계단 하나는 쌍의 1/3 이하에만 걸린다.
  2. gm peak: 잡음이 있는 곡선의 최댓값은 위로 치우친다. 이웃 창끼리 이동 중앙값을 낸 뒤 최댓값을 잡고, 기울기 오차가 5%를 넘으면 창을 넓힌다.
  3. "잡음 크기만큼 낮은 값도 peak로 인정해 가장 이른 창을 고르는" 방식도 시험했으나 버렸다. gm이 천천히 오르는 실제 소자에서 peak보다 훨씬 앞을 골라 Vth와 이동도가 관례(최대 gm)에서 벗어났다.
  4. off 구간 길이는 점 개수가 아니라 전압(2 V, 최소 5점)으로 정한다. 1 V 간격 측정에서 11점 고정 창은 off 구간에 들어가지 않는 경우가 많았다.
  5. `gm_peak_at_sweep_edge`는 "참고" 수준으로 뒀다. 실제 측정 88개 sweep 중 64개가 해당해서, attention으로 두면 상태가 구분력을 잃는다.
  6. SS 구간의 누설은 사유가 아니라 수치(`ss_window_leak_median`)로만 남긴다. off 근처에서는 게이트 전류계 바닥이 드레인 전류보다 큰 것이 보통이다.
- 검증:
  - `pytest`: 54 passed, 2 skipped. `FET_REAL_DATA_DIR` 지정 시 62 passed.
  - 합성 곡선(정답: Vth 5 V, SS 800 mV/dec, 이동도 20 cm²/Vs), 잡음 없음, 간격 0.1 / 0.5 / 1 V: Vth 4.95~4.99 V, 이동도 19.8~19.9, SS 801~825 (1 V 간격에서 +3%), off 전류 정확.
  - 잡음 2% (0.5 V 간격), 5% (0.1 V 간격): Vth 5.0~6.0 V, 이동도 20.1~20.8, SS 708~803.
  - p-type은 n-type과 부호만 반대인 값이 나온다. 히스테리시스 3 V는 3.00 V로 복원된다. 전류 계단(on 전류의 20%)을 넣어도 gm은 3% 이내다.
  - 실제 측정 4개 폴더(측정 44개, sweep 88개): invalid 0, valid 56, attention 32. 사유는 `gm_noisy` 23, `off_plateau_not_found` 13, `leakage_dominated_transition` 3, `on_state_leakage` 1.
  - 현재 legacy 프로그램을 같은 기본 설정으로 실행한 결과와 forward sweep 44개 비교 (legacy는 44개 모두 `good`):
    - 정전류 Vth: 38개가 0.01 V 이내로 일치.
    - on 전류: 중앙값 +5%, 44개 모두 25% 이내.
    - 이동도: 중앙값 차이 −0.2%, 10% 이내 20개, 25% 이내 34개.
    - SS: 중앙값 차이 −0.6%, 10% 이내 21개, 25% 이내 31개.
    - 선형 외삽 Vth: 중앙값 차이 −0.7 V, 2 V 이내 19개, 5 V 이내 28개.
    - off 전류: 중앙값 −36% (이쪽이 더 낮은 바닥 구간을 고른다).
  - 차이가 큰 소자를 원자료로 확인한 것:
    - `INTL#216_C9_BG`: 전류가 오르내리며 뛰는 소자. legacy는 계단 하나를 gm peak로 잡아 2.19 cm²/Vs, 이쪽은 넓은 창으로 0.15이고 `gm_noisy`.
    - `INTL#215_D3_BG`: gm이 15~25 V에서 최대였다가 줄어든다. 이쪽은 18.5 V, legacy는 53 V를 골랐다.
    - `INTL185_C4`: 50~55 V 구간에서 기울기가 일시적으로 커진다. 이쪽은 그 구간을 peak로 잡아 31, legacy는 21. 어느 쪽이 맞는지는 판단하지 못했다.
- 확인하지 못한 것 / 한계:
  - 실제 p-type, 단방향 sweep, 여러 Vds로 측정한 소자 파일이 없어 합성 데이터로만 확인했다.
  - 합성 모델은 gm이 최댓값에서 평평하다. 실제 소자처럼 gm이 peak 뒤에 줄어드는 경우의 정답 시험은 없다.
  - SS는 "가장 가파른 구간"이라 잡음이 크면 실제보다 작게 나온다 (잡음 5%에서 −11%).
  - 선형 외삽 Vth는 gm peak 위치에 민감하다. sweep 끝에서 gm이 아직 오르는 소자는 sweep 범위에 따라 값이 달라진다.
  - output 곡선 분석은 없다 (`curve_not_analysed`로 기록만 한다).

## 3단계: 배치 실행, 검토 상태, 결과 파일, CLI (2026-11-14)

- 파일: `fet_core/review.py`, `pipeline.py`, `report/summary.py`, `report/export.py`, `cli.py`, `__main__.py`, `tests/test_pipeline.py`
- `SweepResult`에 계산에 쓴 치수(`W_um`, `L_um`, `t_ox_nm`, `eps_r`)를 추가했다. 소자별 치수가 다를 수 있어서 행마다 남긴다.
- 사람이 바꾼 것은 `review.json` 하나에 모은다. 분석 입력(치수, 방법 옵션)과 결정(승인·제외, 그룹 이름)을 구분해, 결정만 바꿀 때는 다시 분석하지 않는다.
- legacy와 다르게 한 것:
  1. 소자 삭제 대신 `rejected` 결정이다. 행은 표에 남고 통계와 곡선 표에서만 빠진다.
  2. 그림 파일(PNG)은 내보내지 않는다. 표와 메타데이터만 쓴다.
  3. `transfer_curves`는 A 단위 하나만 쓴다 (legacy는 A와 uA/um 두 벌).
- 검증: `pytest` 60 passed, 2 skipped. 실제 폴더 `260823`을 CLI로 실행해 파일 13개가 쓰이는 것을 확인했다.

## 4단계: Streamlit 화면과 labkit (2026-11-14)

- 파일: `gui/Main.py`, `gui/state.py`, `gui/components/figures.py`, `gui/pages/1_Run.py` ~ `5_Finalize.py`, `tests/test_gui.py`, 저장소 루트의 `labkit/` (`plot_theme.py`, `sidebar.py`)
- `requirements.txt`에 `streamlit`, `plotly`를 추가했다.
- 화면 구성과 규칙은 `AGENTS.md`의 "화면 (4단계)"에 정리했다.
- 결정:
  1. "분석 실행" 버튼을 두지 않았다. 배치를 고르거나 치수·옵션을 바꾸면 분석이 돌고 결과가 캐시된다 (실제 배치에서 0.2~3초).
  2. `labkit`은 FET만 쓴다. MoS2는 아직 자기 폴더의 `paper_theme.py`와 `report_loader.sidebar_section`을 쓴다. MoS2를 옮기려면 Dockerfile과 PyInstaller 설정을 같이 바꿔야 한다.
  3. 화면 그림은 Plotly이고, 저장은 그림의 카메라 버튼(PNG, 3배 해상도)으로 한다.
- 검증:
  - `pytest`: 78 passed, 2 skipped (측정 폴더가 없을 때). `data/raw`에 실제 배치 4개를 두면 86 passed. `tests/test_gui.py`가 합성 배치로 6개 페이지를 실행해 예외가 없는지, 사이드바가 번호 구획만 쓰는지, 배치가 없을 때 안내가 나오는지, 치수 저장·결정 저장·결과 파일 쓰기가 되는지 확인한다.
  - 브라우저에서 실제 배치 `260916`으로 Device Viewer(log / linear 그림, 값, 결정 영역)와 Compare(overlay, 이동도 box)를 눈으로 확인했다.
- 확인하지 못한 것:
  - Run, Review, Finalize 페이지는 브라우저에서 눈으로 보지 않았다 (자동 실행만).
  - 파일 업로드, 소자별 치수 표 저장, 그룹 이름·순서 저장, zip 내려받기는 눌러 보지 않았다.
  - 클라우드와 exe 환경은 다루지 않았다 (6단계).
- 한계:
  - 그래프에서 구간을 직접 고르는 기능과 웨이퍼 위치 맵은 없다 (5단계).
  - Device Viewer에 gm 곡선 그림은 없다. 접선과 gm 창만 표시한다.
  - 업로드는 `.csv`와 `.xls` 개별 파일만 받는다 (zip 미지원).

## 화면 개편: Review + Device Viewer → Devices (2026-11-14)

- 이유: 판단하는 표(Review)와 근거가 되는 그림(Device Viewer)이 다른 페이지에 있었다. 배치 하나가 소자 10~50개라 나눌 이유가 없었다.
- 페이지: `Run`(진입 페이지, 이전 Main과 Run을 합침) / `Devices` / `Compare` / `Finalize`.
- 파일: `gui/Run.py`, `gui/pages/1_Devices.py`, `2_Compare.py`, `3_Finalize.py`, `gui/components/values.py`, `figures.py`(`gallery_figure`), `gui/state.py`, `tests/test_gui.py`. 지운 것: `gui/Main.py`, `pages/2_Review.py`, `pages/3_Device_Viewer.py`.
- 바뀐 점:
  1. Devices Detail: 왼쪽 목록에서 행을 누르면 오른쪽 그림이 바뀐다. `Approve` / `Reject`는 즉시 저장하고 다음 sweep으로 넘어간다. 메모는 Enter에 저장한다.
  2. Devices Gallery: 모든 소자를 작은 log 그림 격자로 그린다 (검정 valid, 주황 attention, 빨강 invalid, 회색 점선 rejected). 패널을 누르면 Detail로 간다.
  3. Sweep 선택 라디오를 없앴다. 사이드바 필터에서 고른 방향마다 목록에 한 행이 생긴다.
  4. Compare: 지표 여러 개를 2열로 한 번에 그린다. 그룹 이름·순서 표를 사이드바에서 본문 탭으로 옮기고 즉시 저장한다. Overlay는 통계에 드는 sweep만 그린다.
  5. 사이드바: `1) Run` → `1) Batch`. 페이지별 3번 구획을 없앴다. 필터는 모든 페이지가 같은 상태를 쓰고 기본값은 전부 표시다.
- Streamlit에서 확인한 것:
  - `st.dataframe` / `st.plotly_chart`의 `on_select` 콜백은 `args`를 받지 않는다. `functools.partial`을 쓴다.
  - 선 그림은 marker가 없으면 클릭 선택이 전달되지 않는다. 투명 marker를 넣고 `hoverdistance=-1`로 두면 패널 어디를 눌러도 가장 가까운 점이 선택된다.
  - 선택 상태를 코드로 바꿀 수 없어서, 선택을 옮길 때 위젯 key의 번호를 올려 이전 선택을 버리고 목록의 `▶` 열로 현재 행을 표시한다.
- 검증: `pytest` 전체 통과 (아래 숫자는 실제 배치 4개가 있을 때). 브라우저에서 실제 배치 `260916`으로 Devices Detail, 목록 행 클릭, Gallery 패널 클릭, Reject 저장 후 다음 행 이동, Clear를 눌러 확인했다. Compare는 지표 4개가 2x2로 그려지는 것을 페이지 구조로 확인했다 (스크린샷은 실패).
- 확인하지 못한 것: Compare의 그룹 이름·순서 즉시 저장은 브라우저에서 눌러 보지 않았다. 메모 저장은 자동 테스트로만 확인했다. Run과 Finalize는 내용이 바뀌지 않아 다시 보지 않았다.

## 그래프 크기 입력 (2026-11-14)

- 요구: 모든 그래프의 가로·세로를 사용자가 정할 수 있어야 한다.
- 파일: `labkit/figure_size.py`(`figure_size_inputs`, `show_figure`), `gui/pages/1_Devices.py`, `2_Compare.py`, `gui/components/figures.py`(`gallery_size`), `tests/test_gui.py`.
- 사이드바 `3) Figure size`: Devices는 Detail 곡선 크기, Gallery 패널 크기, 한 줄의 패널 수. Compare는 Statistics 한 칸의 크기, Overlay 크기.
- 가로 기본값은 "Fit width to the page"다. 끄면 Width 입력이 켜진다 (숨기지 않고 비활성화). 선택은 세션 동안 페이지를 옮겨도 유지된다.
- 크기는 그림의 layout에도 써서 카메라 버튼으로 저장한 그림이 화면과 같은 크기다 (해상도는 3배).
- 검증: `tests/test_gui.py`가 두 페이지의 모든 그림이 사이드바 값(610 x 330)을 따르는지 확인한다. 브라우저에서 Devices Detail의 가로 고정(520 x 420)을 확인했다. Compare와 Gallery의 고정 크기는 브라우저에서 보지 않았다.

- 추가 (같은 날): MoS2도 `labkit`을 쓰게 하면서 `labkit.plot_theme`에 `colorbar_style`, `MUTED_INK`를, `labkit.figure_size`에 `stored_figure_size`와 `show_figure(theme=...)`를 넣었다. FET 동작은 그대로다 (`pytest` 89 passed).

- 추가 (같은 날): 두 프로그램의 그래프 모양을 하나로 맞췄다.
  - `gui/components/figures.py`의 색(`MUTED`, `MARK`, `FIT`, `STATUS_COLORS`)과 선 굵기·점 크기 숫자를 `labkit.plot_theme`의 이름으로 바꿨다. 눈에 보이는 차이: I_off 구간 선 4 → 2.4, gm 접선 2 → 2.4, Overlay 선 1.4 → 1.6, Statistics 점 9 → 7.
  - 페이지는 `show_figure(fig, size, filename=...)`만 부른다. 이미지 형식과 3배 해상도는 `show_figure`가 정한다.
  - `3) Figure size` 구획에 `Grid`(기본 꺼짐)와 `Image format`(png/svg)이 생겼고 모든 그래프에 적용된다.
  - 검증: `pytest` 90 passed. 브라우저에서 Devices Detail과 Compare의 그림이 Arial 14, 격자 없음, 지정한 파일 이름으로 뜨는 것을 확인했다. FET 화면에서 `Grid`를 켜 보지는 않았다 (MoS2 화면과 자동 테스트로 확인).

- 추가 (같은 날): 원칙 점검에서 나온 것을 고쳤다.
  - gm 잡음을 재는 범위(`0.5 * top`)를 `config.yaml`의 `analysis.gm.noise_top_fraction`으로 옮겼다. 값은 그대로 0.5라 결과는 같다.
  - Devices 제목의 상태 글자: valid는 색 없이, attention은 orange, invalid는 red (그래프의 상태 색과 맞춤. 이전에는 valid가 초록).
  - `figures.py`의 점 테두리 굵기와 Gallery 글씨 크기를 `labkit.plot_theme`의 `OUTLINE`, `OUTLINE_THIN`과 `GALLERY_FONT_SIZE`로 바꿨다. Statistics 점 테두리 1 → 0.8.
  - 검증: `pytest` 90 passed. 화면은 Devices와 Compare가 오류 없이 뜨는 것만 확인했다.
