"""Editable peak table widget for desktop manual refit UI."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from .models import PeakRow


class PeakTableWidget(QTableWidget):
    """Simple editable peak table with numeric fields and fixed flags."""

    HEADERS = [
        "Peak",
        "Fraction",
        "Fix F",
        "Center",
        "Fix C",
        "Height",
        "Fix H",
        "FWHM",
        "Fix W",
    ]

    def __init__(
        self,
        on_changed: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._on_changed = on_changed
        self._is_populating = False
        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.itemChanged.connect(self._handle_item_changed)

    def set_peaks(self, peaks: list[PeakRow]) -> None:
        self._is_populating = True
        self.setRowCount(len(peaks))
        for row_idx, peak in enumerate(peaks):
            self._set_readonly_text(row_idx, 0, peak.peak.upper())
            self._set_float_text(row_idx, 1, float(min(max(peak.fraction, 0.0), 1.0)))
            self._set_check(row_idx, 2, bool(peak.fixed_fraction))
            self._set_float_text(row_idx, 3, float(peak.center))
            self._set_check(row_idx, 4, bool(peak.fixed_center))
            self._set_float_text(row_idx, 5, float(max(peak.height, 0.0)))
            self._set_check(row_idx, 6, bool(peak.fixed_height))
            self._set_float_text(row_idx, 7, float(max(peak.fwhm, 1.0e-6)))
            self._set_check(row_idx, 8, bool(peak.fixed_fwhm))
        self.resizeColumnsToContents()
        self._is_populating = False

    def collect_peaks(self) -> list[PeakRow]:
        peaks: list[PeakRow] = []
        for row_idx in range(self.rowCount()):
            peaks.append(
                PeakRow(
                    peak=self._text(row_idx, 0).strip().lower(),
                    fraction=min(max(self._float(row_idx, 1, default=0.5), 0.0), 1.0),
                    fixed_fraction=self._checked(row_idx, 2),
                    center=self._float(row_idx, 3, default=0.0),
                    height=max(self._float(row_idx, 5, default=0.0), 0.0),
                    fwhm=max(self._float(row_idx, 7, default=1.0), 1.0e-6),
                    fixed_center=self._checked(row_idx, 4),
                    fixed_height=self._checked(row_idx, 6),
                    fixed_fwhm=self._checked(row_idx, 8),
                )
            )
        return peaks

    def _set_readonly_text(self, row: int, col: int, value: str) -> None:
        item = QTableWidgetItem(value)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, col, item)

    def _set_float_text(self, row: int, col: int, value: float) -> None:
        item = QTableWidgetItem(f"{value:.6g}")
        self.setItem(row, col, item)

    def _set_check(self, row: int, col: int, checked: bool) -> None:
        item = QTableWidgetItem("")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.setItem(row, col, item)

    def _text(self, row: int, col: int) -> str:
        item = self.item(row, col)
        return item.text() if item is not None else ""

    def _float(self, row: int, col: int, default: float) -> float:
        text = self._text(row, col)
        try:
            return float(text)
        except (TypeError, ValueError):
            return float(default)

    def _checked(self, row: int, col: int) -> bool:
        item = self.item(row, col)
        if item is None:
            return False
        return item.checkState() == Qt.CheckState.Checked

    def _handle_item_changed(self, _item: QTableWidgetItem) -> None:
        if self._is_populating:
            return
        self._on_changed()
