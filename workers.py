from __future__ import annotations
import threading, time

from PySide6.QtCore import QThread, Signal

from extractor import verify_email
from search import run_search


class SearchWorker(QThread):
    progress    = Signal(int, str)
    result      = Signal(object)
    finished    = Signal(bool, str)
    source_done = Signal(str, str, int)   # source, trade, count (-1 = error)

    def __init__(self, location, trades, limit, radius_m, enrich, sources):
        super().__init__()
        self.location = location
        self.trades   = trades
        self.limit    = limit
        self.radius_m = radius_m
        self.enrich   = enrich
        self.sources  = sources
        self._stop    = threading.Event()

    def run(self):
        run_search(
            self.location, self.trades, self.limit, self.radius_m,
            self.enrich, self.sources,
            self.progress.emit, self.result.emit, self.finished.emit, self._stop,
            source_cb=self.source_done.emit,
        )

    def stop(self):
        self._stop.set()


class VerifyWorker(QThread):
    progress = Signal(int, str)
    result   = Signal(int, str, str)
    finished = Signal()

    def __init__(self, rows):
        super().__init__()
        self.rows  = rows
        self._stop = threading.Event()

    def run(self):
        total = len(self.rows)
        for i, c in enumerate(self.rows):
            if self._stop.is_set():
                break
            self.progress.emit(
                int(i / total * 100),
                f"Verifying {i+1}/{total}: {c.email or '(no email)'}...",
            )
            status, reason = verify_email(c.email) if c.email else ("unknown", "No email")
            c.email_status = status
            self.result.emit(i, status, reason)
            if c.email:
                time.sleep(0.1)  # brief rate-limit guard only when a DNS call was made
        self.finished.emit()

    def stop(self):
        self._stop.set()
