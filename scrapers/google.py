from __future__ import annotations
import json, re, time
import logging
from urllib.parse import quote_plus, unquote_plus

from constants import TRADE_KW, PHONE_RE, ADDR_RE
from compat import HAS_SCRAPLING, StealthySession, Adaptor
from models import Contractor

logger = logging.getLogger("ContractorFinder")

# ── APP_INITIALIZATION_STATE parser ──────────────────────────────────────────

def _parse_app_state(html: str) -> dict:
    """
    Google Maps embeds all listing data in window.APP_INITIALIZATION_STATE.
    Extract phones and external website URLs via regex on the raw text.
    Also attempt to pull business names by finding title-case strings
    that appear within 800 chars of a phone number in the blob.
    """
    m = re.search(r"APP_INITIALIZATION_STATE\s*=\s*(\[.{200,})", html, re.DOTALL)
    if not m:
        return {"names": [], "phones": [], "websites": []}
    chunk = m.group(1)[:1_000_000]   # cap at 1 MB

    phones = list(dict.fromkeys(re.findall(
        r'"(\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4})"', chunk
    )))

    skip_domains = {
        "google", "gstatic", "googleapis", "googleusercontent",
        "ggpht", "youtube", "facebook", "instagram", "twitter",
        "yelp", "yellowpages", "bbb.org", "schema.org",
    }
    websites: list[str] = []
    for raw in re.findall(r'"(https?://[^"]{10,300})"', chunk):
        if not any(d in raw for d in skip_domains) and raw not in websites:
            websites.append(raw)

    # Business name extraction: look for title-case strings near each phone
    names: list[str] = []
    seen_n: set[str] = set()
    phone_pat = re.compile(r'"\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}"')
    name_pat  = re.compile(
        r'"([A-Z][A-Za-z0-9&\'\.\s\-]{4,55})"'
    )
    for pm in phone_pat.finditer(chunk):
        window = chunk[max(0, pm.start() - 900): pm.start()]
        for nm in name_pat.finditer(window):
            candidate = nm.group(1).strip()
            # Filter out obvious non-names
            if (len(candidate) < 5 or len(candidate) > 60
                    or candidate in seen_n
                    or re.search(r"https?://|\\u|\\n|\d{4,}", candidate)
                    or candidate.isupper()):
                continue
            seen_n.add(candidate)
            names.append(candidate)

    return {"names": names, "phones": phones, "websites": websites}


# ── Place-link name extractor ─────────────────────────────────────────────────

def _names_from_place_links(page) -> list[str]:
    """
    Extract business names from Google Maps place URLs.
    /maps/place/Smith+Heating+%26+Cooling/@lat,lon,...
    Most deploy-stable selector — Google always encodes the business name
    in the URL even when all CSS class names change.
    """
    names: list[str] = []
    seen:  set[str]  = set()
    for el in page.css("a[href*='/maps/place/']"):
        href = el.attrib.get("href", "")
        m = re.search(r"/maps/place/([^@]{3,}?)(?:/@|/data=|$)", href)
        if not m:
            continue
        raw  = m.group(1)
        name = unquote_plus(raw).strip()
        # Strip leading/trailing noise
        name = re.sub(r"\s*\(\d+\)\s*$", "", name).strip()
        # Remove only a trailing city/state suffix like ", Warren, MI"
        name = re.sub(r",\s*[A-Z][a-z].*$", "", name).strip()
        if name and 3 <= len(name) <= 70 and name not in seen:
            seen.add(name)
            names.append(name)
    return names


# ── Feed-card extractor ───────────────────────────────────────────────────────

def _parse_feed(page, limit: int) -> list[dict]:
    """Parse div[role='feed'] cards using aria-label + place-link names."""
    out:  list[dict] = []
    seen: set[str]   = set()

    feed      = page.css("div[role='feed']")
    container = feed[0] if feed else page

    skip_words = {"search", "result", "map", "back", "menu", "list",
                  "view", "zoom", "more", "filter", "directions", "open",
                  "sponsored", "ad "}

    # Method A: aria-label on feed items
    for el in container.css("div[aria-label]"):
        if len(out) >= limit:
            break
        label = el.attrib.get("aria-label", "").strip()
        if not label or len(label) < 3:
            continue
        name = label.split("·")[0].split("\n")[0].strip()
        if not name or len(name) < 3 or name in seen:
            continue
        if any(w in name.lower() for w in skip_words):
            continue
        seen.add(name)

        txt   = el.get_all_text(separator="\n")
        phone = ""
        pm    = PHONE_RE.search(txt)
        if pm:
            phone = pm.group(1)

        address = ""
        am      = ADDR_RE.search(txt)
        if am:
            address = am.group(0).strip()

        website = ""
        for a in el.css("a[href^='http']:not([href*='google'])"):
            h = a.attrib.get("href", "")
            if h and "google" not in h and "gstatic" not in h:
                website = h
                break

        out.append({"name": name, "phone": phone,
                    "address": address, "website": website})

    # Method B: place-link URL names
    for name in _names_from_place_links(container if feed else page):
        if len(out) >= limit:
            break
        if name not in seen:
            seen.add(name)
            out.append({"name": name, "phone": "", "address": "", "website": ""})

    return out


# ── Scroll helper ─────────────────────────────────────────────────────────────

def _try_scroll(session, n: int = 8, wait_ms: int = 1000) -> str | None:
    """
    Attempt to scroll the Google Maps feed panel to trigger lazy-loading.
    Tries several attribute paths to find the Playwright page handle.
    Returns updated HTML string if successful, None if page handle unavailable.
    """
    _pg = None
    # Direct attributes
    for attr in ("_page", "page", "_browser_page", "_pw_page"):
        candidate = getattr(session, attr, None)
        if candidate and hasattr(candidate, "evaluate"):
            _pg = candidate
            break
    # One level of nesting (e.g. session._fetcher._page)
    if not _pg:
        for attr in ("_fetcher", "_browser", "_driver", "_context"):
            parent = getattr(session, attr, None)
            if not parent:
                continue
            for inner in ("_page", "page", "_browser_page"):
                candidate = getattr(parent, inner, None)
                if candidate and hasattr(candidate, "evaluate"):
                    _pg = candidate
                    break
            if _pg:
                break

    if not _pg:
        logger.debug("[Google] No Playwright page handle found — scroll skipped")
        return None

    scroll_js = (
        "(function(){"
        "  var f=document.querySelector('[role=\"feed\"]');"
        "  if(f){f.scrollBy(0,2500);return 'feed';}"
        "  window.scrollBy(0,2500); return 'window';"
        "})()"
    )
    try:
        for i in range(n):
            _pg.evaluate(scroll_js)
            _pg.wait_for_timeout(wait_ms)
        html = _pg.content()
        logger.debug(f"[Google] Scrolled {n}x, re-captured HTML ({len(html)} bytes)")
        return html
    except Exception as e:
        logger.debug(f"[Google] Scroll failed: {e}")
        return None


# ── Main scraper ──────────────────────────────────────────────────────────────

def scrape_google(trade: str, location: str, limit: int,
                  lat: float | None = None, lon: float | None = None) -> list[Contractor]:
    """
    Google Maps scraper.

    URL: uses lat/lon from the geocoder (passed from search.py) to anchor
    the map at zoom-12 city level.  Without coordinates Google Maps
    centres on a global default (zoom 3, Pacific Ocean) which returns
    far fewer local results.

    Three extraction layers:
      1. APP_INITIALIZATION_STATE JS blob — phones + websites + name candidates
      2. div[role='feed'] aria-label cards — names with card-level detail
      3. a[href*='/maps/place/'] links — names from stable place URLs

    Scroll: attempted via the Playwright page handle if accessible.
    """
    out: list[Contractor] = []
    if not HAS_SCRAPLING:
        return out

    term = quote_plus(f"{TRADE_KW[trade]['google']} near {location}")
    if lat and lon:
        # City-level zoom (12) centred on the geocoded coordinates
        url = f"https://www.google.com/maps/search/{term}/@{lat},{lon},12z?hl=en"
    else:
        url = f"https://www.google.com/maps/search/{term}?hl=en"

    try:
        with StealthySession(headless=True, network_idle=True,
                             disable_resources=False) as session:
            try:
                resp = session.fetch(url, wait=9000)
                raw  = resp.body or b""
                html = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
            except Exception as e:
                logger.warning(f"[Google] Load error: {type(e).__name__}")
                return out

            if not html:
                return out

            # ── Scroll to trigger IntersectionObserver lazy-loading ───────────
            scrolled = _try_scroll(session, n=8, wait_ms=1000)
            if scrolled:
                html = scrolled

            # ── Extract from APP_INITIALIZATION_STATE JS blob ─────────────────
            app_data    = _parse_app_state(html)
            js_names    = app_data["names"]
            js_phones   = app_data["phones"]
            js_websites = [w for w in app_data["websites"]
                           if not any(d in w for d in
                                      {"google", "gstatic", "yelp", "yellowpages"})]
            logger.debug(
                f"[Google] APP_STATE: {len(js_names)} name candidates, "
                f"{len(js_phones)} phones, {len(js_websites)} websites"
            )

            # ── Extract from feed cards + place links ─────────────────────────
            page    = Adaptor(html)
            entries = _parse_feed(page, limit)
            logger.info(f"[Google] {trade}: {len(entries)} entries from feed/place-links")

            # Supplement entries with JS blob data
            phone_pool   = list(js_phones)
            website_pool = list(js_websites)

            for i, entry in enumerate(entries[:limit]):
                phone   = entry.get("phone", "")
                website = entry.get("website", "")
                if not phone and i < len(phone_pool):
                    phone = phone_pool[i]
                if not website and website_pool:
                    website = website_pool.pop(0)
                out.append(Contractor(
                    trade=trade,
                    name=entry["name"],
                    phone=phone,
                    website=website,
                    address=entry.get("address", ""),
                    source="Google",
                ))

            # ── Fallback: JS blob name candidates if feed gave nothing ─────────
            if not out:
                seen_names = set()
                for name in js_names[:limit]:
                    if name in seen_names:
                        continue
                    seen_names.add(name)
                    p = phone_pool.pop(0) if phone_pool else ""
                    w = website_pool.pop(0) if website_pool else ""
                    out.append(Contractor(
                        trade=trade, name=name, phone=p,
                        website=w, source="Google",
                    ))

    except Exception as e:
        logger.error(f"[Google] Session error: {type(e).__name__}: {e}")

    logger.info(f"[Google] {trade}: {len(out)} results")
    return out[:limit]
