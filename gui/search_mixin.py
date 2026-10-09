from __future__ import annotations

import re
import time

from PySide6.QtWidgets import QMessageBox

from cache import SEARCH_HISTORY
from location import valid_location
from proxy import PROXY_MGR
from workers import SearchWorker, VerifyWorker

_SRC_IDLE_STYLE = (
    "color:#475569;font-size:10px;font-family:monospace;"
    "padding:2px 8px;background:#161925;border-radius:4px;"
)
_SRC_RUN_STYLE = (
    "color:#f59e0b;font-size:10px;font-family:monospace;"
    "padding:2px 8px;background:#161925;border-radius:4px;"
)
_SRC_OK_STYLE = (
    "color:#10b981;font-size:10px;font-family:monospace;"
    "padding:2px 8px;background:#161925;border-radius:4px;"
)
_SRC_ERR_STYLE = (
    "color:#ef4444;font-size:10px;font-family:monospace;"
    "padding:2px 8px;background:#161925;border-radius:4px;"
)
_WARN_ELAPSED = "color:#f59e0b;font-size:10px;font-family:monospace;"


class SearchMixin:
    def start_search(self):
        if self.worker and self.worker.isRunning():
            return
        loc = self.loc.currentText().strip()

        if not valid_location(loc):
            QMessageBox.warning(self, "Invalid Location", "Enter a US city/state or ZIP code.")
            return
        if self._busy():
            return

        trades = [t for t, cb in self.chk_t.items() if cb.isChecked()]
        sources = [s for s, cb in self.chk_s.items() if cb.isChecked()]
        if not trades:
            QMessageBox.warning(self, "Error", "Select at least one trade.")
            return
        if not sources:
            QMessageBox.warning(self, "Error", "Select at least one source.")
            return

        self._set_busy(True)
        self.rows.clear()
        self.table.setRowCount(0)
        for c in self.stats.values():
            c.set(0)
        self.tf.setCurrentIndex(0)
        self.sf2.setCurrentIndex(0)
        self.nf.clear()
        self.sbtn.setEnabled(False)
        self.xbtn.setEnabled(True)
        self.pbar.setValue(0)
        self._reset_source_status(sources)

        SEARCH_HISTORY.save(loc)
        _hist = SEARCH_HISTORY.load()
        current = self.loc.currentText()
        self.loc.clear()
        for h in _hist:
            self.loc.addItem(h)
        self.loc.setCurrentText(current)

        if self.chk_proxy.isChecked():
            PROXY_MGR.enable()
        else:
            PROXY_MGR.disable()

        self._search_start = time.time()
        self._warned_5min = False
        self._timer.start()

        self.worker = SearchWorker(
            loc,
            trades,
            int(self.per.currentText()),
            int(self.rmap[self.radius.currentText()]),
            self.chk_enrich.isChecked(),
            sources,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.result.connect(self._add_row)
        self.worker.completed.connect(self._on_done)
        self.worker.finished.connect(self._worker_exited)
        self.worker.source_done.connect(self._on_source_done)
        self.worker.start()

    def stop_search(self):
        if self.worker:
            self.worker.stop()
        if self.vworker:
            self.vworker.stop()
        self.xbtn.setEnabled(False)

    def _on_progress(self, p: int, msg: str):
        self.pbar.setValue(p)
        self.statusBar().showMessage(msg)
        for src in self._src_labels:
            if f"[{src}]" in msg and "Searching" in msg:
                lbl = self._src_labels[src]
                prior = self._src_counts.get(src, 0)
                suffix = f" {prior}" if prior else ""
                lbl.setText(f"{src}: ⏳{suffix}")
                lbl.setStyleSheet(_SRC_RUN_STYLE)
                break

    def _on_done(self, status: str, detail: str):
        self._timer.stop()
        self._elapsed_lbl.setText("")
        self.pbar.setValue(100 if status == "completed" else self.pbar.value())
        self.xbtn.setEnabled(False)
        labels = {
            "completed": "Completed",
            "partial": "Partial results",
            "cancelled": "Cancelled",
            "failed": "Failed",
        }
        self.statusBar().showMessage(
            f"{labels.get(status, status)} — {len(self.rows)} contractors"
            + (f" | {detail}" if detail else "")
        )
        if status == "failed":
            QMessageBox.warning(self, "Search Failed", detail)

    def _tick_elapsed(self):
        elapsed = int(time.time() - self._search_start)
        mins, secs = divmod(elapsed, 60)
        self._elapsed_lbl.setText(f"⏱ {mins}:{secs:02d}")
        if elapsed >= 300 and not self._warned_5min:
            self._warned_5min = True
            self._elapsed_lbl.setStyleSheet(_WARN_ELAPSED)
            self.statusBar().showMessage(
                "⚠ Search running 5+ min — normal for 3 trades with enrichment. Still working..."
            )

    def _reset_source_status(self, active_sources: list[str]):
        self._src_counts = {}
        for src, lbl in self._src_labels.items():
            lbl.setText(f"{src}: {'—' if src in active_sources else 'skip'}")
            lbl.setStyleSheet(_SRC_IDLE_STYLE)

    def _on_source_done(self, src: str, trade: str, count: int):
        lbl = self._src_labels.get(src)
        if not lbl:
            return
        if count >= 0:
            self._src_counts[src] = self._src_counts.get(src, 0) + count
            total = self._src_counts[src]
            lbl.setText(f"{src}: ✓ {total}")
            lbl.setStyleSheet(_SRC_OK_STYLE)
        else:
            if self._src_counts.get(src, 0) == 0:
                lbl.setText(f"{src}: ✗")
                lbl.setStyleSheet(_SRC_ERR_STYLE)

    def start_verify(self):
        if self._busy():
            return
        if not self.rows:
            QMessageBox.information(self, "", "Run a search first.")
            return
        self._set_busy(True)
        self.xbtn.setEnabled(True)
        self.vbtn.setEnabled(False)
        self.pbar.setValue(0)
        self.vworker = VerifyWorker(self.rows)
        self.vworker.progress.connect(
            lambda p, m: (self.pbar.setValue(p), self.statusBar().showMessage(m))
        )
        self.vworker.result.connect(self._on_verify)
        self.vworker.completed.connect(self._on_verify_done)
        self.vworker.finished.connect(self._worker_exited)
        self.vworker.start()

    def _on_verify(self, record_id: str, status: str, reason: str):
        contractor = next((row for row in self.rows if row.record_id == record_id), None)
        if contractor is None:
            return
        contractor.email_status = status
        self._filter()

    def _on_verify_done(self):
        self.pbar.setValue(100)
        self.xbtn.setEnabled(False)
        v = sum(1 for r in self.rows if r.email_status == "valid")
        inv = sum(1 for r in self.rows if r.email_status == "invalid")
        unk = sum(1 for r in self.rows if r.email_status == "unknown")
        self.statusBar().showMessage(
            f"Email verify done  —  ✅ Valid:{v}  ❌ Invalid:{inv}  ❓ Unknown:{unk}"
        )

    def _busy(self):
        return any(
            worker is not None and worker.isRunning() for worker in (self.worker, self.vworker)
        )

    def _set_busy(self, busy):
        for control in [self.sbtn, self.vbtn, self.clear_btn, self.clear_cache_btn]:
            control.setEnabled(not busy)

    def _worker_exited(self):
        if not self._busy():
            self._set_busy(False)
            if getattr(self, "_close_pending", False):
                self.close()
