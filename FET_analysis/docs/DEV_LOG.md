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
