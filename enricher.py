from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote_plus, urljoin, urlparse

from cache import CACHE
from compat import HAS_AIOHTTP, HAS_SCRAPLING, Adaptor
from config import DDG_CAP, SEM_DDG, SEM_DEFAULT, SEM_GOOGLE, SEM_YELLOWPAGES
from constants import _FATAL_PROXY_ERRORS, SCRAPE_SKIP, SKIP_DOMAINS, TRADE_KW
from email_hunter import _ddg_email_hunt, _scan_js_for_email, _scan_sitemap_for_email, _whois_email
from extractor import _clean_email, _ok_email, extract_contacts, verify_email
from http_client import SearchCancelled, call_with_stop, http_get
from models import Contractor
from provenance import record_contact
from proxy import PROXY_MGR

logger = logging.getLogger("ContractorFinder")

_AIOHTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Deduplication helpers ─────────────────────────────────────────────────────


def _name_key(name: str) -> str:
    s = name.lower()
    for suf in [
        " llc",
        " inc",
        " co",
        " corp",
        " ltd",
        " services",
        " company",
        " heating",
        " cooling",
        " hvac",
        " electric",
        " plumbing",
        " excavating",
    ]:
        s = s.replace(suf, " ")
    return re.sub(r"[^a-z0-9]", "", s).strip()


def _similar(a: str, b: str) -> bool:
    ka, kb = _name_key(a), _name_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    short, long = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if len(short) >= 8 and short in long:
        return True
    match = sum(1 for x, y in zip(ka, kb) if x == y)
    min_len = min(len(ka), len(kb))
    return min_len >= 6 and match / min_len >= 0.85


def _domain_key(website: str) -> str:
    if not website:
        return ""
    try:
        p = urlparse(website)
        d = p.netloc.lower().replace("www.", "")
        return d.split(":")[0]
    except Exception:
        return ""


def _phone_key(phone: str) -> str:
    d = re.sub(r"[^0-9]", "", phone or "")
    return d[-10:] if len(d) >= 10 else ""


def _build_domain_candidates(clean_name: str, clean_city: str, trade_suffix: str = "") -> list[str]:
    """Return ordered list of domain URLs to probe for a contractor."""
    if len(clean_name) < 3:
        return []
    base = [
        f"https://www.{clean_name}.com",
        f"https://{clean_name}.com",
        f"https://www.{clean_name}{clean_city}.com",
        f"https://www.{clean_name}hvac.com",
        f"https://www.{clean_name}heating.com",
        f"https://www.{clean_name}electric.com",
        f"https://www.{clean_name}excavating.com",
        f"https://www.{clean_name}contracting.com",
        f"https://www.{clean_name}plumbing.com",
        f"https://www.{clean_name}roofing.com",
        # .net variants
        f"https://www.{clean_name}.net",
        f"https://{clean_name}.net",
        f"https://www.{clean_name}{clean_city}.net",
    ]
    if trade_suffix:
        base.insert(3, f"https://www.{clean_name}{trade_suffix}.com")
        base.insert(4, f"https://www.{clean_name}{trade_suffix}.net")
    return base


def _address_key(address: str) -> str:
    return re.sub(r"[^a-z0-9]", "", address.lower())


def _same_business(left: Contractor, right: Contractor) -> bool:
    lp, rp = _phone_key(left.phone), _phone_key(right.phone)
    la, ra = _address_key(left.address), _address_key(right.address)
    if lp and rp and lp != rp:
        return False
    if la and ra and la != ra:
        return False
    if left.place_id and left.place_id == right.place_id:
        return True
    phone_match = bool(lp and lp == rp)
    domain_match = bool(
        _domain_key(left.website) and _domain_key(left.website) == _domain_key(right.website)
    )
    address_match = bool(la and la == ra)
    exact_name = re.sub(r"[^a-z0-9]", "", left.name.lower()) == re.sub(
        r"[^a-z0-9]", "", right.name.lower()
    )
    return bool(
        phone_match
        or domain_match
        or (address_match and _similar(left.name, right.name))
        or (exact_name and left.name.strip())
    )


def dedup(rows: list[Contractor]) -> list[Contractor]:
    """Merge corroborated identities without discarding conflicting branches."""
    sorted_rows = sorted(rows, key=lambda r: -r.quality_score)
    out: list[Contractor] = []
    for row in sorted_rows:
        existing = next((item for item in out if _same_business(row, item)), None)
        if existing is None:
            out.append(row)
            continue
        for field in ("phone", "email", "website", "address"):
            if not getattr(existing, field) and getattr(row, field):
                setattr(existing, field, getattr(row, field))
                related = {
                    "email": ("email_method", "email_source_url", "email_status"),
                    "phone": ("phone_source_url",),
                    "website": ("website_method",),
                }.get(field, ())
                for key in related:
                    setattr(existing, key, getattr(row, key))
    return out


def website_matches(contractor: Contractor, html: str) -> bool:
    """Require a business name plus phone or location evidence before guessing."""
    text = re.sub(r"<[^>]*>", " ", html).lower()
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", contractor.name.lower())
        if word not in {"llc", "inc", "co", "corp", "company", "the", "and"}
    ]
    if not words or not all(word in text for word in words):
        return False
    _, phone = extract_contacts(html)
    if _phone_key(contractor.phone) and _phone_key(contractor.phone) == _phone_key(phone):
        return True
    address_words = re.findall(r"[a-z0-9]+", contractor.address.lower())
    return bool(
        any(word.isdigit() and word in text for word in address_words)
        and sum(word in text for word in address_words if len(word) >= 4) >= 2
    )


# ── Async website scraping ────────────────────────────────────────────────────


async def _fetch_one(session, url: str, timeout, use_proxy: bool = False) -> str:
    """
    Fetch one URL with the shared aiohttp session.
    Certificate validation remains enabled, including proxied connections.
    """
    proxy = PROXY_MGR.get_for(url) if (use_proxy and PROXY_MGR.ready) else None
    ssl_mode = True
    try:
        kwargs: dict = {"timeout": timeout, "ssl": ssl_mode, "allow_redirects": True}
        if proxy:
            kwargs["proxy"] = proxy
        async with session.get(url, **kwargs) as resp:
            if resp.status in (200, 201, 206):
                if proxy:
                    PROXY_MGR.report(proxy, True)
                return await resp.text(errors="ignore")
            if proxy:
                PROXY_MGR.report(proxy, resp.status == 200)
            return ""
    except Exception as e:
        err = str(e)
        if proxy:
            PROXY_MGR.report(proxy, False, err)
        if any(fe in err for fe in _FATAL_PROXY_ERRORS):
            return ""
        return ""


async def async_scrape_website(url: str, session, timeout, origins=None) -> tuple[str, str]:
    """
    Scrape a contractor website using the shared session.
    Checks homepage + up to 3 contact/about subpages.
    """
    if not url or any(s in url for s in SCRAPE_SKIP):
        return "", ""
    html = await _fetch_one(session, url, timeout)
    if not html:
        return "", ""
    email, phone = extract_contacts(html)
    if origins is not None:
        if email:
            origins["email_source_url"] = url
        if phone:
            origins["phone_source_url"] = url
    # Fetch linked scripts asynchronously so Stop cancels these requests too.
    if not email and HAS_SCRAPLING:
        page = Adaptor(html)
        domain = urlparse(url).netloc
        scripts = [urljoin(url, el.attrib.get("src", "")) for el in page.css("script[src]")]
        for script_url in [item for item in scripts if urlparse(item).netloc == domain][:5]:
            javascript = await _fetch_one(session, script_url, timeout)
            if len(javascript) > 500_000:
                continue
            email, _ = extract_contacts(javascript)
            if email:
                if origins is not None:
                    origins["email_source_url"] = script_url
                break
    if (not email or not phone) and HAS_SCRAPLING:
        page = Adaptor(html)
        hints = ("contact", "about", "team", "reach", "support")
        domain = urlparse(url).netloc
        sub_urls = []
        for el in page.css("a[href]"):
            href = el.attrib.get("href", "").strip()
            if not href or href.startswith(("mailto:", "tel:", "#", "javascript:")):
                continue
            abs_url = urljoin(url, href)
            p = urlparse(abs_url)
            if p.scheme not in {"http", "https"} or p.netloc != domain:
                continue
            if any(h in p.path.lower() for h in hints):
                sub_urls.append(abs_url)
        CONTACT_PATHS = [
            "/contact",
            "/contact-us",
            "/about",
            "/about-us",
            "/team",
            "/company",
            "/support",
            "/reach-us",
            "/get-in-touch",
        ]
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        direct_pages = [base + path for path in CONTACT_PATHS if base + path not in sub_urls]
        for sub_url in sub_urls[:2] + direct_pages[:4]:
            if email and phone:
                break
            sub_html = await _fetch_one(session, sub_url, timeout)
            if sub_html:
                se, sp = extract_contacts(sub_html)
                if not email:
                    email = se
                    if se and origins is not None:
                        origins["email_source_url"] = sub_url
                if not phone:
                    phone = sp
                    if sp and origins is not None:
                        origins["phone_source_url"] = sub_url
    return email, phone


async def enrich_batch_async(
    contractors: list[Contractor],
    city_hint: str,
    location: str = "",
    _ddg_state: list | None = None,
    stop_ev=None,
) -> None:
    """
    Async parallel enrichment using ONE shared aiohttp.ClientSession.
    Domain-specific semaphores prevent hammering any single target.
    """
    if not HAS_AIOHTTP:
        return
    import aiohttp

    _sems = {
        "duckduckgo": asyncio.Semaphore(SEM_DDG),
        "google": asyncio.Semaphore(SEM_GOOGLE),
        "yellowpages": asyncio.Semaphore(SEM_YELLOWPAGES),
        "default": asyncio.Semaphore(SEM_DEFAULT),
    }

    def _get_sem(url: str):
        for k, s in _sems.items():
            if k in url:
                return s
        return _sems["default"]

    # 8s total / 4s connect — tight enough to skip hung sites, loose enough for slow hosting
    timeout = aiohttp.ClientTimeout(total=8, connect=4)
    conn = aiohttp.TCPConnector(
        limit=20, ttl_dns_cache=300, force_close=False, enable_cleanup_closed=True
    )

    async def _guess_domain(contractor: Contractor, session) -> str:
        clean = re.sub(r"[^a-z0-9]", "", contractor.name.lower())
        city_c = re.sub(r"[^a-z0-9]", "", city_hint.lower())
        trade_kws = TRADE_KW.get(contractor.trade, {}).get("ddg", [])
        suffix = re.sub(r"[^a-z0-9]", "", trade_kws[0].lower()) if trade_kws else ""
        short_timeout = aiohttp.ClientTimeout(total=3)
        for url in _build_domain_candidates(clean, city_c, suffix)[:8]:
            if stop_ev is not None and stop_ev.is_set():
                raise asyncio.CancelledError()
            html = await _fetch_one(session, url, short_timeout)
            if html and website_matches(contractor, html):
                return url
        return ""

    loc_hint = location or city_hint
    # Counter is shared across all batch calls for the same trade (passed in from
    # search.py) so the 8-call cap is per-trade, not per-15-contractor-batch.
    ddg_count = _ddg_state if _ddg_state is not None else [0]
    # DDG_CAP from config — max DDG lookups per trade to avoid rate-limiting

    async def enrich_one(c: Contractor, session):
        async with _get_sem(c.website or ""):
            # Step 1: domain guessing
            if not c.website and c.name:
                guessed = await _guess_domain(c, session)
                if guessed:
                    c.website = guessed
                    c.website_method = "corroborated-domain"
                    c.confidence = "corroborated"
            # Step 2: DDG website lookup — capped at DDG_CAP per trade.
            # OSM contractors rarely have websites; hitting DDG 30+ times
            # causes 202 rate-limit responses and blocks all three trades.
            if not c.website and c.name and ddg_count[0] < DDG_CAP:
                ddg_count[0] += 1
                await asyncio.sleep(0.3)
                from scrapers.ddg import ddg_search

                q = quote_plus(f'"{c.name}" "{loc_hint}" -yelp -yellowpages -bbb')
                candidates = await asyncio.to_thread(
                    call_with_stop, stop_ev, ddg_search, q, pages=1
                )
                for _, url, _ in candidates:
                    if url.startswith("http") and not any(d in url for d in SKIP_DOMAINS):
                        candidate_html = await _fetch_one(session, url, timeout)
                        if website_matches(c, candidate_html):
                            c.website = url
                            c.website_method = "corroborated-search"
                            c.confidence = "corroborated"
                            break
            # Step 3: scrape website (cache first)
            if c.website and (not c.email or not c.phone):
                cache_key = "contact-v2:" + c.website.rstrip("/") + "|" + _address_key(c.address)
                cached_contact = CACHE.get_contact(cache_key) if cache_key else None
                if cached_contact:
                    if not c.email:
                        raw_e = cached_contact.get("email", "")
                        c.email = _clean_email(raw_e) if raw_e else ""
                        c.email_source_url = cached_contact.get("email_source_url", "")
                    if not c.phone:
                        c.phone = cached_contact.get("phone", "")
                        c.phone_source_url = cached_contact.get("phone_source_url", "")
                    if not c.website:
                        c.website = cached_contact.get("website", "")
                else:
                    origins = {}
                    we, wp = await async_scrape_website(c.website, session, timeout, origins)
                    if not c.email:
                        c.email = we
                        c.email_source_url = origins.get("email_source_url", "")
                    if not c.phone:
                        c.phone = wp
                        c.phone_source_url = origins.get("phone_source_url", "")
                    if cache_key and (we or wp):
                        CACHE.set_contact(cache_key, we, wp, c.website, origins)
                record_contact(c, c.website)
            # Step 4: email pattern guessing from domain (MX-verified)
            if not c.email and c.website:
                domain = urlparse(c.website).netloc.replace("www.", "").split(":")[0]
                if domain:
                    status, _ = await asyncio.to_thread(verify_email, f"info@{domain}")
                    if status == "valid":
                        candidate = f"info@{domain}"
                        if _ok_email(candidate):
                            c.email = candidate
                            c.email_status = "unknown"
                            c.email_method = "guessed"
                            c.email_source_url = ""
                            c.confidence = "unconfirmed"

    async with aiohttp.ClientSession(
        headers=_AIOHTTP_HEADERS,
        connector=conn,
        timeout=timeout,
    ) as session:
        tasks = [asyncio.create_task(enrich_one(c, session)) for c in contractors]
        pending = set(tasks)
        try:
            while pending:
                if stop_ev is not None and stop_ev.is_set():
                    raise asyncio.CancelledError()
                completed, pending = await asyncio.wait(
                    pending, timeout=0.1, return_when=asyncio.FIRST_COMPLETED
                )
                for task in completed:
                    try:
                        task.result()
                    except SearchCancelled as exc:
                        raise asyncio.CancelledError() from exc
                    except Exception as exc:
                        logger.debug("[Enrich] task error: %s", exc)
            if stop_ev is not None and stop_ev.is_set():
                raise asyncio.CancelledError()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def scrape_website(url: str) -> tuple[str, str]:
    """
    Sync multi-page website scraper (fallback when aiohttp not available).
    Checks homepage + up to 4 contact/about subpages.
    """
    if not url or any(s in url for s in SCRAPE_SKIP):
        return "", ""
    html = http_get(url, timeout=12)
    if not html:
        return "", ""
    email, phone = extract_contacts(html)
    if (not email or not phone) and HAS_SCRAPLING:
        page = Adaptor(html)
        hints = ("contact", "about", "team", "reach", "support", "service", "us")
        domain = urlparse(url).netloc
        visited = {url}
        ranked: list[tuple[int, str]] = []
        for el in page.css("a[href]"):
            href = el.attrib.get("href", "").strip()
            if not href or href.startswith(("mailto:", "tel:", "#", "javascript")):
                continue
            abs_url = urljoin(url, href)
            p = urlparse(abs_url)
            if p.scheme not in {"http", "https"} or p.netloc != domain:
                continue
            if abs_url in visited:
                continue
            path = p.path.lower()
            score = sum(2 for h in hints if h in path)
            if score > 0:
                ranked.append((score, abs_url))
        ranked.sort(reverse=True)
        for _, sub_url in ranked[:4]:
            if email and phone:
                break
            visited.add(sub_url)
            sub_html = http_get(sub_url, timeout=10)
            se, sp = extract_contacts(sub_html)
            if not email:
                email = se
            if not phone:
                phone = sp

    # ── Deep email hunt (runs only when HTML scan found nothing) ─────────────
    if not email:
        domain = urlparse(url).netloc.replace("www.", "").split(":")[0]
        # Strategy A: scan linked JS files on the homepage
        email = _scan_js_for_email(url, html)
    if not email:
        # Strategy B: sitemap → contact/about/team pages
        email = _scan_sitemap_for_email(url)
    if not email:
        # Strategy C: WHOIS registrant email (requires python-whois)
        email = _whois_email(domain)
    if not email:
        # Strategy D: DDG search for "@domain.com" in snippets/cached pages
        email = _ddg_email_hunt(domain)

    return email, phone
