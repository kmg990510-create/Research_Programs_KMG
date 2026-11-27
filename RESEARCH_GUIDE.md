# RESEARCH_GUIDE.md — 탐색 연구 실행·기록·정리 공통 규범

이 문서는 세 프로그램(`MoS2_optical_analysis`, `FET_analysis`, `MoS2_adsorption_sim`)에서 **특정 연구 주제를 탐색 분석·시뮬레이션할 때** 사람과 AI가 반드시 지켜야 하는 표준 절차다.
공통 UI·개발 원칙은 [`AGENTS.md`](AGENTS.md)에 있고, 이 문서는 **연구 작업의 시작–종료–정리 게이트와 과학적 정직성 규칙**을 다룬다.

---

## 1. 공개 레포 vs 비공개 연구 공간

| 구분 | 위치 | git 추적 | 내용 |
| --- | --- | --- | --- |
| 공용 프로그램·테스트 | `<Program>/<pkg>_core/`, `<pkg>_gui/`, `tests/`, 공용 `config.yaml`, `docs/` | **공개** | 누구에게나 적용되는 분석·시뮬레이션·GUI 방법과 **합성 fixture 기반** 단위 테스트 (`tests/`) |
| 측정/배치 데이터 | `<Program>/data/{raw,results,molecules,bin}/` | **비공개(제외)** | 측정 원본 및 정규 GUI/CLI 배치 결과 |
| 특정 주제 연구 | `<Program>/research/<topic>/` | **비공개(제외)** | 연구 스크립트, 공정/후보 YAML, 연구 전용 모듈·테스트, 계산 결과(`mlip/`, `dft/`), 보고서(`reports/*.md`, `*.pptx`), 그림(`figures/`), 로그(`logs/`), `README.md`, `PLANS.md` |

- **`tests/` vs `research/` 경계:** 공용 `tests/`는 **프로그램 코드 자체가 정상 동작하는지** 합성 데이터로 검증한다. 특정 분자·공정 조건·실험 결정 구조(`.cif`)·연구 가설을 검증하는 테스트나 스크립트는 `research/<topic>/` 안에만 둔다.
- `research/<topic>/` 안의 코드와 데이터는 **이중 분리하지 않고 한 주제 폴더 안에 함께 보관**한다. `.gitignore`가 `research/` 전체를 제외한다.

---

## 2. 시작 게이트 (Start Gate)

새 연구 주제를 시작할 때 임의로 루트나 `docs/`에 폴더·파일을 만들지 않고 반드시 초기화 스크립트를 먼저 실행한다.

```bash
python scripts/init_research.py --program <MoS2_optical_analysis|FET_analysis|MoS2_adsorption_sim> --topic <topic_name>
```

생성되는 표준 구조:

```text
<Program>/research/<topic_name>/
  README.md          주제 개요 및 실행 이력 표
  PLANS.md           연구 가설·단계별 계획·체크리스트
  configs/           연구 전용 YAML, 공정 조건, 후보 리스트, 구조 파일(.cif 등)
  engine/            공용 코어에 넣기 전 연구 전용 분석/시뮬레이션 모듈 (필요 시)
  scripts/           번호 또는 단계 이름이 붙은 재실행 가능 스크립트
  tests/             해당 연구 전용 검증 테스트
  logs/              실행 표준 출력 로그 (*.txt)
  figures/           보고서·발표용 그림 (*.png)
  reports/           단계별 마크다운 보고서 (YYYYMMDD_<step>.md), TEMPLATE_report.md, 발표 자료(*.pptx)
  scratch/           일회성 탐색 스크립트 (정리 대상)
```

(`MoS2_adsorption_sim`은 `molecules/`, `mlip/`, `dft/`가 함께 만들어지고, `MoS2_optical_analysis`는 `slides/`, `slides/templates/`가 함께 만들어진다.)

---

## 3. 종료 게이트 (Done Gate — 필수 산출물)

AI 또는 연구자가 **어떤 분석·시뮬레이션 실행을 "완료"로 보고하기 전**, 아래 4가지를 모두 `research/<topic>/` 아래에 남겨야 한다. 하나라도 빠지면 미완료로 간주한다.

1. **마크다운 보고서 (`reports/YYYYMMDD_<단계_또는_주제>.md`)**
   - `reports/TEMPLATE_report.md` 구조를 따라 작성한다:
     - **목적과 질문:** 무엇을 검증/비교하려 했는가
     - **입력·설정 요약:** 사용한 입력 데이터/구조, YAML 설정 경로, 주요 파라미터(온도·컷오프·모델 등)
     - **정량 결과 표:** 핵심 수치를 단위와 함께 정리 (성공/실패·경고 개수 포함)
     - **해석 및 한계:** 관찰된 경향, 대안 가설, 현재 모델/데이터의 한계·주의사항
     - **산출물 및 로그 위치:** CSV, JSON, 그림, 로그 파일의 정확한 상대 경로
2. **표준 정량 테이블 + 재현성 메타데이터**
   - 요약 수치 CSV (Origin 호환 UTF-8 BOM, 첫 행 열 이름 + 단위 표기)
   - 메타데이터 JSON (`git commit`, 실행 시각, 사용한 설정 YAML 전체 스냅샷, 입력 파일 목록, `method_warnings`)
3. **실행 로그 (`logs/*.txt`) 및 시각 자료 (`figures/*.png`)**
   - 스크립트 실행 표준 출력·경고를 텍스트 로그로 보존해 사후 재확인이 가능하게 한다.
4. **주제 `README.md` 실행 이력 갱신**
   - `README.md` 맨 아래 `실행 이력` 표에 날짜, 실행 스크립트, 보고서 링크, 핵심 결론 1줄을 추가한다.

---

## 4. 정리·수명주기 게이트 (Cleanup Gate)

작업이 끝난 뒤 작업 공간이 어질러지지 않도록 아래를 정리한다.

- **스크래치 정리:** 일회성으로 `scratch/`에 만든 파일은 검증이 끝나면 삭제하거나, 재사용할 것만 정리해 `scripts/`로 승격한다.
- **임시/중복 파일 방치 금지:** 깨진 테스트 출력이나 이름만 다른 중복 스크립트를 남기지 않는다. 폐기할 연구 설정이나 후보는 조용히 지우기보다 `DEPRECATED` 주석·경고를 붙여 구분한다.
- **공개 영역 오염 점검:** 실수로 `<Program>/config.yaml`, `docs/DEV_LOG.md`, `AGENTS.md`, `tests/`에 연구 수치·샘플 ID·연구 전용 YAML을 적지 않았는지 확인한다.
- **위생 검사:** git 작업 시 `python scripts/check_repo_hygiene.py` 통과를 확인한다 (`.git/hooks/pre-commit` 자동 실행).

---

## 5. 과학적 정직성 및 AI 흔한 함정 방지

AI 에이전트가 탐색 연구를 수행할 때 자주 범하는 오류를 막기 위한 필수 수칙이다.

1. **타겟 누출(Target Leakage) 금지:** 실험 관측값(두께, 탈착 온도, 소자 특성 등)을 시뮬레이션 입력이나 모델 매개변수에 역주입하지 않는다. 모든 계산·예측은 독립 실행 후 사후 대조만 한다.
2. **과장·단정 표현 금지:** 보고서·슬라이드 본문에 `"확정"`, `"입증"`, `"완벽 복원"` 같은 단정 표현을 쓰지 않는다. 근거 데이터, 가정, 대안 해석 가능성을 함께 적는다.
3. **지원 불가 영역 추론 금지:**
   - 무스핀 uMLIP(`MACE-MP` 등)로 삼중항 $\text{O}_2$·열린 껍질 라디칼·반응 장벽을 계산하지 않는다 (`spinpol=True` DFT로 계산).
   - 결함 화학흡착·전하 이동·근접 후보 간 최종 순위는 uMLIP만으로 결론내리지 않고 DFT 검증과 함께 보고한다.
   - 지원하지 않는 소자/모드(p-type FET 등)는 추정하지 않고 제외 사유로 남긴다.
4. **조용한 값 대체·점 제거 금지:** 추출 실패 값을 `0`으로 채우지 않고 `None`/NaN과 사유 코드로 남기며, 이상치 점은 기본값으로 지우지 않는다.
5. **외부 입력·단위 교차 검증:** 외부 CIF·문헌 상수·장비 파일은 원자 조성, 공간군, 격자 상수, 단위를 원본과 직접 대조한 뒤 사용한다.
