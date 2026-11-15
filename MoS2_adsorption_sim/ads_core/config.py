"""Strict access to ``config.yaml``.

Scientific values and simulation rules live only in the YAML file. There are
no code-side defaults: a missing key or a value of the wrong type raises
``ConfigKeyError`` naming the key. Every read is recorded so a test can prove
that no key in the file is dead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Mapping

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


class ConfigKeyError(KeyError):
    """A config key is missing or holds a value of the wrong type."""

    def __str__(self) -> str:  # KeyError would wrap the message in quotes
        return str(self.args[0]) if self.args else ""


def _leaf_paths(node: Any, prefix: str) -> Iterator[str]:
    if isinstance(node, Mapping) and node:
        for key, value in node.items():
            yield from _leaf_paths(value, f"{prefix}.{key}" if prefix else str(key))
    else:
        yield prefix


class Config:
    """Dotted-path reader over the parsed YAML mapping."""

    def __init__(self, data: Mapping[str, Any], source: Path | None = None) -> None:
        if not isinstance(data, Mapping):
            raise ConfigKeyError(f"config root must be a mapping ({source})")
        self._data = data
        self._source = source
        self._read: set[str] = set()

    @property
    def source(self) -> Path | None:
        return self._source

    def _lookup(self, path: str) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, Mapping) or part not in node:
                raise ConfigKeyError(f"config key missing: {path} ({self._source})")
            node = node[part]
        return node

    def _wrong_type(self, path: str, expected: str, value: Any) -> ConfigKeyError:
        return ConfigKeyError(f"config key {path} must be {expected}, got {value!r} ({self._source})")

    def number(self, path: str) -> float:
        value = self._lookup(path)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self._wrong_type(path, "a number", value)
        self._read.add(path)
        return float(value)

    def integer(self, path: str) -> int:
        value = self._lookup(path)
        if isinstance(value, bool) or not isinstance(value, int):
            raise self._wrong_type(path, "an integer", value)
        self._read.add(path)
        return value

    def boolean(self, path: str) -> bool:
        value = self._lookup(path)
        if not isinstance(value, bool):
            raise self._wrong_type(path, "true or false", value)
        self._read.add(path)
        return value

    def text(self, path: str) -> str:
        value = self._lookup(path)
        if not isinstance(value, str):
            raise self._wrong_type(path, "text", value)
        self._read.add(path)
        return value

    def number_list(self, path: str) -> list[float]:
        value = self._lookup(path)
        if (
            not isinstance(value, list)
            or not value
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
        ):
            raise self._wrong_type(path, "a non-empty list of numbers", value)
        self._read.add(path)
        return [float(item) for item in value]

    def text_list(self, path: str) -> list[str]:
        value = self._lookup(path)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise self._wrong_type(path, "a list of text", value)
        self._read.add(path)
        return list(value)

    def text_lists(self, path: str) -> dict[str, list[str]]:
        value = self._lookup(path)
        if not isinstance(value, Mapping) or not value:
            raise self._wrong_type(path, "a mapping of text lists", value)
        return {str(key): self.text_list(f"{path}.{key}") for key in value}

    def texts(self, path: str) -> dict[str, str]:
        value = self._lookup(path)
        if not isinstance(value, Mapping) or not value:
            raise self._wrong_type(path, "a mapping of text", value)
        return {str(key): self.text(f"{path}.{key}") for key in value}

    def leaf_keys(self) -> set[str]:
        return set(_leaf_paths(self._data, ""))

    def unread_keys(self) -> set[str]:
        return self.leaf_keys() - self._read

    def as_dict(self) -> dict[str, Any]:
        """Plain copy of the whole config, for reproducibility metadata."""
        return yaml.safe_load(yaml.safe_dump(dict(self._data), allow_unicode=True))


def load_config(path: Path | str | None = None) -> Config:
    source = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    return Config(payload, source)
