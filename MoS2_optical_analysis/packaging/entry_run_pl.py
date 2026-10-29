"""PyInstaller launcher for PL raw pipeline."""

from __future__ import annotations

import multiprocessing

from fitting.mos2_pl.run_raw_pipeline import main


if __name__ == "__main__":
    # Required for `--workers > 1` in the frozen exe: pool children re-launch this
    # exe with `--multiprocessing-fork` and must run the worker loop, not `main()`.
    multiprocessing.freeze_support()
    main()
