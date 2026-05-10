from __future__ import annotations
import asyncio, re
import logging
from urllib.parse import quote_plus, urljoin, urlparse

from compat import HAS_SCRAPLING, HAS_AIOHTTP, HAS_DNS, Adaptor
from constants import SCRAPE_SKIP, SKIP_DOMAINS, _FATAL_PROXY_ERRORS
from cache import CACHE
from proxy import PROXY_MGR
from http_client import http_get
from extractor import extract_contacts, _ok_email
from models import Contractor

logger = logging.getLogger("ContractorFinder")

_AIOHTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Deduplication helpers ─────────────────────────────────────────────────────

def _name_key(name: str) -> str:
    s = name.lower()
    for suf in [" llc", " inc", " co", " corp", " ltd", " services", " company",
                " heating", " cooling", " hvac", " electric", " plumbing", " excavating"]:
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
    match   = sum(1 for x, y in zip(ka, kb) if x == y)
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


def dedup(rows: list[Contractor]) -> list[Contractor]:
    """
    Smart dedup using name similarity + phone + domain.
    Merges data from duplicates (keeps best record, fills missing fields).
    """
    sorted_rows = sorted(
        rows,
        key=lambda r: -(bool(r.phone) * 2 + bool(r.email) * 3 + bool(r.website) * 2),
    )
    out: list[Contractor] = []
    for r in sorted_rows:
        is_dup   = False
        r_phone  = _phone_key(r.phone)
        r_domain = _domain_key(r.website)
        for ex in out:
            name_match   = _similar(r.name, ex.name)
            phone_match  = bool(r_phone  and r_phone  == _phone_key(ex.phone))
            domain_match = bool(r_domain and r_domain == _domain_key(ex.website))
            if name_match or phone_match or domain_match:
                if not ex.phone   and r.phone:   ex.phone   = r.phone
                if not ex.email   and r.email:   ex.email   = r.email
                if not ex.website and r.website: ex.website = r.website
                if not ex.address and r.address: ex.address = r.address
                is_dup = True
                break
        if not is_dup:
            out.append(r)
    return out


# ── Async website scraping ────────────────────────────────────────────────────

async def _fetch_one(session, url: str, timeout, use_proxy: bool = False) -> str:
    """
    Fetch one URL with the shared aiohttp session.
    ssl=False only when proxied; direct connections keep SSL validation.
    """
    proxy    = PROXY_MGR.get_for(url) if (use_proxy and PROXY_MGR.ready) else None
    ssl_mode = False if proxy else True
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
        if not proxy and ("ssl" in err.lower() or "certificate" in err.lower()):
            try:
                async with session.get(url, timeout=timeout, ssl=False,
                                       allow_redirects=True) as resp:
                    if resp.status in (200, 201, 206):
                        return await resp.text(errors="ignore")
            except Exception:
                pass
        return ""


async def async_scrape_website(url: str, session, timeout) -> tuple[str, str]:
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
    if (not email or not phone) and HAS_SCRAPLING:
        page  = Adaptor(html)
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
        CONTACT_PATHS = ["/contact", "/contact-us", "/about", "/about-us",
                         "/team", "/company", "/support", "/reach-us", "/get-in-touch"]
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        direct_pages = [base + path for path in CONTACT_PATHS if base + path not in sub_urls]
        for sub_url in (sub_urls[:2] + direct_pages[:4]):
            if email and phone:
                break
            sub_html = await _fetch_one(session, sub_url, timeout)
            if sub_html:
                se, sp = extract_contacts(sub_html)
                if not email:
                    email = se
                if not phone:
                    phone = sp
    return email, phone


async def enrich_batch_async(contractors: list[Contractor], city_hint: str) -> None:
    """
    Async parallel enrichment using ONE shared aiohttp.ClientSession.
    Domain-specific semaphores prevent hammering any single target.
    """
    if not HAS_AIOHTTP:
        return
    import aiohttp

    _sems = {
        "duckduckgo": asyncio.Semaphore(2),
        "google":     asyncio.Semaphore(1),
        "yellowpages": asyncio.Semaphore(2),
        "default":    asyncio.Semaphore(6),
    }

    def _get_sem(url: str):
        for k, s in _sems.items():
            if k in url:
                return s
        return _sems["default"]

    timeout = aiohttp.ClientTimeout(total=8, connect=4)
    conn    = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300,
                                   force_close=False, enable_cleanup_closed=True)

    async def _guess_domain(name: str, session) -> str:
        clean  = re.sub(r"[^a-z0-9]", "", name.lower())
        if len(clean) < 3:
            return ""
        city_c = re.sub(r"[^a-z]", "", city_hint.lower())
        candidates = [
            f"https://www.{clean}.com",
            f"https://{clean}.com",
            f"https://www.{clean}michigan.com",
            f"https://www.{clean}{city_c}.com",
            f"https://www.{clean}hvac.com",
            f"https://www.{clean}heating.com",
            f"https://www.{clean}electric.com",
            f"https://www.{clean}excavating.com",
            f"https://www.{clean}contracting.com",
        ]
        t_short = aiohttp.ClientTimeout(total=3)
        for url in candidates[:5]:
            try:
                async with session.head(url, timeout=t_short, ssl=True,
                                        allow_redirects=True) as r:
                    if r.status in (200, 301, 302, 304):
                        return str(r.url)
            except Exception:
                try:
                    async with session.head(url, timeout=t_short, ssl=False,
                                            allow_redirects=True) as r:
                        if r.status in (200, 301, 302, 304):
                            return str(r.url)
                except Exception:
                    pass
        return ""

    async def enrich_one(c: Contractor, session):
        async with _get_sem(c.website or ""):
            # Step 1: domain guessing
            if not c.website and c.name:
                guessed = await _guess_domain(c.name, session)
                if guessed:
                    c.website = guessed
            # Step 2: DDG website lookup (only if domain guess failed)
            if not c.website and c.name:
                await asyncio.sleep(0.3)
                from scrapers.ddg import ddg_search
                q = quote_plus(f'"{c.name}" {city_hint} Michigan contractor')
                for _, url, _ in ddg_search(q, pages=1):
                    if url.startswith("http") and not any(d in url for d in SKIP_DOMAINS):
                        c.website = url
                        break
            # Step 3: scrape website (cache first)
            if c.website and (not c.email or not c.phone):
                cache_key      = _domain_key(c.website)
                cached_contact = CACHE.get_contact(cache_key) if cache_key else None
                if cached_contact:
                    if not c.email:   c.email   = cached_contact.get("email", "")
                    if not c.phone:   c.phone   = cached_contact.get("phone", "")
                    if not c.website: c.website = cached_contact.get("website", "")
                else:
                    we, wp = await async_scrape_website(c.website, session, timeout)
                    if not c.email:
                        c.email = we
                    if not c.phone:
                        c.phone = wp
                    if cache_key and (we or wp):
                        CACHE.set_contact(cache_key, we, wp, c.website)
            # Step 4: email pattern guessing from domain (MX-verified)
            if not c.email and c.website:
                domain = urlparse(c.website).netloc.replace("www.", "").split(":")[0]
                if domain:
                    has_mx = True
                    if HAS_DNS:
                        import dns.resolver as _dns
                        try:
                            await asyncio.to_thread(_dns.resolve, domain, "MX")
                        except Exception:
                            has_mx = False
                    if has_mx:
                        for prefix in ["info", "contact", "service", "office",
                                       "admin", "support", "hello"]:
                            candidate = f"{prefix}@{domain}"
                            if _ok_email(candidate):
                                c.email = candidate
                                break

    async with aiohttp.ClientSession(
        headers=_AIOHTTP_HEADERS,
        connector=conn,
        timeout=timeout,
    ) as session:
        tasks = [asyncio.create_task(enrich_one(c, session)) for c in contractors]
        for coro in asyncio.as_completed(tasks):
            try:
                await coro
            except Exception as e:
                logger.debug(f"[Enrich] task error: {type(e).__name__}: {e}")


def scrape_website(url: str) -> tuple[str, str]:
    """
    Sync multi-page website scraper (fallback when aiohttp not available).
    Checks homepage + up to 4 contact/about subpages.
    """
    if not url:
        return "", ""
    skip = {"yellowpages.com", "yelp.com", "google.com", "facebook.com",
            "scheduler.netic.ai", "servicetitan.com", "localsearch.com"}
    if any(s in url for s in skip):
        return "", ""
    html = http_get(url, timeout=12)
    if not html:
        return "", ""
    email, phone = extract_contacts(html)
    if (not email or not phone) and HAS_SCRAPLING:
        page    = Adaptor(html)
        hints   = ("contact", "about", "team", "reach", "support", "service", "us")
        domain  = urlparse(url).netloc
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
            path  = p.path.lower()
            score = sum(2 for h in hints if h in path)
            if score > 0:
                ranked.append((score, abs_url))
        ranked.sort(reverse=True)
        for _, sub_url in ranked[:4]:
            if email and phone:
                break
            visited.add(sub_url)
            sub_html = http_get(sub_url, timeout=10)
            se, sp   = extract_contacts(sub_html)
            if not email:
                email = se
            if not phone:
                phone = sp
    return email, phone
