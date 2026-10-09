"""Keep contact origin distinct from domain-level email checks."""

from __future__ import annotations

from models import Contractor


def record_contact(contractor: Contractor, url: str = "") -> None:
    if contractor.email and not contractor.email_method:
        contractor.email_method = "scraped"
        contractor.email_source_url = url or contractor.discovery_url
    if contractor.phone and not contractor.phone_source_url:
        contractor.phone_source_url = url or contractor.discovery_url
    if contractor.website and not contractor.website_method:
        contractor.website_method = "listed"
    if not contractor.confidence:
        contractor.confidence = "listed" if contractor.source else "unconfirmed"


def email_label(contractor: Contractor) -> str:
    status = contractor.email_status or "unchecked"
    if contractor.email_method == "guessed":
        return f"Guessed / {status}"
    return status
