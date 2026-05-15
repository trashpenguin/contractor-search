"""
Deep email hunting strategies used by enricher.scrape_website.
Each function is a self-contained last-resort called only when homepage HTML yielded nothing.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urljoin, urlparse

from compat import HAS_SCRAPLING, Adaptor
from constants import EMAIL_RE
from extractor import _clean_email, _ok_email
from http_client import http_get

logger = logging.getLogger("ContractorFinder")


def _scan_js_for_email(url: str, html: str) -> str:
    """
    Download every same-domain <script src> file and scan for email addresses.
    Site builders (Wix, Squarespace, GoDaddy) often embed the contact form
    destination email inside a JS config file even when hiding it from HTML.
    """
    if not html or not HAS_SCRAPLING:
        return ""
    domain = urlparse(url).netloc
    page = Adaptor(html)
    checked = 0
    for script in page.css("script[src]"):
        src = script.attrib.get("src", "")
        if not src:
            continue
        abs_src = urljoin(url, src)
        if urlparse(abs_src).netloc not in ("", domain):
            continue
        if checked >= 5:  # cap at 5 same-domain scripts — beyond that it's CDN noise
            break
        checked += 1
        js = http_get(abs_src, timeout=5)
        if not js or len(js) > 500_000:  # skip huge bundles
            continue
        for raw in EMAIL_RE.findall(js):
            e = _clean_email(raw)
            if _ok_email(e):
                logger.debug(f"[JS] email found in {abs_src[:60]}")
                return e
    return ""


def _scan_sitemap_for_email(url: str) -> str:
    """
    Fetch /sitemap.xml (or the URL in robots.txt), find contact/about pages,
    and scan each for an email address.
    """
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    sitemap_content = http_get(base + "/sitemap.xml", timeout=6)
    if not sitemap_content:
        robots = http_get(base + "/robots.txt", timeout=4)
        if robots:
            m = re.search(r"Sitemap:\s*(https?://\S+)", robots, re.I)
            if m:
                sitemap_content = http_get(m.group(1), timeout=6)
    if not sitemap_content:
        return ""
    all_urls = re.findall(r"<loc>(https?://[^<]+)</loc>", sitemap_content)
    priority_words = ("contact", "about", "team", "staff", "reach", "people")
    priority_urls = [u for u in all_urls if any(w in u.lower() for w in priority_words)]
    for page_url in priority_urls[:5]:
        html = http_get(page_url, timeout=8)
        if not html:
            continue
        from extractor import extract_contacts

        email, _ = extract_contacts(html)
        if email:
            logger.debug(f"[Sitemap] email found on {page_url[:60]}")
            return email
    return ""


def _whois_email(domain: str) -> str:
    """
    Check WHOIS registration record for the domain owner's email.
    Requires `pip install python-whois`. Skipped silently if not installed.
    """
    try:
        import whois  # type: ignore[import]

        w = whois.whois(domain)
        emails = w.emails if hasattr(w, "emails") else []
        if isinstance(emails, str):
            emails = [emails]
        privacy = ("privacy", "protect", "whoisguard", "redacted", "withheld")
        for raw in emails or []:
            e = _clean_email(raw)
            if _ok_email(e) and not any(p in e for p in privacy):
                logger.debug(f"[WHOIS] email found for {domain}")
                return e
    except Exception:
        pass
    return ""


def _ddg_email_hunt(domain: str) -> str:
    """
    Search DuckDuckGo for an email address associated with this domain.
    Useful when the email appeared on a cached page, BBB listing, or forum post.
    """
    from scrapers.ddg import ddg_search

    queries = [
        quote_plus(f'"{domain}" email contact'),
        quote_plus(f'"@{domain}"'),
    ]
    for q in queries:
        for _, _, snippet in ddg_search(q, pages=1):
            for raw in EMAIL_RE.findall(snippet):
                e = _clean_email(raw)
                if _ok_email(e) and domain in e:
                    logger.debug(f"[DDG-hunt] email found in snippet for {domain}")
                    return e
    return ""
