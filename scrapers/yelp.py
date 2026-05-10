from __future__ import annotations
import time
import logging
from dataclasses import asdict
from urllib.parse import quote_plus, unquote, urlparse

from constants import TRADE_KW, PHONE_RE, SCRAPE_SKIP
from compat import HAS_SCRAPLING, StealthySession, Adaptor
from cache import CACHE
from extractor import _parse_phone
from models import Contractor

logger = logging.getLogger("ContractorFinder")


def _extract_yelp_website(page: "Adaptor") -> str:
    """
    Extract the real company website from a Yelp card.
    Yelp hides outbound links behind biz_redir redirects.
    """
    from urllib.parse import parse_qs
    for el in page.css("a[href*='biz_redir']"):
        href = el.attrib.get("href", "")
        if not href:
            continue
        try:
            qs   = parse_qs(urlparse(href).query)
            real = unquote(qs.get("url", [""])[0])
            if real.startswith("http") and not any(d in real for d in SCRAPE_SKIP):
                return real
        except Exception:
            pass
    for el in page.css("a[href^='http']:not([href*='yelp.com'])"):
        href = el.attrib.get("href", "")
        if href and "yelp" not in href:
            return href
    return ""


def scrape_yelp(trade: str, location: str, limit: int) -> list[Contractor]:
    """
    Uses ONE persistent StealthySession browser for all Yelp pages.
    Results cached for 24h.
    """
    out: list[Contractor] = []
    if not HAS_SCRAPLING:
        return out
    seen: set[str] = set()
    keyword  = TRADE_KW[trade]["yelp"]
    city_raw = location.split(",")[0].strip()
    state    = (
        "MI" if "mi" in location.lower()
        else location.split(",")[-1].strip()[:2].upper()
    )

    cache_key = f"yelp_{trade}_{city_raw}".lower()
    cached    = CACHE.get_ddg(cache_key)
    if cached:
        logger.info(f"[Yelp] {trade}: {len(cached)} results from cache")
        return [Contractor(**r) for r in cached if isinstance(r, dict)][:limit]

    def _parse_yelp_page(html: str) -> list[Contractor]:
        results = []
        if not html or len(html) < 500:
            return results
        page  = Adaptor(html)
        cards = (
            page.css("li[class*='businessList']")
            or page.css("div[data-testid*='serp']")
            or page.css("ul > li[class*='css-']")
            or page.css("div[class*='container__']")
        )
        for card in cards:
            if len(results) >= limit:
                break
            name = ""
            for sel in ["a[class*='businessName'] span", "h3 a span",
                        "span[class*='display-name']", "a[name] span", "h3 span"]:
                els = card.css(sel)
                if els:
                    name = els[0].text.strip()
                    if name and len(name) > 2:
                        break
            if not name or len(name) < 2 or name in seen:
                continue
            bad = ["Top ", "Best ", "Near ", "Yelp", "Results", "Reviews in", "Sponsored"]
            if any(w in name for w in bad):
                continue
            seen.add(name)

            phone = ""
            for sel in ["p[class*='css-1p9ibgf']", "[class*='secondaryAttributes'] p",
                        "span[class*='raw-css']", "p[class*='lemon']"]:
                els = card.css(sel)
                if els:
                    p = _parse_phone(els[0].text.strip())
                    if p:
                        phone = p
                        break
            if not phone:
                m = PHONE_RE.search(card.get_all_text(separator=" "))
                if m:
                    phone = m.group(1)

            website = _extract_yelp_website(card)

            address = ""
            for sel in ["address", "p[class*='css-qgunke']",
                        "[class*='secondaryAttributes'] address"]:
                els = card.css(sel)
                if els:
                    address = els[0].get_all_text(separator=" ").strip()[:100]
                    break

            results.append(Contractor(
                trade=trade, name=name, phone=phone,
                website=website, address=address, source="Yelp",
            ))
        return results

    term = quote_plus(keyword)
    loc  = quote_plus(f"{city_raw}, {state}")
    try:
        with StealthySession(headless=True, network_idle=True,
                             disable_resources=False) as session:
            for pg in range(0, min(limit, 90), 10):
                if len(out) >= limit:
                    break
                url = f"https://www.yelp.com/search?find_desc={term}&find_loc={loc}&start={pg}"
                try:
                    resp = session.fetch(url, wait=5000)
                    raw  = resp.body or b""
                    html = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
                except Exception as e:
                    logger.warning(f"[Yelp] page offset {pg} error: {type(e).__name__}")
                    break
                if not html or len(html) < 500:
                    logger.warning(f"[Yelp] Empty/blocked on offset {pg}")
                    break
                batch = _parse_yelp_page(html)
                if not batch:
                    logger.info(f"[Yelp] No cards at offset {pg} — stopping pagination")
                    break
                out.extend(batch)
                logger.info(f"[Yelp] offset {pg}: {len(batch)} found (total {len(out)})")
                if len(batch) < 5:
                    break
                time.sleep(2.0)
    except Exception as e:
        logger.error(f"[Yelp] Session error: {type(e).__name__}: {e}")

    out = out[:limit]
    if out:
        CACHE.set_ddg(cache_key, [asdict(c) for c in out])
    logger.info(f"[Yelp] {trade}: {len(out)} total")
    return out
