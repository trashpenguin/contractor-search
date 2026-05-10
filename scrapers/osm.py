from __future__ import annotations
import json, re
import logging
from urllib.parse import quote_plus

from constants import TRADE_KW, OVERPASS_EPS
from http_client import http_get, post_bytes
from models import Contractor

logger = logging.getLogger("ContractorFinder")


def geocode(location: str) -> tuple[float, float]:
    url  = (f"https://nominatim.openstreetmap.org/search"
            f"?q={quote_plus(location)}&format=jsonv2&limit=1&countrycodes=us")
    html = http_get(url, timeout=30)
    if not html:
        raise RuntimeError(f"Cannot geocode: {location}")
    data = json.loads(html)
    if not data:
        raise RuntimeError(f"Location not found: {location}")
    return float(data[0]["lat"]), float(data[0]["lon"])


def scrape_osm(trade: str, lat: float, lon: float, radius_m: int, limit: int) -> list[Contractor]:
    kw    = TRADE_KW[trade]["osm"]
    regex = "|".join(re.escape(k) for k in kw)
    q     = (
        f'[out:json][timeout:90];'
        f'(nwr(around:{radius_m},{lat},{lon})["name"~"{regex}",i];'
        f'nwr(around:{radius_m},{lat},{lon})["shop"~"hvac|electrical|heating",i];'
        f'nwr(around:{radius_m},{lat},{lon})["craft"~"electrician|hvac|excavation",i];'
        f'nwr(around:{radius_m},{lat},{lon})["trade"~"electrician|hvac|excavation",i];'
        f');out center tags;'
    )
    payload  = f"data={quote_plus(q)}".encode()
    hdrs     = {"User-Agent": "ContractorFinder/3.0",
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

    # Nominatim keyword search for broader coverage
    for kword in kw[:3]:
        if len(elements) >= limit * 3:
            break
        try:
            nm_url = (
                f"https://nominatim.openstreetmap.org/search"
                f"?q={quote_plus(kword)}"
                f"&format=jsonv2&limit=50&addressdetails=1&countrycodes=us"
                f"&viewbox={lon-1.0},{lat-1.0},{lon+1.0},{lat+1.0}&bounded=1"
            )
            nm_html = http_get(nm_url, timeout=15)
            if nm_html:
                places = json.loads(nm_html)
                for p in places:
                    name = (p.get("name") or "").strip()
                    if not name:
                        continue
                    bad = ["slag", "subdivision", "blast furnace", "heating plant",
                           "boiler plant", "distribution", "manufacturing"]
                    ok_words = ["heating", "cooling", "hvac", "air", "electric", "excavat",
                                "grading", "plumb", "mechanical", "service", "refriger"]
                    if any(b in name.lower() for b in bad):
                        continue
                    if not any(b in name.lower() for b in ok_words):
                        continue
                    ap = p.get("address", {})
                    elements.append({
                        "type": "nominatim",
                        "id":   p.get("place_id", ""),
                        "tags": {
                            "name":          name,
                            "addr:housenumber": ap.get("house_number", ""),
                            "addr:street":   ap.get("road", ""),
                            "addr:city":     ap.get("city") or ap.get("town", ""),
                            "addr:state":    ap.get("state", ""),
                            "addr:postcode": ap.get("postcode", ""),
                        },
                    })
        except Exception:
            pass

    out: list[Contractor] = []
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
            address=addr, source="OSM", place_id=pid,
        ))
        if len(out) >= limit:
            break

    logger.info(f"[OSM] {trade}: {len(out)} results")
    return out
