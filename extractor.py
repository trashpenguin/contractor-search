from __future__ import annotations
import re
import logging

from constants import (
    EMAIL_RE, PHONE_RE,
    BAD_EMAIL, BAD_EMAIL_DOMAINS, ROLE_EMAILS,
)
from compat import HAS_SCRAPLING, HAS_DNS, Adaptor

logger = logging.getLogger("ContractorFinder")


def email_role_warning(email: str) -> str:
    local = email.split("@")[0].lower().strip()
    if local in ROLE_EMAILS:
        return f"Role account ({local}@) — may not reach a real person"
    return ""


def _clean_email(e: str) -> str:
    from urllib.parse import unquote as _uq
    e = _uq(e)  # decode %20, %40, etc. before stripping
    return e.strip().strip(".,;:()[]{}<>\"'").lower()


def _ok_email(e: str) -> bool:
    if not e or "@" not in e:
        return False
    parts = e.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    if not domain or "." not in domain:
        return False
    if len(e) < 6 or len(e) > 80:
        return False
    if any(b in e for b in BAD_EMAIL):
        return False
    if any(bd in domain for bd in BAD_EMAIL_DOMAINS):
        return False
    if re.search(r"\.(png|jpg|gif|svg|webp|ico|js|css|php)$", local, re.I):
        return False
    return True


def _parse_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw)
    if len(d) >= 10:
        d = d[-10:]
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    return ""


def extract_contacts(html: str) -> tuple[str, str]:
    """
    Multi-strategy contact extraction:
    1. JSON-LD schema.org
    2. mailto/tel links
    3. Meta tags
    4. Structured data attributes
    5. Footer/contact section scan
    6. Cloudflare email obfuscation decode
    7. Obfuscated patterns ([at], (at), AT)
    8. Full text regex fallback
    """
    email = phone = ""
    if not html:
        return email, phone
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="ignore")

    # Strategy 1: JSON-LD / schema.org
    import json as _j
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    ):
        try:
            data  = _j.loads(match.group(1))
            items = data if isinstance(data, list) else [data]
            for item in items:
                sub_items = item.get("@graph", [item])
                for si in (sub_items if isinstance(sub_items, list) else [sub_items]):
                    if not email:
                        e = si.get("email", "") or (
                            si.get("contactPoint", {}).get("email", "")
                            if isinstance(si.get("contactPoint"), dict) else ""
                        )
                        e = _clean_email(str(e)) if e else ""
                        if _ok_email(e):
                            email = e
                    if not phone:
                        p = si.get("telephone", "") or si.get("phone", "")
                        if p:
                            phone = _parse_phone(str(p)) or str(p)[:20]
            if email and phone:
                return email, phone
        except Exception:
            pass

    if HAS_SCRAPLING:
        page = Adaptor(html)

        # Strategy 2: mailto/tel links
        for el in page.css("a[href*='mailto:']"):
            href = el.attrib.get("href", "")
            if "mailto:" in href:
                e = _clean_email(href.split("mailto:")[-1].split("?")[0])
                if _ok_email(e):
                    email = e
                    break

        for el in page.css("a[href*='tel:']"):
            href = el.attrib.get("href", "")
            if "tel:" in href:
                p = _parse_phone(href.split("tel:")[-1])
                if p:
                    phone = p
                    break

        # Strategy 3: meta tags
        if not email:
            for el in page.css("meta[name*='email'], meta[property*='email']"):
                c = el.attrib.get("content", "")
                e = _clean_email(c)
                if _ok_email(e):
                    email = e
                    break

        # Strategy 4: structured data attributes
        if not email:
            for el in page.css("[itemprop='email'], [data-email]"):
                raw = (
                    el.text.strip()
                    or el.attrib.get("content", "")
                    or el.attrib.get("data-email", "")
                )
                e = _clean_email(raw)
                if _ok_email(e):
                    email = e
                    break
        if not phone:
            for el in page.css("[itemprop='telephone'], [data-phone]"):
                raw = (
                    el.text.strip()
                    or el.attrib.get("content", "")
                    or el.attrib.get("data-phone", "")
                )
                if raw:
                    p = _parse_phone(raw)
                    if p:
                        phone = p
                        break

        # Strategy 5: footer + contact section scan
        if not email or not phone:
            for sel in ["footer", "#footer", ".footer", "#contact", ".contact",
                        "[id*='contact']", "[class*='contact']"]:
                section = page.css(sel)
                if not section:
                    continue
                sec_html = section[0].get_all_text(separator=" ")
                if not email:
                    for raw in EMAIL_RE.findall(sec_html):
                        e = _clean_email(raw)
                        if _ok_email(e):
                            email = e
                            break
                if not phone:
                    m = PHONE_RE.search(sec_html)
                    if m:
                        phone = m.group(1)
                if email and phone:
                    break

        # Strategy 6: Cloudflare email obfuscation (data-cfemail XOR decode)
        if not email:
            for el in page.css("[data-cfemail]"):
                encoded = el.attrib.get("data-cfemail", "")
                if encoded:
                    try:
                        b      = bytes.fromhex(encoded)
                        key    = b[0]
                        decoded = "".join(chr(c ^ key) for c in b[1:])
                        e = _clean_email(decoded)
                        if _ok_email(e):
                            email = e
                            break
                    except Exception:
                        pass

        # Strategy 7: obfuscated patterns in text
        if not email:
            text = page.get_all_text(separator=" ")
            obf_patterns = [
                r"([\w.+-]+)\s*\[at\]\s*([\w.-]+\.[a-z]{2,})",
                r"([\w.+-]+)\s*\(at\)\s*([\w.-]+\.[a-z]{2,})",
                r"([\w.+-]+)\s*AT\s*([\w.-]+\.[a-z]{2,})",
                r"([\w.+-]+)\s*@\s*([\w.-]+\.[a-z]{2,})",
            ]
            for pat in obf_patterns:
                m = re.search(pat, text, re.I)
                if m:
                    e = _clean_email(f"{m.group(1)}@{m.group(2)}")
                    if _ok_email(e):
                        email = e
                        break

        # Strategy 8: full text fallback
        if not email or not phone:
            text = page.get_all_text(separator=" ") if not email else ""
            if text and not email:
                for raw in EMAIL_RE.findall(text):
                    e = _clean_email(raw)
                    if _ok_email(e):
                        email = e
                        break
            if not phone:
                if not text:
                    text = page.get_all_text(separator=" ")
                m = PHONE_RE.search(text)
                if m:
                    phone = m.group(1)
    else:
        # No Scrapling — pure regex + obfuscation
        for raw in EMAIL_RE.findall(html):
            e = _clean_email(raw)
            if _ok_email(e):
                email = e
                break
        if not email:
            for pat, grp in [
                (r"([\w.+-]+)\s*\[at\]\s*([\w.-]+\.[a-z]{2,})",
                 lambda m: f"{m.group(1)}@{m.group(2)}"),
                (r"([\w.+-]+)\s*\(at\)\s*([\w.-]+\.[a-z]{2,})",
                 lambda m: f"{m.group(1)}@{m.group(2)}"),
            ]:
                m = re.search(pat, html, re.I)
                if m:
                    e = _clean_email(grp(m))
                    if _ok_email(e):
                        email = e
                        break
        m = PHONE_RE.search(html)
        if m:
            phone = m.group(1)

    return email, phone


def verify_email(email: str) -> tuple[str, str]:
    """
    Email verification via syntax + MX record only.
    SMTP RCPT TO removed: unreliable in 2026 (tarpitting, greylisting, catch-all).
    """
    if not re.match(r'^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$', email, re.I):
        return "invalid", "Bad syntax"
    if not _ok_email(email):
        return "invalid", "Filtered (spam/CDN pattern)"
    domain = email.split("@")[1].lower()
    if not HAS_DNS:
        return "unknown", "dnspython not installed"
    import dns.resolver as _dns
    try:
        mx_records = _dns.resolve(domain, "MX")
        if mx_records:
            return "valid", f"MX verified ({len(mx_records)} records)"
    except _dns.NXDOMAIN:
        return "invalid", "Domain doesn't exist"
    except _dns.NoAnswer:
        try:
            _dns.resolve(domain, "A")
            return "unknown", "No MX but domain exists"
        except Exception:
            return "invalid", "No MX or A record"
    except Exception as e:
        return "unknown", f"DNS: {type(e).__name__}"
    return "unknown", "Unexpected"
