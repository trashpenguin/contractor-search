from __future__ import annotations
import json, re, time
import logging
from dataclasses import asdict
from urllib.parse import quote_plus, unquote, urlparse, parse_qs

from constants import TRADE_KW, PHONE_RE, SCRAPE_SKIP
from compat import HAS_SCRAPLING, StealthySession, Adaptor
from cache import CACHE
from proxy import PROXY_MGR
from extractor import extract_contacts, _parse_phone
from models import Contractor

logger = logging.getLogger("ContractorFinder")


# ── __NEXT_DATA__ parser ──────────────────────────────────────────────────────

def _parse_next_data(html: str) -> list[dict]:
    """
    Yelp is a Next.js app — every page embeds all its data as JSON in:
      <script id="__NEXT_DATA__" type="application/json">{ ... }</script>
    This is far more stable than hashed CSS class names which break on deploys.
    Returns a list of raw business dicts with at least 'name' and 'businessUrl'.
    """
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:
        return []

    # Try known paths first, then fall back to recursive search
    businesses = (
        _try_path(data, ["props", "pageProps", "searchPageProps",
                         "mainContentComponentsListProps"])
        or _try_path(data, ["props", "pageProps", "searchPageProps", "businessList"])
        or _try_path(data, ["props", "pageProps", "businessList"])
        or _recursive_find_businesses(data)
    )

    out = []
    for item in (businesses or []):
        # Items are sometimes wrapped in a searchResultBusiness key
        biz = item.get("searchResultBusiness") or item
        if not isinstance(biz, dict):
            continue
        name = biz.get("name", "").strip()
        biz_url = biz.get("businessUrl") or biz.get("url") or biz.get("href", "")
        if not name or not biz_url:
            continue
        out.append({
            "name":     name,
            "biz_url":  biz_url if biz_url.startswith("http") else f"https://www.yelp.com{biz_url}",
            "phone":    biz.get("displayPhone") or biz.get("phone", ""),
            "address":  biz.get("formattedAddress") or biz.get("address", ""),
        })
    return out


def _try_path(data: dict, keys: list) -> list | None:
    """Walk a dot-path into nested dicts/lists, return None if any step misses."""
    node = data
    for k in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(k)
        if node is None:
            return None
    return node if isinstance(node, list) else None


def _recursive_find_businesses(node, depth: int = 0) -> list | None:
    """
    Last-resort recursive search for a list that looks like Yelp businesses
    (each item has both 'name' and 'businessUrl').
    """
    if depth > 10:
        return None
    if isinstance(node, list) and len(node) >= 2:
        sample = node[0] if isinstance(node[0], dict) else {}
        inner  = sample.get("searchResultBusiness", sample)
        if isinstance(inner, dict) and inner.get("name") and (
            inner.get("businessUrl") or inner.get("url")
        ):
            return node
    if isinstance(node, dict):
        for v in node.values():
            result = _recursive_find_businesses(v, depth + 1)
            if result:
                return result
    elif isinstance(node, list):
        for item in node:
            result = _recursive_find_businesses(item, depth + 1)
            if result:
                return result
    return None


# ── HTML card fallback (CSS selectors — used when __NEXT_DATA__ fails) ────────

def _parse_html_cards(html: str, limit: int) -> list[dict]:
    """
    Fallback CSS selector parsing. Less reliable than __NEXT_DATA__ but covers
    edge cases where Yelp A/B tests a non-Next.js render.
    """
    if not HAS_SCRAPLING or not html or len(html) < 500:
        return []
    page  = Adaptor(html)
    cards = (
        page.css("li[class*='businessList']")
        or page.css("div[data-testid*='serp']")
        or page.css("ul > li[class*='css-']")
        or page.css("div[class*='container__']")
    )
    out  = []
    seen = set()
    for card in cards:
        if len(out) >= limit:
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

        # Try to get the Yelp business URL from the card link
        biz_url = ""
        for el in card.css("a[href*='/biz/']"):
            href = el.attrib.get("href", "")
            if "/biz/" in href:
                biz_url = href if href.startswith("http") else f"https://www.yelp.com{href}"
                break

        phone = ""
        m = PHONE_RE.search(card.get_all_text(separator=" "))
        if m:
            phone = m.group(1)

        address = ""
        for sel in ["address", "p[class*='css-qgunke']",
                    "[class*='secondaryAttributes'] address"]:
            els = card.css(sel)
            if els:
                address = els[0].get_all_text(separator=" ").strip()[:100]
                break

        out.append({"name": name, "biz_url": biz_url, "phone": phone, "address": address})
    return out


# ── Individual business page ──────────────────────────────────────────────────

def _extract_biz_page(html: str) -> tuple[str, str]:
    """
    Extract phone + real website URL from a Yelp individual business page.

    Phone: JSON-LD schema.org telephone (most reliable, included for SEO).
    Website: JSON-LD url field or biz_redir link (Yelp wraps outbound links).
    """
    phone = website = ""

    # JSON-LD — most stable source on biz pages
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        try:
            data  = json.loads(match.group(1))
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not phone:
                    raw = item.get("telephone") or item.get("phone", "")
                    if raw:
                        phone = _parse_phone(str(raw)) or str(raw)[:20]
                if not website:
                    raw_url = item.get("url") or item.get("sameAs", "")
                    if (isinstance(raw_url, str)
                            and raw_url.startswith("http")
                            and "yelp.com" not in raw_url):
                        website = raw_url
            if phone and website:
                break
        except Exception:
            pass

    if HAS_SCRAPLING and html:
        page = Adaptor(html)

        # Phone fallback: tel: links
        if not phone:
            for el in page.css("a[href*='tel:']"):
                href = el.attrib.get("href", "")
                if "tel:" in href:
                    p = _parse_phone(href.split("tel:")[-1])
                    if p:
                        phone = p
                        break

        # Phone fallback: regex on visible text
        if not phone:
            m = PHONE_RE.search(page.get_all_text(separator=" "))
            if m:
                phone = m.group(1)

        # Website fallback: biz_redir outbound links
        if not website:
            for el in page.css("a[href*='biz_redir']"):
                href = el.attrib.get("href", "")
                if not href:
                    continue
                try:
                    qs   = parse_qs(urlparse(href).query)
                    real = unquote(qs.get("url", [""])[0])
                    if real.startswith("http") and not any(d in real for d in SCRAPE_SKIP):
                        website = real
                        break
                except Exception:
                    pass

        # Website last resort: any external link on the page
        if not website:
            for el in page.css("a[href^='http']:not([href*='yelp.com'])"):
                href = el.attrib.get("href", "")
                if href and "yelp" not in href and not any(d in href for d in SCRAPE_SKIP):
                    website = href
                    break

    return phone, website


# ── Main scraper ──────────────────────────────────────────────────────────────

def scrape_yelp(trade: str, location: str, limit: int) -> list[Contractor]:
    """
    Two-pass Yelp scraper:
      Pass 1 — search results page  → __NEXT_DATA__ JSON → business list + Yelp URLs
      Pass 2 — each /biz/<slug> page → JSON-LD          → phone + website

    Email is NOT on Yelp; it comes from website scraping in the enricher.
    """
    if not HAS_SCRAPLING:
        return []

    keyword  = TRADE_KW[trade]["yelp"]
    city_raw = location.split(",")[0].strip()
    state    = (
        "MI" if "mi" in location.lower()
        else location.split(",")[-1].strip()[:2].upper()
    )

    cache_key = f"yelp_{trade}_{city_raw}".lower()
    cached    = CACHE.get_ddg(cache_key)
    if cached:
        logger.info(f"[Yelp] {trade}: {len(cached)} from cache")
        return [Contractor(**r) for r in cached if isinstance(r, dict)][:limit]

    term = quote_plus(keyword)
    loc  = quote_plus(f"{city_raw}, {state}")
    raw_businesses: list[dict] = []
    out: list[Contractor] = []

    try:
        proxy_url = PROXY_MGR.get() if PROXY_MGR.ready else None
        session_kwargs: dict = {"headless": True, "network_idle": True, "disable_resources": False}
        if proxy_url:
            session_kwargs["proxy"] = proxy_url

        with StealthySession(**session_kwargs) as session:

            # ── Pass 1: collect business list ─────────────────────────────────
            blocked = False
            for offset in range(0, min(limit, 90), 10):
                if len(raw_businesses) >= limit:
                    break
                search_url = (
                    f"https://www.yelp.com/search"
                    f"?find_desc={term}&find_loc={loc}&start={offset}"
                )
                try:
                    resp   = session.fetch(search_url, wait=5000)
                    status = getattr(resp, "status", 200) or 200
                    html   = (resp.body or b"")
                    if isinstance(html, bytes):
                        html = html.decode("utf-8", errors="ignore")
                    if status in (403, 429):
                        logger.warning(f"[Yelp] HTTP {status} at offset {offset} — blocked")
                        blocked = True
                        break
                except Exception as e:
                    logger.warning(f"[Yelp] search offset {offset}: {type(e).__name__}")
                    break

                if not html or len(html) < 500:
                    logger.warning(f"[Yelp] Empty/blocked at offset {offset}")
                    blocked = True
                    break

                # __NEXT_DATA__ first, CSS fallback
                batch = _parse_next_data(html)
                if not batch:
                    logger.debug(f"[Yelp] __NEXT_DATA__ missed at offset {offset}, using CSS")
                    batch = _parse_html_cards(html, limit)

                if not batch:
                    logger.info(f"[Yelp] No results at offset {offset} — stopping")
                    break

                raw_businesses.extend(batch)
                logger.info(
                    f"[Yelp] offset {offset}: {len(batch)} found "
                    f"(total {len(raw_businesses)})"
                )
                if len(batch) < 5:
                    break   # last page
                time.sleep(2.0)

            # ── DDG fallback: find Yelp biz URLs when search page is blocked ────
            if blocked and not raw_businesses:
                logger.info("[Yelp] Search blocked — falling back to DDG for Yelp biz URLs")
                from scrapers.ddg import ddg_search
                kw       = TRADE_KW[trade]["yelp"]
                q        = quote_plus(f"site:yelp.com/biz {kw} {city_raw} {state}")
                seen_ddg: set[str] = set()
                for _, biz_url, _ in ddg_search(q, pages=3):
                    if "yelp.com/biz/" not in biz_url or biz_url in seen_ddg:
                        continue
                    seen_ddg.add(biz_url)
                    slug = biz_url.split("/biz/")[-1].split("?")[0]
                    name = slug.replace("-", " ").title()
                    raw_businesses.append({"name": name, "biz_url": biz_url,
                                           "phone": "", "address": ""})
                if raw_businesses:
                    logger.info(f"[Yelp] DDG fallback: {len(raw_businesses)} Yelp URLs found")

            # ── Pass 2: visit each biz page for phone + website ───────────────
            seen_names: set[str] = set()
            for biz in raw_businesses[:limit]:
                name = biz.get("name", "").strip()
                if not name or name in seen_names:
                    continue
                seen_names.add(name)

                phone   = biz.get("phone", "")
                website = ""

                biz_url = biz.get("biz_url", "")
                if biz_url:
                    try:
                        resp = session.fetch(biz_url, wait=3000)
                        biz_html = resp.body or b""
                        if isinstance(biz_html, bytes):
                            biz_html = biz_html.decode("utf-8", errors="ignore")
                        bp, bw  = _extract_biz_page(biz_html)
                        if not phone and bp:
                            phone = bp
                        if bw:
                            website = bw
                        logger.debug(
                            f"[Yelp/biz] {name[:30]} → phone={bool(phone)} "
                            f"website={bool(website)}"
                        )
                    except Exception as e:
                        logger.debug(f"[Yelp/biz] {name[:30]}: {type(e).__name__}")
                    time.sleep(1.0)   # polite delay between biz page fetches

                out.append(Contractor(
                    trade=trade, name=name, phone=phone,
                    website=website, address=biz.get("address", ""),
                    source="Yelp",
                ))

    except Exception as e:
        logger.error(f"[Yelp] Session error: {type(e).__name__}: {e}")

    out = out[:limit]
    if out:
        CACHE.set_ddg(cache_key, [asdict(c) for c in out])
    logger.info(f"[Yelp] {trade}: {len(out)} total")
    return out
