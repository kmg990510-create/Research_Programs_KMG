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

- 테스트는 `data/raw/`를 읽지 않는다. `tests/conftest.py`의 합성 곡선과 장비 형식 작성 함수를 쓴다.
- 실제 파일 검사는 `FET_REAL_DATA_DIR`이 있을 때만 돌고, 없으면 skip한다.
- 추출 방법의 기준은 합성 곡선의 정답이다. legacy 출력은 참고값이며, 차이는 설명할 수 있어야 한다.

## 진행 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 0 | 뼈대, 규칙 문서, 설정, 테스트 틀 | 완료 |
| 1 | 측정 모델, reader 2종, 합성 곡선 생성기 | 완료 |
| 2 | transfer 추출 (전처리, off/on, gm, Vth, SS, 이동도, 히스테리시스, 누설, 품질) | 예정 |
| 3 | 배치 실행, 출력 파일, CLI | 예정 |
| 4 | Streamlit 페이지 (Run, Review, Device Viewer, Compare, Finalize) | 예정 |
| 5 | 그래프에서 구간 수동 지정, 위치 맵 | 예정 |
| 6 | exe와 클라우드 배포 | 예정 |
