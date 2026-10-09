from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

import config as _settings
from cache import CACHE, SEARCH_HISTORY
from compat import HAS_AIOHTTP, HAS_DNS, HAS_SCRAPLING
from constants import TRADE_COLORS
from gui.export_mixin import ExportMixin
from gui.search_mixin import SearchMixin
from gui.style import COLS
from gui.table_mixin import TableMixin
from gui.widgets import StatCard, TradeSelector
from location import miles_to_meters
from models import Contractor

_SRC_IDLE_STYLE = (
    "color:#475569;font-size:10px;font-family:monospace;"
    "padding:2px 8px;background:#161925;border-radius:4px;"
)
_ELAPSED_STYLE = "color:#475569;font-size:10px;font-family:monospace;"


class MainWindow(SearchMixin, TableMixin, ExportMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contractor Finder v3  ·  Scrapling Powered")
        self.resize(1300, 820)
        self.rows: list[Contractor] = []
        self.worker = None
        self.vworker = None
        self._src_counts: dict[str, int] = {}
        self._search_start: float = 0
        self._warned_5min = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_elapsed)
        self._build()

    def _lbl(self, txt: str) -> QLabel:
        lbl = QLabel(txt)
        lbl.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:600;")
        return lbl

    def _build(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
        root.setContentsMargins(18, 12, 18, 8)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        t = QLabel("Contractor Finder")
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
        _hist = SEARCH_HISTORY.load()
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
        self.rmap = {f"{miles} mi": miles_to_meters(miles) for miles in (10, 25, 40, 60, 80)}
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

        # Trades dropdown selector
        rt = QHBoxLayout()
        rt.setSpacing(6)
        rt.addWidget(self._lbl("Trades:"))
        self.trade_selector = TradeSelector(TRADE_COLORS)
        self.chk_t = self.trade_selector._checkboxes
        rt.addWidget(self.trade_selector)
        rt.addStretch()
        sl.addLayout(rt)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(self._lbl("Sources:"))
        self.chk_s: dict[str, QCheckBox] = {}
        src_colors = {
            "OSM": "#8b5cf6",
            "YellowPages": "#f97316",
            "Yelp": "#ef4444",
            "Google": "#34d399",
            "Google Search": "#60a5fa",
            "Google Places": "#4ade80",
        }
        for s, col in src_colors.items():
            cb = QCheckBox(s)
            cb.setChecked(s != "Google Places")  # off by default until API key entered
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

        # Google Places API key row
        r2b = QHBoxLayout()
        r2b.setSpacing(6)
        gp_lbl = self._lbl("Google Places API Key:")
        gp_lbl.setToolTip(
            "Configure a key at console.cloud.google.com\n"
            "Enable 'Places API (New)' in your project.\n"
            "Review billing and quotas in your Google Cloud project."
        )
        r2b.addWidget(gp_lbl)
        self.gp_key = QLineEdit()
        self.gp_key.setPlaceholderText("AIza... (optional — enables Google Places source)")
        self.gp_key.setFixedHeight(28)
        self.gp_key.setEchoMode(QLineEdit.Password)
        self.gp_key.setFixedWidth(340)
        saved_key = _settings.get("google_places_api_key", "")
        if saved_key:
            self.gp_key.setText(saved_key)
            self.chk_s["Google Places"].setChecked(True)
        self.gp_key.textChanged.connect(self._on_gp_key_changed)
        r2b.addWidget(self.gp_key)
        self.gp_show_btn = QPushButton("Show")
        self.gp_show_btn.setFixedHeight(28)
        self.gp_show_btn.setFixedWidth(46)
        self.gp_show_btn.setCheckable(True)
        self.gp_show_btn.toggled.connect(
            lambda on: (
                self.gp_key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                self.gp_show_btn.setText("Hide" if on else "Show"),
            )
        )
        r2b.addWidget(self.gp_show_btn)
        r2b.addStretch()
        sl.addLayout(r2b)

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

        # Source status strip + elapsed timer
        sr = QHBoxLayout()
        sr.setSpacing(6)
        self._src_labels: dict[str, QLabel] = {}
        for src in ["OSM", "YellowPages", "Yelp", "Google", "Google Search", "Google Places"]:
            lbl = QLabel(f"{src}: —")
            lbl.setStyleSheet(_SRC_IDLE_STYLE)
            self._src_labels[src] = lbl
            sr.addWidget(lbl)
        sr.addStretch()
        self._elapsed_lbl = QLabel("")
        self._elapsed_lbl.setStyleSheet(_ELAPSED_STYLE)
        sr.addWidget(self._elapsed_lbl)
        sl.addLayout(sr)

        root.addWidget(sg)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(4)
        self.stats: dict[str, StatCard] = {}
        for t, col in {**TRADE_COLORS, "Total": "#6366f1"}.items():
            card = StatCard(t, col)
            self.stats[t] = card
            stats_row.addWidget(card)
        stats_row.addStretch()
        root.addLayout(stats_row)

        # Filter row
        filter_wrap = QWidget()
        filter_wrap.setStyleSheet("background:#0f1117;border:1px solid #1e293b;border-radius:6px;")
        filter_row = QHBoxLayout(filter_wrap)
        filter_row.setContentsMargins(10, 4, 10, 4)
        filter_row.setSpacing(8)
        filter_row.addWidget(self._lbl("Trade:"))
        self.tf = QComboBox()
        self.tf.addItems(["All"] + list(TRADE_COLORS.keys()))
        self.tf.setFixedWidth(175)
        self.tf.setFixedHeight(28)
        self.tf.currentTextChanged.connect(self._filter)
        filter_row.addWidget(self.tf)
        filter_row.addWidget(self._lbl("Source:"))
        self.sf2 = QComboBox()
        self.sf2.addItems(
            [
                "All Sources",
                "OSM",
                "YellowPages",
                "Yelp",
                "Google",
                "Google Search",
                "Google Places",
            ]
        )
        self.sf2.setFixedWidth(130)
        self.sf2.setFixedHeight(28)
        self.sf2.currentTextChanged.connect(self._filter)
        filter_row.addWidget(self.sf2)
        self.nf = QLineEdit()
        self.nf.setPlaceholderText("Search by name...")
        self.nf.setFixedWidth(180)
        self.nf.setFixedHeight(28)
        self.nf.textChanged.connect(self._filter)
        filter_row.addWidget(self.nf)
        self.chk_hide = QCheckBox("Hide incomplete")
        self.chk_hide.setToolTip("Hide contractors with no phone, email, or website")
        self.chk_hide.setFixedHeight(28)
        self.chk_hide.stateChanged.connect(self._filter)
        filter_row.addWidget(self.chk_hide)
        filter_row.addStretch()
        root.addWidget(filter_wrap)

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
        self._setup_link_columns()
        root.addWidget(self.table)

        # Export buttons
        er = QHBoxLayout()
        er.setSpacing(8)
        for txt, fn in [
            ("Export CSV", self.export_csv),
            ("Export Board CSV", self.export_board_csv),
            ("Export TXT", self.export_txt),
            ("Clear", self.clear),
        ]:
            b = QPushButton(txt)
            b.clicked.connect(fn)
            b.setFixedHeight(32)
            if txt == "Clear":
                self.clear_btn = b
            er.addWidget(b)
        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.setFixedHeight(32)
        self.clear_cache_btn.setToolTip(
            "Delete all cached Yelp/DDG/contact results so the next search fetches fresh data."
        )
        self.clear_cache_btn.clicked.connect(self._clear_cache)
        er.addWidget(self.clear_cache_btn)
        er.addStretch()
        root.addLayout(er)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            f"Ready  ·  Scrapling: {'✓' if HAS_SCRAPLING else '✗'}  "
            f"Async: {'✓' if HAS_AIOHTTP else '✗'}  "
            f"DNS verify: {'✓' if HAS_DNS else '✗'}"
        )

    def clear(self):
        if self._busy():
            return
        self.rows.clear()
        self.table.setRowCount(0)
        for c in self.stats.values():
            c.set(0)
        self.pbar.setValue(0)
        self.statusBar().showMessage("Cleared")

    def _on_gp_key_changed(self, text: str):
        key = text.strip()
        _settings.set("google_places_api_key", key)
        # Auto-enable the Google Places checkbox when a key is entered
        if "Google Places" in self.chk_s:
            self.chk_s["Google Places"].setChecked(bool(key))

    def _clear_cache(self):
        if self._busy():
            return
        CACHE.clear_all()
        self.statusBar().showMessage("Cache cleared — next search will fetch fresh data")

    def closeEvent(self, event):
        if self._busy():
            self._close_pending = True
            self.stop_search()
            self.statusBar().showMessage("Stopping workers before closing...")
            event.ignore()
            return
        event.accept()
