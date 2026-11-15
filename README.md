# Research_Programs_KMG

Data analysis programs.

| Folder | Description |
| --- | --- |
| [`MoS2_optical_analysis`](MoS2_optical_analysis/README.md) | MoS2 Raman/PL spectrum fitting pipeline with a Streamlit GUI (`mos2_gui`) and a Windows exe build |
| [`FET_analysis`](FET_analysis/README.md) | FET transfer-curve analysis with a Streamlit GUI (`fet_gui`) and a CLI (Keysight B1500 CSV, Keithley 4200A Clarius XLS) |
| [`MoS2_adsorption_sim`](MoS2_adsorption_sim/README.md) | Monolayer MoS2 molecular adsorption simulation & analysis (uMLIP + DFT-D3) with a Streamlit GUI (`ads_gui`) and a CLI |
| `labkit` | Code shared by the programs: Plotly paper theme, sidebar sections, figure sizing |

## Unified Streamlit GUI (`app.py`)

Run all three programs from one landing hub (or launch standalone from each subfolder via `Run_*.cmd`):

```powershell
# Windows (double-click Run_Lab_GUI.cmd or run directly)
streamlit run app.py
```

Each program uses a distinct GUI package name (`mos2_gui`, `fet_gui`, `ads_gui`) and unique `st.Page(..., url_path=...)` routes so switching across programs in `app.py` does not collide in `sys.modules` or widget/session state.

## Windows exe builds (GitHub Actions)

- `MoS2_optical_analysis`: Actions tab -> "Build MoS2 optical analysis (Windows exe)" -> "Run workflow".
  When it finishes, download `mos2-analysis` from the run's Artifacts (kept 30 days, GitHub login required).
- Releases for users: pushing a tag `mos2-v<version>` builds and attaches `mos2-analysis-v<version>.zip` to
  [Releases](https://github.com/kmg990510-create/Research_Programs_KMG/releases) (public download).

## License

MIT (see `LICENSE`).
