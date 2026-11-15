# MoS2_adsorption_sim

단층 $\text{MoS}_2$(기저면 및 점결함 표면)와 분자(ALD 전구체, 시드 레이어 리간드, 촉매·도판트 분자 등) 사이의 **흡착 에너지($E_{\text{ads}}$)와 평형 구조**를 **uMLIP(MACE, MatterSim) + DFT-D3 반데르발스 분산력 보정**으로 스크리닝하는 시뮬레이션 및 분석 프로그램이다.

- 프로그램 규칙과 출력 계약: [`AGENTS.md`](AGENTS.md)
- 과학적 보완 설계 및 단계별 구현 계획: [`docs/PLAN.md`](docs/PLAN.md)

## 핵심 특징

1. **uMLIP + DFT-D3 결합 (`SumCalculator`):** 반데르발스 인력이 지배적인 2D $\text{MoS}_2$ 기저면에서 PBE 기반 uMLIP 단독 계산의 분산력 과소평가 문제를 `torch-dftd` 결합으로 보정하고, 총 흡착 에너지를 **uMLIP 성분($E_{\text{ads}}^{\text{uMLIP}}$)과 분산력 성분($E_{\text{ads}}^{\text{D3}}$)으로 정량 분해**한다.
2. **자체 일관적 기준 에너지 및 변형 에너지($E_{\text{def}}$) 분해:** 슬랩 단독($E_{\text{slab}}$)과 진공 기체 분자 단독($E_{\text{mol}}$)을 동일한 계산기와 수렴 기준으로 이완하며, 흡착 전후 격자·분자의 뒤틀림 비용($E_{\text{def, slab}}, E_{\text{def, mol}}$)과 순수 상호작용 에너지($E_{\text{int}}$)를 분리한다.
3. **다중 초기 포즈(Multi-Pose) 샘플링:** 대칭 사이트(`Mo_top`, `S_top`, `Hollow`, `Bridge`, 황 공공 `V_S`, `V_S2`)와 분자 배향 조합을 자동으로 생성·이완하여 **최안정 포즈($E_{\text{ads, min}}$)**와 **볼츠만 가중 평균($\langle E_{\text{ads}} \rangle_{300\text{ K}}$)**을 함께 도출한다.
4. **자동 품질 판정 및 Streamlit 검토 화면 (`labkit` 공용 테마):** 미수렴, 원자 겹침, 진공 이탈, 해리 흡착 후보를 자동으로 판정(`valid` / `attention` / `invalid`)하고, 화면에서 원자 배치(Top/Side view)와 수렴 곡선을 확인하며 승인·제외·비교·내보내기(Origin용 CSV + `.xyz` 구조 파일)를 수행한다.

## 로컬 환경 구축 (Windows WSL2 Ubuntu 권장)

```bash
# 1. 가상환경 생성 및 활성화 (Python 3.11 권장)
conda create -n umlip python=3.11 -y
conda activate umlip

# 2. PyTorch 설치 (NVIDIA GPU가 있는 경우 CUDA 버전에 맞춰 설치)
pip install torch torchvision torchaudio

# 3. 원자 시뮬레이션, 분산력 보정 및 3D/UI 패키지 설치
pip install ase pymatgen torch-dftd py3Dmol streamlit plotly pandas pyyaml pytest matplotlib

# 4. uMLIP 모델 설치 (MACE 또는 MatterSim 중 택 1, 둘 다 설치 가능)
pip install mace-torch
pip install mattersim
```

> **참고:** uMLIP 패키지(`mace-torch`, `mattersim`, `torch-dftd`)가 없는 환경에서도 내장 합성 포텐셜(`synth_morse`)을 통한 파이프라인 테스트(`pytest`)와 이미 계산된 결과 배치의 GUI 검토·비교·내보내기가 모두 동작한다.

## 빠른 실행

```bash
# 1. 배치 시뮬레이션 실행 (예: pristine vs V_S, D3 대조 및 전체 사이트 1D 결합 곡선 포함)
python -m ads_core run --batch demo_screening --surfaces pristine_4x4 V_S_4x4 --molecules H2O NH3 TMA --backend synth_morse --scan-binding-curves --scan-all-sites --compare-no-d3

# 2. 물리적 흡착 레짐 벤치마크 실행 (H2O, NH3, TMA × pristine/V_S)
python -m ads_core benchmark --fast --backend synth_morse

# 3. review.json 반영 후 CSV·구조 재내보내기
python -m ads_core export --batch-dir data/results/demo_screening

# 4. Streamlit 검토·비교 화면 실행 (단독 실행: Run_Adsorption_GUI.cmd / 통합 실행: ..\Run_Lab_GUI.cmd)
python -m streamlit run ads_gui/Run.py

# 5. 전체 자동 테스트
python -m pytest -v
```
