"""CLI entrypoint for external PySide6 manual refit editor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gui.components.manual_refit_contract import REQUEST_SCHEMA_VERSION


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual refit desktop editor")
    parser.add_argument("--request", required=True, help="Path to request JSON")
    parser.add_argument("--output", required=True, help="Path to output JSON")
    return parser.parse_args()


def _load_request(path: Path):
    from .models import EditorRequest

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    request = EditorRequest.from_payload(payload)
    schema = str(payload.get("schema_version", "")).strip()
    if schema != REQUEST_SCHEMA_VERSION:
        raise ValueError(f"Unsupported request schema_version: {schema}")
    if not request.spectrum_id:
        raise ValueError("Request missing spectrum_id")
    if not request.selected_model:
        raise ValueError("Request missing selected_model")
    if not request.peaks:
        raise ValueError("Request has no editable peaks")
    return request


def main() -> int:
    args = _parse_args()
    request_path = Path(args.request).resolve()
    output_path = Path(args.output).resolve()
    if not request_path.exists():
        print(f"[desktop_editor] request file not found: {request_path}", file=sys.stderr)
        return 2

    try:
        request = _load_request(request_path)
    except Exception as exc:
        print(f"[desktop_editor] failed to parse request: {exc}", file=sys.stderr)
        return 2

    try:
        from PySide6.QtWidgets import QApplication
    except Exception as exc:
        print(f"[desktop_editor] PySide6 import failed: {exc}", file=sys.stderr)
        return 3
    try:
        from .controller import ManualEditorController
        from .main_window import ManualRefitMainWindow
    except Exception as exc:
        print(f"[desktop_editor] editor module import failed: {exc}", file=sys.stderr)
        return 3

    app = QApplication(sys.argv)
    controller = ManualEditorController(request)
    window = ManualRefitMainWindow(controller=controller, output_path=output_path)
    window.show()
    app.exec()
    return 0 if output_path.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
