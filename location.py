"""Shared location validation and distance conversion."""

from __future__ import annotations

import math
import re


def valid_location(value: str) -> bool:
    value = value.strip()
    return bool(
        re.fullmatch(r"\d{5}(?:-\d{4})?", value)
        or (len(value) >= 3 and re.search(r"[a-zA-Z]", value))
    )


def miles_to_meters(miles: float) -> int:
    return round(miles * 1609.344)


def distance_m(lat: float, lon: float, other_lat: float, other_lon: float) -> float:
    a, b = math.radians(lat), math.radians(other_lat)
    delta_lat = b - a
    delta_lon = math.radians(other_lon - lon)
    h = math.sin(delta_lat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(delta_lon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1.0, h)))
