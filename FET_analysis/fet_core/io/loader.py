"""Find the right reader for each file and load a folder into the standard model."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Iterable

from fet_core.config import Config
from fet_core.io import b1500_csv, clarius_xls
from fet_core.model import SEVERITY_ERROR, SEVERITY_INFO, InputFile, LoadResult, WarningRecord

logger = logging.getLogger(__name__)

# Tried in this order. A new reader is added only when real example files exist.
READERS = (b1500_csv, clarius_xls)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_reader(path: Path, config: Config):
    """The reader module for ``path``, or None when no reader recognises it."""
    suffix = path.suffix.casefold()
    for reader in READERS:
        extensions = {ext.casefold() for ext in config.text_list(f"readers.{reader.NAME}.extensions")}
        if suffix in extensions and reader.sniff(path, config):
            return reader
    return None


def load_files(paths: Iterable[Path], config: Config) -> LoadResult:
    """Read every file. A file that fails is recorded and the rest still load."""
    result = LoadResult()
    ordered = sorted(Path(p) for p in paths)
    hashes = {path: sha256_of(path) for path in ordered}
    # Among byte-for-byte copies keep the shortest name ("x.csv" rather than "x-1.csv").
    keeper: dict[str, Path] = {}
    for path in sorted(ordered, key=lambda item: (len(item.name), item.name)):
        keeper.setdefault(hashes[path], path)
    for path in ordered:
        sha256 = hashes[path]
        reader = detect_reader(path, config)
        if reader is None:
            result.files.append(InputFile(path, sha256, None, "skipped", "no reader recognises this file"))
            continue
        if keeper[sha256] != path:
            original = keeper[sha256].name
            result.files.append(InputFile(path, sha256, reader.NAME, "skipped", f"same content as {original}"))
            result.warnings.append(
                WarningRecord(
                    "duplicate_file",
                    f"Skipped: byte-for-byte copy of '{original}'.",
                    path.name,
                    severity=SEVERITY_INFO,
                    context={"duplicate_of": original},
                )
            )
            continue
        try:
            measurements, warnings = reader.read(path, sha256, config)
        except Exception as exc:  # one unreadable file must not stop the batch
            logger.exception("Reader %s failed on %s", reader.NAME, path)
            result.files.append(InputFile(path, sha256, reader.NAME, "skipped", f"reader error: {exc}"))
            result.warnings.append(
                WarningRecord(
                    "reader_failed",
                    f"Could not read the file: {exc}",
                    path.name,
                    severity=SEVERITY_ERROR,
                    context={"error_type": type(exc).__name__},
                )
            )
            continue
        result.measurements.extend(measurements)
        result.warnings.extend(warnings)
        if measurements:
            result.files.append(InputFile(path, sha256, reader.NAME, "read", measurement_count=len(measurements)))
        else:
            result.files.append(InputFile(path, sha256, reader.NAME, "skipped", "no usable measurement in the file"))
    logger.info(
        "Loaded %d measurement(s) from %d file(s); %d warning(s)",
        len(result.measurements),
        sum(1 for item in result.files if item.status == "read"),
        len(result.warnings),
    )
    return result


def load_folder(folder: Path | str, config: Config) -> LoadResult:
    """Load the files directly inside ``folder`` (sub-folders are separate batches)."""
    directory = Path(folder)
    if not directory.is_dir():
        raise NotADirectoryError(f"Input folder not found: {directory}")
    return load_files((p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")), config)
