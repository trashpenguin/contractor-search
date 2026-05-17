"""Tests for yellowpages.py parsing logic.

_parse_yp_nextdata is the first thing to break when YP restructures their
Next.js page — these tests document every JSON key path it relies on.
No network calls are made.
"""

from __future__ import annotations

import json

from scrapers.yellowpages import _parse_yp_nextdata


def _make_html(page_props: dict) -> str:
    """Wrap page_props in a minimal Yelp-style __NEXT_DATA__ script tag."""
    data = {"props": {"pageProps": page_props}}
    return f'<script id="__NEXT_DATA__" type="application/json">' f"{json.dumps(data)}</script>"


class TestParseYPNextData:
    # ── happy-path key paths ─────────────────────────────────────────────────

    def test_parses_listings_key(self):
        html = _make_html(
            {
                "listings": [
                    {
                        "businessName": "Smith Electric",
                        "phone": "(313) 555-0001",
                        "website": "https://smithelectric.com",
                        "address": {
                            "street": "100 Main St",
                            "city": "Warren",
                            "state": "MI",
                            "zip": "48091",
                        },
                    }
                ]
            }
        )
        results = _parse_yp_nextdata(html)
        assert len(results) == 1
        r = results[0]
        assert r.name == "Smith Electric"
        assert r.phone == "(313) 555-0001"
        assert r.website == "https://smithelectric.com"
        assert "Warren" in r.address

    def test_parses_searchResults_listings(self):
        html = _make_html(
            {
                "searchResults": {
                    "listings": [{"businessName": "Jones HVAC", "phone": "(313) 555-0002"}]
                }
            }
        )
        results = _parse_yp_nextdata(html)
        assert len(results) == 1
        assert results[0].name == "Jones HVAC"

    def test_parses_results_key(self):
        html = _make_html({"results": [{"businessName": "A Corp"}]})
        results = _parse_yp_nextdata(html)
        assert results[0].name == "A Corp"

    def test_parses_businesses_key(self):
        html = _make_html({"businesses": [{"businessName": "B Corp"}]})
        results = _parse_yp_nextdata(html)
        assert results[0].name == "B Corp"

    # ── name field fallbacks ─────────────────────────────────────────────────

    def test_name_field_fallback(self):
        html = _make_html({"listings": [{"name": "Fallback Name Corp"}]})
        assert _parse_yp_nextdata(html)[0].name == "Fallback Name Corp"

    def test_business_name_field_fallback(self):
        html = _make_html({"listings": [{"business_name": "Snake Case Corp"}]})
        assert _parse_yp_nextdata(html)[0].name == "Snake Case Corp"

    # ── phone / website field fallbacks ─────────────────────────────────────

    def test_phoneNumber_fallback(self):
        html = _make_html(
            {"listings": [{"businessName": "Apex Corp", "phoneNumber": "(313) 900-0001"}]}
        )
        assert _parse_yp_nextdata(html)[0].phone == "(313) 900-0001"

    def test_primaryPhone_fallback(self):
        html = _make_html(
            {"listings": [{"businessName": "Apex Corp", "primaryPhone": "(313) 900-0002"}]}
        )
        assert _parse_yp_nextdata(html)[0].phone == "(313) 900-0002"

    def test_websiteUrl_fallback(self):
        html = _make_html(
            {"listings": [{"businessName": "Apex Corp", "websiteUrl": "https://apex.com"}]}
        )
        assert _parse_yp_nextdata(html)[0].website == "https://apex.com"

    def test_url_fallback(self):
        html = _make_html({"listings": [{"businessName": "Beta Corp", "url": "https://beta.com"}]})
        assert _parse_yp_nextdata(html)[0].website == "https://beta.com"

    # ── filtering ────────────────────────────────────────────────────────────

    def test_filters_yellowpages_website(self):
        html = _make_html(
            {
                "listings": [
                    {
                        "businessName": "A Corp",
                        "website": "https://www.yellowpages.com/listing/123",
                    }
                ]
            }
        )
        assert _parse_yp_nextdata(html)[0].website == ""

    def test_skips_name_too_short(self):
        html = _make_html({"listings": [{"businessName": "A"}]})
        assert _parse_yp_nextdata(html) == []

    def test_skips_non_dict_entry(self):
        # Raw string in the list should not crash
        data = {"props": {"pageProps": {"listings": ["not-a-dict"]}}}
        html = f'<script id="__NEXT_DATA__" type="application/json">' f"{json.dumps(data)}</script>"
        assert _parse_yp_nextdata(html) == []

    # ── address assembly ─────────────────────────────────────────────────────

    def test_address_assembled_from_dict(self):
        html = _make_html(
            {
                "listings": [
                    {
                        "businessName": "Test Co",
                        "address": {
                            "street": "500 Oak Ave",
                            "city": "Detroit",
                            "state": "MI",
                            "zip": "48201",
                        },
                    }
                ]
            }
        )
        addr = _parse_yp_nextdata(html)[0].address
        assert "500 Oak Ave" in addr
        assert "Detroit" in addr
        assert "MI" in addr

    def test_address_streetAddress_fallback(self):
        html = _make_html(
            {
                "listings": [
                    {
                        "businessName": "Test Co",
                        "address": {"streetAddress": "42 Elm St", "city": "Flint"},
                    }
                ]
            }
        )
        addr = _parse_yp_nextdata(html)[0].address
        assert "42 Elm St" in addr

    def test_string_address_used_directly(self):
        html = _make_html(
            {"listings": [{"businessName": "Test Co", "address": "123 Plain St, Lansing, MI"}]}
        )
        addr = _parse_yp_nextdata(html)[0].address
        assert "123 Plain St" in addr

    # ── metadata ─────────────────────────────────────────────────────────────

    def test_source_is_yellowpages(self):
        html = _make_html({"listings": [{"businessName": "Test Corp"}]})
        assert _parse_yp_nextdata(html)[0].source == "YellowPages"

    def test_multiple_listings(self):
        html = _make_html(
            {
                "listings": [
                    {"businessName": f"Company {i}", "phone": f"(313) 555-{i:04d}"}
                    for i in range(5)
                ]
            }
        )
        assert len(_parse_yp_nextdata(html)) == 5

    # ── error cases ──────────────────────────────────────────────────────────

    def test_missing_script_tag_returns_empty(self):
        assert _parse_yp_nextdata("<html><body>plain page</body></html>") == []

    def test_invalid_json_returns_empty(self):
        html = '<script id="__NEXT_DATA__" type="application/json">{bad}</script>'
        assert _parse_yp_nextdata(html) == []

    def test_no_listings_key_returns_empty(self):
        html = _make_html({"otherData": "irrelevant"})
        assert _parse_yp_nextdata(html) == []

    def test_empty_listings_returns_empty(self):
        html = _make_html({"listings": []})
        assert _parse_yp_nextdata(html) == []
