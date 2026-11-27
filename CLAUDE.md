# CLAUDE.md

이 저장소의 공통 UI·개발 원칙은 **[AGENTS.md](AGENTS.md)** 에 있다. 작업 전에 읽는다.
프로그램별 규칙은 각 폴더의 `AGENTS.md`를 따른다 ([MoS2_optical_analysis/AGENTS.md](MoS2_optical_analysis/AGENTS.md), [FET_analysis/AGENTS.md](FET_analysis/AGENTS.md), [MoS2_adsorption_sim/AGENTS.md](MoS2_adsorption_sim/AGENTS.md)).
통합 Streamlit 진입점은 루트 [app.py](app.py) (`Run_Lab_GUI.cmd`)다.
공개 저장소 원칙 — 측정 원본·분석/시뮬레이션 결과·연구 보고서·그림·로그는 전부 각 프로그램의 `data/` 아래에만 두고 git 추적에서 제외한다.
