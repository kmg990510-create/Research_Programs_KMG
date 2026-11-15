# FET_analysis

FET 측정 파일에서 소자 파라미터를 추출하는 프로그램이다. 측정 파일을 읽어 transfer 곡선의 파라미터를 추출하고, 화면에서 검토한 뒤 결과 파일로 내보낸다 (진행 단계와 규칙은 [AGENTS.md](AGENTS.md) 참고).

## 지원하는 입력

| 장비 | 형식 | reader |
| --- | --- | --- |
| Keysight B1500 (EasyEXPERT) | `.csv` 내보내기, 파일 하나에 측정 하나 | `fet_core/io/b1500_csv.py` |
| Keithley 4200A (Clarius) | `.xls` 워크북, 시트 하나에 측정 하나 | `fet_core/io/clarius_xls.py` |

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 사용

측정 파일을 `data/raw/<배치 이름>/`에 넣거나, 화면의 Run 페이지에서 올린다.

```powershell
# 화면 (단독 실행: Run_FET_GUI.cmd / 통합 실행: ..\Run_Lab_GUI.cmd)
.\.venv\Scripts\python.exe -m streamlit run fet_gui/Run.py

# 명령줄: 분석하고 data/results/<배치 이름>/ 에 결과 파일 쓰기
.\.venv\Scripts\python.exe -m fet_core --input-dir data/raw/my_batch
```

결과 파일 목록은 [AGENTS.md](AGENTS.md)의 "출력 계약"에 있다.

### 코드에서 쓰기

```python
from fet_core.config import load_config
from fet_core.io.loader import load_folder

result = load_folder("data/raw/my_batch", load_config())
for m in result.measurements:
    print(m.group, m.position, m.curve_type, len(m.data), m.conditions["vds_V"])
for w in result.warnings:
    print(w.severity, w.code, w.source_file, w.message)
```

transfer 곡선 분석:

```python
from fet_core.analysis.settings import AnalysisSettings
from fet_core.analysis.transfer import analyze_transfer_batch, results_table
from fet_core.model import DeviceGeometry

config = load_config()
analysis = analyze_transfer_batch(
    result.measurements,
    DeviceGeometry.from_config(config),
    AnalysisSettings.from_config(config),
)
table = results_table(analysis.results)  # sweep 방향마다 한 행
print(table[["label", "sweep", "status", "reasons", "vth_linear_V", "ss_mV_per_dec", "mobility_cm2_per_Vs"]])
```

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest
```

측정 데이터는 `data/raw/`에 두며 git에 올라가지 않는다.
