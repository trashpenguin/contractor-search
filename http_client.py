from __future__ import annotations
import asyncio, threading
import logging
from urllib.request import Request, urlopen

from compat import HAS_SCRAPLING, Fetcher, StealthyFetcher
from proxy import PROXY_MGR

logger = logging.getLogger("ContractorFinder")

_ASYNC_LOOP: asyncio.AbstractEventLoop | None = None
_ASYNC_LOOP_LOCK = threading.Lock()


def get_event_loop() -> asyncio.AbstractEventLoop:
    """Returns a persistent event loop for the scraping thread."""
    global _ASYNC_LOOP
    with _ASYNC_LOOP_LOCK:
        if _ASYNC_LOOP is None or _ASYNC_LOOP.is_closed():
            _ASYNC_LOOP = asyncio.new_event_loop()
            asyncio.set_event_loop(_ASYNC_LOOP)
            logger.debug("Created new persistent async event loop")
        return _ASYNC_LOOP


def _urllib_get(url: str, timeout: int = 15) -> str:
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"
        })
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def http_get(url: str, timeout: int = 8, use_proxy: bool = False) -> str:
    """Fast HTTP with browser fingerprint + smart proxy routing."""
    proxy = PROXY_MGR.get_for(url) if (use_proxy and PROXY_MGR.ready) else None
    if not HAS_SCRAPLING:
        return _urllib_get(url, timeout)
    try:
        kwargs: dict = {"timeout": timeout}
        if proxy:
            kwargs["proxy"] = proxy
        r      = Fetcher.get(url, **kwargs)
        body   = r.body or ""
        result = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
        if proxy:
            PROXY_MGR.report(proxy, len(result) >= 200)
        return result
    except Exception as e:
        err = str(e)
        if proxy:
            PROXY_MGR.report(proxy, False, err)
        return _urllib_get(url, min(timeout, 8))


def stealth_get(url: str, wait: int = 3000, need_js: bool = False) -> str:
    """Single stealth browser fetch. Always returns str."""
    if not HAS_SCRAPLING:
        return ""
    try:
        r    = StealthyFetcher.fetch(
            url, headless=True, network_idle=True,
            disable_resources=not need_js, wait=wait,
        )
        body = r.body or ""
        return body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
    except Exception as e:
        logger.warning(f"[stealth] {url[:50]}: {type(e).__name__}")
        return ""


def post_bytes(url: str, data: bytes, hdrs: dict) -> bytes:
    try:
        req = Request(url, data=data, headers=hdrs, method="POST")
        with urlopen(req, timeout=60) as r:
            return r.read()
    except Exception:
        return b""
