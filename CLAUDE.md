# CLAUDE.md

이 저장소의 공통 UI·개발 원칙은 **[AGENTS.md](AGENTS.md)**, 탐색 연구 실행·기록·정리 규범은 **[RESEARCH_GUIDE.md](RESEARCH_GUIDE.md)** 에 있다. 작업 전에 읽는다.
프로그램별 규칙은 각 폴더의 `AGENTS.md`를 따른다 ([MoS2_optical_analysis/AGENTS.md](MoS2_optical_analysis/AGENTS.md), [FET_analysis/AGENTS.md](FET_analysis/AGENTS.md), [MoS2_adsorption_sim/AGENTS.md](MoS2_adsorption_sim/AGENTS.md)).
통합 Streamlit 진입점은 루트 [app.py](app.py) (`Run_Lab_GUI.cmd`)다.

## 절대 규칙 (공개 레포 위생 & 연구 기록)

- **`data/`와 `research/`는 100% 비공개(git 제외):** 측정 원본, GUI/CLI 배치 결과(`data/`)뿐 아니라 **모든 탐색 연구 스크립트·연구 전용 YAML/후보·엔진·테스트·결과·로그·그림·보고서(`.md`, `.pptx`)·`PLANS.md`·`build_*pptx*.py`** 도 각 프로그램 `research/<topic>/` 아래에만 둔다.
- **연구 시작·종료 게이트:** 새 연구를 시작할 때는 `python scripts/init_research.py --program <prog> --topic <topic>`을 먼저 실행하고, 분석·시뮬레이션 완료 전 반드시 `research/<topic>/reports/YYYYMMDD_*.md` 보고서, CSV/메타데이터 JSON, 로그(`logs/`), `README.md` 이력 갱신을 마친다.
- `docs/DEV_LOG.md`, `AGENTS.md`, `docs/PLAN.md`, `config.yaml`, `tests/`에는 공용 프로그램 코드·방법·설계·합성 테스트만 두고 미공개 연구 수치·시료 관찰·후보 리스트·결론을 쓰지 않는다.
- git 추적 파일에 `_v2`, `_updated`, `_final`, `_review` 접미를 붙이지 않으며, 공용 `tests/`는 `data/`/`research/` 파일에 의존하지 않는다.
- 커밋 전 `python scripts/check_repo_hygiene.py` 통과를 확인한다(`.git/hooks/pre-commit` 자동 점검).
