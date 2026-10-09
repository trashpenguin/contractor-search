from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, unquote_plus

from compat import HAS_SCRAPLING, Adaptor, StealthySession
from constants import TRADE_KW
from http_client import SearchCancelled, check_cancelled, interruptible_sleep
from models import Contractor
from proxy import PROXY_MGR

logger = logging.getLogger("ContractorFinder")

_PHONE_RE = re.compile(r"[+]?1?\s?[(]?\d{3}[)./-]\s?\d{3}[./-]\s?\d{4}")
_MAPS_NAME_RE = re.compile(r"/maps/dir//([^/,]+)")
_MAPS_ADDR_RE = re.compile(r"/maps/dir//[^/]+/([^/]+)/data=")

# Max pages to fetch per query term (20 cards per page)
_PAGES_PER_QUERY = 2


def _name_from_maps_href(href: str) -> str:
    m = _MAPS_NAME_RE.search(href)
    return unquote_plus(m.group(1)).strip() if m else ""


def _addr_from_maps_href(href: str) -> str:
    m = _MAPS_ADDR_RE.search(href)
    if not m:
        return ""
    addr = unquote_plus(m.group(1)).strip()
    return re.sub(r",\s*United States$", "", addr).strip()


_NAME_STOP_RE = re.compile(
    r"\s+\d\.\d\b"  # rating  e.g. " 4.7"
    r"|\s+No\s+reviews"  # "No reviews"
    r"|\s+·"  # Google bullet separator
    r"|\s+\("  # "(123)"  review count
    r"|\s+Open\b"  # hours info
    r"|\s+Closed\b"
)


def _clean_name_fallback(text: str) -> str:
    """Extract business name from raw card text when no maps href is available."""
    # Stop at rating, bullet, review count, or hours info
    name = _NAME_STOP_RE.split(text)[0].strip()
    # Drop a leading "Sponsored" label
    name = re.sub(r"^Sponsored\s+", "", name, flags=re.IGNORECASE).strip()
    return name[:100]


def _parse_cards(html: str) -> list[Contractor]:
    """Extract Contractor objects from a Google Search local results page."""
    page = Adaptor(html)
    cards = page.css("div[class*=VkpGBb]") or page.css("div[class*=uMdZh]")
    results: list[Contractor] = []
    for card in cards:
        text = card.get_all_text(separator=" ")

        # Skip sponsored ads — they have /aclk links and no maps directions href
        hrefs = [a.attrib.get("href", "") for a in card.css("a")]
        if all("/aclk" in h or not h for h in hrefs):
            continue

        phone_m = _PHONE_RE.search(text)
        phone = phone_m.group(0).strip() if phone_m else ""

        website = ""
        maps_href = ""
        for h in hrefs:
            if h.startswith("http") and "google" not in h and not website:
                website = re.split(r"[?&]utm_|[?&]rwg_token", h)[0]
            if "/maps/dir//" in h and not maps_href:
                maps_href = h

        name = _name_from_maps_href(maps_href) or _clean_name_fallback(text)
        if not name or len(name) < 2:
            continue

        results.append(
            Contractor(
                trade="",  # filled in by caller
                name=name,
                phone=phone,
                website=website,
                address=_addr_from_maps_href(maps_href),
                source="Google Search",
            )
        )
    return results


_PROXY_CONN_ERRORS = (
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ECONNREFUSED",
    "ETIMEDOUT",
    "ERR_CONNECTION_TIMED_OUT",
    "ProxyError",
    "net::ERR_PROXY",
    "net::ERR_TUNNEL",
)


def _is_proxy_error(exc: Exception) -> bool:
    s = str(exc)
    return any(e in s for e in _PROXY_CONN_ERRORS)


def scrape_google_search(trade: str, location: str, limit: int) -> list[Contractor]:
    """Multi-query + paginated Google Search local results (udm=1).

    Runs each query term in TRADE_KW[trade]['gsearch'], fetching up to
    _PAGES_PER_QUERY pages each. Deduplicates by phone and name within
    the scraper before returning. Restarts session with a new proxy on
    connection failures (ERR_PROXY_CONNECTION_FAILED etc.).
    """
    check_cancelled()
    if not HAS_SCRAPLING:
        raise RuntimeError("Google Search requires Scrapling browser dependencies")

    query_terms: list[str] = TRADE_KW[trade].get("gsearch", [TRADE_KW[trade]["google"]])
    seen_records: set[tuple] = set()
    out: list[Contractor] = []

    terms_todo = list(query_terms)
    rate_limited = False

    for _session_attempt in range(4):  # up to 4 proxy rotations
        if not terms_todo or len(out) >= limit or rate_limited:
            break

        proxy_url = PROXY_MGR.get() if PROXY_MGR.ready else None
        sk: dict = {"headless": True, "network_idle": True, "disable_resources": False}
        if proxy_url:
            sk["proxy"] = proxy_url
            logger.info(f"[GSearch] using proxy {proxy_url.split('@')[-1]}")

        need_new_session = False
        try:
            with StealthySession(**sk) as session:
                while terms_todo and len(out) < limit and not rate_limited and not need_new_session:
                    term = terms_todo[0]
                    query = quote_plus(f'"{term} {location}"')
                    term_done = True

                    for page_num in range(_PAGES_PER_QUERY):
                        if len(out) >= limit:
                            break
                        start = page_num * 20
                        url = f"https://www.google.com/search?q={query}&udm=1&start={start}"
                        try:
                            resp = session.fetch(url, wait=5000)
                            html = resp.body or ""
                            if isinstance(html, bytes):
                                html = html.decode("utf-8", errors="ignore")
                        except SearchCancelled:
                            raise
                        except Exception as e:
                            if proxy_url and PROXY_MGR.ready and _is_proxy_error(e):
                                PROXY_MGR.mark_bad(proxy_url, "dead")
                                logger.info(
                                    f"[GSearch] proxy dead ({proxy_url.split('@')[-1]}) — rotating"
                                )
                                need_new_session = True
                                term_done = False
                            else:
                                logger.info(f"[GSearch] fetch error: {type(e).__name__}: {e}")
                            break

                        if resp.status == 429 or "google.com/sorry" in (resp.url or ""):
                            if PROXY_MGR.ready:
                                if proxy_url:
                                    PROXY_MGR.mark_bad(proxy_url, "429")
                                logger.info("[GSearch] 429 — rotating proxy, skipping term")
                                need_new_session = True
                                term_done = False
                            else:
                                logger.info(f"[GSearch] {trade}: rate-limited — skipping source")
                                rate_limited = True
                            break

                        if resp.status != 200 or len(html) < 50_000:
                            logger.info(
                                f"[GSearch] {trade} term={term!r} p{page_num+1}: "
                                f"status={resp.status} len={len(html)}"
                            )
                            break

                        cards = _parse_cards(html)
                        logger.info(
                            f"[GSearch] {trade} term={term!r} p{page_num+1}: {len(cards)} cards"
                        )
                        if not cards:
                            break

                        new = 0
                        for c in cards:
                            if len(out) >= limit:
                                break
                            c.trade = trade
                            c.discovery_url = url
                            norm_name = re.sub(r"[^a-z0-9]", "", c.name.lower())
                            phone_key = re.sub(r"[^0-9]", "", c.phone)[-10:] if c.phone else ""
                            address_key = re.sub(r"[^a-z0-9]", "", c.address.lower())
                            identity = (norm_name, phone_key, address_key)
                            if identity in seen_records:
                                continue
                            seen_records.add(identity)
                            out.append(c)
                            new += 1

                        logger.info(f"[GSearch] {trade}: +{new} new (total {len(out)})")
                        if page_num < _PAGES_PER_QUERY - 1:
                            interruptible_sleep(1.5)

                    if term_done:
                        terms_todo.pop(0)
                        if terms_todo and not need_new_session:
                            interruptible_sleep(1.5)

        except SearchCancelled:
            raise
        except Exception as e:
            logger.info(f"[GSearch] {trade}: session error: {type(e).__name__}: {e}")
            if proxy_url and PROXY_MGR.ready and _is_proxy_error(e):
                PROXY_MGR.mark_bad(proxy_url, "dead")
            need_new_session = True

        if not need_new_session or not PROXY_MGR.ready:
            break

    if rate_limited and not out:
        raise RuntimeError("Google Search was rate limited")
    logger.info(f"[GSearch] {trade}: {len(out)} total")
    return out[:limit]
