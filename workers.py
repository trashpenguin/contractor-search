from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from extractor import verify_email
from search import run_search


class SearchWorker(QThread):
    progress = Signal(int, str)
    result = Signal(object)
    completed = Signal(str, str)
    source_done = Signal(str, str, int)

    def __init__(self, location, trades, limit, radius_m, enrich, sources):
        super().__init__()
        self.location = location
        self.trades = trades
        self.limit = limit
        self.radius_m = radius_m
        self.enrich = enrich
        self.sources = sources
        self._stop = threading.Event()

    def run(self):
        run_search(
            self.location,
            self.trades,
            self.limit,
            self.radius_m,
            self.enrich,
            self.sources,
            self.progress.emit,
            self.result.emit,
            self.completed.emit,
            self._stop,
            source_cb=self.source_done.emit,
        )

    def stop(self):
        self._stop.set()


class VerifyWorker(QThread):
    progress = Signal(int, str)
    result = Signal(str, str, str)
    completed = Signal(str)

    def __init__(self, rows):
        super().__init__()
        self.rows = [(row.record_id, row.email) for row in rows]
        self._stop = threading.Event()

    def run(self):
        try:
            total = len(self.rows)
            for index, (record_id, email) in enumerate(self.rows):
                if self._stop.is_set():
                    break
                self.progress.emit(
                    int(index / max(total, 1) * 100), f"Checking {email or '(no email)'}..."
                )
                status, reason = verify_email(email) if email else ("unknown", "No email")
                if self._stop.is_set():
                    break
                self.result.emit(record_id, status, reason)
                if self._stop.wait(0.1):
                    break
        finally:
            self.completed.emit("cancelled" if self._stop.is_set() else "completed")

    def stop(self):
        self._stop.set()
