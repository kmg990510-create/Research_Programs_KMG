# Research_Programs_KMG

Data analysis programs.

| Folder | Description |
| --- | --- |
| [`MoS2_optical_analysis`](MoS2_optical_analysis/README.md) | MoS2 Raman/PL spectrum fitting pipeline with a Streamlit GUI and a Windows exe build |

## Windows exe builds (GitHub Actions)

- `MoS2_optical_analysis`: Actions tab -> "Build MoS2 optical analysis (Windows exe)" -> "Run workflow".
  When it finishes, download `mos2-analysis` from the run's Artifacts (kept 30 days, GitHub login required).
- Releases for users: pushing a tag `mos2-v<version>` builds and attaches `mos2-analysis-v<version>.zip` to
  [Releases](https://github.com/kmg990510-create/Research_Programs_KMG/releases) (public download).

## License

MIT (see `LICENSE`).
