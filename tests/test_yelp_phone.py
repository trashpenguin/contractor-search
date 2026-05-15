import json

from scrapers.yelp import _parse_next_data


def _wrap(biz: dict) -> str:
    """Wrap a business dict in minimal __NEXT_DATA__ structure."""
    payload = {
        "props": {
            "pageProps": {"searchPageProps": {"businessList": [{"searchResultBusiness": biz}]}}
        }
    }
    blob = json.dumps(payload)
    return f'<script id="__NEXT_DATA__" type="application/json">{blob}</script>'


def test_parse_next_data_display_phone():
    html = _wrap(
        {"name": "Acme HVAC", "businessUrl": "/biz/acme", "displayPhone": "(313) 555-0101"}
    )
    results = _parse_next_data(html)
    assert results[0]["phone"] == "(313) 555-0101"


def test_parse_next_data_primary_phone_fallback():
    html = _wrap(
        {"name": "Acme HVAC", "businessUrl": "/biz/acme", "primaryPhone": "(313) 555-0102"}
    )
    results = _parse_next_data(html)
    assert results[0]["phone"] == "(313) 555-0102"


def test_parse_next_data_formatted_phone_fallback():
    html = _wrap(
        {
            "name": "Acme HVAC",
            "businessUrl": "/biz/acme",
            "formattedPhone": "(313) 555-0103",
        }
    )
    results = _parse_next_data(html)
    assert results[0]["phone"] == "(313) 555-0103"


def test_parse_next_data_phone_empty_when_none():
    html = _wrap({"name": "Acme HVAC", "businessUrl": "/biz/acme"})
    results = _parse_next_data(html)
    assert results[0]["phone"] == ""
