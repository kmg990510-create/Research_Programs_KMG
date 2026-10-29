from __future__ import annotations

import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.desktop_editor.plot_widget import SpectrumPlotWidget  # noqa: E402


def test_set_data_autoscale_uses_raman_anchor_window() -> None:
    _app = QApplication.instance() or QApplication([])
    widget = SpectrumPlotWidget()
    x = np.linspace(340.0, 430.0, 200)
    row = {"modality": "raman", "e2g_position": 384.0, "a1g_position": 403.0}

    # Regression: autoscale referenced a local from set_data and raised NameError.
    widget.set_data(x, np.ones_like(x), peaks=[], row_snapshot=row)

    padding = float(widget._x_window_cfg["peak_padding"])
    assert widget._resolve_main_x_range() == (384.0 - padding, 403.0 + padding)
