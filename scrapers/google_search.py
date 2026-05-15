from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote_plus, unquote_plus

from compat import HAS_SCRAPLING, Adaptor, StealthySession
from constants import TRADE_KW
from models import Contractor

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


def scrape_google_search(trade: str, location: str, limit: int) -> list[Contractor]:
    """Multi-query + paginated Google Search local results (udm=1).

    Runs each query term in TRADE_KW[trade]['gsearch'], fetching up to
    _PAGES_PER_QUERY pages each. Deduplicates by phone and name within
    the scraper before returning.
    """
    if not HAS_SCRAPLING:
        return []

    query_terms: list[str] = TRADE_KW[trade].get("gsearch", [TRADE_KW[trade]["google"]])
    seen_phones: set[str] = set()
    seen_names: set[str] = set()
    out: list[Contractor] = []

    try:
        with StealthySession(headless=True, network_idle=True, disable_resources=False) as session:
            for term in query_terms:
                if len(out) >= limit:
                    break
                query = quote_plus(f'"{term} {location}"')
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
                    except Exception as e:
                        logger.info(f"[GSearch] fetch error: {type(e).__name__}: {e}")
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
                        break  # no more results for this term

                    new = 0
                    for c in cards:
                        if len(out) >= limit:
                            break
                        c.trade = trade
                        # dedup within this scraper by phone or normalised name
                        norm_name = re.sub(r"[^a-z0-9]", "", c.name.lower())
                        phone_key = re.sub(r"[^0-9]", "", c.phone)[-10:] if c.phone else ""
                        if phone_key and phone_key in seen_phones:
                            continue
                        if norm_name and norm_name in seen_names:
                            continue
                        if phone_key:
                            seen_phones.add(phone_key)
                        if norm_name:
                            seen_names.add(norm_name)
                        out.append(c)
                        new += 1

                    logger.info(f"[GSearch] {trade}: +{new} new (total {len(out)})")
                    if page_num < _PAGES_PER_QUERY - 1:
                        time.sleep(1.5)  # polite gap between pages

                if len(out) < limit:
                    time.sleep(1.5)  # polite gap between query terms

    except Exception as e:
        logger.info(f"[GSearch] {trade}: {type(e).__name__}: {e}")

    logger.info(f"[GSearch] {trade}: {len(out)} total")
    return out[:limit]
