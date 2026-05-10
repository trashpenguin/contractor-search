from __future__ import annotations
import csv, os, tempfile, webbrowser
from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtGui  import QColor, QFont, QBrush
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QProgressBar, QFileDialog,
    QStatusBar, QMessageBox, QAbstractItemView,
    QGroupBox, QDialog, QTextEdit, QDialogButtonBox,
)

from compat import HAS_SCRAPLING, HAS_AIOHTTP, HAS_DNS
from constants import TRADE_COLORS, SOURCE_COLORS
from cache import SEARCH_HISTORY
from proxy import PROXY_MGR
from extractor import email_role_warning
from models import Contractor
from workers import SearchWorker, VerifyWorker
from gui.style import COLS, VERIFY_COLORS, VERIFY_ICONS
from gui.widgets import StatCard


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contractor Finder v3  ·  Scrapling Powered")
        self.resize(1300, 820)
        self.rows: list[Contractor] = []
        self.worker  = None
        self.vworker = None
        self._build()

    def _lbl(self, txt: str) -> QLabel:
        l = QLabel(txt)
        l.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:600;")
        return l

    def _build(self):
        cw   = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
        root.setContentsMargins(18, 12, 18, 8)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        t   = QLabel("Contractor Finder")
        t.setStyleSheet("font-size:18px;font-weight:700;")
        hdr.addWidget(t)
        sub = QLabel("  v3  ·  Phone · Email · Website  ·  USA Locations")
        sub.setStyleSheet("color:#94a3b8;font-size:11px;")
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)

        # Search parameters group
        sg = QGroupBox("Search Parameters")
        sl = QVBoxLayout(sg)
        sl.setSpacing(8)

        r1 = QHBoxLayout()
        r1.setSpacing(10)
        lc = QVBoxLayout()
        lc.addWidget(self._lbl("Location (US City, State or ZIP)"))
        self.loc = QComboBox()
        self.loc.setEditable(True)
        self.loc.setFixedHeight(34)
        self.loc.setInsertPolicy(QComboBox.InsertAtTop)
        _hist   = SEARCH_HISTORY.load()
        default = "Warren, MI 48091"
        for loc in [default] + [h for h in _hist if h != default]:
            self.loc.addItem(loc)
        self.loc.setCurrentText(default)
        self.loc.lineEdit().returnPressed.connect(self.start_search)
        lc.addWidget(self.loc)
        r1.addLayout(lc, 3)

        rc = QVBoxLayout()
        rc.addWidget(self._lbl("Radius"))
        self.radius = QComboBox()
        self.radius.setFixedHeight(34)
        self.rmap = {"10 mi": "10000", "25 mi": "25000", "40 mi": "40000",
                     "60 mi": "60000", "80 mi": "80000"}
        for k in self.rmap:
            self.radius.addItem(k)
        self.radius.setCurrentIndex(2)
        rc.addWidget(self.radius)
        r1.addLayout(rc, 1)

        pc = QVBoxLayout()
        pc.addWidget(self._lbl("Per Trade/Source"))
        self.per = QComboBox()
        self.per.setFixedHeight(34)
        for n in ["10", "20", "30", "50", "75", "100"]:
            self.per.addItem(n)
        self.per.setCurrentIndex(2)
        pc.addWidget(self.per)
        r1.addLayout(pc, 1)
        sl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(self._lbl("Trades:"))
        self.chk_t: dict[str, QCheckBox] = {}
        for t, col in TRADE_COLORS.items():
            cb = QCheckBox(t)
            cb.setChecked(True)
            cb.setStyleSheet(f"color:{col};font-weight:700;font-size:13px;")
            self.chk_t[t] = cb
            r2.addWidget(cb)
        r2.addSpacing(16)
        r2.addWidget(self._lbl("Sources:"))
        self.chk_s: dict[str, QCheckBox] = {}
        src_colors = {"OSM": "#8b5cf6", "YellowPages": "#f97316",
                      "Yelp": "#ef4444", "Google": "#34d399"}
        for s, col in src_colors.items():
            cb = QCheckBox(s)
            cb.setChecked(True)
            cb.setStyleSheet(f"color:{col};font-size:12px;font-weight:600;")
            self.chk_s[s] = cb
            r2.addWidget(cb)
        r2.addSpacing(16)
        self.chk_enrich = QCheckBox("Scrape websites for phone+email (recommended)")
        self.chk_enrich.setChecked(True)
        r2.addWidget(self.chk_enrich)
        self.chk_proxy = QCheckBox("Use Proxy (proxifly)")
        self.chk_proxy.setChecked(False)
        self.chk_proxy.setStyleSheet("color:#94a3b8;font-size:12px;")
        self.chk_proxy.setToolTip(
            "Rotate free proxies from proxifly/free-proxy-list.\n"
            "Adds ~45s startup to build the pool.\n"
            "Helps if your IP gets rate-limited by Yelp or DDG."
        )
        r2.addWidget(self.chk_proxy)
        r2.addStretch()
        sl.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(8)
        self.sbtn = QPushButton("Search Contractors ↗")
        self.sbtn.setObjectName("searchBtn")
        self.sbtn.setFixedHeight(38)
        self.sbtn.clicked.connect(self.start_search)
        self.xbtn = QPushButton("Stop")
        self.xbtn.setObjectName("stopBtn")
        self.xbtn.setFixedHeight(38)
        self.xbtn.setFixedWidth(70)
        self.xbtn.setEnabled(False)
        self.xbtn.clicked.connect(self.stop_search)
        self.vbtn = QPushButton("✉ Verify Emails")
        self.vbtn.setObjectName("verifyBtn")
        self.vbtn.setFixedHeight(38)
        self.vbtn.clicked.connect(self.start_verify)
        self.gbtn = QPushButton("📊 Export → Google Sheets")
        self.gbtn.setObjectName("sheetsBtn")
        self.gbtn.setFixedHeight(38)
        self.gbtn.clicked.connect(self.export_sheets)
        for w in [self.sbtn, self.xbtn, self.vbtn, self.gbtn]:
            r3.addWidget(w)
        r3.addStretch()
        sl.addLayout(r3)

        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(7)
        self.pbar.setTextVisible(False)
        sl.addWidget(self.pbar)
        root.addWidget(sg)

        # Stats + filter row
        sf = QHBoxLayout()
        sf.setSpacing(8)
        self.stats: dict[str, StatCard] = {}
        for t, col in {**TRADE_COLORS, "Total": "#6366f1"}.items():
            card = StatCard(t, col)
            self.stats[t] = card
            sf.addWidget(card)
        sf.addStretch()
        sf.addWidget(self._lbl("Filter:"))
        self.tf = QComboBox()
        self.tf.addItems(["All", "HVAC", "Electrical", "Excavating"])
        self.tf.setFixedWidth(120)
        self.tf.setFixedHeight(30)
        self.tf.currentTextChanged.connect(self._filter)
        sf.addWidget(self.tf)
        self.sf2 = QComboBox()
        self.sf2.addItems(["All Sources", "OSM", "YellowPages", "Yelp", "Google"])
        self.sf2.setFixedWidth(130)
        self.sf2.setFixedHeight(30)
        self.sf2.currentTextChanged.connect(self._filter)
        sf.addWidget(self.sf2)
        self.nf = QLineEdit()
        self.nf.setPlaceholderText("Search by name...")
        self.nf.setFixedWidth(160)
        self.nf.setFixedHeight(30)
        self.nf.textChanged.connect(self._filter)
        sf.addWidget(self.nf)
        root.addLayout(sf)

        # Results table
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        for i, w in enumerate([80, 100, 200, 135, 185, 90, 175, 180, 140]):
            self.table.setColumnWidth(i, w)
        root.addWidget(self.table)

        # Export buttons
        er = QHBoxLayout()
        er.setSpacing(8)
        for txt, fn in [("Export CSV", self.export_csv),
                        ("Export TXT", self.export_txt),
                        ("Clear",      self.clear)]:
            b = QPushButton(txt)
            b.clicked.connect(fn)
            b.setFixedHeight(32)
            er.addWidget(b)
        er.addStretch()
        root.addLayout(er)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            f"Ready  ·  Scrapling: {'✓' if HAS_SCRAPLING else '✗'}  "
            f"Async: {'✓' if HAS_AIOHTTP else '✗'}  "
            f"DNS verify: {'✓' if HAS_DNS else '✗'}"
        )

    # ── Search controls ───────────────────────────────────────────────────────

    def start_search(self):
        loc = self.loc.currentText().strip()
        if not loc:
            QMessageBox.warning(self, "Error", "Enter a US location.")
            return
        trades  = [t for t, cb in self.chk_t.items() if cb.isChecked()]
        sources = [s for s, cb in self.chk_s.items() if cb.isChecked()]
        if not trades:
            QMessageBox.warning(self, "Error", "Select at least one trade.")
            return
        if not sources:
            QMessageBox.warning(self, "Error", "Select at least one source.")
            return
        self.rows.clear()
        self.table.setRowCount(0)
        for c in self.stats.values():
            c.set(0)
        self.sbtn.setEnabled(False)
        self.xbtn.setEnabled(True)
        self.pbar.setValue(0)

        SEARCH_HISTORY.save(loc)
        _hist   = SEARCH_HISTORY.load()
        current = self.loc.currentText()
        self.loc.clear()
        for h in _hist:
            self.loc.addItem(h)
        self.loc.setCurrentText(current)

        if self.chk_proxy.isChecked():
            PROXY_MGR.enable()
        else:
            PROXY_MGR.disable()

        self.worker = SearchWorker(
            loc, trades, int(self.per.currentText()),
            int(self.rmap[self.radius.currentText()]),
            self.chk_enrich.isChecked(), sources,
        )
        self.worker.progress.connect(lambda p, m: (
            self.pbar.setValue(p), self.statusBar().showMessage(m)))
        self.worker.result.connect(self._add_row)
        self.worker.finished.connect(self._on_done)
        self.worker.start()

    def stop_search(self):
        if self.worker:
            self.worker.stop()
        self.xbtn.setEnabled(False)

    def _on_done(self, ok: bool, err: str):
        self.pbar.setValue(100)
        self.sbtn.setEnabled(True)
        self.xbtn.setEnabled(False)
        if ok:
            counts = {t: sum(1 for r in self.rows if r.trade == t) for t in TRADE_COLORS}
            self.statusBar().showMessage(
                f"Done — {len(self.rows)} contractors  |  " +
                "  ".join(f"{t}:{counts[t]}" for t in TRADE_COLORS)
            )
        else:
            QMessageBox.critical(self, "Error", err)

    # ── Table ─────────────────────────────────────────────────────────────────

    def _add_row(self, c: Contractor):
        self.rows.append(c)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._fill_row(row, c)
        self._update_stats()

    def _fill_row(self, row: int, c: Contractor):
        bg   = QColor("#161925") if row % 2 == 1 else QColor("#1a1d27")
        vc   = VERIFY_COLORS.get(c.email_status, "#94a3b8")
        vi   = f"{VERIFY_ICONS.get(c.email_status, '')} {c.email_status}".strip()
        note = email_role_warning(c.email) if c.email else ""
        vals = [
            (c.trade,   TRADE_COLORS.get(c.trade,   "#e2e8f0"), True),
            (c.source,  SOURCE_COLORS.get(c.source, "#94a3b8"), True),
            (c.name,    "#e2e8f0", False),
            (c.phone,   "#10b981" if c.phone else "#94a3b8", False),
            (c.email,   "#93c5fd" if c.email else "#94a3b8", False),
            (vi,        vc, True),
            (c.website, "#93c5fd", False),
            (c.address, "#e2e8f0", False),
            (note,      "#f59e0b" if note else "#94a3b8", False),
        ]
        for col, (val, color, bold) in enumerate(vals):
            item = QTableWidgetItem(val)
            item.setForeground(QBrush(QColor(color)))
            item.setBackground(QBrush(bg))
            if bold:
                item.setFont(QFont("Segoe UI", 11, QFont.Bold))
            self.table.setItem(row, col, item)
        self.table.setRowHeight(row, 30)

    def _update_stats(self):
        for t in TRADE_COLORS:
            self.stats[t].set(sum(1 for r in self.rows if r.trade == t))
        self.stats["Total"].set(len(self.rows))

    def _filter(self):
        trade = self.tf.currentText()
        src   = self.sf2.currentText()
        name  = self.nf.text().strip().lower()
        self.table.setRowCount(0)
        for i, c in enumerate(self.rows):
            if trade != "All" and c.trade != trade:
                continue
            if src != "All Sources" and c.source != src:
                continue
            if name and name not in c.name.lower():
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._fill_row(row, c)

    # ── Email verify ──────────────────────────────────────────────────────────

    def start_verify(self):
        if not self.rows:
            QMessageBox.information(self, "", "Run a search first.")
            return
        self.vbtn.setEnabled(False)
        self.pbar.setValue(0)
        self.vworker = VerifyWorker(self.rows)
        self.vworker.progress.connect(lambda p, m: (
            self.pbar.setValue(p), self.statusBar().showMessage(m)))
        self.vworker.result.connect(self._on_verify)
        self.vworker.finished.connect(self._on_verify_done)
        self.vworker.start()

    def _on_verify(self, idx: int, status: str, reason: str):
        if idx < self.table.rowCount():
            vi   = f"{VERIFY_ICONS.get(status, '')} {status}".strip()
            item = QTableWidgetItem(vi)
            item.setForeground(QBrush(QColor(VERIFY_COLORS.get(status, "#94a3b8"))))
            self.table.setItem(idx, 5, item)

    def _on_verify_done(self):
        self.pbar.setValue(100)
        self.vbtn.setEnabled(True)
        v   = sum(1 for r in self.rows if r.email_status == "valid")
        inv = sum(1 for r in self.rows if r.email_status == "invalid")
        unk = sum(1 for r in self.rows if r.email_status == "unknown")
        self.statusBar().showMessage(
            f"Email verify done  —  ✅ Valid:{v}  ❌ Invalid:{inv}  ❓ Unknown:{unk}"
        )

    # ── Export ────────────────────────────────────────────────────────────────

    def export_sheets(self):
        if not self.rows:
            return
        tmp    = tempfile.NamedTemporaryFile(
            delete=False, suffix=".csv", mode="w", newline="", encoding="utf-8")
        fields = ["trade", "source", "name", "phone", "email", "website", "address"]
        w      = csv.DictWriter(tmp, fieldnames=fields)
        w.writeheader()
        for c in self.rows:
            d = asdict(c)
            w.writerow({k: d.get(k, "") for k in fields})
        tmp.close()
        dlg = QDialog(self)
        dlg.setWindowTitle("Export to Google Sheets")
        dlg.resize(460, 260)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("<b>CSV saved! Import steps:</b>"))
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(
            f"File: {tmp.name}\n\n"
            "1. Google Sheets will open in your browser\n"
            "2. Click  File → Import → Upload tab\n"
            f"3. Select file: {os.path.basename(tmp.name)}\n"
            "4. Choose 'Replace spreadsheet' → Import data"
        )
        lay.addWidget(te)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() == QDialog.Accepted:
            webbrowser.open("https://sheets.new")

    def export_csv(self):
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV", "contractors.csv", "CSV (*.csv)")
        if not path:
            return
        fields = ["trade", "source", "name", "phone", "email", "website", "address"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for c in self.rows:
                d = asdict(c)
                w.writerow({k: d.get(k, "") for k in fields})
        self.statusBar().showMessage(f"Saved {len(self.rows)} rows → {path}")

    def export_txt(self):
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save TXT", "contractors.txt", "Text (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for trade in ["HVAC", "Electrical", "Excavating"]:
                g = [c for c in self.rows if c.trade == trade]
                if not g:
                    continue
                f.write(f"\n{'='*50}\n{trade.upper()} ({len(g)})\n{'='*50}\n")
                for i, c in enumerate(g, 1):
                    f.write(
                        f"\n{i}. {c.name}  [{c.source}]\n"
                        f"   Phone:   {c.phone or 'N/A'}\n"
                        f"   Email:   {c.email or 'N/A'}\n"
                        f"   Website: {c.website or 'N/A'}\n"
                        f"   Address: {c.address or 'N/A'}\n"
                    )
        self.statusBar().showMessage(f"Saved → {path}")

    def clear(self):
        self.rows.clear()
        self.table.setRowCount(0)
        for c in self.stats.values():
            c.set(0)
        self.pbar.setValue(0)
        self.statusBar().showMessage("Cleared")
