from __future__ import annotations

import json
from pathlib import Path

_FILE = Path.home() / ".contractor_finder_settings.json"


def _load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        _FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def get(key: str, default=None):
    return _load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001
    data = _load()
    data[key] = value
    _save(data)
