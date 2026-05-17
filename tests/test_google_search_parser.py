"""Tests for google_search.py parsing logic.

Covers the pure functions used to extract business data from Google Search
result pages. No network calls or browser required.
"""

from __future__ import annotations

from scrapers.google_search import (
    _addr_from_maps_href,
    _clean_name_fallback,
    _is_proxy_error,
    _name_from_maps_href,
)

# ── _name_from_maps_href ──────────────────────────────────────────────────────


class TestNameFromMapsHref:
    def test_basic_extraction(self):
        href = "/maps/dir//Smith+HVAC+LLC/123+Main+St+Warren+MI/data=abc"
        assert _name_from_maps_href(href) == "Smith HVAC LLC"

    def test_plus_signs_decoded_to_spaces(self):
        href = "/maps/dir//Jones+Electric+Inc/456+Elm+St/data=xyz"
        name = _name_from_maps_href(href)
        assert "Jones" in name
        assert "Electric" in name

    def test_returns_empty_for_no_match(self):
        assert _name_from_maps_href("https://example.com/page") == ""

    def test_returns_empty_for_non_maps_url(self):
        assert _name_from_maps_href("https://google.com/search?q=hvac") == ""

    def test_strips_trailing_whitespace(self):
        href = "/maps/dir//Warren+Plumbing+/123+St/data=abc"
        name = _name_from_maps_href(href)
        assert not name.startswith(" ")
        assert not name.endswith(" ")


# ── _addr_from_maps_href ──────────────────────────────────────────────────────


class TestAddrFromMapsHref:
    def test_basic_address_extraction(self):
        href = "/maps/dir//Smith+HVAC/123+Main+St%2C+Warren%2C+MI+48091/data=abc"
        addr = _addr_from_maps_href(href)
        assert "123 Main St" in addr or "Warren" in addr

    def test_strips_united_states_suffix(self):
        href = "/maps/dir//Smith+HVAC/500+Oak+Ave%2C+Detroit%2C+MI%2C+United+States/data=abc"
        addr = _addr_from_maps_href(href)
        assert "United States" not in addr
        assert "Detroit" in addr

    def test_returns_empty_for_no_match(self):
        assert _addr_from_maps_href("https://google.com") == ""

    def test_returns_empty_for_non_maps_href(self):
        assert _addr_from_maps_href("/search?q=hvac") == ""


# ── _clean_name_fallback ──────────────────────────────────────────────────────


class TestCleanNameFallback:
    def test_stops_at_rating(self):
        result = _clean_name_fallback("Smith HVAC 4.7 (123 reviews) Open now")
        assert result == "Smith HVAC"

    def test_stops_at_no_reviews(self):
        result = _clean_name_fallback("Jones Electric No reviews")
        assert result == "Jones Electric"

    def test_stops_at_google_bullet(self):
        result = _clean_name_fallback("Warren Plumbing · HVAC · Open")
        assert result == "Warren Plumbing"

    def test_stops_at_open_hours(self):
        result = _clean_name_fallback("Detroit Fence Co Open until 6 PM")
        assert result == "Detroit Fence Co"

    def test_stops_at_closed(self):
        result = _clean_name_fallback("Apex Grading Closed opens 8 AM")
        assert result == "Apex Grading"

    def test_strips_sponsored_prefix(self):
        result = _clean_name_fallback("Sponsored Smith Heating & Cooling")
        assert result == "Smith Heating & Cooling"

    def test_sponsored_case_insensitive(self):
        result = _clean_name_fallback("SPONSORED Michigan Electric")
        assert result == "Michigan Electric"

    def test_plain_name_unchanged(self):
        result = _clean_name_fallback("Michigan Electric Co")
        assert result == "Michigan Electric Co"

    def test_truncates_at_100_chars(self):
        long_name = "A" * 150
        assert len(_clean_name_fallback(long_name)) == 100

    def test_empty_string(self):
        assert _clean_name_fallback("") == ""

    def test_whitespace_stripped(self):
        result = _clean_name_fallback("  Smith HVAC  ")
        assert result == "Smith HVAC"

    def test_stops_at_review_count_paren(self):
        # "(123)" review count pattern — \s+\(
        result = _clean_name_fallback("Acme Fencing (500 reviews)")
        assert result == "Acme Fencing"


# ── _is_proxy_error ───────────────────────────────────────────────────────────


class TestIsProxyError:
    def test_detects_proxy_connection_failed(self):
        assert _is_proxy_error(Exception("net::ERR_PROXY_CONNECTION_FAILED"))

    def test_detects_tunnel_connection_failed(self):
        assert _is_proxy_error(Exception("ERR_TUNNEL_CONNECTION_FAILED"))

    def test_detects_econnrefused(self):
        assert _is_proxy_error(Exception("ECONNREFUSED 127.0.0.1:8080"))

    def test_detects_etimedout(self):
        assert _is_proxy_error(Exception("ETIMEDOUT connecting to proxy"))

    def test_detects_connection_timed_out(self):
        assert _is_proxy_error(Exception("ERR_CONNECTION_TIMED_OUT"))

    def test_detects_proxyerror_string(self):
        assert _is_proxy_error(Exception("ProxyError: upstream connect error"))

    def test_detects_net_err_proxy(self):
        assert _is_proxy_error(Exception("net::ERR_PROXY something"))

    def test_detects_net_err_tunnel(self):
        assert _is_proxy_error(Exception("net::ERR_TUNNEL_CONNECTION_FAILED"))

    def test_timeout_not_proxy_error(self):
        assert not _is_proxy_error(Exception("TimeoutError: 30s exceeded"))

    def test_generic_exception_not_proxy_error(self):
        assert not _is_proxy_error(Exception("Something went wrong"))

    def test_404_not_proxy_error(self):
        assert not _is_proxy_error(Exception("HTTP 404 Not Found"))

    def test_empty_message_not_proxy_error(self):
        assert not _is_proxy_error(Exception(""))
