#!/usr/bin/env python3
"""
Contractor Finder GUI v3 — Correct Scrapling API
Focus: Phone · Email · Website accuracy for USA locations

Scrapling fetcher strategy (per docs v0.4+):
  FetcherSession   → Fast HTTP with browser fingerprint (DDG, contractor websites)
  StealthySession  → Persistent stealth browser (YP, Google Maps — 1 browser, many pages)
  StealthyFetcher  → Single-shot stealth (Google Maps when session not available)

Key pipeline: Find contractor → get website → scrape website for phone+email
"""
from __future__ import annotations
import asyncio, csv, json, os, re, sys, tempfile, threading, time, webbrowser
from dataclasses import dataclass, asdict
from urllib.parse import quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor

# ── Scrapling (correct API — no deprecated warnings) ──────────────────────────
try:
    from scrapling.fetchers import (
        Fetcher, FetcherSession, AsyncFetcher,
        StealthyFetcher, StealthySession
    )
    from scrapling.parser import Adaptor
    HAS_SCRAPLING = True
except Exception as e:
    HAS_SCRAPLING = False
    logger.warning(f"[WARN] Scrapling unavailable: {e}")

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    import dns.resolver as _dns
    HAS_DNS = True
except ImportError:
    HAS_DNS = False

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui  import QColor, QFont, QBrush
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QProgressBar, QFileDialog,
    QStatusBar, QMessageBox, QFrame, QAbstractItemView,
    QGroupBox, QDialog, QTextEdit, QDialogButtonBox
)

import logging
from logging.handlers import RotatingFileHandler

# ── Structured Logging (replaces all print() calls) ──────────────────────────
_LOG_FILE = os.path.join(os.path.expanduser("~"), "contractor_finder.log")
logger = logging.getLogger("ContractorFinder")
logger.setLevel(logging.DEBUG)
# File handler — rotates at 5MB, keeps 3 backups
_fh = RotatingFileHandler(_LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
# Console handler — INFO and above only
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(_fh)
logger.addHandler(_ch)
logger.propagate = False

# ── Search History ────────────────────────────────────────────────────────────
class SearchHistory:
    """Saves last 20 location searches to ~/.contractor_search_history.json"""
    PATH = os.path.join(os.path.expanduser("~"), ".contractor_search_history.json")
    MAX  = 20

    def load(self) -> list[str]:
        try:
            with open(self.PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [str(x) for x in data if x]
        except Exception:
            return []

    def save(self, location: str):
        history = self.load()
        if location in history:
            history.remove(location)
        history.insert(0, location)
        try:
            with open(self.PATH, "w", encoding="utf-8") as f:
                json.dump(history[:self.MAX], f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save search history: {e}")

SEARCH_HISTORY = SearchHistory()

# ── Constants ─────────────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]\d{4})")

# ── Pre-compiled regex (module level for performance) ────────────────────────
ADDR_RE = re.compile(
    r"\d+\s+\w[\w\s]+(?:St|Ave|Rd|Blvd|Dr|Way|Ln|Ct|Street|Avenue|Road|Boulevard|Drive)")
JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']+application/ld\+json["\']+[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE)
OBFUSC_RE = re.compile(
    r"([\w.+-]+)\s*(?:\[at\]|\(at\)|\bAT\b)\s*([\w.-]+\.[a-z]{2,})", re.I)
FILENAME_RE = re.compile(r"\.(png|jpg|gif|svg|webp|ico|js|css|php)$", re.I)

# ── Role account detection (#9) ───────────────────────────────────────────────
ROLE_EMAILS = {"info","contact","service","office","admin","support","hello",
               "sales","mail","webmaster","team","help","enquiries","enquiry"}

def email_role_warning(email: str) -> str:
    """Returns a warning string if email is a role account, empty string otherwise."""
    local = email.split("@")[0].lower().strip()
    if local in ROLE_EMAILS:
        return f"Role account ({local}@) — may not reach a real person"
    return ""

# ── Persistent async event loop (#1) ─────────────────────────────────────────
_ASYNC_LOOP: asyncio.AbstractEventLoop | None = None
_ASYNC_LOOP_LOCK = threading.Lock()

def get_event_loop() -> asyncio.AbstractEventLoop:
    """
    Returns a persistent event loop for the scraping thread.
    Creating/destroying loops per-batch causes overhead and Windows issues.
    """
    global _ASYNC_LOOP
    with _ASYNC_LOOP_LOCK:
        if _ASYNC_LOOP is None or _ASYNC_LOOP.is_closed():
            _ASYNC_LOOP = asyncio.new_event_loop()
            asyncio.set_event_loop(_ASYNC_LOOP)
            logger.debug("Created new persistent async event loop")
        return _ASYNC_LOOP
BAD_EMAIL = {
    # Generic/placeholder
    "example.","test@","user@","admin@example","info@example","email@email",
    "your@email","yourname@","youremail","name@domain","email@domain",
    # Service/CDN noise
    "wixpress","sentry","schema","noreply","no-reply","donotreply","do-not-reply",
    "bounce@","postmaster@","mailer-daemon","abuse@",
    # Analytics/tracking noise (common in JS bundles scraped by regex)
    "cloudflare","cdn.","static.","assets.","images.","img.",
    "tracking","analytics","pixel","beacon",
    # Image filenames sometimes match EMAIL_RE (e.g. a@2x.png, b@3x.jpg)
    ".png","@2x","@3x",".jpg",".gif",".svg",".webp",
}
# Separate set for domain-level rejections
BAD_EMAIL_DOMAINS = {
    "cloudflare.com","amazonaws.com","akamai.net","fastly.net",
    "cdnjs.com","jsdelivr.net","unpkg.com","sentry.io",
}

def _ok_email(e: str) -> bool:
    if not e or "@" not in e: return False
    parts = e.split("@")
    if len(parts) != 2: return False
    local, domain = parts
    if not domain or "." not in domain: return False
    if len(e) < 6 or len(e) > 80: return False
    if any(b in e for b in BAD_EMAIL): return False
    if any(bd in domain for bd in BAD_EMAIL_DOMAINS): return False
    # Reject if local part looks like a filename (has dot before extension)
    if re.search(r"\.(png|jpg|gif|svg|webp|ico|js|css|php)$", local, re.I): return False
    return True
SKIP_DOMAINS = {"yelp.com","yellowpages.com","bbb.org","facebook.com","linkedin.com",
                "google.com","mapquest.com","whitepages.com","angi.com","homeadvisor.com",
                "thumbtack.com","angieslist.com","nextdoor.com","duckduckgo.com"}

# ── Persistent SQLite Cache ───────────────────────────────────────────────────
import sqlite3, hashlib

class ContactCache:
    """
    SQLite cache for contractor contact data.
    Prevents re-scraping the same websites and re-querying DDG for the same names.
    Cache TTL: 7 days for contact data, 1 day for DDG results.
    """
    DB_PATH = os.path.join(os.path.expanduser("~"), ".contractor_finder_cache.db")
    TTL_CONTACT = 7 * 86400   # 7 days
    TTL_DDG     = 1 * 86400   # 1 day

    def __init__(self):
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.DB_PATH, check_same_thread=False)
            conn.execute("""CREATE TABLE IF NOT EXISTS contacts (
                key TEXT PRIMARY KEY,
                email TEXT, phone TEXT, website TEXT,
                created_at REAL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS ddg_cache (
                query_hash TEXT PRIMARY KEY,
                results TEXT,
                created_at REAL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_ts ON contacts(created_at)")
            conn.commit()
            self._conn = conn
        except Exception as e:
            logger.debug(f"[Cache] Init failed: {e}")

    def get_contact(self, key: str) -> dict | None:
        if not self._conn: return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT email, phone, website, created_at FROM contacts WHERE key=?",
                    (key,)
                ).fetchone()
                if row and (time.time() - row[3]) < self.TTL_CONTACT:
                    return {"email": row[0], "phone": row[1], "website": row[2]}
        except Exception: pass
        return None

    def set_contact(self, key: str, email: str, phone: str, website: str):
        if not self._conn: return
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO contacts VALUES (?,?,?,?,?)",
                    (key, email, phone, website, time.time())
                )
                self._conn.commit()
        except Exception: pass

    def get_ddg(self, query: str) -> list | None:
        if not self._conn: return None
        qhash = hashlib.md5(query.encode()).hexdigest()
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT results, created_at FROM ddg_cache WHERE query_hash=?",
                    (qhash,)
                ).fetchone()
                if row and (time.time() - row[1]) < self.TTL_DDG:
                    import json as _j
                    return _j.loads(row[0])
        except Exception: pass
        return None

    def set_ddg(self, query: str, results: list):
        if not self._conn: return
        qhash = hashlib.md5(query.encode()).hexdigest()
        try:
            import json as _j
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO ddg_cache VALUES (?,?,?)",
                    (qhash, _j.dumps(results), time.time())
                )
                self._conn.commit()
        except Exception: pass

    def purge_old(self):
        """Remove expired entries to keep DB small."""
        if not self._conn: return
        cutoff = time.time() - max(self.TTL_CONTACT, self.TTL_DDG)
        try:
            with self._lock:
                self._conn.execute("DELETE FROM contacts WHERE created_at < ?", (cutoff,))
                self._conn.execute("DELETE FROM ddg_cache WHERE created_at < ?", (cutoff,))
                self._conn.commit()
        except Exception: pass


CACHE = ContactCache()

# ── Proxy Manager (Elite Pool with Health Scoring + Sticky Sessions) ──────────
PROXY_SOURCES = [
    "https://cdn.jsdelivr.net/gh/TheSpeedX/PROXY-List@master/http.txt",
    "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt",
    "https://cdn.jsdelivr.net/gh/SoliSpirit/proxy-list@main/proxies/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
]

# Non-recoverable error substrings — discard proxy immediately, never retry
_FATAL_PROXY_ERRORS = (
    "CONNECT tunnel",  "TLS connect",    "SSL",
    "OPENSSL",         "handshake",      "certificate",
    "403",             "407",            "CONNECT aborted",
)

class ProxyEntry:
    """Tracks health of one proxy."""
    __slots__ = ("url","score","uses","latency")
    def __init__(self, url: str, latency: float):
        self.url     = url
        self.score   = 5          # Starts at 5, drops on failure
        self.uses    = 0          # Requests served
        self.latency = latency

class ProxyManager:
    """
    Elite proxy pool with:
    - Health scoring (score 5→0, remove at ≤0)
    - Sticky sessions (one proxy handles up to 10 requests before rotating)
    - Circuit breakers (TLS/CONNECT errors = immediate discard)
    - Traffic routing (OSM/company websites bypass proxy entirely)
    """
    def __init__(self):
        self._lock    = threading.Lock()
        self._pool:   list[ProxyEntry] = []
        self._cur_idx = 0
        self._loaded  = False
        self._loading = False
        self.STICKY_LIMIT = 10  # Requests per proxy before rotating

    def load_async(self):
        if self._loading or self._loaded: return
        self._loading = True
        threading.Thread(target=self._build_pool, daemon=True).start()

    def _build_pool(self):
        import random, urllib.request as _ur
        raw: list[str] = []
        for src in PROXY_SOURCES:
            if len(raw) >= 300: break
            try:
                req = Request(src, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=10) as r:
                    data = r.read().decode("utf-8", errors="ignore")
                for line in data.strip().splitlines():
                    line = line.strip()
                    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", line):
                        raw.append(f"http://{line}")
                logger.info(f"[Proxy] {len(raw)} raw from {src.split('/')[-1]}")
            except Exception as e:
                logger.info(f"[Proxy] Source failed: {type(e).__name__}")

        # Concurrent HTTPS test — both HTTP and HTTPS must work
        test_url  = "https://httpbin.org/ip"
        test_http = "http://httpbin.org/ip"
        scored: list[ProxyEntry] = []
        random.shuffle(raw)

        import concurrent.futures
        def _test(proxy: str):
            try:
                t0 = time.time()
                opener = _ur.build_opener(
                    _ur.ProxyHandler({"http": proxy, "https": proxy})
                )
                # Test HTTPS specifically (most targets are HTTPS)
                with opener.open(test_url, timeout=4) as r:
                    if r.status == 200:
                        lat = time.time() - t0
                        if lat < 3.0:
                            return ProxyEntry(proxy, lat)
            except Exception as e:
                err = str(e)
                # If fatal error, don't try HTTP fallback
                if any(fe in err for fe in _FATAL_PROXY_ERRORS):
                    return None
                # Try HTTP test as fallback
                try:
                    t0 = time.time()
                    opener2 = _ur.build_opener(
                        _ur.ProxyHandler({"http": proxy, "https": proxy})
                    )
                    with opener2.open(test_http, timeout=3) as r2:
                        if r2.status == 200:
                            return ProxyEntry(proxy, time.time() - t0)
                except Exception:
                    pass
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
            futs = [ex.submit(_test, p) for p in raw[:200]]
            for fut in concurrent.futures.as_completed(futs):
                entry = fut.result()
                if entry and len(scored) < 25:
                    scored.append(entry)

        scored.sort(key=lambda e: e.latency)
        with self._lock:
            self._pool    = scored
            self._loaded  = True
            self._loading = False

        if scored:
            avg = sum(e.latency for e in scored) / len(scored)
            logger.info(f"[Proxy] Elite pool ready: {len(scored)} proxies, avg {avg:.2f}s")
        else:
            print("[Proxy] No working proxies — direct connection only")

    def get_for(self, url: str) -> str | None:
        """
        Traffic-aware proxy selection:
        - OSM/Overpass/Nominatim: NO proxy (they don't block)
        - Company websites: NO proxy (rarely block, proxy slows down)
        - YellowPages/Google/DDG: YES proxy (they block by IP)
        Returns proxy URL string or None.
        """
        # Routes that should NOT use proxy
        no_proxy_domains = (
            "overpass-api.de", "overpass.kumi.systems",
            "nominatim.openstreetmap.org",
        )
        if any(d in url for d in no_proxy_domains):
            return None
        # Company websites (not directories) — direct is fine
        skip_dirs = ("yelp.com","yellowpages.com","google.com","duckduckgo.com")
        is_directory = any(d in url for d in skip_dirs)
        if not is_directory:
            # Check if it looks like a company site (has path beyond /)
            p = urlparse(url)
            if p.netloc and not any(d in p.netloc for d in skip_dirs):
                return None  # Company site — no proxy needed

        return self._get_next()

    def _get_next(self) -> str | None:
        with self._lock:
            now = time.time()
            active = [e for e in self._pool
                      if e.score > 0 and
                      not (hasattr(e, "_cooldown_until") and now < e._cooldown_until)]
            if not active: return None
            # Sticky: reuse current proxy up to STICKY_LIMIT
            if active and self._cur_idx < len(active):
                entry = active[self._cur_idx % len(active)]
                if entry.uses < self.STICKY_LIMIT:
                    entry.uses += 1
                    return entry.url
                # Rotate to next
                self._cur_idx = (self._cur_idx + 1) % len(active)
                entry = active[self._cur_idx]
                entry.uses = 1
                return entry.url
            return None

    def get(self) -> str | None:
        """Legacy compat — returns proxy or None."""
        return self._get_next()

    def report(self, proxy: str, success: bool, error: str = ""):
        """Update proxy health. Fatal = immediate removal. Timeout = cooldown."""
        if not proxy: return
        is_fatal   = any(fe in error for fe in _FATAL_PROXY_ERRORS)
        is_timeout = "timeout" in error.lower() or "timed out" in error.lower()
        with self._lock:
            for entry in self._pool:
                if entry.url == proxy:
                    if is_fatal:
                        entry.score = -99   # Circuit break — never retry
                        logger.info(f"[Proxy] Circuit broken: {proxy[7:30]}")
                    elif is_timeout:
                        # Timeout = cooling down, not dead — longer backoff
                        entry.score -= 2
                        entry._cooldown_until = time.time() + 60  # 60s cooldown
                    elif success:
                        entry.score = min(entry.score + 1, 5)
                        if hasattr(entry, "_cooldown_until"):
                            del entry._cooldown_until  # Clear cooldown on success
                    else:
                        entry.score -= 1
                    break
            # Remove permanently broken proxies
            self._pool = [e for e in self._pool if e.score > -10]

    def ban_for_domain(self, proxy: str, domain: str):
        """Ban a specific proxy from being used for a specific domain."""
        with self._lock:
            for entry in self._pool:
                if entry.url == proxy:
                    if not hasattr(entry, "_domain_bans"):
                        entry._domain_bans = set()
                    entry._domain_bans.add(domain)
                    break

    def mark_bad(self, proxy: str, error: str = ""):
        """Backwards compat."""
        self.report(proxy, False, error)

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._loaded and any(e.score > 0 for e in self._pool)

    def stats(self) -> str:
        with self._lock:
            active = sum(1 for e in self._pool if e.score > 0)
            return f"{active}/{len(self._pool)} proxies active"


# Global elite proxy pool
PROXY_MGR = ProxyManager()



OVERPASS_EPS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
TRADE_KW = {
    "HVAC": {
        "osm":    ["heating","hvac","furnace","cooling","air conditioning"],
        "yp":     "hvac+heating+cooling+contractor",
        "google": "HVAC contractor",
        "yelp":   "hvac",
    },
    "Electrical": {
        "osm":    ["electrician","electrical","electric"],
        "yp":     "electrician+electrical+contractor",
        "google": "electrical contractor",
        "yelp":   "electricians",
    },
    "Excavating": {
        "osm":    ["excavating","earthwork","grading","dirt work","excavation"],
        "yp":     "excavating+grading+earthwork+contractor",
        "google": "excavating grading contractor",
        "yelp":   "excavation services",
    },
}
TRADE_COLORS  = {"HVAC":"#10b981","Electrical":"#3b82f6","Excavating":"#f59e0b"}
SOURCE_COLORS = {"OSM":"#8b5cf6","YellowPages":"#f97316","Yelp":"#06b6d4",
                 "Google":"#34d399","Direct":"#94a3b8"}

# ── Theme ─────────────────────────────────────────────────────────────────────
STYLE = """
QMainWindow,QWidget{background:#0f1117;color:#e2e8f0;font-family:'Segoe UI',Arial;}
QGroupBox{border:1px solid #2a2d3e;border-radius:8px;margin-top:12px;padding:10px;font-size:11px;color:#94a3b8;}
QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 6px;color:#94a3b8;}
QLineEdit,QComboBox{background:#1a1d27;border:1px solid #2a2d3e;border-radius:6px;padding:5px 10px;color:#e2e8f0;font-size:13px;}
QLineEdit:focus,QComboBox:focus{border-color:#6366f1;}
QComboBox::drop-down{border:none;width:20px;}
QComboBox QAbstractItemView{background:#1a1d27;color:#e2e8f0;selection-background-color:#6366f1;}
QPushButton{background:#1a1d27;border:1px solid #2a2d3e;border-radius:6px;padding:6px 16px;color:#e2e8f0;font-size:13px;font-weight:500;}
QPushButton:hover{background:#2a2d3e;}
QPushButton:disabled{color:#94a3b8;}
QPushButton#searchBtn{background:#6366f1;border:none;color:white;font-weight:700;font-size:14px;}
QPushButton#searchBtn:hover{background:#4f52c9;}
QPushButton#searchBtn:disabled{background:#3a3d56;color:#94a3b8;}
QPushButton#stopBtn{background:#ef4444;border:none;color:white;font-weight:600;}
QPushButton#stopBtn:hover{background:#c53030;}
QPushButton#verifyBtn{background:#0ea5e9;border:none;color:white;font-weight:600;}
QPushButton#verifyBtn:hover{background:#0284c7;}
QPushButton#sheetsBtn{background:#16a34a;border:none;color:white;font-weight:600;}
QPushButton#sheetsBtn:hover{background:#15803d;}
QCheckBox{color:#e2e8f0;font-size:13px;spacing:6px;}
QCheckBox::indicator{width:15px;height:15px;border:1px solid #2a2d3e;border-radius:4px;background:#1a1d27;}
QCheckBox::indicator:checked{background:#6366f1;border-color:#6366f1;}
QProgressBar{border:none;border-radius:4px;background:#1a1d27;height:8px;}
QProgressBar::chunk{background:#6366f1;border-radius:4px;}
QTableWidget{background:#1a1d27;border:1px solid #2a2d3e;border-radius:8px;gridline-color:#2a2d3e;color:#e2e8f0;font-size:12px;selection-background-color:#2d3050;}
QTableWidget::item{padding:4px 8px;border-bottom:1px solid #2a2d3e;}
QTableWidget::item:selected{background:#2d3050;}
QHeaderView::section{background:#0f1117;color:#94a3b8;font-size:10px;font-weight:700;padding:7px 8px;border:none;border-bottom:1px solid #2a2d3e;}
QScrollBar:vertical{background:#1a1d27;width:7px;border-radius:4px;}
QScrollBar::handle:vertical{background:#2a2d3e;border-radius:4px;min-height:20px;}
QScrollBar:horizontal{background:#1a1d27;height:7px;border-radius:4px;}
QScrollBar::handle:horizontal{background:#2a2d3e;border-radius:4px;min-width:20px;}
QStatusBar{background:#0f1117;color:#94a3b8;font-size:12px;padding:4px 10px;}
QTextEdit{background:#1a1d27;border:1px solid #2a2d3e;border-radius:6px;color:#e2e8f0;}
"""

# ── Data ──────────────────────────────────────────────────────────────────────
@dataclass
class Contractor:
    trade:str=""; name:str=""; phone:str=""; email:str=""
    website:str=""; address:str=""; source:str=""
    email_status:str=""; place_id:str=""

# ── HTTP helpers (correct API, no deprecated warning) ─────────────────────────
def http_get(url: str, timeout=8, use_proxy=False) -> str:
    """
    Fast HTTP with browser fingerprint + smart proxy routing.
    Proxy auto-selected by URL type (directories get proxy, company sites don't).
    """
    proxy = PROXY_MGR.get_for(url) if (use_proxy and PROXY_MGR.ready) else None
    if not HAS_SCRAPLING:
        return _urllib_get(url, timeout)
    try:
        kwargs: dict = {"timeout": timeout}
        if proxy: kwargs["proxy"] = proxy
        r = Fetcher.get(url, **kwargs)
        body = r.body or ""
        result = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
        if proxy:
            PROXY_MGR.report(proxy, len(result) >= 200)
        return result
    except Exception as e:
        err = str(e)
        if proxy:
            PROXY_MGR.report(proxy, False, err)
        return _urllib_get(url, min(timeout, 8))

def _urllib_get(url: str, timeout=15) -> str:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"})
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""

def stealth_get(url: str, wait=3000, need_js=False) -> str:
    """Single stealth browser fetch. Always returns str."""
    if not HAS_SCRAPLING:
        return ""
    try:
        r = StealthyFetcher.fetch(
            url, headless=True, network_idle=True,
            disable_resources=not need_js, wait=wait
        )
        body = r.body or ""
        return body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
    except Exception as e:
        logger.warning(f"[stealth] {url[:50]}: {type(e).__name__}")
        return ""

def post_bytes(url: str, data: bytes, hdrs: dict) -> bytes:
    try:
        req = Request(url, data=data, headers=hdrs, method="POST")
        with urlopen(req, timeout=60) as r:
            return r.read()
    except Exception:
        return b""

# ── Contact extraction ────────────────────────────────────────────────────────
def _clean_email(e: str) -> str:
    return e.strip().strip(".,;:()[]{}<>\"'").lower()

# _ok_email defined in BAD_EMAIL block above

def _parse_phone(raw: str) -> str:
    """Normalize any phone string to (XXX) XXX-XXXX format."""
    d = re.sub(r"\D", "", raw)
    if len(d) >= 10:
        d = d[-10:]
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    return ""

def extract_contacts(html: str) -> tuple[str, str]:
    """
    Multi-strategy contact extraction:
    1. JSON-LD schema.org (most reliable for modern sites)
    2. Scrapling CSS selectors (mailto/tel links)
    3. Meta tags (some sites put contact in meta)
    4. Full text regex scan (fallback)
    """
    email = phone = ""
    if not html:
        return email, phone
    # Always work with str, never bytes
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="ignore")

    # ── Strategy 1: JSON-LD / schema.org ─────────────────────────────────────
    # Most modern contractor sites use LocalBusiness schema which has email+telephone
    for match in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                              html, re.DOTALL | re.IGNORECASE):
        try:
            import json as _j
            data = _j.loads(match.group(1))
            items = data if isinstance(data, list) else [data]
            for item in items:
                # Handle @graph wrapper
                sub_items = item.get("@graph", [item])
                for si in (sub_items if isinstance(sub_items, list) else [sub_items]):
                    if not email:
                        e = si.get("email","") or si.get("contactPoint",{}).get("email","") if isinstance(si.get("contactPoint"),dict) else ""
                        e = _clean_email(str(e)) if e else ""
                        if _ok_email(e): email = e
                    if not phone:
                        p = si.get("telephone","") or si.get("phone","")
                        if p: phone = _parse_phone(str(p)) or str(p)[:20]
            if email and phone: return email, phone
        except Exception:
            pass

    if HAS_SCRAPLING:
        page = Adaptor(html)

        # ── Strategy 2: mailto/tel links ──────────────────────────────────────
        for el in page.css("a[href*='mailto:']"):
            href = el.attrib.get("href", "")
            if "mailto:" in href:
                e = _clean_email(href.split("mailto:")[-1].split("?")[0])
                if _ok_email(e): email = e; break

        for el in page.css("a[href*='tel:']"):
            href = el.attrib.get("href", "")
            if "tel:" in href:
                p = _parse_phone(href.split("tel:")[-1])
                if p: phone = p; break

        # ── Strategy 3: meta tags ─────────────────────────────────────────────
        if not email:
            for el in page.css("meta[name*='email'], meta[property*='email']"):
                c = el.attrib.get("content","")
                e = _clean_email(c)
                if _ok_email(e): email = e; break

        # ── Strategy 4: structured data attributes ────────────────────────────
        if not email:
            for el in page.css("[itemprop='email'], [data-email]"):
                raw = el.text.strip() or el.attrib.get("content","") or el.attrib.get("data-email","")
                e = _clean_email(raw)
                if _ok_email(e): email = e; break
        if not phone:
            for el in page.css("[itemprop='telephone'], [data-phone]"):
                raw = el.text.strip() or el.attrib.get("content","") or el.attrib.get("data-phone","")
                if raw:
                    p = _parse_phone(raw)
                    if p: phone = p; break

        # ── Strategy 5: footer + contact section scan ─────────────────────────
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
                        if _ok_email(e): email = e; break
                if not phone:
                    m = PHONE_RE.search(sec_html)
                    if m: phone = m.group(1)
                if email and phone: break

        # ── Strategy 6: Cloudflare email obfuscation decode ─────────────────
        # CF encodes emails as hex in data-cfemail attribute on <a> tags
        if not email:
            for el in page.css("[data-cfemail]"):
                encoded = el.attrib.get("data-cfemail","")
                if encoded:
                    try:
                        # CF decode: XOR each byte with first byte
                        b = bytes.fromhex(encoded)
                        key = b[0]
                        decoded = "".join(chr(c ^ key) for c in b[1:])
                        e = _clean_email(decoded)
                        if _ok_email(e): email = e; break
                    except Exception:
                        pass

        # ── Strategy 7: Obfuscated email patterns in text ─────────────────────
        if not email:
            text = page.get_all_text(separator=" ")
            # Common obfuscation patterns
            obf_patterns = [
                r"([\w.+-]+)\s*\[at\]\s*([\w.-]+\.[a-z]{2,})",   # john [at] gmail.com
                r"([\w.+-]+)\s*\(at\)\s*([\w.-]+\.[a-z]{2,})",   # john(at)gmail.com
                r"([\w.+-]+)\s*AT\s*([\w.-]+\.[a-z]{2,})",       # john AT gmail.com
                r"([\w.+-]+)\s*@\s*([\w.-]+\.[a-z]{2,})",        # john @ gmail.com
            ]
            for pat in obf_patterns:
                m = re.search(pat, text, re.I)
                if m:
                    e = _clean_email(f"{m.group(1)}@{m.group(2)}")
                    if _ok_email(e): email = e; break

        # ── Strategy 8: full text fallback ───────────────────────────────────
        if not email or not phone:
            text = page.get_all_text(separator=" ") if not email else ""
            if text and not email:
                for raw in EMAIL_RE.findall(text):
                    e = _clean_email(raw)
                    if _ok_email(e): email = e; break
            if not phone:
                if not text: text = page.get_all_text(separator=" ")
                m = PHONE_RE.search(text)
                if m: phone = m.group(1)
    else:
        # No Scrapling — pure regex + obfuscation
        for raw in EMAIL_RE.findall(html):
            e = _clean_email(raw)
            if _ok_email(e): email = e; break
        # Check obfuscation
        if not email:
            for pat, grp in [
                (r"([\w.+-]+)\s*\[at\]\s*([\w.-]+\.[a-z]{2,})", lambda m: f"{m.group(1)}@{m.group(2)}"),
                (r"([\w.+-]+)\s*\(at\)\s*([\w.-]+\.[a-z]{2,})", lambda m: f"{m.group(1)}@{m.group(2)}"),
            ]:
                m = re.search(pat, html, re.I)
                if m:
                    e = _clean_email(grp(m))
                    if _ok_email(e): email = e; break
        m = PHONE_RE.search(html)
        if m: phone = m.group(1)

    return email, phone

# ── Shared async HTTP session (ONE session for all async requests) ────────────
_AIOHTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_AIOHTTP_TIMEOUT = None  # Set per-batch in enrich_batch_async

SCRAPE_SKIP = {"yellowpages.com","yelp.com","google.com","facebook.com",
               "scheduler.netic.ai","servicetitan.com","localsearch.com",
               "rwg_token","netic.ai"}

async def _fetch_one(session: "aiohttp.ClientSession", url: str, timeout,
                     use_proxy: bool = False) -> str:
    """
    Fetch one URL using the shared session.
    ssl=False ONLY when using a proxy (proxy needs MITM to intercept HTTPS).
    ssl=True (default) for direct connections — safer, HTTP/2, correct behavior.
    """
    proxy = PROXY_MGR.get_for(url) if (use_proxy and PROXY_MGR.ready) else None
    # ssl=False only when proxied — direct connections keep ssl validation
    ssl_mode = False if proxy else True
    try:
        kwargs: dict = {"timeout": timeout, "ssl": ssl_mode, "allow_redirects": True}
        if proxy: kwargs["proxy"] = proxy
        async with session.get(url, **kwargs) as resp:
            if resp.status in (200, 201, 206):
                if proxy: PROXY_MGR.report(proxy, True)
                return await resp.text(errors="ignore")
            if proxy: PROXY_MGR.report(proxy, resp.status == 200)
            return ""
    except Exception as e:
        err = str(e)
        if proxy: PROXY_MGR.report(proxy, False, err)
        if any(fe in err for fe in _FATAL_PROXY_ERRORS):
            return ""
        # If SSL error on direct connection, retry without SSL (some sites have bad certs)
        if not proxy and ("ssl" in err.lower() or "certificate" in err.lower()):
            try:
                async with session.get(url, timeout=timeout, ssl=False,
                                       allow_redirects=True) as resp:
                    if resp.status in (200, 201, 206):
                        return await resp.text(errors="ignore")
            except Exception:
                pass
        return ""

async def async_scrape_website(url: str, session: "aiohttp.ClientSession", timeout) -> tuple[str, str]:
    """
    Scrape a contractor website using the SHARED session (no session creation overhead).
    Checks homepage + up to 3 contact/about subpages.
    """
    if not url or any(s in url for s in SCRAPE_SKIP):
        return "", ""
    html = await _fetch_one(session, url, timeout)
    if not html:
        return "", ""
    email, phone = extract_contacts(html)
    if (not email or not phone) and HAS_SCRAPLING:
        page = Adaptor(html)
        hints = ("contact","about","team","reach","support")
        domain = urlparse(url).netloc
        sub_urls = []
        for el in page.css("a[href]"):
            href = el.attrib.get("href","").strip()
            if not href or href.startswith(("mailto:","tel:","#","javascript:")):
                continue
            abs_url = urljoin(url, href)
            p = urlparse(abs_url)
            if p.scheme not in {"http","https"} or p.netloc != domain:
                continue
            if any(h in p.path.lower() for h in hints):
                sub_urls.append(abs_url)
        # Add common contact page patterns directly — don't rely only on links found
        CONTACT_PATHS = ["/contact","/contact-us","/about","/about-us",
                         "/team","/company","/support","/reach-us","/get-in-touch"]
        direct_pages = []
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        for path in CONTACT_PATHS:
            cp = base + path
            if cp not in sub_urls: direct_pages.append(cp)

        for sub_url in (sub_urls[:2] + direct_pages[:4]):
            if email and phone: break
            sub_html = await _fetch_one(session, sub_url, timeout)
            if sub_html:
                se, sp = extract_contacts(sub_html)
                if not email: email = se
                if not phone: phone = sp
    return email, phone


async def enrich_batch_async(contractors: list, city_hint: str) -> None:
    """
    Async parallel enrichment. Uses ONE shared aiohttp.ClientSession for all requests.
    Semaphore limits concurrency. All sleeps are await asyncio.sleep (non-blocking).
    """
    if not HAS_AIOHTTP:
        return
    # Domain-specific semaphores prevent hammering any one target
    _sems = {
        "duckduckgo": asyncio.Semaphore(2),   # DDG is rate-sensitive
        "google":     asyncio.Semaphore(1),   # Google Maps = stealth only
        "yellowpages":asyncio.Semaphore(2),   # YP has Cloudflare
        "default":    asyncio.Semaphore(6),   # Company websites — generous
    }
    def _get_sem(url: str):
        for k, s in _sems.items():
            if k in url: return s
        return _sems["default"]

    timeout  = aiohttp.ClientTimeout(total=8, connect=4)
    conn     = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300,
                                    force_close=False, enable_cleanup_closed=True)

    async def _guess_domain(name: str, session: "aiohttp.ClientSession") -> str:
        """Try common domain patterns — zero rate limiting, no DDG needed."""
        clean = re.sub(r"[^a-z0-9]", "", name.lower())
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
                # ssl=True for HEAD check — no proxy needed for domain guessing
                async with session.head(url, timeout=t_short, ssl=True,
                                        allow_redirects=True) as r:
                    if r.status in (200, 301, 302, 304):
                        return str(r.url)
            except Exception:
                # Try ssl=False fallback (some .com sites have expired/bad certs)
                try:
                    async with session.head(url, timeout=t_short, ssl=False,
                                            allow_redirects=True) as r:
                        if r.status in (200, 301, 302, 304):
                            return str(r.url)
                except Exception:
                    pass
        return ""

    async def enrich_one(c, session: "aiohttp.ClientSession"):
        async with _get_sem(c.website or ""):
            # Step 1: Domain guessing (fast, uses shared session, no rate limits)
            if not c.website and c.name:
                guessed = await _guess_domain(c.name, session)
                if guessed: c.website = guessed
            # Step 2: DDG website lookup (only if domain guess failed)
            if not c.website and c.name:
                await asyncio.sleep(0.3)  # Non-blocking sleep
                q = quote_plus(f'"{c.name}" {city_hint} Michigan contractor')
                for _, url, _ in ddg_search(q, pages=1):
                    if url.startswith("http") and not any(d in url for d in SKIP_DOMAINS):
                        c.website = url; break
            # Step 3: Scrape website for phone+email (check cache first)
            if c.website and (not c.email or not c.phone):
                cache_key = _domain_key(c.website)
                cached_contact = CACHE.get_contact(cache_key) if cache_key else None
                if cached_contact:
                    if not c.email:   c.email   = cached_contact.get("email","")
                    if not c.phone:   c.phone   = cached_contact.get("phone","")
                    if not c.website: c.website = cached_contact.get("website","")
                else:
                    we, wp = await async_scrape_website(c.website, session, timeout)
                    if not c.email: c.email = we
                    if not c.phone: c.phone = wp
                    # Cache result for future searches
                    if cache_key and (we or wp):
                        CACHE.set_contact(cache_key, we, wp, c.website)
            # Step 4: Email pattern guessing from domain
            # Try common prefixes: info@, service@, contact@ etc.
            # Much faster than DDG and no rate limiting
            if not c.email and c.website:
                domain = urlparse(c.website).netloc.replace("www.","").split(":")[0]
                if domain:
                    # Verify MX exists before guessing (non-blocking via asyncio.to_thread)
                    has_mx = True
                    if HAS_DNS:
                        try:
                            # asyncio.to_thread prevents blocking the event loop
                            await asyncio.to_thread(_dns.resolve, domain, "MX")
                        except Exception:
                            has_mx = False
                    if has_mx:
                        prefixes = ["info","contact","service","office","admin","support","hello"]
                        for prefix in prefixes:
                            candidate = f"{prefix}@{domain}"
                            if _ok_email(candidate):
                                c.email = candidate
                                break

            # Step 5: DDG email hunt completely removed
            # Per logs: returns 202 (rate-limited) for virtually every OSM query
            # OSM businesses without websites are mostly inactive — skip them
            # YP/Google already provide phone; email comes from website scraping

    # ONE session for all contractors in this batch
    async with aiohttp.ClientSession(
        headers=_AIOHTTP_HEADERS,
        connector=conn,
        timeout=timeout
    ) as session:
        # asyncio.as_completed() is safer than gather():
        # - isolates exceptions per task (one failure doesn't kill others)
        # - prevents memory spikes from all tasks starting simultaneously
        # - allows streaming results as they complete
        tasks = [asyncio.create_task(enrich_one(c, session)) for c in contractors]
        for coro in asyncio.as_completed(tasks):
            try:
                await coro
            except Exception as e:
                logger.debug(f"[Enrich] task error: {type(e).__name__}: {e}")


def scrape_website(url: str) -> tuple[str, str]:
    """
    Multi-page website scraper for phone + email.
    Priority: JSON-LD → mailto/tel → meta → structured data → footer → full text
    Checks homepage + contact/about/team subpages.
    """
    if not url:
        return "", ""
    # Skip known directories and booking sites
    skip = {"yellowpages.com","yelp.com","google.com","facebook.com",
            "scheduler.netic.ai","servicetitan.com","localsearch.com"}
    if any(s in url for s in skip):
        return "", ""
    html = http_get(url, timeout=12)
    if not html:
        return "", ""
    email, phone = extract_contacts(html)
    # Check up to 4 contact/about/team subpages
    if (not email or not phone) and HAS_SCRAPLING:
        page = Adaptor(html)
        hints = ("contact","about","team","reach","support","service","us")
        domain = urlparse(url).netloc
        visited = {url}
        ranked: list[tuple[int,str]] = []
        for el in page.css("a[href]"):
            href = el.attrib.get("href","").strip()
            if not href or href.startswith(("mailto:","tel:","#","javascript")):
                continue
            abs_url = urljoin(url, href)
            p = urlparse(abs_url)
            if p.scheme not in {"http","https"} or p.netloc != domain:
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
            if not email: email = se
            if not phone: phone = sp
    return email, phone

# ── DDG search helper ─────────────────────────────────────────────────────────
def _ddg_decode(href: str) -> str:
    """Decode DDG redirect: //duckduckgo.com/l/?uddg=ENCODED_URL → real URL"""
    if "uddg=" in href:
        try:
            return unquote(href.split("uddg=")[1].split("&")[0])
        except Exception:
            pass
    return href

# Global DDG rate limiter — prevents 202/403 from rapid-fire requests
_DDG_LOCK = threading.Lock()
_DDG_REQ_TIMES: list[float] = []
_DDG_MAX_PER_MIN = 12  # Max DDG requests per 60 seconds

def _ddg_rate_limit():
    """Pause if we're making too many DDG requests. Prevents 202/403 blocking."""
    with _DDG_LOCK:
        now = time.time()
        # Remove requests older than 60 seconds
        while _DDG_REQ_TIMES and now - _DDG_REQ_TIMES[0] > 60:
            _DDG_REQ_TIMES.pop(0)
        if len(_DDG_REQ_TIMES) >= _DDG_MAX_PER_MIN:
            wait = 65 - (now - _DDG_REQ_TIMES[0])
            if wait > 0:
                logger.debug(f"[DDG] Rate limit pause: {wait:.0f}s")
                time.sleep(wait)
        # Also add minimum gap of 1.5s between requests
        if _DDG_REQ_TIMES:
            gap = time.time() - _DDG_REQ_TIMES[-1]
            if gap < 1.5:
                time.sleep(1.5 - gap)
        _DDG_REQ_TIMES.append(time.time())

def ddg_search(query: str, pages: int = 2) -> list[tuple[str, str, str]]:
    """
    Search DuckDuckGo HTML endpoint. Rate-limited to prevent 202/403 blocking.
    Returns (title, real_url, snippet). Results cached for 24h.
    """
    # Check cache first — avoids re-hitting DDG for same query
    cached = CACHE.get_ddg(query)
    if cached is not None:
        return [tuple(r) for r in cached]

    results = []
    for page_idx in range(pages):
        _ddg_rate_limit()
        dc = f"&dc={page_idx * 11}" if page_idx > 0 else ""
        url = f"https://html.duckduckgo.com/html/?q={query}{dc}"
        html = http_get(url, timeout=15, use_proxy=True)
        if not html or not HAS_SCRAPLING:
            break
        if len(html) < 200:  # 202 rate limit returns near-empty response
            logger.debug(f"[DDG] Rate-limited (short response), backing off 20s")
            time.sleep(20)
            break
        page = Adaptor(html)
        found = 0
        for card in page.css("div.result"):
            title_els = card.css("a.result__a")
            if not title_els:
                continue
            name = title_els[0].text.strip()
            raw_href = title_els[0].attrib.get("href", "")
            real_url = _ddg_decode(raw_href)
            snippet = ""
            snip_els = card.css("a.result__snippet")
            if snip_els:
                snippet = snip_els[0].get_all_text(separator=" ")
            if name and real_url:
                results.append((name, real_url, snippet))
                found += 1
        if found == 0:
            break
    if results:
        CACHE.set_ddg(query, [(n,u,s) for n,u,s in results])
    return results

# ── OSM ───────────────────────────────────────────────────────────────────────
def geocode(location: str) -> tuple[float, float]:
    url = (f"https://nominatim.openstreetmap.org/search"
           f"?q={quote_plus(location)}&format=jsonv2&limit=1&countrycodes=us")
    html = http_get(url, timeout=30)
    if not html:
        raise RuntimeError(f"Cannot geocode: {location}")
    data = json.loads(html)
    if not data:
        raise RuntimeError(f"Location not found: {location}")
    return float(data[0]["lat"]), float(data[0]["lon"])

def scrape_osm(trade: str, lat: float, lon: float, radius_m: int, limit: int) -> list[Contractor]:
    kw = TRADE_KW[trade]["osm"]
    regex = "|".join(re.escape(k) for k in kw)
    q = (f'[out:json][timeout:90];'
         f'(nwr(around:{radius_m},{lat},{lon})["name"~"{regex}",i];'
         f'nwr(around:{radius_m},{lat},{lon})["shop"~"hvac|electrical|heating",i];'
         f'nwr(around:{radius_m},{lat},{lon})["craft"~"electrician|hvac|excavation",i];'
         f'nwr(around:{radius_m},{lat},{lon})["trade"~"electrician|hvac|excavation",i];'
         f');out center tags;')
    payload = f"data={quote_plus(q)}".encode()
    hdrs = {"User-Agent": "ContractorFinder/3.0",
            "Content-Type": "application/x-www-form-urlencoded"}
    elements = []
    for ep in OVERPASS_EPS:
        raw = post_bytes(ep, payload, hdrs)
        if raw:
            try:
                elements = json.loads(raw).get("elements", [])
                break
            except Exception:
                continue

    # Nominatim search — use short keywords (not "heating contractor" which finds nothing)
    # Search for "hvac", "heating", "electrician" etc. as business name fragments
    for kword in kw[:3]:
        if len(elements) >= limit * 3:
            break
        try:
            nm_url = (f"https://nominatim.openstreetmap.org/search"
                      f"?q={quote_plus(kword)}"
                      f"&format=jsonv2&limit=50&addressdetails=1&countrycodes=us"
                      f"&viewbox={lon-1.0},{lat-1.0},{lon+1.0},{lat+1.0}&bounded=1")
            nm_html = http_get(nm_url, timeout=15)
            if nm_html:
                places = json.loads(nm_html)
                for p in places:
                    name = (p.get("name") or "").strip()
                    if not name:
                        continue
                    # Filter industrial/non-contractor results
                    bad = ["slag","subdivision","blast furnace","heating plant",
                           "boiler plant","distribution","manufacturing"]
                    ok_words = ["heating","cooling","hvac","air","electric","excavat",
                                "grading","plumb","mechanical","service","refriger"]
                    if any(b in name.lower() for b in bad):
                        continue
                    if not any(b in name.lower() for b in ok_words):
                        continue
                    # Convert to fake Overpass element format
                    ap = p.get("address", {})
                    elements.append({
                        "type": "nominatim",
                        "id": p.get("place_id", ""),
                        "tags": {
                            "name": name,
                            "addr:housenumber": ap.get("house_number", ""),
                            "addr:street": ap.get("road", ""),
                            "addr:city": ap.get("city") or ap.get("town", ""),
                            "addr:state": ap.get("state", ""),
                            "addr:postcode": ap.get("postcode", ""),
                        }
                    })
        except Exception:
            pass

    out = []
    seen: set[str] = set()
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name or len(name) < 2:
            continue
        pid = f"osm:{el.get('type','')}:{el.get('id','')}"
        if pid in seen:
            continue
        seen.add(pid)
        addr = ", ".join(filter(None, [
            tags.get("addr:housenumber", ""),
            tags.get("addr:street", ""),
            tags.get("addr:city", ""),
            tags.get("addr:state", ""),
            tags.get("addr:postcode", ""),
        ]))
        out.append(Contractor(
            trade=trade, name=name,
            phone=tags.get("phone") or tags.get("contact:phone", ""),
            website=tags.get("website") or tags.get("contact:website", ""),
            email=tags.get("email") or tags.get("contact:email", ""),
            address=addr, source="OSM", place_id=pid
        ))
        if len(out) >= limit:
            break
    logger.info(f"[OSM] {trade}: {len(out)} results")
    return out

# ── Yellow Pages (StealthySession — persistent browser for multi-page) ────────
def scrape_yellowpages(trade: str, location: str, limit: int) -> list[Contractor]:
    """
    Uses StealthySession to keep ONE browser open for all YP pages.
    Per Scrapling docs: sessions are much faster than opening a new browser per request.
    """
    out: list[Contractor] = []
    term = TRADE_KW[trade]["yp"]
    loc  = quote_plus(location)
    if not HAS_SCRAPLING:
        return out

    def _is_cloudflare(html) -> bool:
        if not html: return True
        if isinstance(html, bytes): html = html.decode("utf-8", errors="ignore")
        return ("cf-browser-verification" in html
                or "Checking your browser" in html
                or len(html) < 500)

    for attempt in range(3):  # retry up to 3 times on Cloudflare block
        out = []
        try:
            with StealthySession(headless=True, network_idle=True,
                                 disable_resources=False) as session:
                for pg in range(1, 6):
                    if len(out) >= limit:
                        break
                    url = f"https://www.yellowpages.com/search?search_terms={term}&geo_location_terms={loc}&page={pg}"
                    try:
                        resp = session.fetch(url, wait=4000)
                        html = resp.body or ""
                    except Exception as e:
                        logger.info(f"[YP] page {pg} error: {type(e).__name__}")
                        break
                    if not html or _is_cloudflare(html):
                        logger.info(f"[YP] Cloudflare on page {pg}, attempt {attempt+1}/3")
                        time.sleep(3 + attempt * 2)
                        break
                    page = Adaptor(html)
                    # YP listing cards — multiple selector strategies
                    cards = (page.css("div.srp-listing") or
                             page.css("div.result") or
                             page.css("div[class*='listing']") or
                             page.css("article"))
                    if not cards:
                        logger.info(f"[YP] No cards on page {pg} (status {resp.status})")
                        break
                    found = 0
                    for card in cards:
                        if len(out) >= limit:
                            break
                        name = ""
                        for sel in ["h2.n a", "a.business-name", "h2 a", ".business-name span",
                                    "a[class*='business'] span", "h3 a"]:
                            els = card.css(sel)
                            if els:
                                name = els[0].text.strip()
                                if name: break
                        if not name or len(name) < 2:
                            continue
                        phone = ""
                        for sel in ["div.phones.phone.primary", "div.phones", ".phone",
                                    "[class*='phone']"]:
                            els = card.css(sel)
                            if els: phone = els[0].text.strip(); break
                        if not phone:
                            m = PHONE_RE.search(card.get_all_text(separator=" "))
                            if m: phone = m.group(1)
                        website = ""
                        for sel in ["a.track-visit-website", "a[class*='website']",
                                    "a[href^='http']:not([href*='yellowpages'])"]:
                            els = card.css(sel)
                            if els:
                                h = els[0].attrib.get("href", "")
                                if h.startswith("http") and "yellowpages" not in h:
                                    website = h; break
                        address = ""
                        for sel in ["p.adr", "address", ".address", "[class*='address']"]:
                            els = card.css(sel)
                            if els:
                                address = els[0].get_all_text(separator=" ").strip(); break
                        out.append(Contractor(trade=trade, name=name, phone=phone,
                            website=website, address=address, source="YellowPages"))
                        found += 1
                    logger.info(f"[YP] page {pg}: {found} found (total {len(out)})")
                    if found == 0:
                        break
                    time.sleep(1.5)
        except Exception as e:
            logger.info(f"[YP] Session error attempt {attempt+1}: {type(e).__name__}: {e}")
            time.sleep(2)
            continue
        if out:
            break  # Got results — no need to retry
        logger.info(f"[YP] Attempt {attempt+1} got 0 results, retrying...")
        time.sleep(3)

    logger.info(f"[YP] {trade}: {len(out)} total")
    return out[:limit]

def _extract_yelp_website(page: "Adaptor") -> str:
    """
    Extract the REAL company website from a Yelp business page.
    Yelp hides outbound links behind biz_redir redirects.
    Example: https://www.yelp.com/biz_redir?url=https%3A%2F%2Facmehvac.com&...
    """
    from urllib.parse import parse_qs
    for el in page.css("a[href*='biz_redir']"):
        href = el.attrib.get("href","")
        if not href: continue
        try:
            qs = parse_qs(urlparse(href).query)
            real = unquote(qs.get("url",[""])[0])
            if real.startswith("http") and not any(d in real for d in SCRAPE_SKIP):
                return real
        except Exception:
            pass
    # Fallback: look for website link with external icon
    for el in page.css("a[href^='http']:not([href*='yelp.com'])"):
        href = el.attrib.get("href","")
        if href and "yelp" not in href:
            return href
    return ""

# ── Yelp — StealthySession (same approach as YellowPages) ───────────────────
def scrape_yelp(trade: str, location: str, limit: int) -> list[Contractor]:
    """
    Uses ONE persistent StealthySession browser for all Yelp pages.
    Bypasses Yelp anti-bot via patchright (same as YellowPages).
    Pipeline: Yelp search → extract name/phone/website → website scraper finds email.
    Yelp is discovery-only — no DDG, no email hunting from Yelp itself.
    """
    out: list[Contractor] = []
    if not HAS_SCRAPLING:
        return out
    seen: set[str] = set()
    keyword  = TRADE_KW[trade]["yelp"]
    city_raw = location.split(",")[0].strip()
    state    = "MI" if "mi" in location.lower() else location.split(",")[-1].strip()[:2].upper()

    # Check cache first
    cache_key = f"yelp_{trade}_{city_raw}".lower()
    cached = CACHE.get_ddg(cache_key)
    if cached:
        logger.info(f"[Yelp] {trade}: {len(cached)} results from cache")
        return [Contractor(**r) for r in cached if isinstance(r, dict)][:limit]

    def _parse_yelp_page(html: str) -> list[Contractor]:
        """Parse contractors from a Yelp search results page."""
        results = []
        if not html or len(html) < 500: return results
        page = Adaptor(html)

        # Yelp search result cards (multiple selector strategies for resilience)
        cards = (page.css("li[class*='businessList']") or
                 page.css("div[data-testid*='serp']") or
                 page.css("ul > li[class*='css-']") or
                 page.css("div[class*='container__']"))

        for card in cards:
            if len(results) >= limit: break
            # Name
            name = ""
            for sel in ["a[class*='businessName'] span", "h3 a span",
                        "span[class*='display-name']", "a[name] span", "h3 span"]:
                els = card.css(sel)
                if els:
                    name = els[0].text.strip()
                    if name and len(name) > 2: break
            if not name or len(name) < 2 or name in seen: continue
            bad = ["Top ","Best ","Near ","Yelp","Results","Reviews in","Sponsored"]
            if any(w in name for w in bad): continue
            seen.add(name)

            # Phone
            phone = ""
            for sel in ["p[class*='css-1p9ibgf']", "[class*='secondaryAttributes'] p",
                        "span[class*='raw-css']", "p[class*='lemon']"]:
                els = card.css(sel)
                if els:
                    p = _parse_phone(els[0].text.strip())
                    if p: phone = p; break
            if not phone:
                m = PHONE_RE.search(card.get_all_text(separator=" "))
                if m: phone = m.group(1)

            # Real website via biz_redir decoding
            website = _extract_yelp_website(card)

            # Address
            address = ""
            for sel in ["address", "p[class*='css-qgunke']", "[class*='secondaryAttributes'] address"]:
                els = card.css(sel)
                if els:
                    address = els[0].get_all_text(separator=" ").strip()[:100]; break

            results.append(Contractor(trade=trade, name=name, phone=phone,
                website=website, address=address, source="Yelp"))
        return results

    # StealthySession: one persistent browser for all Yelp pages
    term = quote_plus(keyword)
    loc  = quote_plus(f"{city_raw}, {state}")

    try:
        with StealthySession(headless=True, network_idle=True,
                             disable_resources=False) as session:
            for pg in range(0, min(limit, 90), 10):  # Yelp paginates by 10
                if len(out) >= limit: break
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
                if len(batch) < 5: break  # Last page
                time.sleep(2.0)  # Be polite — Yelp is aggressive
    except Exception as e:
        logger.error(f"[Yelp] Session error: {type(e).__name__}: {e}")

    out = out[:limit]
    # Cache results
    if out:
        import json as _j
        CACHE.set_ddg(cache_key, [asdict(c) for c in out])
    logger.info(f"[Yelp] {trade}: {len(out)} total")
    return out



# ── Google Maps — StealthySession with scroll for more results ────────────────
def scrape_google(trade: str, location: str, limit: int) -> list[Contractor]:
    """
    StealthySession for Google Maps:
    - One persistent browser (no repeated launches)
    - Waits for div[role='feed'] to fully render
    - Scrolls down to load more results
    - Multiple selector strategies for resilience
    """
    out: list[Contractor] = []
    if not HAS_SCRAPLING:
        return out

    term = quote_plus(f"{TRADE_KW[trade]['google']} near {location}")
    url  = f"https://www.google.com/maps/search/{term}"

    try:
        with StealthySession(headless=True, network_idle=True,
                             disable_resources=False) as session:
            # Initial load — wait for feed to render
            try:
                resp = session.fetch(url, wait=6000)
                raw  = resp.body or b""
                html = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
            except Exception as e:
                logger.warning(f"[Google] Initial load error: {type(e).__name__}")
                return out

            if not html:
                return out

            page = Adaptor(html)

            # Strategy 1: div[role='feed'] — the main Google Maps results list
            feed = page.css("div[role='feed']")
            if feed:
                items = feed[0].css("div[aria-label]")
                for el in items:
                    if len(out) >= limit: break
                    label = el.attrib.get("aria-label","").strip()
                    if not label or len(label) < 2: continue
                    name = label.split("·")[0].strip()
                    skip = ["search","result","map","back","menu","list","view","zoom","more","filter"]
                    if any(w in name.lower() for w in skip) or len(name) < 2: continue

                    txt = el.get_all_text(separator="\n")
                    # Phone
                    phone = ""
                    m = PHONE_RE.search(txt)
                    if m: phone = m.group(1)
                    # Address
                    address = ""
                    addr_m = ADDR_RE.search(txt)
                    if addr_m: address = addr_m.group(0).strip()
                    # Website
                    website = ""
                    for lel in el.css("a[href^='http']:not([href*='google'])"):
                        h = lel.attrib.get("href","")
                        if h and "google" not in h and "gstatic" not in h:
                            website = h; break

                    out.append(Contractor(trade=trade, name=name, phone=phone,
                        website=website, address=address, source="Google"))

            # Strategy 2: JSON data embedded in page scripts
            if not out:
                for s in page.css("script"):
                    txt = s.text or ""
                    matches = re.findall(
                        r'"([A-Z][A-Za-z\s&\.]{5,50}'
                        r'(?:HVAC|Electric|Heating|Cooling|Excavat|Grading|Plumb)'
                        r'[A-Za-z\s&\.]{0,30})"', txt)
                    for m in matches[:limit]:
                        if m not in [c.name for c in out]:
                            out.append(Contractor(trade=trade, name=m, source="Google"))
                    if out: break

    except Exception as e:
        logger.error(f"[Google] Session error: {type(e).__name__}: {e}")

    logger.info(f"[Google] {trade}: {len(out)} results")
    return out[:limit]


# ── Dedup ─────────────────────────────────────────────────────────────────────
def _name_key(name: str) -> str:
    s = name.lower()
    for suf in [" llc"," inc"," co"," corp"," ltd"," services"," company",
                " heating"," cooling"," hvac"," electric"," plumbing"," excavating"]:
        s = s.replace(suf, " ")
    return re.sub(r"[^a-z0-9]", "", s).strip()

def _similar(a: str, b: str) -> bool:
    ka, kb = _name_key(a), _name_key(b)
    if not ka or not kb: return False
    if ka == kb: return True
    short, long = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if len(short) >= 8 and short in long: return True
    match = sum(1 for x,y in zip(ka,kb) if x==y)
    min_len = min(len(ka), len(kb))
    return min_len >= 6 and match / min_len >= 0.85

def _domain_key(website: str) -> str:
    """Extract root domain for comparison."""
    if not website: return ""
    try:
        p = urlparse(website)
        d = p.netloc.lower().replace("www.","")
        return d.split(":")[0]
    except Exception:
        return ""

def _phone_key(phone: str) -> str:
    """Normalize phone to digits for comparison."""
    d = re.sub(r"[^0-9]","",phone or "")
    return d[-10:] if len(d) >= 10 else ""

def dedup(rows: list[Contractor]) -> list[Contractor]:
    """
    Smart dedup using name similarity + phone + domain.
    Merges data from duplicates (keeps best record, fills missing fields).
    """
    # Sort: most data first (phone + email + website each count)
    sorted_rows = sorted(rows,
        key=lambda r: -(bool(r.phone)*2 + bool(r.email)*3 + bool(r.website)*2))
    out: list[Contractor] = []
    for r in sorted_rows:
        is_dup = False
        r_phone  = _phone_key(r.phone)
        r_domain = _domain_key(r.website)
        for ex in out:
            name_match   = _similar(r.name, ex.name)
            phone_match  = bool(r_phone  and r_phone  == _phone_key(ex.phone))
            domain_match = bool(r_domain and r_domain == _domain_key(ex.website))
            # Duplicate if: names similar OR same phone OR same domain
            if name_match or phone_match or domain_match:
                if not ex.phone   and r.phone:   ex.phone   = r.phone
                if not ex.email   and r.email:   ex.email   = r.email
                if not ex.website and r.website: ex.website = r.website
                if not ex.address and r.address: ex.address = r.address
                is_dup = True; break
        if not is_dup: out.append(r)
    return out

# ── Email verification ────────────────────────────────────────────────────────
def verify_email(email: str) -> tuple[str, str]:
    """
    Email verification via syntax + MX record ONLY.
    SMTP RCPT TO removed: unreliable in 2026 (tarpitting, greylisting, catch-all).
    MX existence + valid syntax is the commercial standard.
    """
    # Step 1: Syntax check
    if not re.match(r'^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$', email, re.I):
        return "invalid", "Bad syntax"
    if not _ok_email(email):
        return "invalid", "Filtered (spam/CDN pattern)"
    domain = email.split("@")[1].lower()

    # Step 2: MX record check (domain exists and accepts email)
    if not HAS_DNS:
        return "unknown", "dnspython not installed"
    try:
        mx_records = _dns.resolve(domain, "MX")
        if mx_records:
            return "valid", f"MX verified ({len(mx_records)} records)"
    except _dns.NXDOMAIN:
        return "invalid", "Domain doesn't exist"
    except _dns.NoAnswer:
        # Try A record as fallback (some small domains skip MX)
        try:
            _dns.resolve(domain, "A")
            return "unknown", "No MX but domain exists"
        except Exception:
            return "invalid", "No MX or A record"
    except Exception as e:
        return "unknown", f"DNS: {type(e).__name__}"
    return "unknown", "Unexpected"

# ── Master search ─────────────────────────────────────────────────────────────
SRC_FN = {
    "YellowPages": scrape_yellowpages,
    "Yelp":        scrape_yelp,
    "Google":      scrape_google,
}

def run_search(location, trades, limit, radius_m, enrich,
               sources, progress_cb, result_cb, done_cb, stop_ev):
    try:
        progress_cb(0, "Geocoding location...")
        lat, lon = geocode(location)
    except Exception as e:
        done_cb(False, str(e))
        return

    total = len(trades) * len(sources)
    step  = 0

    for trade in trades:
        if stop_ev.is_set():
            break
        collected: list[Contractor] = []

        for src in sources:
            if stop_ev.is_set():
                break
            step += 1
            pct = int(step / total * 70)
            progress_cb(pct, f"[{src}] Searching {trade} near {location}...")
            try:
                if src == "OSM":
                    batch = scrape_osm(trade, lat, lon, radius_m, limit)
                else:
                    batch = SRC_FN[src](trade, location, limit)
                collected.extend(batch)
                progress_cb(pct, f"[{src}] {trade}: {len(batch)} found")
            except Exception as e:
                logger.info(f"[{src}] {trade} error: {e}")

        collected = dedup(collected)
        city_hint = location.split(",")[0].strip()

        # Fix URL-encoded emails up front
        for c in collected:
            if c.email and "%" in c.email:
                from urllib.parse import unquote as _uq
                decoded = _clean_email(_uq(c.email))
                if _ok_email(decoded): c.email = decoded

        if enrich and collected:
            # Async batch enrichment in chunks of 15
            # Scrapes 15 websites in parallel — 8x faster than sequential
            BATCH = 15
            total = len(collected)
            for batch_start in range(0, total, BATCH):
                if stop_ev.is_set(): break
                batch = collected[batch_start:batch_start + BATCH]
                pct = int(70 + (batch_start / max(total, 1)) * 25)
                progress_cb(pct,
                    f"[{trade}] Enriching {batch_start+1}-"
                    f"{min(batch_start+BATCH, total)}/{total} (async x{len(batch)})...")
                if HAS_AIOHTTP:
                    try:
                        loop = get_event_loop()
                        loop.run_until_complete(enrich_batch_async(batch, city_hint))
                    except Exception as e:
                        logger.error(f"[Async] batch error: {e}")
                        for c in batch:
                            if not c.website and c.name:
                                q = quote_plus(f'"{c.name}" {city_hint} Michigan contractor')
                                for _, url, _ in ddg_search(q, pages=1):
                                    if url.startswith("http") and not any(d in url for d in SKIP_DOMAINS):
                                        c.website = url; break
                            if c.website and (not c.email or not c.phone):
                                we, wp = scrape_website(c.website)
                                if not c.email: c.email = we
                                if not c.phone: c.phone = wp
                else:
                    for c in batch:
                        if not c.website and c.name:
                            q = quote_plus(f'"{c.name}" {city_hint} Michigan contractor')
                            for _, url, _ in ddg_search(q, pages=1):
                                if url.startswith("http") and not any(d in url for d in SKIP_DOMAINS):
                                    c.website = url; break
                        if c.website and (not c.email or not c.phone):
                            we, wp = scrape_website(c.website)
                            if not c.email: c.email = we
                            if not c.phone: c.phone = wp

        for c in collected:
            if stop_ev.is_set(): break
            result_cb(c)

    done_cb(True, "")

# ── Workers ───────────────────────────────────────────────────────────────────
class SearchWorker(QThread):
    progress = Signal(int, str)
    result   = Signal(object)
    finished = Signal(bool, str)

    def __init__(self, location, trades, limit, radius_m, enrich, sources):
        super().__init__()
        self.location = location
        self.trades   = trades
        self.limit    = limit
        self.radius_m = radius_m
        self.enrich   = enrich
        self.sources  = sources
        self._stop    = threading.Event()

    def run(self):
        run_search(self.location, self.trades, self.limit, self.radius_m,
                   self.enrich, self.sources,
                   self.progress.emit, self.result.emit, self.finished.emit, self._stop)

    def stop(self):
        self._stop.set()


class VerifyWorker(QThread):
    progress = Signal(int, str)
    result   = Signal(int, str, str)
    finished = Signal()

    def __init__(self, rows):
        super().__init__()
        self.rows  = rows
        self._stop = threading.Event()

    def run(self):
        total = len(self.rows)
        for i, c in enumerate(self.rows):
            if self._stop.is_set():
                break
            self.progress.emit(int(i / total * 100),
                               f"Verifying {i+1}/{total}: {c.email or '(no email)'}...")
            status, reason = verify_email(c.email) if c.email else ("unknown", "No email")
            c.email_status = status
            self.result.emit(i, status, reason)
            time.sleep(0.3)
        self.finished.emit()

    def stop(self):
        self._stop.set()

# ── Stat card ─────────────────────────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, label, color):
        super().__init__()
        self.setStyleSheet("background:#1a1d27;border:1px solid #2a2d3e;border-radius:8px;")
        self.setMinimumWidth(90)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(1)
        self.num = QLabel("0")
        self.num.setStyleSheet(f"color:{color};border:none;font-size:22px;font-weight:700;")
        lbl = QLabel(label.upper())
        lbl.setStyleSheet("color:#94a3b8;font-size:9px;font-weight:700;border:none;")
        lay.addWidget(self.num)
        lay.addWidget(lbl)

    def set(self, n):
        self.num.setText(str(n))

# ── Main window ───────────────────────────────────────────────────────────────
VERIFY_COLORS = {"valid":"#10b981","invalid":"#ef4444","unknown":"#94a3b8","":"#94a3b8"}
VERIFY_ICONS  = {"valid":"✅","invalid":"❌","unknown":"❓","":""}
COLS = ["Trade","Source","Company Name","Phone","Email","Email Status","Website","Address","Note"]

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contractor Finder v3  ·  Scrapling Powered")
        self.resize(1300, 820)
        self.rows: list[Contractor] = []
        self.worker = None
        self.vworker = None
        self._build()

    def _lbl(self, txt):
        l = QLabel(txt)
        l.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:600;")
        return l

    def _build(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
        root.setContentsMargins(18, 12, 18, 8)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        t = QLabel("Contractor Finder")
        t.setStyleSheet("font-size:18px;font-weight:700;")
        hdr.addWidget(t)
        sub = QLabel("  v3  ·  Phone · Email · Website  ·  USA Locations")
        sub.setStyleSheet("color:#94a3b8;font-size:11px;")
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)

        # Search params
        sg = QGroupBox("Search Parameters")
        sl = QVBoxLayout(sg)
        sl.setSpacing(8)

        r1 = QHBoxLayout()
        r1.setSpacing(10)
        lc = QVBoxLayout()
        lc.addWidget(self._lbl("Location (US City, State or ZIP)"))
        self.loc = QComboBox()
        self.loc.setEditable(True)
        self.loc.setFixedHeight(34)
        self.loc.setInsertPolicy(QComboBox.InsertAtTop)
        # Load search history
        _hist = SEARCH_HISTORY.load()
        default = "Warren, MI 48091"
        all_locs = [default] + [h for h in _hist if h != default]
        for loc in all_locs:
            self.loc.addItem(loc)
        self.loc.setCurrentText(default)
        self.loc.lineEdit().returnPressed.connect(self.start_search)
        lc.addWidget(self.loc)
        r1.addLayout(lc, 3)

        rc = QVBoxLayout()
        rc.addWidget(self._lbl("Radius"))
        self.radius = QComboBox()
        self.radius.setFixedHeight(34)
        self.rmap = {"10 mi":"10000","25 mi":"25000","40 mi":"40000",
                     "60 mi":"60000","80 mi":"80000"}
        for k in self.rmap:
            self.radius.addItem(k)
        self.radius.setCurrentIndex(2)
        rc.addWidget(self.radius)
        r1.addLayout(rc, 1)

        pc = QVBoxLayout()
        pc.addWidget(self._lbl("Per Trade/Source"))
        self.per = QComboBox()
        self.per.setFixedHeight(34)
        for n in ["10","20","30","40","50"]:
            self.per.addItem(n)
        self.per.setCurrentIndex(2)
        pc.addWidget(self.per)
        r1.addLayout(pc, 1)
        sl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(self._lbl("Trades:"))
        self.chk_t: dict[str, QCheckBox] = {}
        for t, col in TRADE_COLORS.items():
            cb = QCheckBox(t)
            cb.setChecked(True)
            cb.setStyleSheet(f"color:{col};font-weight:700;font-size:13px;")
            self.chk_t[t] = cb
            r2.addWidget(cb)
        r2.addSpacing(16)
        r2.addWidget(self._lbl("Sources:"))
        self.chk_s: dict[str, QCheckBox] = {}
        src_colors = {"OSM":"#8b5cf6","YellowPages":"#f97316",
                      "Yelp":"#ef4444","Google":"#34d399"}
        for s, col in src_colors.items():
            cb = QCheckBox(s)
            cb.setChecked(True)
            cb.setStyleSheet(f"color:{col};font-size:12px;font-weight:600;")
            self.chk_s[s] = cb
            r2.addWidget(cb)
        r2.addSpacing(16)
        self.chk_enrich = QCheckBox("Scrape websites for phone+email (recommended)")
        self.chk_enrich.setChecked(True)
        r2.addWidget(self.chk_enrich)
        r2.addStretch()
        sl.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(8)
        self.sbtn = QPushButton("Search Contractors ↗")
        self.sbtn.setObjectName("searchBtn")
        self.sbtn.setFixedHeight(38)
        self.sbtn.clicked.connect(self.start_search)
        self.xbtn = QPushButton("Stop")
        self.xbtn.setObjectName("stopBtn")
        self.xbtn.setFixedHeight(38)
        self.xbtn.setFixedWidth(70)
        self.xbtn.setEnabled(False)
        self.xbtn.clicked.connect(self.stop_search)
        self.vbtn = QPushButton("✉ Verify Emails")
        self.vbtn.setObjectName("verifyBtn")
        self.vbtn.setFixedHeight(38)
        self.vbtn.clicked.connect(self.start_verify)
        self.gbtn = QPushButton("📊 Export → Google Sheets")
        self.gbtn.setObjectName("sheetsBtn")
        self.gbtn.setFixedHeight(38)
        self.gbtn.clicked.connect(self.export_sheets)
        for w in [self.sbtn, self.xbtn, self.vbtn, self.gbtn]:
            r3.addWidget(w)
        r3.addStretch()
        sl.addLayout(r3)

        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(7)
        self.pbar.setTextVisible(False)
        sl.addWidget(self.pbar)
        root.addWidget(sg)

        # Stats + filter
        sf = QHBoxLayout()
        sf.setSpacing(8)
        self.stats: dict[str, StatCard] = {}
        for t, col in {**TRADE_COLORS, "Total": "#6366f1"}.items():
            card = StatCard(t, col)
            self.stats[t] = card
            sf.addWidget(card)
        sf.addStretch()
        sf.addWidget(self._lbl("Filter:"))
        self.tf = QComboBox()
        self.tf.addItems(["All","HVAC","Electrical","Excavating"])
        self.tf.setFixedWidth(120)
        self.tf.setFixedHeight(30)
        self.tf.currentTextChanged.connect(self._filter)
        sf.addWidget(self.tf)
        self.sf2 = QComboBox()
        self.sf2.addItems(["All Sources","OSM","YellowPages","Yelp","Google"])
        self.sf2.setFixedWidth(130)
        self.sf2.setFixedHeight(30)
        self.sf2.currentTextChanged.connect(self._filter)
        sf.addWidget(self.sf2)
        self.nf = QLineEdit()
        self.nf.setPlaceholderText("Search by name...")
        self.nf.setFixedWidth(160)
        self.nf.setFixedHeight(30)
        self.nf.textChanged.connect(self._filter)
        sf.addWidget(self.nf)
        root.addLayout(sf)

        # Table
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        for i, w in enumerate([80,100,200,135,185,90,175,180,140]):
            self.table.setColumnWidth(i, w)
        root.addWidget(self.table)

        # Export
        er = QHBoxLayout()
        er.setSpacing(8)
        for txt, fn in [("Export CSV", self.export_csv),
                         ("Export TXT", self.export_txt),
                         ("Clear",      self.clear)]:
            b = QPushButton(txt)
            b.clicked.connect(fn)
            b.setFixedHeight(32)
            er.addWidget(b)
        er.addStretch()
        root.addLayout(er)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            f"Ready  ·  Scrapling: {'✓' if HAS_SCRAPLING else '✗'}  "
            f"Async: {'✓' if HAS_AIOHTTP else '✗'}  "
            f"DNS verify: {'✓' if HAS_DNS else '✗'}")

    def start_search(self):
        loc = self.loc.currentText().strip()
        if not loc:
            QMessageBox.warning(self, "Error", "Enter a US location.")
            return
        trades  = [t for t, cb in self.chk_t.items() if cb.isChecked()]
        sources = [s for s, cb in self.chk_s.items() if cb.isChecked()]
        if not trades:
            QMessageBox.warning(self, "Error", "Select at least one trade.")
            return
        if not sources:
            QMessageBox.warning(self, "Error", "Select at least one source.")
            return
        self.rows.clear()
        self.table.setRowCount(0)
        for c in self.stats.values():
            c.set(0)
        self.sbtn.setEnabled(False)
        self.xbtn.setEnabled(True)
        self.pbar.setValue(0)

        # Save location to search history
        SEARCH_HISTORY.save(loc)
        # Update dropdown with new history
        _hist = SEARCH_HISTORY.load()
        current = self.loc.currentText()
        self.loc.clear()
        for h in _hist:
            self.loc.addItem(h)
        self.loc.setCurrentText(current)
        # Start loading proxies in background (non-blocking)
        PROXY_MGR.load_async()

        self.worker = SearchWorker(
            loc, trades, int(self.per.currentText()),
            int(self.rmap[self.radius.currentText()]),
            self.chk_enrich.isChecked(), sources
        )
        self.worker.progress.connect(lambda p, m: (
            self.pbar.setValue(p), self.statusBar().showMessage(m)))
        self.worker.result.connect(self._add_row)
        self.worker.finished.connect(self._on_done)
        self.worker.start()

    def stop_search(self):
        if self.worker:
            self.worker.stop()
        self.xbtn.setEnabled(False)

    def _on_done(self, ok, err):
        self.pbar.setValue(100)
        self.sbtn.setEnabled(True)
        self.xbtn.setEnabled(False)
        if ok:
            counts = {t: sum(1 for r in self.rows if r.trade == t) for t in TRADE_COLORS}
            self.statusBar().showMessage(
                f"Done — {len(self.rows)} contractors  |  " +
                "  ".join(f"{t}:{counts[t]}" for t in TRADE_COLORS))
        else:
            QMessageBox.critical(self, "Error", err)

    def _add_row(self, c: Contractor):
        self.rows.append(c)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._fill_row(row, c)
        self._update_stats()

    def _fill_row(self, row, c: Contractor):
        bg = QColor("#161925") if row % 2 == 1 else QColor("#1a1d27")
        vc   = VERIFY_COLORS.get(c.email_status, "#94a3b8")
        vi   = f"{VERIFY_ICONS.get(c.email_status,'')} {c.email_status}".strip()
        note = email_role_warning(c.email) if c.email else ""
        vals = [
            (c.trade,    TRADE_COLORS.get(c.trade,  "#e2e8f0"), True),
            (c.source,   SOURCE_COLORS.get(c.source, "#94a3b8"), True),
            (c.name,     "#e2e8f0", False),
            (c.phone,    "#10b981" if c.phone else "#94a3b8", False),
            (c.email,    "#93c5fd" if c.email else "#94a3b8", False),
            (vi,         vc, True),
            (c.website,  "#93c5fd", False),
            (c.address,  "#e2e8f0", False),
            (note,       "#f59e0b" if note else "#94a3b8", False),
        ]
        for col, (val, color, bold) in enumerate(vals):
            item = QTableWidgetItem(val)
            item.setForeground(QBrush(QColor(color)))
            item.setBackground(QBrush(bg))
            if bold:
                item.setFont(QFont("Segoe UI", 11, QFont.Bold))
            self.table.setItem(row, col, item)
        self.table.setRowHeight(row, 30)

    def _update_stats(self):
        for t in TRADE_COLORS:
            self.stats[t].set(sum(1 for r in self.rows if r.trade == t))
        self.stats["Total"].set(len(self.rows))

    def _filter(self):
        trade  = self.tf.currentText()
        src    = self.sf2.currentText()
        name   = self.nf.text().strip().lower()
        self.table.setRowCount(0)
        for i, c in enumerate(self.rows):
            if trade != "All" and c.trade != trade:
                continue
            if src != "All Sources" and c.source != src:
                continue
            if name and name not in c.name.lower():
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._fill_row(row, c)

    def start_verify(self):
        if not self.rows:
            QMessageBox.information(self, "", "Run a search first.")
            return
        self.vbtn.setEnabled(False)
        self.pbar.setValue(0)
        self.vworker = VerifyWorker(self.rows)
        self.vworker.progress.connect(lambda p, m: (
            self.pbar.setValue(p), self.statusBar().showMessage(m)))
        self.vworker.result.connect(self._on_verify)
        self.vworker.finished.connect(self._on_verify_done)
        self.vworker.start()

    def _on_verify(self, idx, status, reason):
        if idx < self.table.rowCount():
            vi = f"{VERIFY_ICONS.get(status,'')} {status}".strip()
            item = QTableWidgetItem(vi)
            item.setForeground(QBrush(QColor(VERIFY_COLORS.get(status, "#94a3b8"))))
            self.table.setItem(idx, 5, item)

    def _on_verify_done(self):
        self.pbar.setValue(100)
        self.vbtn.setEnabled(True)
        v   = sum(1 for r in self.rows if r.email_status == "valid")
        inv = sum(1 for r in self.rows if r.email_status == "invalid")
        unk = sum(1 for r in self.rows if r.email_status == "unknown")
        self.statusBar().showMessage(
            f"Email verify done  —  ✅ Valid:{v}  ❌ Invalid:{inv}  ❓ Unknown:{unk}")

    def export_sheets(self):
        if not self.rows:
            return
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv",
                                          mode="w", newline="", encoding="utf-8")
        fields = ["trade","source","name","phone","email","website","address"]
        w = csv.DictWriter(tmp, fieldnames=fields)
        w.writeheader()
        for c in self.rows:
            d = asdict(c)
            w.writerow({k: d.get(k, "") for k in fields})
        tmp.close()
        dlg = QDialog(self)
        dlg.setWindowTitle("Export to Google Sheets")
        dlg.resize(460, 260)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("<b>CSV saved! Import steps:</b>"))
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(
            f"File: {tmp.name}\n\n"
            "1. Google Sheets will open in your browser\n"
            "2. Click  File → Import → Upload tab\n"
            f"3. Select file: {os.path.basename(tmp.name)}\n"
            "4. Choose 'Replace spreadsheet' → Import data")
        lay.addWidget(te)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() == QDialog.Accepted:
            webbrowser.open("https://sheets.new")

    def export_csv(self):
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "contractors.csv", "CSV (*.csv)")
        if not path:
            return
        fields = ["trade","source","name","phone","email","website","address"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for c in self.rows:
                d = asdict(c)
                w.writerow({k: d.get(k, "") for k in fields})
        self.statusBar().showMessage(f"Saved {len(self.rows)} rows → {path}")

    def export_txt(self):
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save TXT", "contractors.txt", "Text (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for trade in ["HVAC", "Electrical", "Excavating"]:
                g = [c for c in self.rows if c.trade == trade]
                if not g:
                    continue
                f.write(f"\n{'='*50}\n{trade.upper()} ({len(g)})\n{'='*50}\n")
                for i, c in enumerate(g, 1):
                    f.write(f"\n{i}. {c.name}  [{c.source}]\n"
                            f"   Phone:   {c.phone or 'N/A'}\n"
                            f"   Email:   {c.email or 'N/A'}\n"
                            f"   Website: {c.website or 'N/A'}\n"
                            f"   Address: {c.address or 'N/A'}\n")
        self.statusBar().showMessage(f"Saved → {path}")

    def clear(self):
        self.rows.clear()
        self.table.setRowCount(0)
        for c in self.stats.values():
            c.set(0)
        self.pbar.setValue(0)
        self.statusBar().showMessage("Cleared")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setApplicationName("Contractor Finder v3")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
