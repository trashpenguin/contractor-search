from __future__ import annotations

import asyncio
import logging
import threading
from urllib.parse import quote_plus

from compat import HAS_AIOHTTP
from config import ENRICH_BATCH_SIZE
from constants import SKIP_DOMAINS
from enricher import dedup, enrich_batch_async, scrape_website, website_matches
from extractor import _clean_email, _ok_email
from http_client import (
    SearchCancelled,
    check_cancelled,
    close_event_loop,
    get_event_loop,
    http_get,
    set_search_stop,
)
from location import valid_location
from models import Contractor
from provenance import record_contact
from scrapers.ddg import ddg_search
from scrapers.google import scrape_google
from scrapers.google_places import scrape_google_places
from scrapers.google_search import scrape_google_search
from scrapers.osm import scrape_osm
from scrapers.yellowpages import scrape_yellowpages
from scrapers.yelp import scrape_yelp

logger = logging.getLogger("ContractorFinder")

SRC_FN = {
    "YellowPages": scrape_yellowpages,
    "Yelp": scrape_yelp,
    "Google": scrape_google,
    "Google Search": scrape_google_search,
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
    source_cb=None,
):
    """Complete exactly once with completed, partial, failed, or cancelled."""
    from scrapers.osm import geocode

    failures = []
    successes = 0
    set_search_stop(stop_ev)
    try:
        if not valid_location(location) or not trades or not sources:
            raise ValueError("Enter a city/state or ZIP and select trades and sources.")
        if limit <= 0 or radius_m <= 0:
            raise ValueError("Limit and radius must be positive.")
        check_cancelled()
        lat = lon = None
        progress_cb(0, "Geocoding location...")
        try:
            lat, lon = geocode(location)
        except SearchCancelled:
            raise
        except Exception as exc:
            logger.warning("Geocoding unavailable: %s", exc)
            if sources == ["OSM"]:
                raise
        allocation = 100.0 / len(trades)
        for trade_idx, trade in enumerate(trades):
            check_cancelled()
            collected = []
            ordered = sorted(
                sources,
                key=lambda source: (
                    0
                    if source == "Google Places"
                    else 1 if source == "Google Search" else 2 if source == "Google" else 3
                ),
            )
            for src_idx, src in enumerate(ordered):
                check_cancelled()
                pct = int((trade_idx + (src_idx + 1) / len(sources) * 0.4) * allocation)
                progress_cb(pct, f"[{src}] Searching {trade} near {location}...")
                try:
                    if src == "OSM":
                        if lat is None:
                            raise RuntimeError("OSM requires geocoding.")
                        batch = scrape_osm(trade, lat, lon, radius_m, limit)
                    elif src == "Google":
                        batch = scrape_google(trade, location, limit, lat=lat, lon=lon)
                    elif src == "Google Places":
                        batch = scrape_google_places(
                            trade, location, limit, lat=lat, lon=lon, radius_m=radius_m
                        )
                    else:
                        batch = SRC_FN[src](trade, location, limit)
                    for contractor in batch:
                        if not contractor.discovery_url:
                            contractor.discovery_url = {
                                "OSM": "https://www.openstreetmap.org",
                                "Google": "https://www.google.com/maps",
                                "Google Search": "https://www.google.com/search",
                                "Google Places": (
                                    "https://places.googleapis.com/v1/places:searchText"
                                ),
                                "YellowPages": "https://www.yellowpages.com/search",
                                "Yelp": "https://www.yelp.com/search",
                            }[src]
                        record_contact(contractor)
                    collected.extend(batch)
                    successes += 1
                    if source_cb:
                        source_cb(src, trade, len(batch))
                except SearchCancelled:
                    raise
                except Exception as exc:
                    failures.append(f"{src}/{trade}: {exc}")
                    logger.warning("[%s] %s failed: %s", src, trade, exc)
                    if source_cb:
                        source_cb(src, trade, -1)

            collected = dedup(collected)
            city_hint = location.split(",")[0].strip()
            for contractor in collected:
                if contractor.email and "%" in contractor.email:
                    decoded = _clean_email(contractor.email)
                    if _ok_email(decoded):
                        contractor.email = decoded
            if enrich and collected:
                collected.sort(key=lambda item: item.quality_score)
                ddg_state = [0]
                for start in range(0, len(collected), ENRICH_BATCH_SIZE):
                    check_cancelled()
                    batch = collected[start : start + ENRICH_BATCH_SIZE]
                    progress_cb(
                        int((trade_idx + 0.4 + 0.6 * start / len(collected)) * allocation),
                        f"[{trade}] Enriching {start + 1}-{start + len(batch)}/{len(collected)}...",
                    )
                    if HAS_AIOHTTP:
                        get_event_loop().run_until_complete(
                            enrich_batch_async(
                                batch,
                                city_hint,
                                location=location,
                                _ddg_state=ddg_state,
                                stop_ev=stop_ev,
                            )
                        )
                    else:
                        _sync_enrich(batch, city_hint, location)
            for contractor in collected:
                check_cancelled()
                result_cb(contractor)
        check_cancelled()
        status = "partial" if failures and successes else "failed" if failures else "completed"
        done_cb(status, "; ".join(failures))
    except (SearchCancelled, asyncio.CancelledError):
        done_cb("cancelled", "Search stopped. Results already displayed are retained.")
    except Exception as exc:
        logger.exception("Search failed")
        done_cb("failed", str(exc))
    finally:
        close_event_loop()
        set_search_stop(None)


def _sync_enrich(batch: list[Contractor], city_hint: str, location: str = ""):
    """Fallback enrichment uses the same business identity requirements."""
    hint = location or city_hint
    for contractor in batch:
        check_cancelled()
        if not contractor.website and contractor.name:
            query = quote_plus(f'"{contractor.name}" "{hint}" contractor')
            for _, url, _ in ddg_search(query, pages=1):
                check_cancelled()
                if url.startswith("http") and not any(domain in url for domain in SKIP_DOMAINS):
                    if website_matches(contractor, http_get(url)):
                        contractor.website = url
                        contractor.website_method = "corroborated-search"
                        contractor.confidence = "corroborated"
                        break
        if contractor.website and (not contractor.email or not contractor.phone):
            email, phone = scrape_website(contractor.website)
            if not contractor.email:
                contractor.email = email
            if not contractor.phone:
                contractor.phone = phone
            record_contact(contractor, contractor.website)
