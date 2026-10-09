"""CSV exports preserve contact provenance and replace destination files atomically."""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import asdict, fields
from pathlib import Path

from models import Contractor

_BOARD_HEADERS = [
    "Name",
    "Follow-up Date",
    "Sub's Phone",
    "Link for file",
    "Bid Deadline",
    "Sub's Email",
    "Job Date",
    "Scope of Work",
    "Project Address",
    "Subcontractor Role",
    "Status",
    "Email Method",
    "Email Verification",
    "Email Source",
    "Website",
    "Source",
    "Discovery URL",
    "Discovered At",
    "Confidence",
]


def _to_board_row(contractor) -> dict:
    return {
        "Name": contractor.name,
        "Follow-up Date": "",
        "Sub's Phone": contractor.phone,
        "Link for file": "",
        "Bid Deadline": "",
        "Sub's Email": contractor.email,
        "Job Date": "",
        "Scope of Work": "",
        "Project Address": contractor.address,
        "Subcontractor Role": contractor.trade,
        "Status": "NOT STARTED",
        "Email Method": contractor.email_method,
        "Email Verification": contractor.email_status,
        "Email Source": contractor.email_source_url,
        "Website": contractor.website,
        "Source": contractor.source,
        "Discovery URL": contractor.discovery_url,
        "Discovered At": contractor.discovered_at,
        "Confidence": contractor.confidence,
    }


def _write_board_csv(writer, rows):
    """Write rows grouped by trade, matching the board's group layout."""
    from collections import defaultdict

    groups: dict = defaultdict(list)
    for c in rows:
        groups[c.trade].append(c)

    for trade, contractors in groups.items():
        # Group header row — mirrors the coloured trade label in the board
        writer.writerow(
            {h: "" for h in _BOARD_HEADERS} | {"Name": f"── {trade} ({len(contractors)})"}
        )
        for c in contractors:
            writer.writerow(_to_board_row(c))
        writer.writerow({h: "" for h in _BOARD_HEADERS})  # blank spacer between groups


FLAT_HEADERS = [field.name for field in fields(Contractor)]


def write_csv(path, rows, board=False):
    destination = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8-sig", dir=destination.parent, delete=False
        ) as handle:
            temporary = handle.name
            headers = _BOARD_HEADERS if board else FLAT_HEADERS
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            if board:
                _write_board_csv(writer, rows)
            else:
                for row in rows:
                    writer.writerow(asdict(row))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
