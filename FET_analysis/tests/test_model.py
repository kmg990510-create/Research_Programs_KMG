from __future__ import annotations

import pytest

from fet_core.model import DeviceGeometry
from fet_core.naming import parse_label


def test_cox_of_300nm_sio2(config) -> None:
    geometry = DeviceGeometry.from_config(config)
    # 8.854e-12 * 3.9 / 300e-9 = 1.151e-4 F/m^2 (11.5 nF/cm^2)
    assert geometry.cox_F_per_m2 == pytest.approx(1.1510e-4, rel=1e-3)
    assert geometry.width_over_length == pytest.approx(2.0)


def test_geometry_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match="L_um"):
        DeviceGeometry(W_um=10.0, L_um=0.0, t_ox_nm=300.0, eps_r=3.9)


@pytest.mark.parametrize(
    ("label", "group", "position"),
    [
        ("#600_4_ATP_B2", "#600_4_ATP", "B2"),
        ("#683-25_1_A5_ATP(re)", "#683-25_1_ATP(re)", "A5"),
        ("INTL#184_B3_BG", "INTL#184_BG", "B3"),
        ("INTL209_C10", "INTL209", "C10"),
        ("#89_pristine", "#89_pristine", None),
        ("S1_A1_B2", "S1_A1_B2", None),  # two candidates: not guessed
        ("  D7 ", "D7", "D7"),
    ],
)
def test_parse_label(config, label, group, position) -> None:
    name = parse_label(label, config)
    assert (name.group, name.position) == (group, position)
