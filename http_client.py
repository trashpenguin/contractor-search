from __future__ import annotations

import asyncio
import logging
import threading
import time as _time
from urllib.request import Request, urlopen

from compat import HAS_SCRAPLING, Fetcher, StealthyFetcher
from proxy import PROXY_MGR

logger = logging.getLogger("ContractorFinder")


class SearchCancelled(Exception):
    """Raised when the current search was stopped."""


_SEARCH_CONTEXT = threading.local()


def set_search_stop(event):
    _SEARCH_CONTEXT.stop = event


def current_search_stop():
    return getattr(_SEARCH_CONTEXT, "stop", None)


def call_with_stop(event, function, *args, **kwargs):
    previous = current_search_stop()
    set_search_stop(event)
    try:
        check_cancelled()
        return function(*args, **kwargs)
    finally:
        set_search_stop(previous)


def check_cancelled():
    event = getattr(_SEARCH_CONTEXT, "stop", None)
    if event is not None and event.is_set():
        raise SearchCancelled()


def interruptible_sleep(seconds):
    event = getattr(_SEARCH_CONTEXT, "stop", None)
    if event is not None:
        if event.wait(seconds):
            raise SearchCancelled()
    else:
        _time.sleep(seconds)


_LOOP_CONTEXT = threading.local()


def get_event_loop() -> asyncio.AbstractEventLoop:
    """One event loop per worker thread; never shared across searches."""
    loop = getattr(_LOOP_CONTEXT, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _LOOP_CONTEXT.loop = loop
    return loop


def close_event_loop():
    loop = getattr(_LOOP_CONTEXT, "loop", None)
    if loop is not None and not loop.is_closed():
        loop.close()
    _LOOP_CONTEXT.loop = None


def _urllib_get(url: str, timeout: int = 15) -> str:
    try:
        req = Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"}
        )
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _http_get_once(url: str, timeout: int = 8, use_proxy: bool = False) -> str:
    """Single HTTP attempt with browser fingerprint + smart proxy routing."""
    proxy = PROXY_MGR.get_for(url) if (use_proxy and PROXY_MGR.ready) else None
    if not HAS_SCRAPLING:
        return _urllib_get(url, timeout)
    try:
        kwargs: dict = {"timeout": timeout, "verify": True}
        if proxy:
            kwargs["proxy"] = proxy
        r = Fetcher.get(url, **kwargs)
        body = r.body or ""
        result = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
        if proxy:
            PROXY_MGR.report(proxy, len(result) >= 200)
        return result
    except Exception as e:
        err = str(e)
        if proxy:
            PROXY_MGR.report(proxy, False, err)
        return _urllib_get(url, min(timeout, 8))


def http_get(url: str, timeout: int = 8, use_proxy: bool = False, retries: int = 2) -> str:
    """HTTP GET with exponential backoff on transient failures (1s, 2s delays)."""
    delay = 1.0
    for attempt in range(retries + 1):
        check_cancelled()
        result = _http_get_once(url, timeout, use_proxy)
        if result:
            return result
        if attempt < retries:
            interruptible_sleep(delay)
            delay *= 2
    return ""


def stealth_get(url: str, wait: int = 3000, need_js: bool = False) -> str:
    """Single stealth browser fetch. Always returns str."""
    check_cancelled()
    if not HAS_SCRAPLING:
        return ""
    try:
        r = StealthyFetcher.fetch(
            url,
            headless=True,
            network_idle=True,
            disable_resources=not need_js,
            wait=wait,
        )
        body = r.body or ""
        return body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
    except Exception as e:
        logger.warning(f"[stealth] {url[:50]}: {type(e).__name__}")
        return ""


def post_bytes(url: str, data: bytes, hdrs: dict) -> bytes:
    check_cancelled()
    try:
        req = Request(url, data=data, headers=hdrs, method="POST")
        with urlopen(req, timeout=60) as r:
            return r.read()
    except Exception:
        return b""
