from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Contractor:
    trade: str = ""
    name: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    address: str = ""
    source: str = ""
    email_status: str = ""
    place_id: str = ""
