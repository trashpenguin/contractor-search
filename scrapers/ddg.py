from __future__ import annotations
import threading, time
import logging

from cache import CACHE
from compat import HAS_SCRAPLING, Adaptor
from http_client import http_get

logger = logging.getLogger("ContractorFinder")

_DDG_LOCK = threading.Lock()
_DDG_REQ_TIMES: list[float] = []
_DDG_MAX_PER_MIN = 12


def _ddg_decode(href: str) -> str:
    """Decode DDG redirect: //duckduckgo.com/l/?uddg=ENCODED_URL → real URL"""
    if "uddg=" in href:
        try:
            from urllib.parse import unquote
            return unquote(href.split("uddg=")[1].split("&")[0])
        except Exception:
            pass
    return href


def _ddg_rate_limit():
    """Pause if too many DDG requests per minute to prevent 202/403 blocking."""
    with _DDG_LOCK:
        now = time.time()
        while _DDG_REQ_TIMES and now - _DDG_REQ_TIMES[0] > 60:
            _DDG_REQ_TIMES.pop(0)
        if len(_DDG_REQ_TIMES) >= _DDG_MAX_PER_MIN:
            wait = 65 - (now - _DDG_REQ_TIMES[0])
            if wait > 0:
                logger.debug(f"[DDG] Rate limit pause: {wait:.0f}s")
                time.sleep(wait)
        if _DDG_REQ_TIMES:
            gap = time.time() - _DDG_REQ_TIMES[-1]
            if gap < 1.5:
                time.sleep(1.5 - gap)
        _DDG_REQ_TIMES.append(time.time())


def ddg_search(query: str, pages: int = 2) -> list[tuple[str, str, str]]:
    """
    Search DuckDuckGo HTML endpoint. Rate-limited. Results cached for 24h.
    Returns list of (title, real_url, snippet).
    """
    cached = CACHE.get_ddg(query)
    if cached is not None:
        return [tuple(r) for r in cached]

    results = []
    for page_idx in range(pages):
        _ddg_rate_limit()
        dc   = f"&dc={page_idx * 11}" if page_idx > 0 else ""
        url  = f"https://html.duckduckgo.com/html/?q={query}{dc}"
        html = http_get(url, timeout=15, use_proxy=True)
        if not html or not HAS_SCRAPLING:
            break
        if len(html) < 200:
            logger.debug("[DDG] Rate-limited (short response), backing off 20s")
            time.sleep(20)
            break
        page  = Adaptor(html)
        found = 0
        for card in page.css("div.result"):
            title_els = card.css("a.result__a")
            if not title_els:
                continue
            name     = title_els[0].text.strip()
            raw_href = title_els[0].attrib.get("href", "")
            real_url = _ddg_decode(raw_href)
            snippet  = ""
            snip_els = card.css("a.result__snippet")
            if snip_els:
                snippet = snip_els[0].get_all_text(separator=" ")
            if name and real_url:
                results.append((name, real_url, snippet))
                found += 1
        if found == 0:
            break

    if results:
        CACHE.set_ddg(query, [(n, u, s) for n, u, s in results])
    return results
