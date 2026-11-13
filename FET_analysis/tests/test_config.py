from __future__ import annotations

from pathlib import Path

import pytest

from fet_core.config import Config, ConfigKeyError, load_config
from fet_core.io import b1500_csv, clarius_xls
from fet_core.io.loader import load_files
from fet_core.model import DeviceGeometry
from tests.conftest import clarius_data_rows, clarius_settings_rows, write_b1500_csv


def test_missing_key_names_the_key() -> None:
    config = Config({"device": {"W_um": 10.0}})
    with pytest.raises(ConfigKeyError, match="device.L_um"):
        config.number("device.L_um")


def test_wrong_type_is_rejected() -> None:
    config = Config({"a": {"flag": True, "name": 3, "items": ["x", 1]}})
    with pytest.raises(ConfigKeyError, match="a.flag"):
        config.number("a.flag")
    with pytest.raises(ConfigKeyError, match="a.name"):
        config.text("a.name")
    with pytest.raises(ConfigKeyError, match="a.items"):
        config.text_list("a.items")


def test_every_config_key_is_read(tmp_path: Path, curve) -> None:
    """A key nobody reads is dead configuration: remove it or use it."""
    config = load_config()
    DeviceGeometry.from_config(config)
    csv_path = write_b1500_csv(tmp_path / "Transfer [S#1_B3_BG ; (1) x].csv", curve)
    load_files([csv_path], config)
    sheets = {"S1_B2": clarius_data_rows(curve), "Settings": clarius_settings_rows(["S1_B2"])}
    clarius_xls.parse_workbook(sheets, tmp_path / "book.xls", "0" * 64, config)
    for reader in (b1500_csv, clarius_xls):
        config.text_list(f"readers.{reader.NAME}.extensions")
    assert config.unread_keys() == set()
