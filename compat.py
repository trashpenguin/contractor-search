"""
Optional dependency detection. Import HAS_* flags and the objects themselves
from here so every module has a single source of truth.
Objects that failed to import are set to None — guard with HAS_* before use.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("ContractorFinder")

try:
    from scrapling.fetchers import (
        AsyncFetcher,
        Fetcher,
        FetcherSession,
        StealthyFetcher,
        StealthySession,
    )
    from scrapling.parser import Adaptor

    HAS_SCRAPLING = True
except Exception as _e:
    HAS_SCRAPLING = False
    Fetcher = FetcherSession = AsyncFetcher = None  # type: ignore[assignment,misc]
    StealthyFetcher = StealthySession = None  # type: ignore[assignment,misc]
    Adaptor = None  # type: ignore[assignment,misc]
    logger.warning(f"[WARN] Scrapling unavailable: {_e}")

try:
    import aiohttp as _aiohttp

    HAS_AIOHTTP = True
except ImportError:
    _aiohttp = None  # type: ignore[assignment]
    HAS_AIOHTTP = False
    logger.warning("[WARN] aiohttp not installed — async enrichment disabled (pip install aiohttp)")

try:
    import dns.resolver as _dns

    HAS_DNS = True
except ImportError:
    _dns = None  # type: ignore[assignment]
    HAS_DNS = False
    logger.warning(
        "[WARN] dnspython not installed — email MX verification disabled (pip install dnspython)"
    )
