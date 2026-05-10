from __future__ import annotations
import logging
import threading
from urllib.parse import quote_plus

from compat import HAS_AIOHTTP
from constants import SKIP_DOMAINS
from enricher import enrich_batch_async, scrape_website, dedup
from extractor import _ok_email, _clean_email
from http_client import get_event_loop
from models import Contractor
from scrapers.ddg import ddg_search
from scrapers.osm import scrape_osm
from scrapers.yellowpages import scrape_yellowpages
from scrapers.yelp import scrape_yelp
from scrapers.google import scrape_google

logger = logging.getLogger("ContractorFinder")

SRC_FN = {
    "YellowPages": scrape_yellowpages,
    "Yelp":        scrape_yelp,
    "Google":      scrape_google,
}


def run_search(
    location: str,
    trades: list[str],
    limit: int,
    radius_m: int,
    enrich: bool,
    sources: list[str],
    progress_cb,
    result_cb,
    done_cb,
    stop_ev: threading.Event,
):
    from scrapers.osm import geocode
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
                elif src == "Google":
                    batch = scrape_google(trade, location, limit, lat=lat, lon=lon)
                else:
                    batch = SRC_FN[src](trade, location, limit)
                collected.extend(batch)
                progress_cb(pct, f"[{src}] {trade}: {len(batch)} found")
            except Exception as e:
                logger.info(f"[{src}] {trade} error: {e}")

        collected = dedup(collected)
        city_hint = location.split(",")[0].strip()

        # Decode URL-encoded emails up front
        for c in collected:
            if c.email and "%" in c.email:
                from urllib.parse import unquote as _uq
                decoded = _clean_email(_uq(c.email))
                if _ok_email(decoded):
                    c.email = decoded

        if enrich and collected:
            BATCH = 15
            n_total = len(collected)
            for batch_start in range(0, n_total, BATCH):
                if stop_ev.is_set():
                    break
                batch = collected[batch_start:batch_start + BATCH]
                pct   = int(70 + (batch_start / max(n_total, 1)) * 25)
                progress_cb(
                    pct,
                    f"[{trade}] Enriching {batch_start+1}-"
                    f"{min(batch_start+BATCH, n_total)}/{n_total} (async x{len(batch)})...",
                )
                if HAS_AIOHTTP:
                    try:
                        loop = get_event_loop()
                        loop.run_until_complete(enrich_batch_async(batch, city_hint, location=location))
                    except Exception as e:
                        logger.error(f"[Async] batch error: {e}")
                        _sync_enrich(batch, city_hint, location)
                else:
                    _sync_enrich(batch, city_hint, location)

        for c in collected:
            if stop_ev.is_set():
                break
            result_cb(c)

    done_cb(True, "")


def _sync_enrich(batch: list[Contractor], city_hint: str, location: str = ""):
    """Sync fallback enrichment when aiohttp is unavailable or async fails."""
    loc_hint = location or city_hint
    for c in batch:
        if not c.website and c.name:
            q = quote_plus(f'"{c.name}" {loc_hint} contractor')
            for _, url, _ in ddg_search(q, pages=1):
                if url.startswith("http") and not any(d in url for d in SKIP_DOMAINS):
                    c.website = url
                    break
        if c.website and (not c.email or not c.phone):
            we, wp = scrape_website(c.website)
            if not c.email:
                c.email = we
            if not c.phone:
                c.phone = wp
