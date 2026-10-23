"""Pyqtgraph-based spectrum plot widget for desktop manual refit UI."""

from __future__ import annotations

from typing import Any, Callable, Iterable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.components.graph_style import fit_curve_cfg as load_fit_curve_cfg
from gui.components.graph_style import overlay_style_cfg as load_overlay_style_cfg
from gui.components.graph_style import x_window_cfg as load_x_window_cfg

from .models import PeakRow

_DEFAULT_STYLE: dict[str, Any] = {
    "raw_marker_color": "#666666",
    "raw_marker_size": 6,
    "fit_line_color": "#FF1E1E",
    "fit_line_width": 2.5,
    "baseline_color": "#111111",
    "baseline_width": 1.8,
    "baseline_dash": "dash",
    "component_line_width": 1.6,
    "component_line_dash": "dot",
    "component_colors": {
        "lo": "#CC00CC",
        "e2g": "#0066FF",
        "a1g": "#00A651",
        "zo": "#00B7C7",
        "la": "#F3C300",
    },
    "editor_handles": {
        "top": "#0B5ED7",
        "fwhm": "#C2185B",
        "fraction": "#FF8C00",
        "size": 11,
    },
}

_DEFAULT_FIT_CURVE: dict[str, int] = {
    "smooth_factor": 5,
    "max_points": 4000,
}

_DEFAULT_X_WINDOW: dict[str, float] = {
    "fallback_min": 340.0,
    "fallback_max": 430.0,
    "peak_padding": 18.0,
}


def _clone_peak(peak: PeakRow) -> PeakRow:
    return PeakRow(
        peak=str(peak.peak),
        center=float(peak.center),
        height=float(peak.height),
        fwhm=float(peak.fwhm),
        fraction=float(min(max(peak.fraction, 0.0), 1.0)),
        fixed_fraction=bool(peak.fixed_fraction),
        fixed_center=bool(peak.fixed_center),
        fixed_height=bool(peak.fixed_height),
        fixed_fwhm=bool(peak.fixed_fwhm),
    )


def _to_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _to_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


_FWHM_TO_SIGMA_GAUSSIAN = 2.3548200450309493
_EPS = 1.0e-12


def _gaussian_normalized_curve(x: np.ndarray, *, center: float, sigma: float) -> np.ndarray:
    sigma_val = max(float(sigma), _EPS)
    z = (x - center) / sigma_val
    return np.exp(-0.5 * z * z) / (sigma_val * np.sqrt(2.0 * np.pi))


def _lorentz_normalized_curve(x: np.ndarray, *, center: float, sigma: float) -> np.ndarray:
    sigma_val = max(float(sigma), _EPS)
    return (1.0 / np.pi) * (sigma_val / (((x - center) ** 2) + (sigma_val * sigma_val)))


def _profiled_component_curve(
    x: np.ndarray,
    *,
    center: float,
    height: float,
    fwhm: float,
    line_profile: str,
    fraction: float,
) -> np.ndarray:
    if fwhm <= 0 or height <= 0:
        return np.zeros_like(x, dtype=float)
    profile = str(line_profile).strip().lower()
    if profile == "gaussian":
        sigma_g = max(float(fwhm) / _FWHM_TO_SIGMA_GAUSSIAN, 1.0e-6)
        area_g = float(height) * sigma_g * np.sqrt(2.0 * np.pi)
        return area_g * _gaussian_normalized_curve(x, center=float(center), sigma=sigma_g)
    if profile == "lorentz":
        sigma_l = max(float(fwhm) / 2.0, 1.0e-6)
        area_l = float(height) * np.pi * sigma_l
        return area_l * _lorentz_normalized_curve(x, center=float(center), sigma=sigma_l)

    sigma_l = max(float(fwhm) / 2.0, 1.0e-6)
    frac = float(np.clip(fraction, 0.0, 1.0))
    sigma_g = sigma_l / np.sqrt(2.0 * np.log(2.0))
    gaussian_height = 1.0 / max(sigma_g * np.sqrt(2.0 * np.pi), _EPS)
    lorentz_height = 1.0 / max(np.pi * sigma_l, _EPS)
    height_to_area_factor = (1.0 - frac) * gaussian_height + frac * lorentz_height
    area = float(height) / max(height_to_area_factor, _EPS)
    return area * (
        (1.0 - frac) * _gaussian_normalized_curve(x, center=float(center), sigma=sigma_g)
        + frac * _lorentz_normalized_curve(x, center=float(center), sigma=sigma_l)
    )


def _pen_style(name: str) -> Qt.PenStyle:
    token = str(name).strip().lower()
    if token == "dash":
        return Qt.PenStyle.DashLine
    if token == "dot":
        return Qt.PenStyle.DotLine
    if token == "dashdot":
        return Qt.PenStyle.DashDotLine
    return Qt.PenStyle.SolidLine


def _resolve_style(style_cfg: dict[str, Any]) -> dict[str, Any]:
    style = dict(_DEFAULT_STYLE)
    style["component_colors"] = dict(_DEFAULT_STYLE["component_colors"])
    style["editor_handles"] = dict(_DEFAULT_STYLE["editor_handles"])

    if isinstance(style_cfg, dict):
        for key in [
            "raw_marker_color",
            "fit_line_color",
            "baseline_color",
            "baseline_dash",
            "component_line_dash",
        ]:
            value = style_cfg.get(key)
            if isinstance(value, str) and value.strip():
                style[key] = value.strip()

        style["raw_marker_size"] = max(1, _to_int(style_cfg.get("raw_marker_size"), style["raw_marker_size"]))
        style["fit_line_width"] = max(1.0e-3, _to_float(style_cfg.get("fit_line_width"), style["fit_line_width"]))
        style["baseline_width"] = max(1.0e-3, _to_float(style_cfg.get("baseline_width"), style["baseline_width"]))
        style["component_line_width"] = max(
            1.0e-3, _to_float(style_cfg.get("component_line_width"), style["component_line_width"])
        )

        component_colors = style_cfg.get("component_colors")
        if isinstance(component_colors, dict):
            for key, value in component_colors.items():
                if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
                    style["component_colors"][key.strip().lower()] = value.strip()

        handles_cfg = style_cfg.get("editor_handles")
        if isinstance(handles_cfg, dict):
            for key in ["top", "fwhm", "fraction"]:
                value = handles_cfg.get(key)
                if isinstance(value, str) and value.strip():
                    style["editor_handles"][key] = value.strip()
            style["editor_handles"]["size"] = max(
                6,
                _to_int(handles_cfg.get("size"), style["editor_handles"]["size"]),
            )

    return style


def _resolve_fit_curve_cfg(config: dict[str, Any]) -> dict[str, int]:
    cfg = dict(_DEFAULT_FIT_CURVE)
    if isinstance(config, dict):
        cfg["smooth_factor"] = max(1, _to_int(config.get("smooth_factor"), cfg["smooth_factor"]))
        cfg["max_points"] = max(32, _to_int(config.get("max_points"), cfg["max_points"]))
    return cfg


def _resolve_x_window_cfg(config: dict[str, Any]) -> dict[str, float]:
    cfg = dict(_DEFAULT_X_WINDOW)
    if isinstance(config, dict):
        cfg["fallback_min"] = _to_float(config.get("fallback_min"), cfg["fallback_min"])
        cfg["fallback_max"] = _to_float(config.get("fallback_max"), cfg["fallback_max"])
        cfg["peak_padding"] = max(0.0, _to_float(config.get("peak_padding"), cfg["peak_padding"]))
    if cfg["fallback_max"] <= cfg["fallback_min"]:
        cfg["fallback_min"], cfg["fallback_max"] = _DEFAULT_X_WINDOW["fallback_min"], _DEFAULT_X_WINDOW["fallback_max"]
    return cfg


def _dense_x_axis(x_axis: np.ndarray, cfg: dict[str, int]) -> np.ndarray:
    if x_axis.size <= 1:
        return np.asarray(x_axis, dtype=float)
    target_points = max(x_axis.size, min(int(cfg["max_points"]), x_axis.size * int(cfg["smooth_factor"])))
    if target_points <= x_axis.size:
        return np.asarray(x_axis, dtype=float)
    return np.linspace(float(np.min(x_axis)), float(np.max(x_axis)), int(target_points))


def _set_target_movable(target: pg.TargetItem, movable: bool) -> None:
    if hasattr(target, "setMovable"):
        target.setMovable(bool(movable))
    else:
        setattr(target, "movable", bool(movable))


class _ManualRefitViewBox(pg.ViewBox):
    """ViewBox extension that adds a main-view autoscale action and zoom double-click reset."""

    def __init__(self, *, autoscale_callback: Callable[[], None], mode_getter: Callable[[], str]) -> None:
        super().__init__()
        self._autoscale_callback = autoscale_callback
        self._mode_getter = mode_getter
        self._autoscale_action: QAction | None = None

    def getMenu(self, ev: object | None = None):  # type: ignore[override]
        menu = super().getMenu(ev)
        if self._autoscale_action is None:
            self._autoscale_action = QAction("Autoscale (Main View)", menu)
            self._autoscale_action.triggered.connect(self._autoscale_callback)
        if self._autoscale_action not in menu.actions():
            actions = menu.actions()
            view_all_idx = -1
            for idx, action in enumerate(actions):
                if "view all" in action.text().strip().lower():
                    view_all_idx = idx
                    break
            if view_all_idx >= 0 and (view_all_idx + 1) < len(actions):
                menu.insertAction(actions[view_all_idx + 1], self._autoscale_action)
            else:
                menu.addAction(self._autoscale_action)
        return menu

    def mouseDoubleClickEvent(self, ev: object) -> None:  # type: ignore[override]
        if self._mode_getter() == SpectrumPlotWidget.MODE_ZOOM:
            self._autoscale_callback()
            if hasattr(ev, "accept"):
                ev.accept()
            return
        super().mouseDoubleClickEvent(ev)


class SpectrumPlotWidget(QWidget):
    """Interactive spectrum plot with mode switching and drag handles."""

    MODE_MOVE = "Move"
    MODE_ZOOM = "Zoom"
    MODE_EDIT = "Edit"
    MODES = [MODE_MOVE, MODE_ZOOM, MODE_EDIT]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._style = _resolve_style(load_overlay_style_cfg())
        self._fit_curve_cfg = _resolve_fit_curve_cfg(load_fit_curve_cfg())
        self._x_window_cfg = _resolve_x_window_cfg(load_x_window_cfg())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        view_box = _ManualRefitViewBox(
            autoscale_callback=self.autoscale_main_view,
            mode_getter=lambda: self._interaction_mode,
        )
        self.plot = pg.PlotWidget(viewBox=view_box)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "Raman Shift (cm^-1)")
        self.plot.setLabel("left", "Intensity")
        self.plot.addLegend(offset=(6, 6))
        layout.addWidget(self.plot)

        self._raw_curve = self.plot.plot(
            [],
            [],
            pen=None,
            symbol="o",
            symbolSize=int(self._style["raw_marker_size"]),
            symbolBrush=pg.mkBrush(self._style["raw_marker_color"]),
            symbolPen=pg.mkPen(self._style["raw_marker_color"]),
            name="Raw",
        )
        self._baseline_curve = self.plot.plot(
            [],
            [],
            pen=pg.mkPen(
                self._style["baseline_color"],
                width=float(self._style["baseline_width"]),
                style=_pen_style(str(self._style["baseline_dash"])),
            ),
            name="Baseline",
        )
        self._fit_curve = self.plot.plot(
            [],
            [],
            pen=pg.mkPen(self._style["fit_line_color"], width=float(self._style["fit_line_width"])),
            name="Preview Fit",
        )

        self._component_curves: list[pg.PlotDataItem] = []
        self._handles: dict[tuple[int, str], pg.TargetItem] = {}
        self._handle_lookup: dict[int, tuple[int, str]] = {}
        self._suspend_handle_events = False

        self._x = np.array([], dtype=float)
        self._y = np.array([], dtype=float)
        self._x_dense = np.array([], dtype=float)
        self._peaks: list[PeakRow] = []
        self._row_snapshot: dict[str, Any] = {}
        self._line_profile = "pvoigt"
        self._baseline_slope = 0.0
        self._baseline_intercept = 0.0
        self._x_min = 0.0
        self._x_max = 1.0
        self._on_peaks_changed: Callable[[list[PeakRow]], None] | None = None
        self._interaction_mode = self.MODE_EDIT
        self.set_interaction_mode(self.MODE_EDIT)

    def set_on_peaks_changed(self, callback: Callable[[list[PeakRow]], None] | None) -> None:
        self._on_peaks_changed = callback

    def set_interaction_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            mode = self.MODE_EDIT
        self._interaction_mode = mode
        view_box = self.plot.getViewBox()
        if mode == self.MODE_MOVE:
            view_box.setMouseMode(pg.ViewBox.PanMode)
            view_box.setMouseEnabled(x=True, y=True)
            self._set_handles_movable(False)
        elif mode == self.MODE_ZOOM:
            view_box.setMouseMode(pg.ViewBox.RectMode)
            view_box.setMouseEnabled(x=True, y=True)
            self._set_handles_movable(False)
        else:
            view_box.setMouseMode(pg.ViewBox.PanMode)
            view_box.setMouseEnabled(x=False, y=False)
            self._update_handle_positions()

    def set_data(
        self,
        x: Iterable[float],
        y_raw: Iterable[float],
        peaks: list[PeakRow],
        row_snapshot: dict[str, Any] | None = None,
        *,
        reset_view: bool = True,
    ) -> None:
        self._x = np.asarray(list(x), dtype=float)
        self._y = np.asarray(list(y_raw), dtype=float)
        self._peaks = [_clone_peak(peak) for peak in peaks]
        self._row_snapshot = dict(row_snapshot or {})
        self._line_profile = self._resolve_line_profile(self._row_snapshot)
        self._sync_baseline_params(self._row_snapshot)

        snapshot_modality = str(self._row_snapshot.get("modality", "")).lower()
        is_pl = snapshot_modality == "pl" or (snapshot_modality != "raman" and "pl_position" in self._row_snapshot)
        if is_pl:
            self.plot.setLabel("bottom", "Wavelength (nm)")
        else:
            self.plot.setLabel("bottom", "Raman Shift (cm^-1)")

        if self._x.size > 0:
            self._x_min = float(np.min(self._x))
            self._x_max = float(np.max(self._x))
        self._x_dense = _dense_x_axis(self._x, self._fit_curve_cfg)
        self._refresh_curves(reset_view=bool(reset_view))

    def set_peaks(self, peaks: list[PeakRow], *, reset_view: bool = False) -> None:
        self._peaks = [_clone_peak(peak) for peak in peaks]
        self._refresh_curves(reset_view=bool(reset_view))

    def _sync_baseline_params(self, row_snapshot: dict[str, Any]) -> None:
        slope = _to_float(row_snapshot.get("bg_slope"), np.nan)
        intercept = _to_float(row_snapshot.get("bg_intercept"), np.nan)
        if np.isfinite(slope) and np.isfinite(intercept):
            self._baseline_slope = float(slope)
            self._baseline_intercept = float(intercept)
            return
        if self._x.size >= 2 and self._y.size >= 2:
            y0 = float(self._y[0])
            y1 = float(self._y[-1])
            x0 = float(self._x[0])
            x1 = float(self._x[-1])
            slope = (y1 - y0) / max(x1 - x0, 1.0e-9)
            self._baseline_slope = float(slope)
            self._baseline_intercept = float(y0 - slope * x0)
        else:
            self._baseline_slope = 0.0
            self._baseline_intercept = 0.0

    def _baseline_at(self, x_axis: np.ndarray | float) -> np.ndarray | float:
        return self._baseline_slope * x_axis + self._baseline_intercept

    def _refresh_curves(self, *, reset_view: bool) -> None:
        if self._x.size == 0 or self._y.size == 0:
            self._raw_curve.setData([], [])
            self._baseline_curve.setData([], [])
            self._fit_curve.setData([], [])
            self._clear_component_curves()
            self._clear_handles()
            return

        self._raw_curve.setData(self._x, self._y)
        baseline_dense = np.asarray(self._baseline_at(self._x_dense), dtype=float)
        self._baseline_curve.setData(self._x_dense, baseline_dense)

        self._ensure_component_curves()
        y_fit_dense = np.array(baseline_dense, dtype=float)
        fallback_palette = ["#3366CC", "#009688", "#FF9800", "#8E24AA", "#795548", "#00838F"]
        for idx, peak in enumerate(self._peaks):
            component = _profiled_component_curve(
                self._x_dense,
                center=float(peak.center),
                height=float(max(peak.height, 0.0)),
                fwhm=float(max(peak.fwhm, 1.0e-6)),
                line_profile=self._line_profile,
                fraction=float(np.clip(peak.fraction, 0.0, 1.0)),
            )
            y_fit_dense += component
            component_color = self._style["component_colors"].get(
                str(peak.peak).strip().lower(),
                fallback_palette[idx % len(fallback_palette)],
            )
            self._component_curves[idx].setData(self._x_dense, baseline_dense + component)
            self._component_curves[idx].setPen(
                pg.mkPen(
                    component_color,
                    width=float(self._style["component_line_width"]),
                    style=_pen_style(str(self._style["component_line_dash"])),
                )
            )

        self._fit_curve.setData(self._x_dense, y_fit_dense)
        self._ensure_handles()
        self._update_handle_positions()

        if reset_view and self._x.size > 1:
            self.autoscale_main_view()

    def _resolve_main_x_range(self) -> tuple[float, float]:
        x_data_min = float(np.min(self._x)) if self._x.size else float(self._x_window_cfg["fallback_min"])
        x_data_max = float(np.max(self._x)) if self._x.size else float(self._x_window_cfg["fallback_max"])
        if x_data_max <= x_data_min:
            x_data_min = float(self._x_window_cfg["fallback_min"])
            x_data_max = float(self._x_window_cfg["fallback_max"])

        peak_padding = float(self._x_window_cfg["peak_padding"])
        pl_pos = _to_float(self._row_snapshot.get("pl_position"), np.nan) if snapshot_modality != "raman" else np.nan
        e2g = _to_float(self._row_snapshot.get("e2g_position"), np.nan)
        a1g = _to_float(self._row_snapshot.get("a1g_position"), np.nan)
        if np.isfinite(pl_pos):
            x_min = pl_pos - max(peak_padding, 60.0)
            x_max = pl_pos + max(peak_padding, 60.0)
        elif np.isfinite(e2g) and np.isfinite(a1g):
            x_min = min(float(e2g), float(a1g)) - peak_padding
            x_max = max(float(e2g), float(a1g)) + peak_padding
        else:
            x_min = x_data_min
            x_max = x_data_max
        if not np.isfinite(x_min) or not np.isfinite(x_max) or x_max <= x_min:
            x_min, x_max = x_data_min, x_data_max
        return float(x_min), float(x_max)

    def autoscale_main_view(self) -> None:
        if self._x.size == 0:
            return
        x_min, x_max = self._resolve_main_x_range()
        view_box = self.plot.getViewBox()
        view_box.setXRange(float(x_min), float(x_max), padding=0.01)
        view_box.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)

    @staticmethod
    def _resolve_line_profile(row_snapshot: dict[str, Any]) -> str:
        profile = str(row_snapshot.get("line_profile", "") or "").strip().lower()
        if profile in {"gaussian", "lorentz", "pvoigt"}:
            return profile
        model_name = str(row_snapshot.get("selected_model", "") or "").strip().lower()
        if "gaussian" in model_name:
            return "gaussian"
        if "lorentz" in model_name:
            return "lorentz"
        return "pvoigt"

    def _fraction_handle_enabled(self) -> bool:
        return self._line_profile not in {"gaussian", "lorentz"}

    def _ensure_component_curves(self) -> None:
        if len(self._component_curves) == len(self._peaks):
            return
        self._clear_component_curves()
        for peak in self._peaks:
            item = self.plot.plot([], [], pen=pg.mkPen("#777777", width=1.0), name=str(peak.peak).upper())
            self._component_curves.append(item)

    def _clear_component_curves(self) -> None:
        for item in self._component_curves:
            self.plot.removeItem(item)
        self._component_curves = []

    def _ensure_handles(self) -> None:
        expected_keys: set[tuple[int, str]] = set()
        for idx, _ in enumerate(self._peaks):
            expected_keys.update({(idx, "top"), (idx, "left"), (idx, "right")})

        stale_keys = [key for key in self._handles if key not in expected_keys]
        for key in stale_keys:
            item = self._handles.pop(key, None)
            if item is None:
                continue
            self._handle_lookup.pop(id(item), None)
            self.plot.removeItem(item)

        for key in sorted(expected_keys):
            if key in self._handles:
                continue
            idx, kind = key
            if kind == "top":
                color = self._style["editor_handles"]["top"]
            elif kind == "left":
                color = self._style["editor_handles"]["fraction"]
            else:
                color = self._style["editor_handles"]["fwhm"]
            handle = pg.TargetItem(
                pos=(0.0, 0.0),
                size=float(self._style["editor_handles"]["size"]),
                pen=pg.mkPen(color, width=1.6),
                brush=pg.mkBrush(color),
                movable=(self._interaction_mode == self.MODE_EDIT),
            )
            handle.sigPositionChanged.connect(self._on_handle_moved)
            self._handles[key] = handle
            self._handle_lookup[id(handle)] = key
            self.plot.addItem(handle)

    def _clear_handles(self) -> None:
        for handle in self._handles.values():
            self.plot.removeItem(handle)
        self._handles = {}
        self._handle_lookup = {}

    def _set_handles_movable(self, movable: bool) -> None:
        for handle in self._handles.values():
            _set_target_movable(handle, bool(movable))

    def _handle_position(self, peak: PeakRow, kind: str) -> tuple[float, float]:
        center = float(peak.center)
        height = float(max(peak.height, 0.0))
        fwhm = float(max(peak.fwhm, 1.0e-6))
        baseline_center = float(self._baseline_at(center))
        if kind == "top":
            return center, baseline_center + height
        if kind == "left":
            frac = float(np.clip(peak.fraction, 0.0, 1.0))
            left_x = center - (fwhm * (1.0 - frac))
            return left_x, baseline_center + (height * 0.5)
        return center + (fwhm * 0.5), baseline_center + (height * 0.5)

    def _update_handle_positions(self) -> None:
        self._suspend_handle_events = True
        try:
            for key, handle in self._handles.items():
                idx, kind = key
                if idx >= len(self._peaks):
                    continue
                x_pos, y_pos = self._handle_position(self._peaks[idx], kind)
                handle.setPos(float(x_pos), float(y_pos))
                if self._interaction_mode == self.MODE_EDIT:
                    if kind == "top":
                        _set_target_movable(handle, not (self._peaks[idx].fixed_center and self._peaks[idx].fixed_height))
                    elif kind == "left":
                        _set_target_movable(
                            handle,
                            self._fraction_handle_enabled() and (not self._peaks[idx].fixed_fraction),
                        )
                    elif kind == "right":
                        _set_target_movable(handle, not self._peaks[idx].fixed_fwhm)
                else:
                    _set_target_movable(handle, False)
        finally:
            self._suspend_handle_events = False

    def _on_handle_moved(self, handle_obj: object) -> None:
        if self._suspend_handle_events or self._interaction_mode != self.MODE_EDIT:
            return
        if not isinstance(handle_obj, pg.TargetItem):
            return
        key = self._handle_lookup.get(id(handle_obj))
        if key is None:
            return
        idx, kind = key
        if idx >= len(self._peaks):
            return

        peak = self._peaks[idx]
        pos = handle_obj.pos()
        x_new = float(np.clip(pos.x(), self._x_min, self._x_max))
        y_new = float(pos.y())
        changed = False

        if kind == "top":
            if not peak.fixed_center:
                peak.center = x_new
                changed = True
            if not peak.fixed_height:
                baseline_at_center = float(self._baseline_at(float(peak.center)))
                peak.height = max(y_new - baseline_at_center, 0.0)
                changed = True
        elif kind == "left":
            if self._fraction_handle_enabled() and (not peak.fixed_fraction):
                left_bound = float(peak.center - peak.fwhm)
                right_bound = float(peak.center)
                if right_bound <= left_bound:
                    right_bound = left_bound + 1.0e-6
                x_frac = float(np.clip(x_new, left_bound, right_bound))
                peak.fraction = float(np.clip((x_frac - left_bound) / max(right_bound - left_bound, 1.0e-9), 0.0, 1.0))
                changed = True
        elif kind == "right":
            if not peak.fixed_fwhm:
                right_x = max(x_new, float(peak.center + 1.0e-6))
                peak.fwhm = max(2.0 * (right_x - float(peak.center)), 1.0e-6)
                changed = True

        if not changed:
            self._update_handle_positions()
            return

        self._refresh_curves(reset_view=False)
        if self._on_peaks_changed is not None:
            self._on_peaks_changed([_clone_peak(p) for p in self._peaks])
