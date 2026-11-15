"""Map viewer prototype: figure builder, style presets, and bulk review edits."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from mos2_gui.components.map_editing import apply_decision, selected_ids_from_event
from mos2_gui.components.map_figure import MapStyle, build_map_figure, load_style_preset, resolve_color_range, save_style_preset


def _frame() -> pd.DataFrame:
    rows = [
        {
            "spectrum_id": f"S:Y{y}-X{x}",
            "map_x": x,
            "map_y": y,
            "delta": 20.0 + 0.1 * x + 0.01 * y,
            "fit_status": "valid",
            "review_decision": "rejected" if (x, y) == (1, 1) else "auto",
            "selected_model": "peak_4_model",
        }
        for y in (1, 2, 3)
        for x in (1, 2, 3)
    ]
    return pd.DataFrame(rows)


def test_figure_hides_and_outlines_points() -> None:
    frame = _frame()
    fig = build_map_figure(frame, "delta", MapStyle(), selected_ids=["S:Y2-X2"], hidden_ids=["S:Y1-X1"])
    heatmap = fig.data[0]
    assert np.isnan(heatmap.z[0][0])
    assert np.isfinite(heatmap.z[1][1])
    assert len(fig.data[1].x) == 9  # every point stays selectable, hidden ones included
    assert [t.name for t in fig.data].count("selected") == 2
    assert "rejected" in [t.name for t in fig.data]
    assert list(fig.layout.xaxis.range) == [0.5, 3.5]


def test_manual_color_range_falls_back_when_invalid() -> None:
    values = pd.Series([1.0, 2.0, 3.0])
    assert resolve_color_range(values, MapStyle(range_mode="Manual", zmin=1.5, zmax=2.5)) == (1.5, 2.5)
    assert resolve_color_range(values, MapStyle(range_mode="Manual", zmin=3.0, zmax=1.0)) == (1.0, 3.0)


def test_style_preset_roundtrip(tmp_path: Path) -> None:
    style = MapStyle(colormap="Magma", show_values=True, font_size=18, title="맵")
    save_style_preset(tmp_path / "presets" / "a.yaml", style)
    assert load_style_preset(tmp_path / "presets" / "a.yaml") == style


def test_selected_ids_from_event() -> None:
    event = {"selection": {"points": [{"customdata": ["a", 1.0]}, {"customdata": ["a", 1.0]}, {"customdata": ["b"]}, {}]}}
    assert selected_ids_from_event(event) == ["a", "b"]
    assert selected_ids_from_event(None) == []


def test_apply_decision_writes_overrides_only(tmp_path: Path) -> None:
    report = tmp_path / "raman" / "reports" / "run1_fit_report.json"
    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")
    count = apply_decision(report, _frame(), ["S:Y2-X2", "missing"], "rejected", "bad spot")
    assert count == 1
    assert report.read_text(encoding="utf-8") == "{}"
    doc = json.loads((tmp_path / "raman" / "manual_refits" / "run1_manual_overrides.json").read_text(encoding="utf-8"))
    assert doc["items"][0]["review_decision"] == "rejected"
    assert doc["items"][0]["action_type"] == "map_viewer_edit"


def test_physical_axis_places_first_and_last_point_at_start_and_end() -> None:
    style = MapStyle(axis_mode="Physical", x_start=0.0, x_end=10.0, y_start=5.0, y_end=-5.0)
    fig = build_map_figure(_frame(), "delta", style)
    assert list(fig.data[0].x) == [0.0, 5.0, 10.0]
    assert list(fig.data[0].y) == [-5.0, 0.0, 5.0]  # descending input is drawn in ascending order
    assert fig.data[0].z[2][0] == 20.0 + 0.1 * 1 + 0.01 * 1  # index (x=1, y=1) -> (0, 5)
    assert list(fig.layout.xaxis.range) == [-2.5, 12.5]


def test_physical_axis_falls_back_to_index_when_degenerate() -> None:
    style = MapStyle(axis_mode="Physical", x_start=3.0, x_end=3.0)
    assert list(build_map_figure(_frame(), "delta", style).data[0].x) == [1, 2, 3]
