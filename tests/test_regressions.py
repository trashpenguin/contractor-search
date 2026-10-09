import asyncio
import csv
import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from browser_setup import driver_command
from enricher import _fetch_one, dedup, website_matches
from exporter import write_csv
from location import distance_m, miles_to_meters, valid_location
from models import Contractor
from provenance import email_label
from scrapers.google_places import _FIELDS_V1, _search_v1
from scrapers.yelp import _cache_key


@pytest.mark.parametrize("location", ["48091", "48091-1234", "Warren, MI", "St. Louis, MO"])
def test_locations(location):
    assert valid_location(location)


@pytest.mark.parametrize("location", ["", "12", "123456", "!!!"])
def test_invalid_locations(location):
    assert not valid_location(location)


def test_radius_units():
    assert miles_to_meters(40) == 64374
    assert distance_m(42, -83, 42, -83) == 0
    assert distance_m(42, -83, 43, -83) > 100000


def test_conflicting_contacts_do_not_merge():
    a = Contractor("HVAC", "Smith HVAC", phone="3135551234", address="1 Main St")
    b = Contractor("HVAC", "Smith HVAC", phone="3135554567", address="2 Main St")
    assert len(dedup([a, b])) == 2


def test_trade_words_alone_do_not_merge():
    assert len(dedup([Contractor("HVAC", "Smith Heating"),
                      Contractor("Electrical", "Smith Electric")])) == 2


def test_domain_requires_business_identity():
    c = Contractor("HVAC", "Smith HVAC", phone="3135551234")
    assert not website_matches(c, "<h1>Smith HVAC</h1><p>Another business</p>")
    assert website_matches(c, "<h1>Smith HVAC</h1><p>(313) 555-1234</p>")
    assert not website_matches(c, "<h1>Other HVAC</h1><p>(313) 555-1234</p>")


def test_yelp_cache_separates_state_and_limit():
    assert _cache_key("HVAC", "Springfield, IL", 10) != _cache_key("HVAC", "Springfield, MO", 10)
    assert _cache_key("HVAC", "Springfield, IL", 10) != _cache_key("HVAC", "Springfield, IL", 30)


def test_places_requests_pagination_and_identity():
    assert "nextPageToken" in _FIELDS_V1
    assert "places.id" in _FIELDS_V1
    responses = [
        {"places": [{"id": "one", "displayName": {"text": "First"}}], "nextPageToken": "next"},
        {"places": [{"id": "two", "displayName": {"text": "Second"}}]},
    ]
    with patch("scrapers.google_places._api_post", side_effect=responses) as api:
        with patch("scrapers.google_places.interruptible_sleep"):
            results = _search_v1("HVAC", "hvac", "48091", 30, "key", 0, 0, 1000)
    assert [row.place_id for row in results] == ["one", "two"]
    assert api.call_args_list[1].args[1]["pageToken"] == "next"
    assert "locationBias" in api.call_args_list[0].args[1]


def test_tls_validation_even_with_proxy():
    class Session:
        def get(self, url, **kwargs):
            assert kwargs["ssl"] is True
            raise RuntimeError("certificate verification failed")
    with patch("enricher.PROXY_MGR", SimpleNamespace(
        ready=True, get_for=lambda url: "http://proxy", report=lambda *args: None
    )):
        assert asyncio.run(_fetch_one(Session(), "https://example.com", 1, True)) == ""


def test_export_preserves_guess_provenance(tmp_path):
    row = Contractor("HVAC", "Smith", email="info@smith.com",
                     email_method="guessed", email_status="valid")
    path = tmp_path / "results.csv"
    write_csv(path, [row])
    with path.open(encoding="utf-8-sig", newline="") as handle:
        exported = list(csv.DictReader(handle))
    assert len(exported) == 1
    assert exported[0]["email_method"] == "guessed"
    assert exported[0]["email_status"] == "valid"
    assert "Guessed" in email_label(row)


def test_failed_atomic_export_retains_existing_file(tmp_path):
    path = tmp_path / "results.csv"
    path.write_text("original")
    with patch("exporter.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            write_csv(path, [Contractor("HVAC", "Smith")])
    assert path.read_text() == "original"
    assert len(list(tmp_path.iterdir())) == 1


def test_browser_command_contains_driver_cli():
    driver = SimpleNamespace(compute_driver_executable=lambda: ("node.exe", "cli.js"),
                             get_driver_env=lambda: {"DRIVER": "yes"})
    with patch("browser_setup.importlib.import_module", return_value=driver):
        command, env = driver_command("playwright")
    assert command == ["node.exe", "cli.js", "install", "chromium"]
    assert env == {"DRIVER": "yes"}


def test_cache_clear_counts_both_tables(tmp_path):
    from cache import ContactCache
    with patch.object(ContactCache, "DB_PATH", str(tmp_path / "cache.db")):
        cache = ContactCache()
    cache.set_contact("site", "email", "phone", "website")
    cache.set_ddg("query", [])
    assert cache.clear_all() == 2


def test_malformed_settings_are_ignored(tmp_path):
    import config
    path = tmp_path / "settings.json"
    path.write_text(json.dumps([]))
    with patch.object(config, "_SETTINGS_FILE", path):
        assert config.get("missing") is None
        config.set("key", "value")
        assert config.get("key") == "value"


def test_search_cancelled_before_network():
    from search import run_search
    event = threading.Event()
    event.set()
    completed = []
    run_search("48091", ["HVAC"], 10, 1000, False, ["OSM"],
               lambda *args: None, lambda *args: None,
               lambda *args: completed.append(args), event)
    assert len(completed) == 1
    assert completed[0][0] == "cancelled"


def test_search_partial_failure_is_reported():
    import search
    completed = []
    with patch("scrapers.osm.geocode", return_value=(42, -83)):
        with patch.dict(search.SRC_FN, {
            "Yelp": lambda *args: [],
            "YellowPages": lambda *args: (_ for _ in ()).throw(RuntimeError("blocked")),
        }):
            search.run_search("48091", ["HVAC"], 10, 1000, False,
                              ["Yelp", "YellowPages"], lambda *args: None,
                              lambda *args: None, lambda *args: completed.append(args),
                              threading.Event())
    assert len(completed) == 1
    assert completed[0][0] == "partial"


def test_osm_fallback_filters_radius():
    from scrapers.osm import scrape_osm
    places = [
        {"lat": "42.001", "lon": "-83", "name": "Smith HVAC", "place_id": "1"},
        {"lat": "43", "lon": "-83", "name": "Far HVAC", "place_id": "2"},
    ]
    with patch("scrapers.osm.post_bytes", return_value=b'{"elements": []}'):
        with patch("scrapers.osm.http_get", return_value=json.dumps(places)):
            with patch("scrapers.osm.interruptible_sleep"):
                rows = scrape_osm("HVAC", 42, -83, 1000, 10)
    assert [row.name for row in rows] == ["Smith HVAC"]
