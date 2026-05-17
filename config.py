from __future__ import annotations

import json
import os
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Enrichment ────────────────────────────────────────────────────────────────
# Contractors per batch sent to async enrichment. Larger = more memory but
# fewer event-loop round-trips. 15 keeps latency predictable.
ENRICH_BATCH_SIZE: int = int(os.environ.get("ENRICH_BATCH_SIZE", "15"))

# Max DDG website-lookup calls per trade. Async sleep(0.3) between calls
# keeps DDG happy; 30 covers a full OSM result set without triggering 202s.
DDG_CAP: int = int(os.environ.get("DDG_CAP", "30"))

# aiohttp semaphore limits — concurrent requests per target domain.
# Google blocks hard at >1 concurrent scrape; DDG at >2; others tolerate 6.
SEM_DDG: int = int(os.environ.get("SEM_DDG", "2"))
SEM_GOOGLE: int = int(os.environ.get("SEM_GOOGLE", "1"))
SEM_YELLOWPAGES: int = int(os.environ.get("SEM_YELLOWPAGES", "2"))
SEM_DEFAULT: int = int(os.environ.get("SEM_DEFAULT", "6"))

# ── Cache TTLs (seconds) ──────────────────────────────────────────────────────
TTL_CONTACT: int = int(os.environ.get("TTL_CONTACT", str(7 * 86400)))  # 7 days
TTL_DDG: int = int(os.environ.get("TTL_DDG", str(1 * 86400)))  # 1 day

# ── User-persistent settings ──────────────────────────────────────────────────
# Stored in ~/.contractor_finder_settings.json so values survive restarts.

_SETTINGS_FILE = Path.home() / ".contractor_finder_settings.json"


def _load_settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get(key: str, default=None):
    return _load_settings().get(key, default)


def set(key: str, value) -> None:  # noqa: A001
    data = _load_settings()
    data[key] = value
    try:
        _SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass
