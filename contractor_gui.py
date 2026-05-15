#!/usr/bin/env python3
"""
Contractor Finder v3 — entry point.

Module layout:
  models.py          Contractor dataclass
  constants.py       Regexes, trade keywords, colour maps, proxy sources
  compat.py          Optional-dep detection (scrapling, aiohttp, dnspython)
  cache.py           ContactCache (SQLite) + SearchHistory
  proxy.py           ProxyManager elite pool
  http_client.py     http_get / stealth_get / post_bytes / get_event_loop
  extractor.py       extract_contacts / verify_email / email helpers
  scrapers/
    ddg.py           DuckDuckGo search
    osm.py           OpenStreetMap / Overpass / Nominatim
    yellowpages.py   YellowPages scraper
    yelp.py          Yelp scraper
    google.py        Google Maps scraper
  enricher.py        async/sync website enrichment + dedup
  search.py          run_search orchestrator
  workers.py         QThread wrappers (SearchWorker, VerifyWorker)
  gui/
    style.py         STYLE CSS + COLS / VERIFY_COLORS / VERIFY_ICONS
    widgets.py       StatCard
    main_window.py   MainWindow
"""
from __future__ import annotations
import logging, os, sys
from logging.handlers import RotatingFileHandler

# ── Logging must be configured before any local import ───────────────────────
_LOG_FILE = os.path.join(os.path.expanduser("~"), "contractor_finder.log")
_logger   = logging.getLogger("ContractorFinder")
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
_logger.setLevel(getattr(logging, _log_level, logging.INFO))
_fh = RotatingFileHandler(_LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
_logger.addHandler(_fh)
_logger.addHandler(_ch)
_logger.propagate = False

# ── Application ───────────────────────────────────────────────────────────────
from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow
from gui.style import STYLE

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setApplicationName("Contractor Finder v3")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
