from __future__ import annotations
import concurrent.futures, random, re, threading, time
import urllib.request as _ur
import logging

from constants import PROXY_SOURCES, _FATAL_PROXY_ERRORS

logger = logging.getLogger("ContractorFinder")


class ProxyEntry:
    """Tracks health of one proxy."""
    __slots__ = ("url", "score", "uses", "latency")

    def __init__(self, url: str, latency: float):
        self.url     = url
        self.score   = 5
        self.uses    = 0
        self.latency = latency


class ProxyManager:
    """
    Elite proxy pool with health scoring, sticky sessions, and circuit breakers.
    Traffic routing: OSM/company sites bypass proxy; directories use proxy.
    """
    def __init__(self):
        self._lock    = threading.Lock()
        self._pool:   list[ProxyEntry] = []
        self._cur_idx = 0
        self._loaded  = False
        self._loading = False
        self.STICKY_LIMIT = 10

    def load_async(self):
        if self._loading or self._loaded:
            return
        self._loading = True
        threading.Thread(target=self._build_pool, daemon=True).start()

    def _build_pool(self):
        raw: list[str] = []
        for src in PROXY_SOURCES:
            if len(raw) >= 300:
                break
            try:
                req = _ur.Request(src, headers={"User-Agent": "Mozilla/5.0"})
                with _ur.urlopen(req, timeout=10) as r:
                    data = r.read().decode("utf-8", errors="ignore")
                for line in data.strip().splitlines():
                    line = line.strip()
                    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", line):
                        raw.append(f"http://{line}")
                logger.info(f"[Proxy] {len(raw)} raw from {src.split('/')[-1]}")
            except Exception as e:
                logger.info(f"[Proxy] Source failed: {type(e).__name__}")

        test_url  = "https://httpbin.org/ip"
        test_http = "http://httpbin.org/ip"
        scored: list[ProxyEntry] = []
        random.shuffle(raw)

        def _test(proxy: str):
            try:
                t0     = time.time()
                opener = _ur.build_opener(_ur.ProxyHandler({"http": proxy, "https": proxy}))
                with opener.open(test_url, timeout=4) as r:
                    if r.status == 200:
                        lat = time.time() - t0
                        if lat < 3.0:
                            return ProxyEntry(proxy, lat)
            except Exception as e:
                err = str(e)
                if any(fe in err for fe in _FATAL_PROXY_ERRORS):
                    return None
                try:
                    t0      = time.time()
                    opener2 = _ur.build_opener(_ur.ProxyHandler({"http": proxy, "https": proxy}))
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
            logger.info("[Proxy] No working proxies — direct connection only")

    def get_for(self, url: str) -> str | None:
        """Return proxy URL for this URL, or None for direct connection."""
        from urllib.parse import urlparse
        no_proxy_domains = (
            "overpass-api.de", "overpass.kumi.systems",
            "nominatim.openstreetmap.org",
        )
        if any(d in url for d in no_proxy_domains):
            return None
        skip_dirs = ("yelp.com", "yellowpages.com", "google.com", "duckduckgo.com")
        is_directory = any(d in url for d in skip_dirs)
        if not is_directory:
            p = urlparse(url)
            if p.netloc and not any(d in p.netloc for d in skip_dirs):
                return None
        return self._get_next()

    def _get_next(self) -> str | None:
        with self._lock:
            now    = time.time()
            active = [e for e in self._pool
                      if e.score > 0 and
                      not (hasattr(e, "_cooldown_until") and now < e._cooldown_until)]
            if not active:
                return None
            if self._cur_idx < len(active):
                entry = active[self._cur_idx % len(active)]
                if entry.uses < self.STICKY_LIMIT:
                    entry.uses += 1
                    return entry.url
                self._cur_idx = (self._cur_idx + 1) % len(active)
                entry = active[self._cur_idx]
                entry.uses = 1
                return entry.url
            return None

    def get(self) -> str | None:
        return self._get_next()

    def report(self, proxy: str, success: bool, error: str = ""):
        if not proxy:
            return
        is_fatal   = any(fe in error for fe in _FATAL_PROXY_ERRORS)
        is_timeout = "timeout" in error.lower() or "timed out" in error.lower()
        with self._lock:
            for entry in self._pool:
                if entry.url == proxy:
                    if is_fatal:
                        entry.score = -99
                        logger.info(f"[Proxy] Circuit broken: {proxy[7:30]}")
                    elif is_timeout:
                        entry.score = -99   # one timeout = dead for free proxies
                        logger.info(f"[Proxy] Circuit broken (timeout): {proxy[7:30]}")
                    elif success:
                        entry.score = min(entry.score + 1, 5)
                        if hasattr(entry, "_cooldown_until"):
                            del entry._cooldown_until
                    else:
                        entry.score -= 1
                    break
            self._pool = [e for e in self._pool if e.score > -10]

    def ban_for_domain(self, proxy: str, domain: str):
        with self._lock:
            for entry in self._pool:
                if entry.url == proxy:
                    if not hasattr(entry, "_domain_bans"):
                        entry._domain_bans = set()
                    entry._domain_bans.add(domain)
                    break

    def mark_bad(self, proxy: str, error: str = ""):
        self.report(proxy, False, error)

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._loaded and any(e.score > 0 for e in self._pool)

    def stats(self) -> str:
        with self._lock:
            active = sum(1 for e in self._pool if e.score > 0)
            return f"{active}/{len(self._pool)} proxies active"


PROXY_MGR = ProxyManager()
