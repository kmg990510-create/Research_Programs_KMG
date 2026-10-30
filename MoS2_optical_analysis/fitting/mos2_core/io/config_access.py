"""Strict readers for scientific settings from the merged config (root config.yaml).

Code must not carry its own copy of a scientific value: a missing key is a config error that
names the full key path, instead of silently falling back to a number hidden in the code.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


class ConfigKeyError(LookupError):
    """A required config.yaml key is missing or has the wrong type.

    Not a ValueError on purpose: per-candidate fit loops catch ValueError as a fit failure,
    and a broken config must stop the run instead of turning every spectrum invalid.
    """


def _where(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def section(mapping: Any, key: str, path: str) -> Mapping[str, Any]:
    value = require(mapping, key, path)
    if not isinstance(value, Mapping):
        raise ConfigKeyError(f"config.yaml: '{_where(path, key)}' must be a mapping (got {value!r})")
    return value


def require(mapping: Any, key: str, path: str) -> Any:
    if not isinstance(mapping, Mapping) or key not in mapping:
        raise ConfigKeyError(f"config.yaml: missing required key '{_where(path, key)}'")
    return mapping[key]


def number(mapping: Any, key: str, path: str) -> float:
    value = require(mapping, key, path)
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ConfigKeyError(f"config.yaml: '{_where(path, key)}' must be a number (got {value!r})") from None
    if not math.isfinite(result):
        raise ConfigKeyError(f"config.yaml: '{_where(path, key)}' must be finite (got {value!r})")
    return result


def integer(mapping: Any, key: str, path: str) -> int:
    return int(number(mapping, key, path))


def flag(mapping: Any, key: str, path: str) -> bool:
    value = require(mapping, key, path)
    if not isinstance(value, bool):
        raise ConfigKeyError(f"config.yaml: '{_where(path, key)}' must be true or false (got {value!r})")
    return value


def text(mapping: Any, key: str, path: str) -> str:
    value = require(mapping, key, path)
    if not isinstance(value, str) or not value.strip():
        raise ConfigKeyError(f"config.yaml: '{_where(path, key)}' must be a non-empty string (got {value!r})")
    return value.strip()


def number_list(mapping: Any, key: str, path: str, length: int | None = None) -> list[float]:
    value = require(mapping, key, path)
    if not isinstance(value, (list, tuple)):
        raise ConfigKeyError(f"config.yaml: '{_where(path, key)}' must be a list (got {value!r})")
    try:
        result = [float(v) for v in value]
    except (TypeError, ValueError):
        raise ConfigKeyError(f"config.yaml: '{_where(path, key)}' must contain numbers (got {value!r})") from None
    if length is not None and len(result) != length:
        raise ConfigKeyError(f"config.yaml: '{_where(path, key)}' must have {length} values (got {value!r})")
    return result


def pair(mapping: Any, key: str, path: str) -> tuple[float, float]:
    lo, hi = number_list(mapping, key, path, length=2)
    return (min(lo, hi), max(lo, hi))


def string_list(mapping: Any, key: str, path: str) -> list[str]:
    value = require(mapping, key, path)
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        raise ConfigKeyError(f"config.yaml: '{_where(path, key)}' must be a list of names (got {value!r})")
    return [v.strip() for v in value]
