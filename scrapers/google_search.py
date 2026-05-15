from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, unquote_plus

from compat import HAS_SCRAPLING, Adaptor, StealthySession
from constants import TRADE_KW
from models import Contractor

logger = logging.getLogger("ContractorFinder")

_PHONE_RE = re.compile(r"[+]?1?\s?[(]?\d{3}[)./-]\s?\d{3}[./-]\s?\d{4}")
_MAPS_NAME_RE = re.compile(r"/maps/dir//([^/,]+)")
_MAPS_ADDR_RE = re.compile(r"/maps/dir//[^/]+/([^/]+)/data=")


def _name_from_maps_href(href: str) -> str:
    m = _MAPS_NAME_RE.search(href)
    return unquote_plus(m.group(1)).strip() if m else ""


def _addr_from_maps_href(href: str) -> str:
    m = _MAPS_ADDR_RE.search(href)
    if not m:
        return ""
    addr = unquote_plus(m.group(1)).strip()
    return re.sub(r",\s*United States$", "", addr).strip()


def scrape_google_search(trade: str, location: str, limit: int) -> list[Contractor]:
    """Scrape Google Search local results (udm=1) — phones are in the card directly."""
    out: list[Contractor] = []
    if not HAS_SCRAPLING:
        return out

    keyword = TRADE_KW[trade]["google"]
    query = quote_plus(f"{keyword} {location}")
    url = f"https://www.google.com/search?q={query}&udm=1"

    try:
        with StealthySession(headless=True, network_idle=True, disable_resources=False) as session:
            resp = session.fetch(url, wait=5000)
            html = resp.body or ""
            if isinstance(html, bytes):
                html = html.decode("utf-8", errors="ignore")

            if resp.status != 200 or len(html) < 50_000:
                logger.info(f"[GSearch] {trade}: status={resp.status} len={len(html)}")
                return out

            page = Adaptor(html)
            cards = page.css("div[class*=VkpGBb]") or page.css("div[class*=uMdZh]")
            logger.info(f"[GSearch] {trade}: {len(cards)} cards")

            for card in cards:
                if len(out) >= limit:
                    break

                text = card.get_all_text(separator=" ")

                phone_m = _PHONE_RE.search(text)
                phone = phone_m.group(0).strip() if phone_m else ""

                hrefs = [a.attrib.get("href", "") for a in card.css("a")]
                website = ""
                maps_href = ""
                for h in hrefs:
                    if h.startswith("http") and "google" not in h and not website:
                        # strip UTM and booking params that aren't the real domain
                        website = re.split(r"[?&]utm_|[?&]rwg_token", h)[0]
                    if "/maps/dir//" in h and not maps_href:
                        maps_href = h

                name = _name_from_maps_href(maps_href)
                if not name:
                    name = text.split("|")[0].split("(")[0].strip()
                if not name or len(name) < 2:
                    continue

                address = _addr_from_maps_href(maps_href)

                out.append(
                    Contractor(
                        trade=trade,
                        name=name,
                        phone=phone,
                        website=website,
                        address=address,
                        source="Google Search",
                    )
                )

    except Exception as e:
        logger.info(f"[GSearch] {trade}: {type(e).__name__}: {e}")

    logger.info(f"[GSearch] {trade}: {len(out)} total")
    return out[:limit]
