from __future__ import annotations
import json, re, time
import logging
from dataclasses import asdict
from urllib.parse import quote_plus, unquote, urlparse, parse_qs

from constants import TRADE_KW, PHONE_RE, SCRAPE_SKIP
from compat import HAS_SCRAPLING, StealthySession, Adaptor
from cache import CACHE
from proxy import PROXY_MGR
from http_client import http_get
from extractor import extract_contacts, _parse_phone
from models import Contractor

logger = logging.getLogger("ContractorFinder")

# Names that look like article/listicle titles rather than real business names
_LISTICLE_RE = re.compile(
    r'(?:'
    r'^\d+\s+best\b'           # "10 Best HVAC..."
    r'|^the\s+\d+\b'           # "The 10 Best..."
    r'|^top[\s\-]rated\b'      # "Top-Rated HVAC..."
    r'|^top\s+\d+\b'           # "Top 10..."
    r'|^best\s+\w'             # "Best HVAC..."
    r'|\bcontractors\s+in\b'   # "...Contractors in Warren..."
    r'|\bcompanies\s+in\b'     # "...Companies in..."
    r'|\bservices\s+in\b'      # "...Services in Warren..."
    r'|\bexperts\s+in\b'       # "...Experts in..."
    r'|\bproviders\s+in\b'     # "...Providers in..."
    r')',
    re.I
)


def _is_listicle_name(name: str) -> bool:
    return bool(_LISTICLE_RE.search(name))


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
        if not name or not biz_url or _is_listicle_name(name):
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

def _yelp_search_fetcher(term: str, loc: str, limit: int) -> list[dict]:
    """
    Phase 1: Try Yelp search via curl_cffi (Fetcher).
    curl_cffi has a different TLS/JA3 fingerprint than Playwright and often
    bypasses Yelp's bot detection where a headless browser gets 403'd.
    """
    results: list[dict] = []
    for offset in range(0, min(limit, 60), 10):
        if len(results) >= limit:
            break
        url  = f"https://www.yelp.com/search?find_desc={term}&find_loc={loc}&start={offset}"
        html = http_get(url, timeout=12)
        if not html or len(html) < 500:
            logger.debug(f"[Yelp/curl] empty at offset {offset}")
            break
        batch = _parse_next_data(html)
        if not batch:
            logger.debug(f"[Yelp/curl] no __NEXT_DATA__ at offset {offset}")
            break
        results.extend(batch)
        logger.info(f"[Yelp/curl] offset {offset}: {len(batch)} found (total {len(results)})")
        if len(batch) < 5:
            break
        time.sleep(1.5)
    return results


def _yelp_search_session(term: str, loc: str, limit: int) -> list[dict]:
    """
    Phase 2: Try Yelp search via StealthySession (full Patchright browser).
    Used only when curl_cffi Phase 1 returned nothing.
    """
    if not HAS_SCRAPLING:
        return []
    results: list[dict] = []
    try:
        proxy_url = PROXY_MGR.get() if PROXY_MGR.ready else None
        sk: dict  = {"headless": True, "network_idle": True, "disable_resources": False}
        if proxy_url:
            sk["proxy"] = proxy_url

        with StealthySession(**sk) as session:
            for offset in range(0, min(limit, 60), 10):
                if len(results) >= limit:
                    break
                url = (f"https://www.yelp.com/search"
                       f"?find_desc={term}&find_loc={loc}&start={offset}")
                try:
                    resp   = session.fetch(url, wait=6000)
                    status = getattr(resp, "status", 200) or 200
                    html   = resp.body or b""
                    if isinstance(html, bytes):
                        html = html.decode("utf-8", errors="ignore")
                except Exception as e:
                    logger.warning(f"[Yelp/session] offset {offset}: {type(e).__name__}")
                    break
                if status in (403, 429) or not html or len(html) < 500:
                    logger.warning(f"[Yelp/session] HTTP {status} / empty at offset {offset}")
                    break
                batch = _parse_next_data(html) or _parse_html_cards(html, limit)
                if not batch:
                    logger.info(f"[Yelp/session] no results at offset {offset}")
                    break
                results.extend(batch)
                logger.info(
                    f"[Yelp/session] offset {offset}: {len(batch)} found "
                    f"(total {len(results)})"
                )
                if len(batch) < 5:
                    break
                time.sleep(2.0)
    except Exception as e:
        logger.error(f"[Yelp/session] error: {type(e).__name__}: {e}")
    return results


def _yelp_ddg_fallback(kw: str, city_raw: str, state: str, limit: int) -> list[dict]:
    """
    Phase 3: DDG fallback when both curl_cffi and StealthySession are blocked.

    Three strategies in one pass over DDG results:
      A) yelp.com/biz/ URL  → add to biz list; Pass 2 fetches phone + website
      B) yelp.com/* URL     → SKIP (also 403'd, proven in logs)
      C) contractor website → use DDG title as name + URL as website directly;
                              no Yelp biz page needed, enricher fills phone/email
    """
    from scrapers.ddg import ddg_search
    from constants import SKIP_DOMAINS

    results: list[dict] = []
    seen:    set[str]   = set()

    queries = [
        quote_plus(f"{kw} contractor {city_raw} {state}"),
        quote_plus(f"{kw} company {city_raw} {state}"),
        quote_plus(f"{kw} {city_raw} {state}"),
    ]

    for q in queries:
        if len(results) >= limit:
            break
        for title, url, snippet in ddg_search(q, pages=2):
            if len(results) >= limit:
                break
            if url in seen:
                continue

            # Strategy A: individual Yelp business page
            if "yelp.com/biz/" in url:
                seen.add(url)
                slug = url.split("/biz/")[-1].split("?")[0]
                name = re.sub(
                    rf"-{re.escape(city_raw.lower().replace(' ', '-'))}$",
                    "", slug, flags=re.I,
                ).replace("-", " ").title()
                results.append({"name": name, "biz_url": url,
                                "phone": "", "address": "", "website": ""})
                continue

            # Strategy B: any other Yelp URL — skip, they're also 403'd
            if "yelp.com" in url:
                continue

            # Strategy C: contractor website from DDG result
            if not url.startswith("http"):
                continue
            if any(d in url for d in SKIP_DOMAINS):
                continue
            seen.add(url)
            # Clean title → business name
            name = title
            for sep in (" - ", " | ", " – ", " — ", " :: ", " » "):
                if sep in name:
                    name = name.split(sep)[0]
                    break
            name = name.strip()
            if not name or len(name) < 3 or _is_listicle_name(name):
                continue
            # Phone from snippet
            phone = ""
            pm = PHONE_RE.search(snippet or "")
            if pm:
                phone = pm.group(1)
            results.append({"name": name, "biz_url": "",
                            "phone": phone, "address": "", "website": url})

    if results:
        from_yelp = sum(1 for r in results if r["biz_url"])
        from_web  = len(results) - from_yelp
        logger.info(
            f"[Yelp/DDG] fallback: {len(results)} total "
            f"({from_yelp} Yelp biz pages, {from_web} contractor websites)"
        )
    return results


def scrape_yelp(trade: str, location: str, limit: int) -> list[Contractor]:
    """
    Three-phase Yelp scraper:
      Phase 1 — curl_cffi (Fetcher)   → __NEXT_DATA__ JSON  [fastest, different fingerprint]
      Phase 2 — StealthySession       → __NEXT_DATA__ + CSS  [full browser, slower]
      Phase 3 — DDG fallback          → biz URLs + Yelp search re-fetch via curl_cffi

    Biz page enrichment (phone + website) always uses http_get (curl_cffi),
    never the StealthySession — individual /biz/ pages are less aggressively
    blocked, and http_get avoids reusing a session that Yelp already flagged.
    """
    keyword  = TRADE_KW[trade]["yelp"]
    city_raw = location.split(",")[0].strip()
    # Extract 2-letter state code from the location string (e.g. "Warren, MI 48091" → "MI")
    # Old code used "mi" in location which matched "Miami, FL" and returned wrong state.
    _state_m = re.search(r'\b([A-Z]{2})\b', location.upper())
    state    = _state_m.group(1) if _state_m else location.split(",")[-1].strip()[:2].upper()

    cache_key = f"yelp_{trade}_{city_raw}".lower()
    cached    = CACHE.get_ddg(cache_key)
    if cached:
        logger.info(f"[Yelp] {trade}: {len(cached)} from cache")
        return [Contractor(**r) for r in cached if isinstance(r, dict)][:limit]

    term = quote_plus(keyword)
    loc  = quote_plus(f"{city_raw}, {state}")

    # ── Phase 1: curl_cffi ────────────────────────────────────────────────────
    raw_businesses = _yelp_search_fetcher(term, loc, limit)

    # ── Phase 2: StealthySession ──────────────────────────────────────────────
    if not raw_businesses:
        logger.info("[Yelp] curl_cffi got nothing — trying StealthySession")
        raw_businesses = _yelp_search_session(term, loc, limit)

    # ── Phase 3: DDG fallback ─────────────────────────────────────────────────
    if not raw_businesses:
        logger.info("[Yelp] StealthySession got nothing — trying DDG fallback")
        raw_businesses = _yelp_ddg_fallback(keyword, city_raw, state, limit)

    # ── Biz page enrichment (http_get — not the blocked session) ─────────────
    out: list[Contractor] = []
    seen_names: set[str]  = set()
    for biz in raw_businesses[:limit]:
        name = biz.get("name", "").strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        phone   = biz.get("phone", "")
        website = biz.get("website", "")   # may already be set by DDG Strategy C

        biz_url = biz.get("biz_url", "")
        if biz_url:
            # Yelp /biz/ page — fetch for phone + real website
            biz_html = http_get(biz_url, timeout=8)
            if biz_html and len(biz_html) > 500:
                bp, bw = _extract_biz_page(biz_html)
                if not phone and bp:
                    phone = bp
                if not website and bw:
                    website = bw
            logger.debug(
                f"[Yelp/biz] {name[:30]} → phone={bool(phone)} website={bool(website)}"
            )
            time.sleep(0.8)
        out.append(Contractor(
            trade=trade, name=name, phone=phone,
            website=website, address=biz.get("address", ""),
            source="Yelp",
        ))

    out = out[:limit]
    if out:
        CACHE.set_ddg(cache_key, [asdict(c) for c in out])
    logger.info(f"[Yelp] {trade}: {len(out)} total")
    return out
