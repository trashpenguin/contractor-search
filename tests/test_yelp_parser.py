"""Tests for yelp.py parsing logic.

These cover the functions most likely to break when Yelp changes their
page structure: the __NEXT_DATA__ parser, listicle filter, biz-page
extractor, and URL builder. No network calls are made.
"""

from __future__ import annotations

import json

from scrapers.yelp import (
    _extract_biz_page,
    _is_listicle_name,
    _parse_next_data,
    _recursive_find_businesses,
    _try_path,
    _yelp_url,
)

# ── _is_listicle_name ────────────────────────────────────────────────────────


class TestIsListicleName:
    def test_numeric_best_prefix(self):
        assert _is_listicle_name("10 Best HVAC Contractors in Warren")

    def test_the_n_best(self):
        assert _is_listicle_name("The 10 Best Electricians")

    def test_top_rated_prefix(self):
        assert _is_listicle_name("Top-Rated HVAC Companies")

    def test_top_n_prefix(self):
        assert _is_listicle_name("Top 5 Electricians Near Me")

    def test_best_word_prefix(self):
        assert _is_listicle_name("Best HVAC Services in Michigan")

    def test_contractors_in(self):
        assert _is_listicle_name("HVAC Contractors in Warren MI")

    def test_companies_in(self):
        assert _is_listicle_name("Plumbing Companies in Detroit")

    def test_services_in(self):
        assert _is_listicle_name("Electrical Services in Chicago")

    def test_real_business_name_passes(self):
        assert not _is_listicle_name("Smith Plumbing & Heating")

    def test_empty_string_passes(self):
        assert not _is_listicle_name("")

    def test_normal_company_name(self):
        assert not _is_listicle_name("Warren Electric LLC")

    def test_name_with_inc(self):
        assert not _is_listicle_name("Jones Excavating Inc")


# ── _try_path ────────────────────────────────────────────────────────────────


class TestTryPath:
    def test_valid_path_returns_list(self):
        data = {"a": {"b": {"c": [1, 2, 3]}}}
        assert _try_path(data, ["a", "b", "c"]) == [1, 2, 3]

    def test_missing_key_returns_none(self):
        data = {"a": {"b": {}}}
        assert _try_path(data, ["a", "b", "c"]) is None

    def test_non_list_value_returns_none(self):
        data = {"a": {"b": "not-a-list"}}
        assert _try_path(data, ["a", "b"]) is None

    def test_empty_path_returns_none(self):
        # root is a dict, not a list — should return None
        assert _try_path({"key": "val"}, []) is None

    def test_intermediate_non_dict_returns_none(self):
        data = {"a": [1, 2, 3]}
        assert _try_path(data, ["a", "b"]) is None

    def test_none_intermediate_returns_none(self):
        data = {"a": None}
        assert _try_path(data, ["a", "b"]) is None


# ── _recursive_find_businesses ────────────────────────────────────────────────


class TestRecursiveFindBusinesses:
    def _biz(self, name, url="/biz/slug"):
        return {"searchResultBusiness": {"name": name, "businessUrl": url}}

    def test_finds_top_level_list(self):
        businesses = [self._biz("Smith HVAC"), self._biz("Jones Electric")]
        result = _recursive_find_businesses({"results": businesses})
        assert result == businesses

    def test_finds_nested_list(self):
        businesses = [self._biz("A Corp"), self._biz("B Corp")]
        data = {"outer": {"inner": {"list": businesses}}}
        assert _recursive_find_businesses(data) == businesses

    def test_returns_none_for_empty_dict(self):
        assert _recursive_find_businesses({}) is None

    def test_returns_none_for_single_item_list(self):
        # list must have >= 2 items to qualify
        assert _recursive_find_businesses({"r": [self._biz("Only One")]}) is None

    def test_depth_limit_prevents_deep_traversal(self):
        # Build 15 levels of nesting — exceeds the depth=10 limit
        node: dict = {}
        cur = node
        for _ in range(15):
            cur["child"] = {}
            cur = cur["child"]
        cur["list"] = [self._biz("A"), self._biz("B")]
        assert _recursive_find_businesses(node) is None


# ── _parse_next_data ──────────────────────────────────────────────────────────


def _wrap_next_data(businesses: list, path="mainContentComponentsListProps") -> str:
    """Helper: embed a business list in a Yelp-style __NEXT_DATA__ script tag."""
    data: dict = {"props": {"pageProps": {"searchPageProps": {path: businesses}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">' f"{json.dumps(data)}</script>"


class TestParseNextData:
    def test_parses_standard_structure(self):
        html = _wrap_next_data(
            [
                {
                    "searchResultBusiness": {
                        "name": "Smith HVAC",
                        "businessUrl": "/biz/smith-hvac",
                        "primaryPhone": "(313) 555-1234",
                        "formattedAddress": "123 Main St, Warren, MI",
                    }
                }
            ]
        )
        results = _parse_next_data(html)
        assert len(results) == 1
        assert results[0]["name"] == "Smith HVAC"
        assert results[0]["phone"] == "(313) 555-1234"
        assert results[0]["address"] == "123 Main St, Warren, MI"

    def test_prefixes_relative_biz_url(self):
        html = _wrap_next_data(
            [{"searchResultBusiness": {"name": "A Corp", "businessUrl": "/biz/a-corp"}}]
        )
        results = _parse_next_data(html)
        assert results[0]["biz_url"].startswith("https://www.yelp.com")

    def test_absolute_url_kept_unchanged(self):
        url = "https://www.yelp.com/biz/smith-hvac"
        html = _wrap_next_data(
            [{"searchResultBusiness": {"name": "Smith HVAC", "businessUrl": url}}]
        )
        assert _parse_next_data(html)[0]["biz_url"] == url

    def test_skips_listicle_names(self):
        html = _wrap_next_data(
            [
                {
                    "searchResultBusiness": {
                        "name": "10 Best HVAC Companies",
                        "businessUrl": "/biz/slug",
                    }
                }
            ]
        )
        assert _parse_next_data(html) == []

    def test_skips_entry_without_biz_url(self):
        html = _wrap_next_data([{"searchResultBusiness": {"name": "No URL Corp"}}])
        assert _parse_next_data(html) == []

    def test_skips_entry_without_name(self):
        html = _wrap_next_data([{"searchResultBusiness": {"businessUrl": "/biz/no-name"}}])
        assert _parse_next_data(html) == []

    def test_displayPhone_fallback(self):
        html = _wrap_next_data(
            [
                {
                    "searchResultBusiness": {
                        "name": "A Corp",
                        "businessUrl": "/biz/a",
                        "displayPhone": "(313) 111-2222",
                    }
                }
            ]
        )
        assert _parse_next_data(html)[0]["phone"] == "(313) 111-2222"

    def test_businessList_alternate_path(self):
        """Yelp sometimes uses searchPageProps.businessList instead."""
        data = {
            "props": {
                "pageProps": {
                    "searchPageProps": {
                        "businessList": [
                            {
                                "searchResultBusiness": {
                                    "name": "Jones Electric",
                                    "businessUrl": "/biz/jones",
                                }
                            }
                        ]
                    }
                }
            }
        }
        html = f'<script id="__NEXT_DATA__" type="application/json">' f"{json.dumps(data)}</script>"
        results = _parse_next_data(html)
        assert len(results) == 1
        assert results[0]["name"] == "Jones Electric"

    def test_missing_script_tag_returns_empty(self):
        assert _parse_next_data("<html><body>no data</body></html>") == []

    def test_invalid_json_returns_empty(self):
        html = '<script id="__NEXT_DATA__" type="application/json">{bad json}</script>'
        assert _parse_next_data(html) == []

    def test_multiple_results(self):
        businesses = [
            {
                "searchResultBusiness": {
                    "name": f"Company {i}",
                    "businessUrl": f"/biz/co-{i}",
                }
            }
            for i in range(5)
        ]
        assert len(_parse_next_data(_wrap_next_data(businesses))) == 5


# ── _extract_biz_page ─────────────────────────────────────────────────────────


class TestExtractBizPage:
    def test_extracts_phone_and_website_from_jsonld(self):
        html = """
        <script type="application/ld+json">
        {"@type": "LocalBusiness", "telephone": "(313) 555-9999",
         "url": "https://smithhvac.com"}
        </script>
        """
        phone, website = _extract_biz_page(html)
        assert phone == "(313) 555-9999"
        assert website == "https://smithhvac.com"

    def test_filters_yelp_url_from_jsonld(self):
        html = """
        <script type="application/ld+json">
        {"telephone": "(313) 555-0000", "url": "https://www.yelp.com/biz/smith"}
        </script>
        """
        phone, website = _extract_biz_page(html)
        assert phone == "(313) 555-0000"
        assert website == ""

    def test_array_jsonld_parsed(self):
        html = """
        <script type="application/ld+json">
        [{"telephone": "(248) 777-8888", "url": "https://example.com"}]
        </script>
        """
        phone, website = _extract_biz_page(html)
        assert phone == "(248) 777-8888"
        assert website == "https://example.com"

    def test_malformed_jsonld_returns_blanks(self):
        html = '<script type="application/ld+json">{bad json}</script>'
        phone, website = _extract_biz_page(html)
        assert phone == ""
        assert website == ""

    def test_empty_html_returns_blanks(self):
        phone, website = _extract_biz_page("")
        assert phone == ""
        assert website == ""

    def test_sameAs_used_as_website_fallback(self):
        html = """
        <script type="application/ld+json">
        {"telephone": "(313) 100-2000", "sameAs": "https://mysite.com"}
        </script>
        """
        phone, website = _extract_biz_page(html)
        assert website == "https://mysite.com"


# ── _yelp_url ────────────────────────────────────────────────────────────────


class TestYelpUrl:
    def test_contains_cflt(self):
        assert "cflt=hvac" in _yelp_url("hvac", "Warren%2C+MI", 0)

    def test_contains_location(self):
        assert "Warren" in _yelp_url("hvac", "Warren%2C+MI", 0)

    def test_offset_zero_has_start_param(self):
        assert "start=0" in _yelp_url("hvac", "Warren%2C+MI", 0)

    def test_offset_ten(self):
        assert "start=10" in _yelp_url("hvac", "Warren%2C+MI", 10)

    def test_referrer_present(self):
        assert "dd_referrer=" in _yelp_url("hvac", "Warren%2C+MI", 0)

    def test_is_yelp_domain(self):
        assert _yelp_url("hvac", "loc", 0).startswith("https://www.yelp.com")
