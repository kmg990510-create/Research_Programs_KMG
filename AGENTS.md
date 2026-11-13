# AGENTS.md — Research_Programs_KMG 공통 원칙

이 저장소의 모든 연구실 프로그램이 따르는 UI·개발 원칙이다.
각 프로그램 폴더의 `AGENTS.md`는 그 프로그램만의 규칙을 담고, 이 문서와 충돌하면 이 문서를 먼저 고친 뒤 맞춘다.

원칙의 출처는 두 가지 기존 코드다.

- `MoS2_optical_analysis/` — Raman/PL 피팅, Streamlit GUI, exe·클라우드 배포
- `legacy/FET device analysis/` — FET transfer/output 분석, CustomTkinter GUI (참고용)

## 1. 저장소 구조

```text
Research_Programs_KMG/
  AGENTS.md                 공통 원칙 (이 문서)
  MoS2_optical_analysis/    Raman/PL 분석
  FET_analysis/             FET 분석 (새로 작성 중, 진행 단계는 FET_analysis/AGENTS.md)
  labkit/                   공용 코드 (아직 없음, 6장 참고)
  legacy/                   이전 프로그램. 참고용이며 수정하지 않고 코드를 가져오지 않는다
```

- 프로그램 하나는 폴더 하나이고, 그 폴더만으로 실행·테스트·배포가 된다.
- 프로그램 폴더는 `AGENTS.md`, `README.md`, 설정 YAML, `tests/`, `docs/`를 가진다.
- 측정 데이터와 분석 결과(`data/raw`, `data/results`, `data/outputs`)는 git에 올리지 않는다.

## 2. 개발 원칙

1. **계산과 화면을 분리한다.** 분석 코드는 `streamlit`을 import하지 않는다. CLI와 GUI는 같은 분석 함수를 부르기만 한다.
2. **장비 파일은 표준 내부 모델로 바꾼 뒤 분석한다.** 장비별 형식(시트 이름, 열 이름, 헤더)은 reader와 파싱 프로필 YAML 안에만 둔다. 새 reader는 실제 예시 파일이 생겼을 때만 만든다.
3. **분석과 저장을 분리한다.** 분석은 메모리에서 끝내고, 디스크 쓰기는 사용자가 검토한 뒤 별도 단계에서 한다 (FET의 `analyze_in_memory` / `export_results` 방식).
4. **자동 분석 후 사람이 검토한다.** 자동 추출 → 의심 항목 표시 → 수동 수정·제외 → 확정 순서를 따른다. 수동 수정과 제외는 원본을 덮어쓰지 않고 별도 기록으로 남긴다.
5. **데이터를 조용히 버리거나 꾸미지 않는다.**
   - 추출에 실패한 값은 `0`이 아니라 빈 값(`None`/NaN)으로 둔다.
   - 품질 문제는 원인을 이름으로 가진 경고로 남긴다.
   - 점을 제거하는 처리(예: 누설 마스킹)는 기본값이 아니라 명시적으로 고른 모드에서만 한다.
   - 지원하지 않는 경우(예: p-type FET)는 추정하지 않고 표시한 뒤 요약에서 뺀다.
6. **방법 선택을 드러낸다.** 방법에 따라 값이 달라지는 항목(Vth 방법, 이동도 영역, sweep 방향, 피팅 모델)은 설정에 이름으로 있고 결과에도 기록된다.
7. **과학적 수치는 YAML에만 둔다.** 피크 위치, 윈도우, 임계값, 소자 치수 같은 값을 Python 리터럴로 쓰지 않는다. 프로그램마다 기준 설정 파일은 하나다 (MoS2 `config.yaml`, FET `config/defaults.yaml`). 설정 키에는 한국어 주석을 단다.
8. **결과는 재현 가능해야 한다.** 결과마다 프로그램 버전과 git commit, 사용한 설정 전체, 입력 파일 목록(가능하면 SHA-256), GUI에서 한 수정 내역을 함께 저장한다.
9. **단위를 명시한다.** 변수·열 이름에 단위를 붙이고(`W_um`, `t_ox_nm`), 단위 변환은 코드에 드러나게 쓴다.
10. **라이브러리 코드는 `print` 대신 `logging`을 쓴다.** 로그 설정은 CLI와 GUI 진입점에서만 한다.
11. **의존성은 실제로 필요할 때만 추가한다.**

## 3. UI 원칙

### 페이지 순서

모든 프로그램이 같은 흐름을 쓴다. 해당 없는 단계는 생략하되 순서는 바꾸지 않는다.

| 단계 | 하는 일 | MoS2 | FET |
| --- | --- | --- | --- |
| Run | 데이터 선택, 설정, 분석 실행 | `1_Run_Analysis` | 파일 불러오기, 치수·분석 설정 |
| Review | 의심 항목 확인, 수정·제외 | `2_Flagged_Spectra` | 경고가 있는 소자 목록 |
| Viewer | 개별 항목 상세 | `3_All_Spectra_Viewer`, `4_Map_Viewer` | 소자별 gm / Vth / SS 진단 |
| Compare | 그룹·시료 비교 | `5_Model_Comparison`, `6_Sample_Comparison` | 그룹 overlay, boxplot |
| Finalize | 확정, 내보내기 | `7_Finalize` | export |

### 화면 규칙

- 사이드바에서는 데이터·결과를 고르고, 본문에서는 결과를 본다.
- 사이드바는 번호 붙은 접이식 구획으로만 구성한다: `1) Report`, `2) Filters`, 그다음 페이지별 구획. 구획 밖에 입력란을 두지 않는다 (MoS2 `report_loader.sidebar_section`).
- 효과가 없는 입력란은 숨기지 않고 비활성화한다.
- 기본값만으로 분석이 실행되어야 한다. 자주 안 쓰는 설정은 `Advanced` expander에 넣는다.
- 분석 결과에 영향을 주는 입력(FET의 `W`, `L`, `t_ox`, `eps_r` 등)은 Run 단계에서 항상 보이고 결과에 기록된다.
- 화면 라벨과 그래프 축은 영어, 사용 매뉴얼과 설정 주석은 한국어로 쓴다.
- 축 라벨에는 항상 단위를 쓴다.
- 삭제는 휴지통 이동(soft-delete)이 먼저고, 영구 삭제는 명시적 확인을 받는다.
- 오래 걸리는 작업은 진행 상태를 보여 주고, 원본 로그는 `Advanced`에 둔다.

### 그래프

- 화면의 대화형 그래프는 Plotly, 내보내는 그림 파일은 matplotlib로 그린다.
- 프로그램 전체가 하나의 테마를 쓴다 (MoS2 `gui/components/plot_theme.py`).
- 그리는 코드는 추출·피팅 함수 안에 넣지 않는다.

### 페이지 코드

- 페이지 파일은 화면 배치만 한다. 로직은 `gui/components/` 또는 분석 패키지에 둔다.
- 페이지 파일이 400줄을 넘으면 component로 나눈다.
- `st.session_state` 키는 `페이지이름_용도` 형태로 붙인다.

## 4. 출력 계약

- 표준 형식은 요약 CSV와 메타데이터 JSON이다. CSV는 Origin에 바로 불러올 수 있는 형태(첫 행이 열 이름, 열마다 단위 표기)로 쓴다.
- 출력 파일 이름, 열 이름, 상태 값은 각 프로그램 `AGENTS.md`의 "Output Contracts"에 적고, 바꿀 때는 코드와 문서를 같은 커밋에서 바꾼다.
- 항목 상태는 3단계로 표시한다: `valid` / `attention` / `invalid`. 세부 원인은 별도 열이나 경고 코드로 남긴다 (FET의 `parameter_quality`, `warnings.csv`).
- 요약 통계에 넣을지 여부는 한 함수에서만 판단한다 (FET `is_valid_for_summary`). GUI, 저장, 통계 그림이 같은 판단을 쓴다.

## 5. 실행 환경

- 로컬(소스 실행, Windows exe)과 클라우드(Streamlit Cloud, Docker)를 모두 지원한다.
- 환경 구분은 한 함수에서만 한다 (MoS2 `runtime_paths.is_cloud_runtime()`).
- 클라우드에서는 업로드로 받고 다운로드로 내보낸다. 로컬 폴더 경로나 데스크톱 창이 필요한 기능은 숨긴다.
- 클라우드 컨테이너는 메모리가 1 GB 수준이라고 가정하고, 병렬 worker 수와 화면 갱신 빈도의 기본값을 낮게 둔다.

## 6. 공용 코드 (`labkit`)

- 두 번째 프로그램에서 실제로 같은 코드가 필요해졌을 때만 `labkit/`으로 옮긴다. 미리 만들지 않는다.
- 후보: Plotly 테마, 사이드바 구획, 클라우드 감지, 업로드/압축 해제, zip 내보내기, 휴지통, 빌드 정보, 재현성 메타데이터 작성.
- 만드는 시점은 FET 화면을 만들 때다. MoS2가 `labkit`을 쓰려면 Dockerfile과 PyInstaller 설정도 같이 바꿔야 하므로 그때 함께 한다.
- `labkit`에는 특정 측정 방법(Raman, FET)에 대한 지식을 넣지 않는다.

## 7. 테스트와 Git

- 테스트는 `data/raw/`의 실제 파일에 의존하지 않는다. 합성 입력을 만들어 쓰고, 실제 파일이 필요한 테스트는 파일이 없으면 skip한다.
- 추출·피팅 방법을 바꾸면 기존 결과와의 차이를 수치로 확인한 뒤 기본값을 바꾼다 (MoS2 TASK-021 방식).
- 작업마다 브랜치를 만든다 (`feat/...`, `fix/...`, `chore/...`, `exp/...`). 커밋은 작게, 동작이 바뀌면 문서도 같은 커밋에 넣는다.
- exe 빌드·패키징은 사용자가 요청했을 때만 실행한다.
- 릴리스 태그는 프로그램별 접두어를 쓴다 (`mos2-v<version>`, `fet-v<version>`).

## 8. FET 구현 방침

`legacy/FET device analysis/`는 참고 자료다. 설계 의도와 정책은 가져오고, 코드는 가져오지 않는다.

- `FET_analysis/`의 코드는 새로 쓴다. legacy 파일을 복사하거나 옮겨 적지 않는다.
- legacy에서 가져오는 것은 정책이다: 표준 내부 모델, 장비별 reader 분리, 분석과 저장의 분리, 누설 전류 정책(점을 지우지 않고 평가만), off 전류 정책(고정 점 개수가 아니라 안정 구간), 실패 값은 빈 값, 원인 이름이 붙은 경고, 재현성 메타데이터.
- legacy의 출력은 검증용 기준값으로 쓴다. 같은 입력에서 값이 다르면 원인을 설명할 수 있어야 한다. 일치시키는 것이 목표는 아니다.
- 화면은 3장의 페이지 순서와 사이드바 규칙을 따르는 Streamlit으로 만든다.

## 9. 현재 코드가 원칙과 다른 부분

고칠 때는 별도 작업으로 한다.

- MoS2 페이지 파일이 크다: `6_Sample_Comparison.py` 1312줄, `1_Run_Analysis.py` 939줄, `3_All_Spectra_Viewer.py` 857줄.
- MoS2 페이지마다 `sys.path` 부트스트랩 코드가 복사되어 있다.
- 루트 `requirements.txt`, `Dockerfile`, GitHub Actions 워크플로가 MoS2 하나만을 전제로 한다.
- 상태 용어가 다르다: MoS2는 `fit_status`, FET는 `parameter_quality` + `valid_for_summary`.
- FET는 화면과 내보내기 모두 matplotlib를 쓴다.
- `legacy/FET device analysis/`는 자체 `.git`을 가진 별도 저장소다. 이 저장소에 그대로 `git add` 하지 않는다.
