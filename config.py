from __future__ import annotations
import os

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Enrichment ────────────────────────────────────────────────────────────────
# Contractors per batch sent to async enrichment. Larger = more memory but
# fewer event-loop round-trips. 15 keeps latency predictable.
ENRICH_BATCH_SIZE: int = int(os.environ.get("ENRICH_BATCH_SIZE", "15"))

# Max DDG website-lookup calls per trade. DDG starts returning 202s at ~10
# rapid requests; 8 leaves headroom for retries.
DDG_CAP: int = int(os.environ.get("DDG_CAP", "8"))

# aiohttp semaphore limits — concurrent requests per target domain.
# Google blocks hard at >1 concurrent scrape; DDG at >2; others tolerate 6.
SEM_DDG: int = int(os.environ.get("SEM_DDG", "2"))
SEM_GOOGLE: int = int(os.environ.get("SEM_GOOGLE", "1"))
SEM_YELLOWPAGES: int = int(os.environ.get("SEM_YELLOWPAGES", "2"))
SEM_DEFAULT: int = int(os.environ.get("SEM_DEFAULT", "6"))

# ── Cache TTLs (seconds) ──────────────────────────────────────────────────────
TTL_CONTACT: int = int(os.environ.get("TTL_CONTACT", str(7 * 86400)))   # 7 days
TTL_DDG: int = int(os.environ.get("TTL_DDG", str(1 * 86400)))           # 1 day
