from __future__ import annotations

import json
import logging
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from constants import TRADE_KW
from models import Contractor
from http_client import check_cancelled, interruptible_sleep

logger = logging.getLogger("ContractorFinder")

_PLACES_V1 = "https://places.googleapis.com/v1/places:searchText"
_PLACES_OLD = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_DETAILS_OLD = "https://maps.googleapis.com/maps/api/place/details/json"
_FIELDS_V1 = (
    "places.displayName,places.formattedAddress," "places.nationalPhoneNumber,places.websiteUri,places.id,nextPageToken"
)


def _api_get(url: str) -> dict:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.info(f"[GPlaces] GET error: {type(e).__name__}: {e}")
        return {}


def _api_post(url: str, body: dict, headers: dict) -> dict:
    try:
        data = json.dumps(body).encode("utf-8")
        hdrs = {"Content-Type": "application/json", **headers}
        req = Request(url, data=data, headers=hdrs, method="POST")
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.info(f"[GPlaces] POST error: {type(e).__name__}: {e}")
        return {}


def _search_v1(
    trade: str,
    keyword: str,
    location: str,
    limit: int,
    api_key: str,
    lat: float,
    lon: float,
    radius_m: int,
) -> list[Contractor]:
    """New Places API v1 — phone + website returned in one call."""
    out: list[Contractor] = []
    page_token = None
    pages = 0

    while len(out) < limit and pages < 3:
        check_cancelled()
        body: dict = {
            "textQuery": f"{keyword} near {location}",
            "maxResultCount": min(20, limit - len(out)),
        }
        if lat is not None and lon is not None:
            body["locationBias"] = {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": float(min(radius_m, 50000)),
                }
            }
        if page_token:
            body["pageToken"] = page_token

        resp = _api_post(
            _PLACES_V1,
            body,
            {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": _FIELDS_V1},
        )

        if not resp:
            raise RuntimeError("Google Places request failed")
        if "error" in resp:
            msg = resp["error"].get("message") or str(resp["error"])
            raise RuntimeError(f"Google Places API error: {msg}")

        places = resp.get("places", [])
        logger.info(f"[GPlaces/v1] page {pages + 1}: {len(places)} results")

        for p in places:
            if len(out) >= limit:
                break
            name = p.get("displayName", {}).get("text", "").strip()
            if not name:
                continue
            out.append(
                Contractor(
                    trade=trade,
                    name=name,
                    phone=p.get("nationalPhoneNumber", ""),
                    website=p.get("websiteUri", ""),
                    address=p.get("formattedAddress", ""),
                    source="Google Places",
                    place_id=p.get("id", ""),
                    discovery_url="https://www.google.com/maps/search/?api=1&query=" + quote_plus(name)
                    + "&query_place_id=" + p.get("id", ""),
                )
            )

        page_token = resp.get("nextPageToken")
        pages += 1
        if not page_token or not places:
            break
        interruptible_sleep(2)  # API requires delay before nextPageToken is valid

    return out


def _search_old(
    trade: str,
    keyword: str,
    location: str,
    limit: int,
    api_key: str,
) -> list[Contractor]:
    """Legacy Places API — text search + per-result details call for phone/website."""
    out: list[Contractor] = []
    page_token = None
    pages = 0

    while len(out) < limit and pages < 3:
        q = quote_plus(f"{keyword} near {location}")
        url = f"{_PLACES_OLD}?query={q}&key={api_key}"
        if page_token:
            url += f"&pagetoken={page_token}"

        resp = _api_get(url)
        status = resp.get("status", "")
        if status not in ("OK", "ZERO_RESULTS"):
            logger.info(f"[GPlaces/old] status={status} — {resp.get('error_message', '')}")
            return out

        results = resp.get("results", [])
        logger.info(f"[GPlaces/old] page {pages + 1}: {len(results)} results")

        for r in results:
            if len(out) >= limit:
                break
            name = r.get("name", "").strip()
            if not name:
                continue

            place_id = r.get("place_id", "")
            phone = website = ""
            if place_id:
                det = _api_get(
                    f"{_DETAILS_OLD}?place_id={place_id}"
                    f"&fields=formatted_phone_number,website&key={api_key}"
                )
                result = det.get("result", {})
                phone = result.get("formatted_phone_number", "")
                website = result.get("website", "")
                time.sleep(0.15)

            out.append(
                Contractor(
                    trade=trade,
                    name=name,
                    phone=phone,
                    website=website,
                    address=r.get("formatted_address", ""),
                    source="Google Places",
                    place_id=place_id,
                    discovery_url="https://www.google.com/maps/search/?api=1&query=" + quote_plus(name)
                    + "&query_place_id=" + place_id,
                )
            )

        page_token = resp.get("next_page_token")
        pages += 1
        if not page_token or not results:
            break
        time.sleep(2)

    return out


def scrape_google_places(
    trade: str,
    location: str,
    limit: int,
    lat: float = 0.0,
    lon: float = 0.0,
    radius_m: int = 40000,
) -> list[Contractor]:
    """Fetch contractors via Google Places API.

    Tries the new Places API v1 first (phone + website in one call),
    falls back to the legacy Text Search + Details API.
    Reads the API key from ~/.contractor_finder_settings.json.
    Returns [] if no key is configured.
    """
    from config import get as settings_get

    api_key = (settings_get("google_places_api_key") or "").strip()
    if not api_key:
        logger.info("[GPlaces] No API key configured — skipping")
        raise RuntimeError("Google Places requires an API key")

    keyword = TRADE_KW[trade]["google"]
    logger.info(f"[GPlaces] {trade}: '{keyword} near {location}'")

    results = _search_v1(trade, keyword, location, limit, api_key, lat, lon, radius_m)
    if results:
        logger.info(f"[GPlaces] {trade}: {len(results)} total (v1 API)")
        return results

    logger.info("[GPlaces] v1 returned nothing — trying legacy Places API")
    results = _search_old(trade, keyword, location, limit, api_key)
    logger.info(f"[GPlaces] {trade}: {len(results)} total (legacy API)")
    return results
