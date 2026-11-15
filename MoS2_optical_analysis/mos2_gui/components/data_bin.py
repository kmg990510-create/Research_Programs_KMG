"""Utilities for soft-delete workflow using data/bin as a staging area."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil

from fitting.mos2_core.review.manual_overrides import (
    is_result_json_selectable,
    result_relpaths_linked_to_report_json,
)


METADATA_FILE = "metadata.json"
PAYLOAD_DIR = "payload"
ALLOWED_SCOPES = ("raw", "results")


@dataclass(frozen=True)
class BinEntry:
    entry_id: str
    scope: str
    modality: str
    original_relpath: str
    original_name: str
    moved_at: str
    item_type: str
    entry_path: Path
    payload_path: Path


def managed_root(project_root: Path, scope: str, modality: str) -> Path:
    _validate_scope(scope)
    return project_root / "data" / scope / modality


def bin_root(project_root: Path, scope: str, modality: str) -> Path:
    _validate_scope(scope)
    return project_root / "data" / "bin" / scope / modality


def list_scope_items(
    project_root: Path,
    scope: str,
    modality: str,
    recursive: bool = False,
    files_only: bool = False,
) -> list[Path]:
    root = managed_root(project_root, scope, modality)
    if not root.exists():
        return []

    if recursive:
        candidates = [p for p in root.rglob("*")]
    else:
        candidates = [p for p in root.iterdir()]

    out: list[Path] = []
    for path in candidates:
        if path.name == ".gitkeep":
            continue
        if files_only and not path.is_file():
            continue
        out.append(path.relative_to(root))
    return sorted(out, key=lambda p: p.as_posix().lower())


def list_result_json_items(project_root: Path, modality: str) -> list[Path]:
    """List only user-selectable result JSON files (report + manual override)."""
    items = list_scope_items(
        project_root,
        scope="results",
        modality=modality,
        recursive=True,
        files_only=True,
    )
    selected = [p for p in items if is_result_json_selectable(p)]
    return sorted(selected, key=lambda p: p.as_posix().lower())


def linked_result_relpaths_for_item(relative_path: str) -> list[str]:
    """
    Expand a selected result item to linked set.

    - report JSON -> report JSON + paired CSV + manual override JSON
    - other selectable JSON -> itself
    """
    rel = Path(relative_path).as_posix()
    return result_relpaths_linked_to_report_json(rel)


def _sanitize_fragment(text: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", text).strip("_") or "item"


def _validate_scope(scope: str) -> None:
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"Unsupported scope: {scope}")


def _ensure_under(path: Path, base: Path) -> None:
    path.resolve().relative_to(base.resolve())


def _entry_payload_path(entry_dir: Path) -> Path | None:
    payload_dir = entry_dir / PAYLOAD_DIR
    if not payload_dir.exists():
        return None
    children = [p for p in payload_dir.iterdir()]
    if not children:
        return None
    return children[0]


def _load_metadata(entry_dir: Path) -> dict:
    meta_path = entry_dir / METADATA_FILE
    if not meta_path.exists():
        return {}
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _write_metadata(entry_dir: Path, payload: dict) -> None:
    meta_path = entry_dir / METADATA_FILE
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def move_scope_item_to_bin(project_root: Path, scope: str, modality: str, relative_path: str) -> BinEntry:
    source_root = managed_root(project_root, scope, modality)
    source = (source_root / relative_path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source item not found: {source}")
    _ensure_under(source, source_root)

    target_bin_root = bin_root(project_root, scope, modality)
    target_bin_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    rel_path = source.relative_to(source_root)
    rel_fragment = _sanitize_fragment(rel_path.as_posix().replace("/", "__"))
    entry_id = f"{stamp}__{rel_fragment}"
    entry_dir = target_bin_root / entry_id
    payload_dir = entry_dir / PAYLOAD_DIR
    payload_dir.mkdir(parents=True, exist_ok=False)

    payload_path = payload_dir / source.name
    shutil.move(str(source), str(payload_path))

    item_type = "dir" if payload_path.is_dir() else "file"
    metadata = {
        "entry_id": entry_id,
        "scope": scope,
        "modality": modality,
        "original_relpath": rel_path.as_posix(),
        "original_name": source.name,
        "moved_at": datetime.now(timezone.utc).isoformat(),
        "item_type": item_type,
    }
    _write_metadata(entry_dir, metadata)
    return BinEntry(
        entry_id=entry_id,
        scope=scope,
        modality=modality,
        original_relpath=metadata["original_relpath"],
        original_name=source.name,
        moved_at=metadata["moved_at"],
        item_type=item_type,
        entry_path=entry_dir,
        payload_path=payload_path,
    )


def list_bin_entries(project_root: Path, scope: str, modality: str) -> list[BinEntry]:
    target_bin_root = bin_root(project_root, scope, modality)
    if not target_bin_root.exists():
        return []

    items: list[BinEntry] = []
    for entry_dir in sorted(
        [p for p in target_bin_root.iterdir() if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    ):
        metadata = _load_metadata(entry_dir)
        payload_path = _entry_payload_path(entry_dir)
        if payload_path is None:
            continue

        entry_id = str(metadata.get("entry_id") or entry_dir.name)
        resolved_scope = str(metadata.get("scope") or scope)
        original_name = str(metadata.get("original_name") or payload_path.name)
        original_relpath = str(metadata.get("original_relpath") or original_name)
        moved_at = str(metadata.get("moved_at") or "")
        item_type = str(metadata.get("item_type") or ("dir" if payload_path.is_dir() else "file"))
        items.append(
            BinEntry(
                entry_id=entry_id,
                scope=resolved_scope,
                modality=modality,
                original_relpath=original_relpath,
                original_name=original_name,
                moved_at=moved_at,
                item_type=item_type,
                entry_path=entry_dir,
                payload_path=payload_path,
            )
        )
    return items


def restore_bin_entry(project_root: Path, scope: str, modality: str, entry_id: str) -> Path:
    entry = _find_entry(project_root, scope, modality, entry_id)
    source_root = managed_root(project_root, scope, modality)
    source_root.mkdir(parents=True, exist_ok=True)

    destination = source_root / Path(entry.original_relpath)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        now_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        if destination.is_dir() or "." not in destination.name:
            destination = destination.parent / f"{destination.name}__restored_{now_tag}"
        else:
            destination = destination.with_name(
                f"{destination.stem}__restored_{now_tag}{destination.suffix}"
            )

    shutil.move(str(entry.payload_path), str(destination))
    shutil.rmtree(entry.entry_path, ignore_errors=True)
    return destination


def purge_bin_entry(project_root: Path, scope: str, modality: str, entry_id: str) -> None:
    entry = _find_entry(project_root, scope, modality, entry_id)
    if entry.payload_path.is_dir():
        shutil.rmtree(entry.payload_path, ignore_errors=True)
    elif entry.payload_path.exists():
        entry.payload_path.unlink(missing_ok=True)
    shutil.rmtree(entry.entry_path, ignore_errors=True)


def _find_entry(project_root: Path, scope: str, modality: str, entry_id: str) -> BinEntry:
    for entry in list_bin_entries(project_root, scope, modality):
        if entry.entry_id == entry_id:
            return entry
    raise FileNotFoundError(
        f"Bin entry not found: scope={scope} modality={modality} entry_id={entry_id}"
    )
