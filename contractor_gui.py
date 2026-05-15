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

import json as _json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


class _JsonFormatter(logging.Formatter):
    """Structured JSON log formatter — enabled via LOG_FORMAT=json env var."""

    def format(self, record: logging.LogRecord) -> str:
        return _json.dumps(
            {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
        )


# ── Logging must be configured before any local import ───────────────────────
_LOG_FILE = os.path.join(os.path.expanduser("~"), "contractor_finder.log")
_logger = logging.getLogger("ContractorFinder")
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
_logger.setLevel(getattr(logging, _log_level, logging.INFO))
_fh = RotatingFileHandler(_LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
if os.environ.get("LOG_FORMAT", "text").lower() == "json":
    _fh.setFormatter(_JsonFormatter())
else:
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
_logger.addHandler(_fh)
_logger.addHandler(_ch)
_logger.propagate = False

# ── Application ───────────────────────────────────────────────────────────────
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.main_window import MainWindow  # noqa: E402
from gui.style import STYLE  # noqa: E402


def _ensure_browsers() -> None:
    """First-run check: install Playwright/Patchright Chromium browsers if missing.

    Browsers live in %LOCALAPPDATA%\\ms-playwright and are NOT bundled in the exe
    (they're ~150 MB). This runs once on first launch and never again.
    Uses the driver executables shipped with the playwright/patchright packages so
    it works whether running from source or as a PyInstaller bundle.
    """
    import glob as _glob
    import subprocess

    localappdata = os.environ.get("LOCALAPPDATA", "")
    if _glob.glob(os.path.join(localappdata, "ms-playwright", "chromium-*")):
        return  # already installed

    from PySide6.QtCore import Qt, QThread
    from PySide6.QtCore import Signal as _Signal
    from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

    class _InstallThread(QThread):
        line_ready = _Signal(str)
        done = _Signal(bool)

        def run(self) -> None:
            ok = True
            try:
                from patchright._impl._driver import compute_driver_executable as _pr_drv
                from playwright._impl._driver import compute_driver_executable as _pw_drv

                for _cde in (_pw_drv, _pr_drv):
                    drv, env = _cde()
                    proc = subprocess.Popen(
                        [str(drv), "install", "chromium"],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    for ln in proc.stdout:
                        self.line_ready.emit(ln.rstrip())
                    proc.wait()
                    if proc.returncode != 0:
                        ok = False
            except Exception as exc:
                self.line_ready.emit(f"Error during browser install: {exc}")
                ok = False
            self.done.emit(ok)

    dlg = QDialog()
    dlg.setWindowTitle("Contractor Finder — First-Time Setup")
    dlg.setMinimumWidth(540)
    dlg.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
    layout = QVBoxLayout(dlg)
    layout.addWidget(
        QLabel(
            "Downloading browser engines (one-time setup, ~150 MB).\n"
            "This may take a few minutes. Please wait..."
        )
    )
    log = QPlainTextEdit()
    log.setReadOnly(True)
    log.setMaximumBlockCount(300)
    layout.addWidget(log)
    btn = QPushButton("Continue")
    btn.setEnabled(False)
    layout.addWidget(btn)
    btn.clicked.connect(dlg.accept)

    thread = _InstallThread()
    thread.line_ready.connect(log.appendPlainText)
    thread.done.connect(lambda _ok: btn.setEnabled(True))
    thread.start()
    dlg.exec()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setApplicationName("Contractor Finder v3")
    _ensure_browsers()
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
