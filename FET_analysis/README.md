# FET_analysis

FET 측정 파일에서 소자 파라미터를 추출하는 프로그램이다. 지금은 측정 파일을 읽고 transfer 곡선에서 파라미터를 추출하는 코어까지 구현되어 있다. 결과 파일 저장, CLI, 화면은 아직 없다 (진행 단계는 [AGENTS.md](AGENTS.md) 참고).

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

## 사용 (현재 단계)

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
