from __future__ import annotations
import re
import logging
from urllib.parse import quote_plus

from constants import TRADE_KW, PHONE_RE, ADDR_RE
from compat import HAS_SCRAPLING, StealthySession, Adaptor
from models import Contractor

logger = logging.getLogger("ContractorFinder")


def scrape_google(trade: str, location: str, limit: int) -> list[Contractor]:
    """
    Uses ONE persistent StealthySession browser for Google Maps.
    Strategy 1: div[role='feed'] aria-label items.
    Strategy 2: JSON embedded in page scripts (fallback).
    """
    out: list[Contractor] = []
    if not HAS_SCRAPLING:
        return out

    term = quote_plus(f"{TRADE_KW[trade]['google']} near {location}")
    url  = f"https://www.google.com/maps/search/{term}"

    try:
        with StealthySession(headless=True, network_idle=True,
                             disable_resources=False) as session:
            try:
                resp = session.fetch(url, wait=6000)
                raw  = resp.body or b""
                html = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
            except Exception as e:
                logger.warning(f"[Google] Initial load error: {type(e).__name__}")
                return out

            if not html:
                return out

            page = Adaptor(html)

            # Strategy 1: div[role='feed']
            feed = page.css("div[role='feed']")
            if feed:
                items = feed[0].css("div[aria-label]")
                for el in items:
                    if len(out) >= limit:
                        break
                    label = el.attrib.get("aria-label", "").strip()
                    if not label or len(label) < 2:
                        continue
                    name = label.split("·")[0].strip()
                    skip = ["search", "result", "map", "back", "menu", "list",
                            "view", "zoom", "more", "filter"]
                    if any(w in name.lower() for w in skip) or len(name) < 2:
                        continue
                    txt = el.get_all_text(separator="\n")
                    phone = ""
                    m = PHONE_RE.search(txt)
                    if m:
                        phone = m.group(1)
                    address = ""
                    addr_m = ADDR_RE.search(txt)
                    if addr_m:
                        address = addr_m.group(0).strip()
                    website = ""
                    for lel in el.css("a[href^='http']:not([href*='google'])"):
                        h = lel.attrib.get("href", "")
                        if h and "google" not in h and "gstatic" not in h:
                            website = h
                            break
                    out.append(Contractor(
                        trade=trade, name=name, phone=phone,
                        website=website, address=address, source="Google",
                    ))

            # Strategy 2: JSON in page scripts (fallback)
            if not out:
                for s in page.css("script"):
                    txt = s.text or ""
                    matches = re.findall(
                        r'"([A-Z][A-Za-z\s&\.]{5,50}'
                        r'(?:HVAC|Electric|Heating|Cooling|Excavat|Grading|Plumb)'
                        r'[A-Za-z\s&\.]{0,30})"', txt
                    )
                    for m in matches[:limit]:
                        if m not in [c.name for c in out]:
                            out.append(Contractor(trade=trade, name=m, source="Google"))
                    if out:
                        break

    except Exception as e:
        logger.error(f"[Google] Session error: {type(e).__name__}: {e}")

    logger.info(f"[Google] {trade}: {len(out)} results")
    return out[:limit]
