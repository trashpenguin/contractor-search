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

from cache import SEARCH_HISTORY
from compat import HAS_AIOHTTP, HAS_DNS, HAS_SCRAPLING
from constants import TRADE_COLORS
from gui.export_mixin import ExportMixin
from gui.search_mixin import SearchMixin
from gui.style import COLS
from gui.table_mixin import TableMixin
from gui.widgets import StatCard
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
        self.rmap = {
            "10 mi": "10000",
            "25 mi": "25000",
            "40 mi": "40000",
            "60 mi": "60000",
            "80 mi": "80000",
        }
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
        src_colors = {
            "OSM": "#8b5cf6",
            "YellowPages": "#f97316",
            "Yelp": "#ef4444",
            "Google": "#34d399",
        }
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

        # Source status strip + elapsed timer
        sr = QHBoxLayout()
        sr.setSpacing(6)
        self._src_labels: dict[str, QLabel] = {}
        for src in ["OSM", "YellowPages", "Yelp", "Google"]:
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
        self.chk_hide = QCheckBox("Hide incomplete")
        self.chk_hide.setToolTip("Hide contractors with no phone, email, or website")
        self.chk_hide.setFixedHeight(30)
        self.chk_hide.stateChanged.connect(self._filter)
        sf.addWidget(self.chk_hide)
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
        for txt, fn in [
            ("Export CSV", self.export_csv),
            ("Export TXT", self.export_txt),
            ("Clear", self.clear),
        ]:
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

    def clear(self):
        self.rows.clear()
        self.table.setRowCount(0)
        for c in self.stats.values():
            c.set(0)
        self.pbar.setValue(0)
        self.statusBar().showMessage("Cleared")
