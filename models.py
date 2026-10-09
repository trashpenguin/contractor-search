from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


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
    record_id: str = field(default_factory=lambda: uuid4().hex)
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    discovery_url: str = ""
    email_method: str = ""
    email_source_url: str = ""
    phone_source_url: str = ""
    website_method: str = ""
    confidence: str = ""

    @property
    def quality_score(self) -> int:
        return bool(self.phone) + bool(self.email) + bool(self.website)
