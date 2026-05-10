from __future__ import annotations
import json, re
import logging
from urllib.parse import quote_plus, unquote_plus

from constants import TRADE_KW, PHONE_RE, ADDR_RE
from compat import HAS_SCRAPLING, StealthySession, Adaptor
from models import Contractor

logger = logging.getLogger("ContractorFinder")

# ── APP_INITIALIZATION_STATE parser ──────────────────────────────────────────

def _parse_app_state(html: str) -> dict:
    """
    Google Maps embeds ALL listing data (names, phones, addresses, websites)
    in window.APP_INITIALIZATION_STATE as a large nested JS array.
    We extract phones and external website URLs from the raw text rather than
    trying to fully parse the complex structure (which changes frequently).
    """
    m = re.search(r"APP_INITIALIZATION_STATE\s*=\s*(\[.{200,})", html, re.DOTALL)
    if not m:
        return {"phones": [], "websites": []}
    chunk = m.group(1)[:800_000]   # cap at 800 KB

    phones = list(dict.fromkeys(re.findall(
        r'"(\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4})"', chunk
    )))

    skip_domains = {
        "google", "gstatic", "googleapis", "googleusercontent",
        "ggpht", "youtube", "facebook", "instagram", "twitter",
        "yelp", "yellowpages", "bbb.org",
    }
    websites: list[str] = []
    for raw in re.findall(r'"(https?://[^"]{10,300})"', chunk):
        if not any(d in raw for d in skip_domains) and raw not in websites:
            websites.append(raw)

    return {"phones": phones, "websites": websites}


# ── Place-link name extractor ─────────────────────────────────────────────────

def _names_from_place_links(page) -> list[str]:
    """
    Extract business names from Google Maps place URLs.
    /maps/place/Smith+Heating+%26+Cooling/@lat,lon,...
    This is the most deploy-stable selector — Google always encodes the
    business name in the URL even when all class names change.
    """
    names: list[str] = []
    seen: set[str]   = set()
    for el in page.css("a[href*='/maps/place/']"):
        href = el.attrib.get("href", "")
        m = re.search(r"/maps/place/([^/@+][^/@]*)", href)
        if not m:
            continue
        raw  = m.group(1).split("/@")[0]
        name = unquote_plus(raw).replace("+", " ").strip()
        # Strip trailing noise like "(2)" or ",+MI"
        name = re.sub(r"\s*\(\d+\)$", "", name)
        name = re.sub(r"[,+].*$", "", name).strip()
        if name and len(name) >= 3 and name not in seen:
            seen.add(name)
            names.append(name)
    return names


# ── Feed-card extractor ───────────────────────────────────────────────────────

def _parse_feed(page, limit: int) -> list[dict]:
    """
    Parse div[role='feed'] cards.  Uses aria-label for name (stable attribute),
    then supplements with phone/address/website from the card text and links.
    Falls back to place-link URL extraction when aria-label misses.
    """
    out: list[dict] = []
    seen: set[str]  = set()

    feed = page.css("div[role='feed']")
    container = feed[0] if feed else page

    # --- Method A: aria-label on feed items ---
    skip_words = {"search", "result", "map", "back", "menu", "list",
                  "view", "zoom", "more", "filter", "directions", "open"}
    for el in container.css("div[aria-label]"):
        if len(out) >= limit:
            break
        label = el.attrib.get("aria-label", "").strip()
        if not label or len(label) < 3:
            continue
        name = label.split("·")[0].split("\n")[0].strip()
        if any(w in name.lower() for w in skip_words) or len(name) < 3:
            continue
        if name in seen:
            continue
        seen.add(name)

        txt     = el.get_all_text(separator="\n")
        phone   = ""
        pm      = PHONE_RE.search(txt)
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

    # --- Method B: place-link URL names (catches what aria-label misses) ---
    place_names = _names_from_place_links(container if feed else page)
    for name in place_names:
        if len(out) >= limit:
            break
        if name not in seen:
            seen.add(name)
            out.append({"name": name, "phone": "", "address": "", "website": ""})

    return out


# ── Main scraper ──────────────────────────────────────────────────────────────

def scrape_google(trade: str, location: str, limit: int) -> list[Contractor]:
    """
    Google Maps scraper — three extraction strategies, most stable first:

    1. APP_INITIALIZATION_STATE JS blob  → phones + website URLs (always present)
    2. div[role='feed'] aria-label cards → names + card-level phone/address/website
    3. a[href*='/maps/place/'] links     → names from place URLs (deploy-stable)

    Scroll is attempted via session._page (Playwright page handle) to trigger
    IntersectionObserver lazy-loading.  Silently skipped if handle unavailable.
    """
    out: list[Contractor] = []
    if not HAS_SCRAPLING:
        return out

    term = quote_plus(f"{TRADE_KW[trade]['google']} near {location}")
    url  = f"https://www.google.com/maps/search/{term}?hl=en"

    try:
        with StealthySession(headless=True, network_idle=True,
                             disable_resources=False) as session:
            try:
                resp = session.fetch(url, wait=7000)
                raw  = resp.body or b""
                html = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
            except Exception as e:
                logger.warning(f"[Google] Load error: {type(e).__name__}")
                return out

            if not html:
                return out

            # ── Scroll to lazy-load more feed items ───────────────────────────
            try:
                _pg = None
                for attr in ("_page", "page", "_fetcher", "_browser_page"):
                    candidate = getattr(session, attr, None)
                    if candidate and hasattr(candidate, "evaluate"):
                        _pg = candidate
                        break
                    # one level deeper (e.g. session._fetcher._page)
                    if candidate:
                        inner = getattr(candidate, "_page", None)
                        if inner and hasattr(inner, "evaluate"):
                            _pg = inner
                            break

                if _pg:
                    for _ in range(8):
                        _pg.evaluate(
                            "(function(){"
                            "  var f=document.querySelector('[role=\"feed\"]');"
                            "  if(f) f.scrollBy(0,2000);"
                            "  else window.scrollBy(0,2000);"
                            "})()"
                        )
                        _pg.wait_for_timeout(1000)
                    html = _pg.content()
                    logger.debug("[Google] Scrolled feed, re-captured HTML")
                else:
                    logger.debug("[Google] No page handle — using initial HTML")
            except Exception as scroll_err:
                logger.debug(f"[Google] Scroll skipped: {scroll_err}")

            # ── Strategy 1: APP_INITIALIZATION_STATE JS blob ──────────────────
            app_data = _parse_app_state(html)
            js_phones   = app_data["phones"]
            js_websites = app_data["websites"]
            logger.debug(
                f"[Google] APP_STATE: {len(js_phones)} phones, "
                f"{len(js_websites)} websites extracted"
            )

            # ── Strategy 2 + 3: feed cards + place-link names ─────────────────
            page    = Adaptor(html)
            entries = _parse_feed(page, limit)

            logger.info(f"[Google] {trade}: {len(entries)} entries from feed/place-links")

            # Merge: assign JS phones/websites to entries that are missing them
            phone_pool   = list(js_phones)
            website_pool = [w for w in js_websites
                            if not any(d in w for d in
                                       {"google", "gstatic", "yelp", "yellowpages"})]

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

            # ── Fallback: name-only from place links if feed gave nothing ──────
            if not out:
                for name in _names_from_place_links(page)[:limit]:
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
