"""Device-name conventions. The only module that interprets operator-written names."""

from __future__ import annotations

import re
from dataclasses import dataclass

from fet_core.config import Config


@dataclass(frozen=True)
class DeviceName:
    label: str
    group: str
    position: str | None


def parse_label(label: str, config: Config) -> DeviceName:
    """Split a device label into sample group and device position.

    ``"#600_4_ATP_B2"`` -> group ``"#600_4_ATP"``, position ``"B2"``. The position
    token may sit anywhere (``"#683-25_1_A5_ATP(re)"``). With no position token,
    or with more than one candidate, the whole label is the group and the
    position is ``None``: an ambiguous name is not guessed.
    """
    separator = config.text("naming.token_separator")
    pattern = re.compile(config.text("naming.position_pattern"))
    clean = label.strip()
    tokens = clean.split(separator)
    matches = [index for index, token in enumerate(tokens) if pattern.fullmatch(token)]
    if len(matches) != 1:
        return DeviceName(label=clean, group=clean, position=None)
    position = tokens[matches[0]]
    rest = [token for index, token in enumerate(tokens) if index != matches[0]]
    group = separator.join(rest) or clean
    return DeviceName(label=clean, group=group, position=position)
