"""Main window for desktop manual refit editor."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .controller import ManualEditorController
from .peak_table import PeakTableWidget
from .plot_widget import SpectrumPlotWidget


class ManualRefitMainWindow(QMainWindow):
    """Desktop editor shell that edits peaks and writes response JSON."""

    def __init__(self, controller: ManualEditorController, output_path: Path) -> None:
        super().__init__()
        self.controller = controller
        self.output_path = output_path
        self.setWindowTitle(f"Manual Refit Editor - {controller.request.spectrum_id}")
        self.resize(1400, 860)
        self._syncing_from_plot = False
        self._current_mode = SpectrumPlotWidget.MODE_EDIT

        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        info = QLabel(
            f"Spectrum: {controller.request.spectrum_id}   |   "
            f"Model: {controller.request.selected_model}   |   "
            f"Modality: {controller.request.modality}"
        )
        root_layout.addWidget(info)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Interaction Mode"))
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QToolButton] = {}
        for mode in SpectrumPlotWidget.MODES:
            button = self._create_mode_button(mode)
            mode_row.addWidget(button)
        mode_row.addWidget(
            QLabel("Move: pan, Zoom: drag zoom box, Edit: left=fraction, top=center/height, right=FWHM.")
        )
        mode_row.addStretch(1)
        root_layout.addLayout(mode_row)

        metrics_row = QHBoxLayout()
        metrics_row.addWidget(QLabel("Live Preview Metrics"))
        self.rmse_label = QLabel(self)
        self.aic_label = QLabel(self)
        metrics_row.addWidget(self.rmse_label)
        metrics_row.addWidget(self.aic_label)
        metrics_row.addStretch(1)
        root_layout.addLayout(metrics_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, stretch=1)

        self.plot = SpectrumPlotWidget(self)
        self.plot.set_on_peaks_changed(self._on_plot_peaks_changed)
        splitter.addWidget(self.plot)

        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        right_layout.addWidget(QLabel("Editable Peaks"))
        self.peak_table = PeakTableWidget(on_changed=self._on_peak_table_changed, parent=self)
        self.peak_table.set_peaks(list(self.controller.peaks))
        right_layout.addWidget(self.peak_table, stretch=1)

        right_layout.addWidget(QLabel("Operator Note"))
        self.note_edit = QTextEdit(self)
        self.note_edit.setPlaceholderText("Optional note for why manual correction was applied.")
        right_layout.addWidget(self.note_edit)

        button_row = QHBoxLayout()
        self.refit_preview_btn = QPushButton("Refresh Preview")
        self.refit_preview_btn.clicked.connect(self._refresh_plot)
        button_row.addWidget(self.refit_preview_btn)

        self.auto_fit_btn = QPushButton("Auto Fit (Use Current as Initial)")
        self.auto_fit_btn.clicked.connect(self._on_auto_fit_clicked)
        button_row.addWidget(self.auto_fit_btn)

        self.save_btn = QPushButton("Save and Close")
        self.save_btn.clicked.connect(self._on_save_clicked)
        button_row.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)
        button_row.addWidget(self.cancel_btn)

        right_layout.addLayout(button_row)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.setCentralWidget(root)
        self._set_active_mode(SpectrumPlotWidget.MODE_EDIT)
        self._refresh_plot(reset_view=True)

    def _create_mode_button(self, mode: str) -> QToolButton:
        button = QToolButton(self)
        button.setText(mode)
        button.setCheckable(True)
        if mode == SpectrumPlotWidget.MODE_MOVE:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward)
            button.setToolTip("Move mode: drag to pan")
        elif mode == SpectrumPlotWidget.MODE_ZOOM:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
            button.setToolTip("Zoom mode: drag a rectangle to zoom")
        else:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
            button.setToolTip("Edit mode: drag handles to modify peak parameters")
        button.setIcon(icon)
        button.setAutoRaise(True)
        button.toggled.connect(lambda checked, selected=mode: self._on_mode_button_toggled(selected, checked))
        self.mode_group.addButton(button)
        self.mode_buttons[mode] = button
        return button

    def _on_mode_button_toggled(self, mode: str, checked: bool) -> None:
        if not checked:
            return
        self._on_mode_changed(mode)

    def _set_active_mode(self, mode: str) -> None:
        if mode not in self.mode_buttons:
            mode = SpectrumPlotWidget.MODE_EDIT
        self._current_mode = mode
        for current_mode, button in self.mode_buttons.items():
            should_check = current_mode == mode
            if button.isChecked() != should_check:
                button.blockSignals(True)
                button.setChecked(should_check)
                button.blockSignals(False)
        self.plot.set_interaction_mode(mode)

    def _on_peak_table_changed(self) -> None:
        if self._syncing_from_plot:
            return
        self.controller.set_peaks(self.peak_table.collect_peaks())
        self.plot.set_peaks(self.controller.peaks, reset_view=False)
        self._refresh_metrics()

    def _on_plot_peaks_changed(self, peaks) -> None:
        self._syncing_from_plot = True
        try:
            self.controller.set_peaks(list(peaks))
            self.peak_table.set_peaks(list(peaks))
        finally:
            self._syncing_from_plot = False
        self._refresh_metrics()

    def _on_mode_changed(self, mode: str) -> None:
        self._set_active_mode(mode)

    def _refresh_plot(self, *, reset_view: bool = False) -> None:
        self.plot.set_data(
            self.controller.x,
            self.controller.y,
            self.controller.peaks,
            row_snapshot=self.controller.request.row_snapshot,
            reset_view=reset_view,
        )
        self.plot.set_interaction_mode(self._current_mode)
        self._refresh_metrics()

    def _refresh_metrics(self) -> None:
        metrics = self.controller.preview_metrics()
        self.rmse_label.setText(
            (
                f"RMSE: {self._fmt(metrics.rmse, digits=4)} "
                f"(delta: {self._fmt_delta(metrics.rmse_delta, digits=4)}, "
                f"editor start: {self._fmt(metrics.initial_rmse, digits=4)})"
            )
        )
        self.aic_label.setText(
            (
                f"AIC: {self._fmt(metrics.aic, digits=2)} "
                f"(delta: {self._fmt_delta(metrics.aic_delta, digits=2)}, "
                f"editor start: {self._fmt(metrics.initial_aic, digits=2)})"
            )
        )

    @staticmethod
    def _fmt(value: float | None, *, digits: int) -> str:
        if value is None:
            return "NA"
        return f"{float(value):.{digits}f}"

    @staticmethod
    def _fmt_delta(value: float | None, *, digits: int) -> str:
        if value is None:
            return "NA"
        number = float(value)
        sign = "+" if number >= 0 else ""
        return f"{sign}{number:.{digits}f}"

    def _on_auto_fit_clicked(self) -> None:
        self.controller.set_peaks(self.peak_table.collect_peaks())
        self.controller.set_operator_note(self.note_edit.toPlainText())
        try:
            result = self.controller.run_auto_fit()
        except Exception as exc:
            QMessageBox.warning(self, "Auto Fit Failed", str(exc))
            return

        self._syncing_from_plot = True
        try:
            self.peak_table.set_peaks(list(self.controller.peaks))
        finally:
            self._syncing_from_plot = False
        self._refresh_plot(reset_view=False)

        metrics = result.get("metrics", {})
        rmse = metrics.get("rmse") if isinstance(metrics, dict) else None
        aic = metrics.get("aic") if isinstance(metrics, dict) else None
        warning_text = ""
        warnings = result.get("warnings", [])
        if isinstance(warnings, list) and warnings:
            warning_text = f"\nWarnings: {', '.join(str(item) for item in warnings)}"
        QMessageBox.information(
            self,
            "Auto Fit Complete",
            f"Model: {self.controller.request.selected_model}\nRMSE: {rmse}\nAIC: {aic}{warning_text}",
        )

    def _on_save_clicked(self) -> None:
        self.controller.set_peaks(self.peak_table.collect_peaks())
        self.controller.set_operator_note(self.note_edit.toPlainText())
        payload = self.controller.build_response()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        QMessageBox.information(self, "Saved", f"Manual refit response saved:\n{self.output_path}")
        self.close()
