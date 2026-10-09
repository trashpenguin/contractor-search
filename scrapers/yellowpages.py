from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus

from compat import HAS_SCRAPLING, Adaptor, StealthySession
from constants import PHONE_RE, TRADE_KW
from http_client import SearchCancelled, check_cancelled, interruptible_sleep
from models import Contractor

logger = logging.getLogger("ContractorFinder")


def _parse_yp_nextdata(html: str) -> list[Contractor]:
    """Extract listings from embedded __NEXT_DATA__ JSON (YP Next.js pages)."""
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>\s*(\{.*?\})\s*</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except SearchCancelled:
        raise
    except Exception:
        return []

    # Walk several possible paths YP uses in pageProps
    pp = data.get("props", {}).get("pageProps", {})
    listings_raw = (
        pp.get("listings")
        or pp.get("searchResults", {}).get("listings")
        or pp.get("results")
        or pp.get("businesses")
        or []
    )
    if not listings_raw:
        return []

    out: list[Contractor] = []
    for biz in listings_raw:
        if not isinstance(biz, dict):
            continue
        name = biz.get("businessName") or biz.get("name") or biz.get("business_name") or ""
        if not name or len(name) < 2:
            continue
        phone = biz.get("phone") or biz.get("phoneNumber") or biz.get("primaryPhone") or ""
        website = biz.get("website") or biz.get("websiteUrl") or biz.get("url") or ""
        if website and "yellowpages" in website:
            website = ""
        addr_obj = biz.get("address") or biz.get("location") or {}
        if isinstance(addr_obj, dict):
            parts = [
                addr_obj.get("street") or addr_obj.get("streetAddress") or "",
                addr_obj.get("city") or "",
                addr_obj.get("state") or addr_obj.get("stateCode") or "",
                addr_obj.get("zip") or addr_obj.get("postalCode") or "",
            ]
            address = ", ".join(p for p in parts if p)
        else:
            address = str(addr_obj) if addr_obj else ""
        out.append(
            Contractor(
                trade="",
                name=name,
                phone=phone,
                website=website,
                address=address,
                source="YellowPages",
            )
        )
    logger.info(f"[YP] __NEXT_DATA__: {len(out)} listings")
    return out


def scrape_yellowpages(trade: str, location: str, limit: int) -> list[Contractor]:
    """
    Uses ONE persistent StealthySession browser for all YP pages.
    Retries up to 3 times on Cloudflare blocks.
    Tries __NEXT_DATA__ JSON extraction first, falls back to CSS selectors.
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
        if len(html) < 500:
            return True
        cf_markers = (
            "cf-browser-verification",
            "Checking your browser",
            "Just a moment",
            "Enable JavaScript and cookies",
            "DDoS protection by Cloudflare",
            "cf_chl_opt",
            "challenge-platform",
        )
        return any(m in html for m in cf_markers)

    for attempt in range(3):
        out = []
        try:
            with StealthySession(
                headless=True, network_idle=True, disable_resources=False
            ) as session:
                # Warm-up: hit YP homepage first so Cloudflare JS challenge
                # can complete and set cookies before we touch the search page.
                try:
                    session.fetch("https://www.yellowpages.com/", wait=5000)
                    interruptible_sleep(2)
                except SearchCancelled:
                    raise
                except Exception:
                    pass

                for pg in range(1, 6):
                    if len(out) >= limit:
                        break
                    # Page 1: no &page param (matches natural browser URL)
                    page_param = f"&page={pg}" if pg > 1 else ""
                    url = (
                        f"https://www.yellowpages.com/search"
                        f"?search_terms={term}&geo_location_terms={loc}{page_param}"
                    )
                    try:
                        resp = session.fetch(url, wait=8000)
                        html = resp.body or ""
                    except SearchCancelled:
                        raise
                    except Exception as e:
                        logger.info(f"[YP] page {pg} error: {type(e).__name__}")
                        break
                    if isinstance(html, bytes):
                        html = html.decode("utf-8", errors="ignore")
                    if (
                        resp.status in (403, 429, 503, 530)
                        or not html
                        or _is_cloudflare(html)
                        or len(html) < 30_000
                    ):
                        logger.info(
                            f"[YP] Blocked on page {pg} "
                            f"(status {resp.status}, len={len(html)}), attempt {attempt+1}/3"
                        )
                        interruptible_sleep(15 + attempt * 10)
                        break

                    # --- Try JSON extraction first ---
                    json_results = _parse_yp_nextdata(html)
                    if json_results:
                        for c in json_results:
                            if len(out) >= limit:
                                break
                            c.trade = trade
                            out.append(c)
                        logger.info(
                            f"[YP] page {pg}: {len(json_results)} from JSON (total {len(out)})"
                        )
                        interruptible_sleep(1.5)
                        continue

                    # --- CSS selector fallback ---
                    page = Adaptor(html)
                    cards = (
                        page.css("div.srp-listing")
                        or page.css("div.result")
                        or page.css("div[class*='srp-listing']")
                        or page.css("div[class*='listing-content']")
                        or page.css("div[class*='listing']")
                        or page.css("li[class*='result']")
                        or page.css("div[class*='business-result']")
                        or page.css("[data-listing-id]")
                        or page.css("[data-analytics*='listing']")
                        or page.css("[data-analytics*='business']")
                        or page.css("article")
                        or page.css("section.result")
                    )
                    if not cards:
                        snippet = html[:1500].replace("\n", " ").strip()
                        logger.info(
                            f"[YP] No cards on page {pg} (status {resp.status}, "
                            f"html_len={len(html)}, snippet={snippet!r})"
                        )
                        break
                    found = 0
                    for card in cards:
                        if len(out) >= limit:
                            break
                        name = ""
                        profile_url = ""
                        for sel in [
                            "h2.n a",
                            "a.business-name",
                            "h2 a",
                            ".business-name span",
                            "a[class*='business'] span",
                            "h3 a",
                            "h2",
                            "h3",
                        ]:
                            els = card.css(sel)
                            if els:
                                name = els[0].text.strip()
                                href = els[0].attrib.get("href", "")
                                if href and "yellowpages.com" in href:
                                    profile_url = (
                                        href
                                        if href.startswith("http")
                                        else f"https://www.yellowpages.com{href}"
                                    )
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
                        c = Contractor(
                            trade=trade,
                            name=name,
                            phone=phone,
                            website=website,
                            address=address,
                            source="YellowPages",
                        )
                        c._yp_profile_url = profile_url  # type: ignore[attr-defined]
                        out.append(c)
                        found += 1
                    logger.info(f"[YP] page {pg}: {found} found (total {len(out)})")
                    if found == 0:
                        break
                    interruptible_sleep(1.5)
                # Fetch individual profile pages for any result still missing a phone
                for contractor in out:
                    _pu = getattr(contractor, "_yp_profile_url", "")
                    if _pu and not contractor.phone:
                        try:
                            resp2 = session.fetch(_pu, wait=3000)
                            html2 = resp2.body or ""
                            if html2 and not _is_cloudflare(html2):
                                m = PHONE_RE.search(Adaptor(html2).get_all_text(separator=" "))
                                if m:
                                    contractor.phone = m.group(1)
                        except SearchCancelled:
                            raise
                        except Exception:
                            pass
                        interruptible_sleep(0.5)
        except SearchCancelled:
            raise
        except Exception as e:
            logger.info(f"[YP] Session error attempt {attempt+1}: {type(e).__name__}: {e}")
            interruptible_sleep(2)
            continue
        if out:
            break
        logger.info(f"[YP] Attempt {attempt+1} got 0 results, retrying...")
        interruptible_sleep(3)

    logger.info(f"[YP] {trade}: {len(out)} total")
    return out[:limit]
