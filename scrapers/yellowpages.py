from __future__ import annotations

import logging
import time
from urllib.parse import quote_plus

from compat import HAS_SCRAPLING, Adaptor, StealthySession
from constants import PHONE_RE, TRADE_KW
from models import Contractor

logger = logging.getLogger("ContractorFinder")


def scrape_yellowpages(trade: str, location: str, limit: int) -> list[Contractor]:
    """
    Uses ONE persistent StealthySession browser for all YP pages.
    Retries up to 3 times on Cloudflare blocks.
    """
    out: list[Contractor] = []
    term = TRADE_KW[trade]["yp"]
    loc = quote_plus(location)
    if not HAS_SCRAPLING:
        return out

    def _is_cloudflare(html) -> bool:
        if not html:
            return True
        if isinstance(html, bytes):
            html = html.decode("utf-8", errors="ignore")
        return (
            "cf-browser-verification" in html or "Checking your browser" in html or len(html) < 500
        )

    for attempt in range(3):
        out = []
        try:
            with StealthySession(
                headless=True, network_idle=True, disable_resources=False
            ) as session:
                for pg in range(1, 6):
                    if len(out) >= limit:
                        break
                    url = (
                        f"https://www.yellowpages.com/search"
                        f"?search_terms={term}&geo_location_terms={loc}&page={pg}"
                    )
                    try:
                        resp = session.fetch(url, wait=4000)
                        html = resp.body or ""
                    except Exception as e:
                        logger.info(f"[YP] page {pg} error: {type(e).__name__}")
                        break
                    if not html or _is_cloudflare(html):
                        logger.info(f"[YP] Cloudflare on page {pg}, attempt {attempt+1}/3")
                        time.sleep(3 + attempt * 2)
                        break
                    page = Adaptor(html)
                    cards = (
                        page.css("div.srp-listing")
                        or page.css("div.result")
                        or page.css("div[class*='listing']")
                        or page.css("article")
                    )
                    if not cards:
                        logger.info(f"[YP] No cards on page {pg} (status {resp.status})")
                        break
                    found = 0
                    for card in cards:
                        if len(out) >= limit:
                            break
                        name = ""
                        for sel in [
                            "h2.n a",
                            "a.business-name",
                            "h2 a",
                            ".business-name span",
                            "a[class*='business'] span",
                            "h3 a",
                        ]:
                            els = card.css(sel)
                            if els:
                                name = els[0].text.strip()
                                if name:
                                    break
                        if not name or len(name) < 2:
                            continue
                        phone = ""
                        for sel in [
                            "div.phones.phone.primary",
                            "div.phones",
                            ".phone",
                            "[class*='phone']",
                        ]:
                            els = card.css(sel)
                            if els:
                                phone = els[0].text.strip()
                                break
                        if not phone:
                            m = PHONE_RE.search(card.get_all_text(separator=" "))
                            if m:
                                phone = m.group(1)
                        website = ""
                        for sel in [
                            "a.track-visit-website",
                            "a[class*='website']",
                            "a[href^='http']:not([href*='yellowpages'])",
                        ]:
                            els = card.css(sel)
                            if els:
                                h = els[0].attrib.get("href", "")
                                if h.startswith("http") and "yellowpages" not in h:
                                    website = h
                                    break
                        address = ""
                        for sel in ["p.adr", "address", ".address", "[class*='address']"]:
                            els = card.css(sel)
                            if els:
                                address = els[0].get_all_text(separator=" ").strip()
                                break
                        out.append(
                            Contractor(
                                trade=trade,
                                name=name,
                                phone=phone,
                                website=website,
                                address=address,
                                source="YellowPages",
                            )
                        )
                        found += 1
                    logger.info(f"[YP] page {pg}: {found} found (total {len(out)})")
                    if found == 0:
                        break
                    time.sleep(1.5)
        except Exception as e:
            logger.info(f"[YP] Session error attempt {attempt+1}: {type(e).__name__}: {e}")
            time.sleep(2)
            continue
        if out:
            break
        logger.info(f"[YP] Attempt {attempt+1} got 0 results, retrying...")
        time.sleep(3)

    logger.info(f"[YP] {trade}: {len(out)} total")
    return out[:limit]
