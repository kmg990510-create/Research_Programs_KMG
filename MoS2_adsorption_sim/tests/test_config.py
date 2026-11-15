from __future__ import annotations

import pytest

from ads_core.builders.molecule import build_preset_molecule
from ads_core.builders.poses import build_poses
from ads_core.builders.slab import build_mos2_slab
from ads_core.calculators.factory import build_calculator_bundle
from ads_core.config import Config, ConfigKeyError, load_config
from ads_core.model import (
    CalculatorSettings,
    MoleculeSettings,
    PoseSettings,
    QualitySettings,
    RelaxationSettings,
    ReportSettings,
    SlabSettings,
)


def test_missing_key_names_the_key() -> None:
    config = Config({"slab": {"lattice_a_A": 3.16}})
    with pytest.raises(ConfigKeyError, match="slab.s_s_thickness_A"):
        config.number("slab.s_s_thickness_A")


def test_wrong_type_is_rejected() -> None:
    config = Config(
        {
            "a": {
                "flag": True,
                "name": 3,
                "items": ["x", 1],
                "nums": [1.0, True],
                "empty": [],
            }
        }
    )
    with pytest.raises(ConfigKeyError, match="a.flag"):
        config.number("a.flag")
    with pytest.raises(ConfigKeyError, match="a.name"):
        config.text("a.name")
    with pytest.raises(ConfigKeyError, match="a.items"):
        config.text_list("a.items")
    with pytest.raises(ConfigKeyError, match="a.nums"):
        config.number_list("a.nums")
    with pytest.raises(ConfigKeyError, match="a.empty"):
        config.number_list("a.empty")


def test_every_config_key_is_read() -> None:
    """Every key in config.yaml must be actively used (no dead config keys)."""
    config = load_config()
    SlabSettings.from_config(config)
    MoleculeSettings.from_config(config)
    PoseSettings.from_config(config)
    CalculatorSettings.from_config(config)
    RelaxationSettings.from_config(config)
    QualitySettings.from_config(config)
    ReportSettings.from_config(config)

    slab = build_mos2_slab(config)
    mol = build_preset_molecule("TMA", config)
    build_poses(slab, mol, config, site_types=["Mo_top"], orientations=["flat"], azimuth_angles_deg=[0.0])
    build_calculator_bundle(config, backend="synth_morse")

    assert config.unread_keys() == set()


def test_invalid_defect_and_orientation_rejected() -> None:
    config = load_config()
    data = config.as_dict()
    data["slab"]["defect_type"] = "grain_boundary"
    with pytest.raises(ValueError, match="defect_type"):
        SlabSettings.from_config(Config(data))

    data2 = config.as_dict()
    data2["poses"]["orientations"] = ["sideways"]
    with pytest.raises(ValueError, match="orientation"):
        PoseSettings.from_config(Config(data2))
