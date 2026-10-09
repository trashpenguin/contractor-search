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
    assert (
        len(
            dedup([Contractor("HVAC", "Smith Heating"), Contractor("Electrical", "Smith Electric")])
        )
        == 2
    )


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

    with patch(
        "enricher.PROXY_MGR",
        SimpleNamespace(ready=True, get_for=lambda url: "http://proxy", report=lambda *args: None),
    ):
        assert asyncio.run(_fetch_one(Session(), "https://example.com", 1, True)) == ""


def test_export_preserves_guess_provenance(tmp_path):
    row = Contractor(
        "HVAC", "Smith", email="info@smith.com", email_method="guessed", email_status="valid"
    )
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
    driver = SimpleNamespace(
        compute_driver_executable=lambda: ("node.exe", "cli.js"),
        get_driver_env=lambda: {"DRIVER": "yes"},
    )
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
    run_search(
        "48091",
        ["HVAC"],
        10,
        1000,
        False,
        ["OSM"],
        lambda *args: None,
        lambda *args: None,
        lambda *args: completed.append(args),
        event,
    )
    assert len(completed) == 1
    assert completed[0][0] == "cancelled"


def test_search_partial_failure_is_reported():
    import search

    completed = []
    with patch("scrapers.osm.geocode", return_value=(42, -83)):
        with patch.dict(
            search.SRC_FN,
            {
                "Yelp": lambda *args: [],
                "YellowPages": lambda *args: (_ for _ in ()).throw(RuntimeError("blocked")),
            },
        ):
            search.run_search(
                "48091",
                ["HVAC"],
                10,
                1000,
                False,
                ["Yelp", "YellowPages"],
                lambda *args: None,
                lambda *args: None,
                lambda *args: completed.append(args),
                threading.Event(),
            )
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


def test_proxy_bans_are_honored():
    from proxy import ProxyEntry, ProxyManager

    manager = ProxyManager()
    manager._enabled = True
    manager._pool = [ProxyEntry("http://proxy:8080", 1)]
    manager.ban_for_domain("http://proxy:8080", "www.yelp.com")
    assert manager.get_for("https://www.yelp.com/search") is None
    manager.disable()
    assert manager.get() is None


def test_async_enrichment_stop_cancels_pending_requests():
    from enricher import enrich_batch_async

    started = threading.Event()
    stop = threading.Event()

    async def slow_fetch(*args, **kwargs):
        started.set()
        await asyncio.sleep(60)
        return ""

    async def scenario():
        task = asyncio.create_task(
            enrich_batch_async(
                [Contractor("HVAC", "Smith", website="https://smith.example")],
                "Warren",
                stop_ev=stop,
            )
        )
        while not started.is_set():
            await asyncio.sleep(0.01)
        stop.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)

    with patch("enricher._fetch_one", side_effect=slow_fetch):
        asyncio.run(scenario())


def test_worker_verification_snapshot_uses_ids():
    from workers import VerifyWorker

    row = Contractor("HVAC", "Smith", email="info@smith.com")
    worker = VerifyWorker([row])
    results = []
    worker.result.connect(lambda *args: results.append(args))
    with patch("workers.verify_email", return_value=("valid", "mail domain")):
        worker.run()
    assert results == [(row.record_id, "valid", "mail domain")]
    assert row.email_status == ""


def test_async_contact_source_tracks_subpage():
    from enricher import async_scrape_website

    origins = {}
    homepage = '<a href="/contact">Contact</a>'
    contact = '<a href="mailto:office@smithhvac.com">Email</a><p>(313) 555-1234</p>'
    with patch("enricher._fetch_one", side_effect=[homepage, contact]):
        email, phone = asyncio.run(async_scrape_website("https://smithhvac.com", None, 1, origins))
    assert email == "office@smithhvac.com"
    assert phone
    assert origins["email_source_url"] == "https://smithhvac.com/contact"


def test_cached_contact_preserves_source_url(tmp_path):
    from cache import ContactCache

    with patch.object(ContactCache, "DB_PATH", str(tmp_path / "cache.db")):
        cache = ContactCache()
    cache.set_contact(
        "site",
        "office@smith.com",
        "",
        "https://smith.com",
        {"email_source_url": "https://smith.com/contact"},
    )
    assert cache.get_contact("site")["email_source_url"] == "https://smith.com/contact"


def test_provenance_keeps_exact_contact_page():
    from provenance import record_contact

    row = Contractor(
        "HVAC",
        "Smith",
        email="office@smith.com",
        website="https://smith.com",
        email_source_url="https://smith.com/contact",
    )
    record_contact(row, row.website)
    assert row.email_source_url == "https://smith.com/contact"


def test_null_mx_is_not_a_valid_mail_domain():
    from extractor import verify_email

    with patch("dns.resolver.resolve", return_value=[SimpleNamespace(exchange=".")]):
        assert verify_email("office@smithhvac.com")[0] == "invalid"


def test_ddg_enrichment_remains_responsive_and_stops():
    from enricher import enrich_batch_async
    from http_client import interruptible_sleep

    started = threading.Event()
    stop = threading.Event()

    def slow_ddg(*args, **kwargs):
        started.set()
        interruptible_sleep(60)
        return []

    async def scenario():
        task = asyncio.create_task(
            enrich_batch_async([Contractor("HVAC", "Smith HVAC")], "Warren", stop_ev=stop)
        )
        await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=2)
        # Reaching here demonstrates DDG did not block the event loop.
        stop.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)

    with patch("enricher._build_domain_candidates", return_value=[]):
        with patch("scrapers.ddg.ddg_search", side_effect=slow_ddg):
            asyncio.run(scenario())


def test_google_does_not_assign_unrelated_page_contacts():
    from scrapers.google import scrape_google

    response = SimpleNamespace(body="<html></html>")
    session = SimpleNamespace(fetch=lambda *args, **kwargs: response)
    with patch("scrapers.google.StealthySession") as factory:
        factory.return_value.__enter__.return_value = session
        with patch("scrapers.google._parse_feed", return_value=[{"name": "Smith HVAC"}]):
            with patch(
                "scrapers.google._parse_app_state",
                return_value={
                    "names": ["Other Company"],
                    "phones": ["3135559999"],
                    "websites": ["https://othercompany.com"],
                },
            ):
                rows = scrape_google("HVAC", "48091", 10)
    assert rows[0].phone == ""
    assert rows[0].website == ""


def test_contact_cache_migrates_old_database(tmp_path):
    import sqlite3

    from cache import ContactCache

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE contacts (key TEXT PRIMARY KEY, email TEXT, phone TEXT, "
            "website TEXT, created_at REAL)"
        )
    with patch.object(ContactCache, "DB_PATH", str(path)):
        cache = ContactCache()
    cache.set_contact(
        "site",
        "office@smith.com",
        "",
        "https://smith.com",
        {"email_source_url": "https://smith.com/contact"},
    )
    assert cache.get_contact("site")["email_source_url"].endswith("/contact")


def test_browser_readiness_uses_patchright_playwright_factory(tmp_path):
    from browser_setup import browsers_ready

    executable = tmp_path / "chromium"
    executable.touch()
    runtime = SimpleNamespace(chromium=SimpleNamespace(executable_path=str(executable)))

    class Context:
        def __enter__(self):
            return runtime

        def __exit__(self, *args):
            pass

    api = SimpleNamespace(sync_playwright=lambda: Context())
    with patch("browser_setup.importlib.import_module", return_value=api):
        assert browsers_ready()
