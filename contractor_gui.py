#!/usr/bin/env python3
"""
Contractor Finder GUI — Powered by Scrapling
Fast HVAC · Electrical · Excavating contractor search with GUI

INSTALL:
    pip install scrapling browserforge curl_cffi PySide6

RUN:
    python3 contractor_gui.py
"""
from __future__ import annotations
import csv, json, re, sys, threading
from dataclasses import dataclass, field, asdict
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

from scrapling import Fetcher
from scrapling.parser import Adaptor

from PySide6.QtCore import Qt, QThread, Signal, QSortFilterProxyModel
from PySide6.QtGui import (
    QColor, QFont, QPalette, QStandardItem, QStandardItemModel,
    QBrush, QIcon, QPixmap, QPainter
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QTableView, QProgressBar, QFileDialog, QStatusBar,
    QHeaderView, QSplitter, QFrame, QMessageBox, QGroupBox,
    QAbstractItemView, QSizePolicy
)

# ── Constants ─────────────────────────────────────────────────────────────────

USER_AGENT  = "ContractorFinderBot/3.0 (local-lead-tool)"
EMAIL_RE    = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE    = re.compile(r"(\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]\d{4})")
BAD_EMAILS  = {"example.", "wixpress", "sentry", "schema", "domain", "youremail", "email@"}

NOMINATIM   = "https://nominatim.openstreetmap.org/search"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

CATEGORY_KEYWORDS = {
    "HVAC":        ["heating", "air conditioning", "hvac", "furnace", "cooling"],
    "Electrical":  ["electrician", "electrical", "electric"],
    "Excavating":  ["excavating", "earthwork", "grading", "dirt work", "excavation", "sitework"],
}


def classify_trade_ai(name: str, tags: dict) -> str | None:
    text = (name + " " + " ".join(tags.values())).lower()

    scores = {
        "HVAC": 0,
        "Electrical": 0,
        "Excavating": 0,
    }

    for k in ["hvac", "heating", "cooling", "air conditioning", "furnace", "ventilation"]:
        if k in text:
            scores["HVAC"] += 2

    for k in ["electric", "electrician", "power", "voltage", "wiring"]:
        if k in text:
            scores["Electrical"] += 2

    for k in ["excavating", "grading", "earthwork", "sitework", "dirt", "trenching"]:
        if k in text:
            scores["Excavating"] += 2

    craft = tags.get("craft", "").lower()
    if "electric" in craft:
        scores["Electrical"] += 3
    if "hvac" in craft:
        scores["HVAC"] += 3
    if "excavation" in craft:
        scores["Excavating"] += 3

    best_trade = max(scores, key=scores.get)
    if scores[best_trade] < 2:
        return None

    return best_trade

TRADE_COLORS = {
    "HVAC":       "#10b981",
    "Electrical": "#3b82f6",
    "Excavating": "#f59e0b",
}

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Contractor:
    trade:    str = ""
    name:     str = ""
    phone:    str = ""
    email:    str = ""
    website:  str = ""
    address:  str = ""
    place_id: str = ""

# ── Scrapling-powered scraper ─────────────────────────────────────────────────

fetcher = Fetcher(auto_match=False)

def clean_email(e: str) -> str:
    return e.strip().strip(".,;:()[]{}<>").lower()

def is_valid_email(e: str) -> bool:
    return "@" in e and "." in e.split("@")[-1] and not any(b in e for b in BAD_EMAILS)

def scrape_email_from_page(page: Adaptor) -> str:
    """Use Scrapling CSS selectors + regex to find email."""
    # Priority 1: mailto links
    for el in page.css("a[href*='mailto:']"):
        href = el.attrib.get("href", "")
        if "mailto:" in href:
            email = clean_email(href.split("mailto:")[-1].split("?")[0])
            if is_valid_email(email):
                return email
    # Priority 2: regex over full text
    text = page.get_all_text(separator=" ")
    for raw in EMAIL_RE.findall(text):
        email = clean_email(raw)
        if is_valid_email(email):
            return email
    return ""

def scrape_phone_from_page(page: Adaptor) -> str:
    """Use Scrapling to extract phone number."""
    # Try tel: links first
    for el in page.css("a[href*='tel:']"):
        href = el.attrib.get("href", "")
        if "tel:" in href:
            digits = re.sub(r"\D", "", href.split("tel:")[-1])
            if len(digits) >= 10:
                d = digits[-10:]
                return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    # Regex over text
    text = page.get_all_text(separator=" ")
    phones = PHONE_RE.findall(text)
    return phones[0] if phones else ""

def get_contact_links(base_url: str, page: Adaptor) -> list[str]:
    """Find likely contact/about pages using Scrapling."""
    hints = ("contact", "about", "team", "reach", "support", "get-in-touch")
    base_domain = urlparse(base_url).netloc
    links: list[tuple[int, str]] = []
    for el in page.css("a[href]"):
        href = el.attrib.get("href", "").strip()
        if not href or href.lower().startswith("mailto:"):
            continue
        absolute = urljoin(base_url, href)
        p = urlparse(absolute)
        if p.scheme not in {"http", "https"} or p.netloc != base_domain:
            continue
        path = p.path.lower()
        score = 10 if any(h in path for h in hints) else 0
        links.append((score, absolute))
    links.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    out: list[str] = []
    for _, url in links:
        if url not in seen:
            seen.add(url)
            out.append(url)
            if len(out) >= 4:
                break
    return out

def fetch_html(url: str) -> str | None:
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=12) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

def extract_contact_info(website: str) -> tuple[str, str]:
    """Return (email, phone) by scraping website with Scrapling."""
    if not website:
        return "", ""
    html = fetch_html(website)
    if not html:
        return "", ""
    page = Adaptor(html)
    email = scrape_email_from_page(page)
    phone = scrape_phone_from_page(page)
    # If missing, check contact sub-pages
    if not email or not phone:
        for link in get_contact_links(website, page):
            sub_html = fetch_html(link)
            if not sub_html:
                continue
            sub = Adaptor(sub_html)
            if not email:
                email = scrape_email_from_page(sub)
            if not phone:
                phone = scrape_phone_from_page(sub)
            if email and phone:
                break
    return email, phone

# ── OSM / Overpass ────────────────────────────────────────────────────────────

def geocode(location: str) -> tuple[float, float]:
    url = f"{NOMINATIM}?q={quote_plus(location)}&format=jsonv2&limit=1&countrycodes=us"
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    if not data:
        raise RuntimeError(f"Location not found: {location}")
    return float(data[0]["lat"]), float(data[0]["lon"])

def overpass_query(lat: float, lon: float, radius_m: int, keywords: list[str]) -> list[dict]:
    regex = "|".join(re.escape(k) for k in keywords)
    q = f"""[out:json][timeout:90];
(
  nwr(around:{radius_m},{lat},{lon})["name"~"{regex}",i];
  nwr(around:{radius_m},{lat},{lon})["shop"~"hvac|trade|electrical",i];
  nwr(around:{radius_m},{lat},{lon})["craft"~"electrician|hvac|excavation",i];
  nwr(around:{radius_m},{lat},{lon})["trade"~"electrician|hvac|excavation",i];
);
out center tags;"""
    payload = f"data={quote_plus(q)}".encode()
    for ep in OVERPASS_ENDPOINTS:
        try:
            req = Request(ep, data=payload,
                          headers={"User-Agent": USER_AGENT,
                                   "Content-Type": "application/x-www-form-urlencoded"},
                          method="POST")
            with urlopen(req, timeout=90) as r:
                return json.loads(r.read()).get("elements", [])
        except Exception:
            continue
    return []

def element_to_contractor(trade: str, el: dict) -> Contractor:
    tags    = el.get("tags", {})
    name    = tags.get("name", "")
    phone   = tags.get("phone") or tags.get("contact:phone", "")
    website = tags.get("website") or tags.get("contact:website", "")
    email   = tags.get("email") or tags.get("contact:email", "")
    addr    = ", ".join(filter(None, [
        tags.get("addr:housenumber", ""),
        tags.get("addr:street", ""),
        tags.get("addr:city", ""),
        tags.get("addr:state", ""),
        tags.get("addr:postcode", ""),
    ]))
    place_id = f"osm:{el.get('type','')}:{el.get('id','')}"
    return Contractor(trade, name, phone, email, website, addr, place_id)

def search_contractors(
    location: str,
    trades: list[str],
    limit: int,
    radius_m: int,
    enrich: bool,
    progress_cb,
    result_cb,
    done_cb,
    stop_event: threading.Event,
) -> None:
    try:
        progress_cb(0, "Geocoding location...")
        lat, lon = geocode(location)
    except Exception as e:
        done_cb(False, str(e))
        return

    total_trades = len(trades)
    all_seen: set[str] = set()

    for t_idx, trade in enumerate(trades):
        if stop_event.is_set():
            break
        keywords = CATEGORY_KEYWORDS.get(trade, [trade.lower()])
        progress_cb(
            int((t_idx / total_trades) * 40),
            f"Searching {trade} contractors..."
        )
        elements = overpass_query(lat, lon, radius_m, keywords)
        contractors: list[Contractor] = []
        for el in elements:
            name = el.get("tags", {}).get("name", "").strip()
            if not name:
                continue
            pid = f"osm:{el.get('type','')}:{el.get('id','')}"
            if pid in all_seen:
                continue
            all_seen.add(pid)
            tags = el.get("tags", {})
            name = tags.get("name", "").strip()

            ai_trade = classify_trade_ai(name, tags)
            if not ai_trade:
                continue

            contractor = element_to_contractor(ai_trade, el)
            contractors.append(contractor)
            if len(contractors) >= limit:
                break

        base_pct = int(((t_idx + 0.4) / total_trades) * 80)
        for i, c in enumerate(contractors):
            if stop_event.is_set():
                break
            pct = base_pct + int((i / max(len(contractors), 1)) * (80 // total_trades))
            progress_cb(pct, f"[{trade}] Enriching: {c.name[:40]}...")
            if enrich and c.website and (not c.email or not c.phone):
                scraped_email, scraped_phone = extract_contact_info(c.website)
                if not c.email:
                    c.email = scraped_email
                if not c.phone:
                    c.phone = scraped_phone
            result_cb(c)

    done_cb(True, "")

# ── Worker thread ─────────────────────────────────────────────────────────────

class SearchWorker(QThread):
    progress  = Signal(int, str)
    result    = Signal(object)
    finished  = Signal(bool, str)

    def __init__(self, location, trades, limit, radius_m, enrich):
        super().__init__()
        self.location = location
        self.trades   = trades
        self.limit    = limit
        self.radius_m = radius_m
        self.enrich   = enrich
        self._stop    = threading.Event()

    def run(self):
        search_contractors(
            self.location, self.trades, self.limit, self.radius_m, self.enrich,
            self.progress.emit, self.result.emit, self.finished.emit, self._stop
        )

    def stop(self):
        self._stop.set()

# ── GUI ───────────────────────────────────────────────────────────────────────

DARK_BG     = "#0f1117"
PANEL_BG    = "#1a1d27"
BORDER      = "#2a2d3e"
ACCENT      = "#6366f1"
ACCENT_DARK = "#4f52c9"
TEXT        = "#e2e8f0"
TEXT_DIM    = "#94a3b8"
SUCCESS     = "#10b981"
WARNING     = "#f59e0b"
DANGER      = "#ef4444"

STYLE = f"""
QMainWindow, QWidget {{ background: {DARK_BG}; color: {TEXT}; font-family: 'Segoe UI', Arial; }}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 8px; margin-top: 12px;
    padding: 12px; font-size: 12px; color: {TEXT_DIM};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; color: {TEXT_DIM}; }}
QLineEdit, QComboBox {{
    background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 6px 10px; color: {TEXT}; font-size: 13px; height: 32px;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: {PANEL_BG}; color: {TEXT}; selection-background-color: {ACCENT}; }}
QPushButton {{
    background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 7px 18px; color: {TEXT}; font-size: 13px; font-weight: 500;
}}
QPushButton:hover {{ background: {BORDER}; }}
QPushButton#searchBtn {{
    background: {ACCENT}; border: none; color: white; font-weight: 600; font-size: 14px;
}}
QPushButton#searchBtn:hover {{ background: {ACCENT_DARK}; }}
QPushButton#searchBtn:disabled {{ background: #3a3d56; color: {TEXT_DIM}; }}
QPushButton#stopBtn {{ background: {DANGER}; border: none; color: white; }}
QPushButton#stopBtn:hover {{ background: #c53030; }}
QCheckBox {{ color: {TEXT}; font-size: 13px; spacing: 6px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid {BORDER}; border-radius: 4px;
    background: {PANEL_BG};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QProgressBar {{
    border: 1px solid {BORDER}; border-radius: 6px; background: {PANEL_BG};
    height: 10px; text-align: center; color: {TEXT}; font-size: 11px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QTableView {{
    background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: {BORDER}; color: {TEXT}; font-size: 13px; selection-background-color: #2d3050;
}}
QTableView::item {{ padding: 6px 10px; border-bottom: 1px solid {BORDER}; }}
QTableView::item:selected {{ background: #2d3050; color: {TEXT}; }}
QHeaderView::section {{
    background: {DARK_BG}; color: {TEXT_DIM}; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px; padding: 8px 10px;
    border: none; border-bottom: 1px solid {BORDER};
}}
QStatusBar {{ background: {DARK_BG}; color: {TEXT_DIM}; font-size: 12px; padding: 4px 8px; }}
QLabel#heading {{ font-size: 20px; font-weight: 700; color: {TEXT}; }}
QLabel#sub {{ font-size: 13px; color: {TEXT_DIM}; }}
QLabel#stat {{ font-size: 22px; font-weight: 700; color: {TEXT}; }}
QLabel#statLabel {{ font-size: 11px; color: {TEXT_DIM}; text-transform: uppercase; }}
QFrame#statCard {{
    background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px;
}}
"""

class StatCard(QFrame):
    def __init__(self, label: str, color: str):
        super().__init__()
        self.setObjectName("statCard")
        self.setMinimumWidth(100)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        self.num = QLabel("0")
        self.num.setObjectName("stat")
        self.num.setStyleSheet(f"color: {color}; font-size: 26px; font-weight: 700;")
        lbl = QLabel(label)
        lbl.setObjectName("statLabel")
        layout.addWidget(self.num)
        layout.addWidget(lbl)

    def set_value(self, n: int):
        self.num.setText(str(n))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contractor Finder  ·  Powered by Scrapling")
        self.resize(1200, 780)
        self.worker: SearchWorker | None = None
        self.all_rows: list[Contractor] = []
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 10)
        root.setSpacing(12)

        # ── Header ──
        hdr = QHBoxLayout()
        title_col = QVBoxLayout()
        h = QLabel("Contractor Finder")
        h.setObjectName("heading")
        s = QLabel("HVAC · Electrical · Excavating  |  Powered by Scrapling")
        s.setObjectName("sub")
        title_col.addWidget(h)
        title_col.addWidget(s)
        hdr.addLayout(title_col)
        hdr.addStretch()
        root.addLayout(hdr)

        # ── Search panel ──
        search_group = QGroupBox("Search Parameters")
        sg_layout = QVBoxLayout(search_group)
        sg_layout.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(10)

        loc_col = QVBoxLayout()
        loc_col.addWidget(QLabel("Location"))
        self.loc_input = QLineEdit()
        self.loc_input.setPlaceholderText("e.g. Warren, MI 48091  or  Chicago, IL")
        self.loc_input.setText("Warren, MI 48091")
        self.loc_input.returnPressed.connect(self.start_search)
        loc_col.addWidget(self.loc_input)
        row1.addLayout(loc_col, 3)

        radius_col = QVBoxLayout()
        radius_col.addWidget(QLabel("Radius"))
        self.radius_combo = QComboBox()
        for r, label in [("10000","10 miles"), ("25000","25 miles"),
                          ("40000","40 miles"), ("60000","60 miles"), ("80000","80 miles")]:
            self.radius_combo.addItem(label, r)
        self.radius_combo.setCurrentIndex(2)
        radius_col.addWidget(self.radius_combo)
        row1.addLayout(radius_col, 1)

        per_col = QVBoxLayout()
        per_col.addWidget(QLabel("Per Trade"))
        self.per_combo = QComboBox()
        for n in ["10", "20", "30", "40", "50"]:
            self.per_combo.addItem(n, int(n))
        self.per_combo.setCurrentIndex(2)
        per_col.addWidget(self.per_combo)
        row1.addLayout(per_col, 1)

        sg_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(20)
        trade_lbl = QLabel("Trades:")
        trade_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        row2.addWidget(trade_lbl)
        self.chk_hvac = QCheckBox("HVAC"); self.chk_hvac.setChecked(True)
        self.chk_elec = QCheckBox("Electrical"); self.chk_elec.setChecked(True)
        self.chk_dirt = QCheckBox("Excavating"); self.chk_dirt.setChecked(True)
        row2.addWidget(self.chk_hvac)
        row2.addWidget(self.chk_elec)
        row2.addWidget(self.chk_dirt)
        row2.addSpacing(20)
        self.chk_enrich = QCheckBox("Scrape websites for missing contacts (slower)")
        self.chk_enrich.setChecked(True)
        row2.addWidget(self.chk_enrich)
        row2.addStretch()
        sg_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.search_btn = QPushButton("Search Contractors")
        self.search_btn.setObjectName("searchBtn")
        self.search_btn.setFixedHeight(40)
        self.search_btn.clicked.connect(self.start_search)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.setFixedWidth(80)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_search)
        row3.addWidget(self.search_btn)
        row3.addWidget(self.stop_btn)
        sg_layout.addLayout(row3)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        sg_layout.addWidget(self.progress_bar)

        root.addWidget(search_group)

        # ── Stats ──
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.stat_hvac  = StatCard("HVAC", TRADE_COLORS["HVAC"])
        self.stat_elec  = StatCard("Electrical", TRADE_COLORS["Electrical"])
        self.stat_dirt  = StatCard("Excavating", TRADE_COLORS["Excavating"])
        self.stat_total = StatCard("Total", ACCENT)
        for s in [self.stat_hvac, self.stat_elec, self.stat_dirt, self.stat_total]:
            stats_row.addWidget(s)
        stats_row.addStretch()

        # Filter row
        filter_lbl = QLabel("Filter:")
        filter_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        stats_row.addWidget(filter_lbl)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All Trades", "HVAC", "Electrical", "Excavating"])
        self.filter_combo.setFixedWidth(140)
        self.filter_combo.currentTextChanged.connect(self.apply_filter)
        stats_row.addWidget(self.filter_combo)

        self.name_filter = QLineEdit()
        self.name_filter.setPlaceholderText("Search by name...")
        self.name_filter.setFixedWidth(180)
        self.name_filter.textChanged.connect(self.apply_filter)
        stats_row.addWidget(self.name_filter)

        root.addLayout(stats_row)

        # ── Table ──
        self.model = QStandardItemModel(0, 6)
        self.model.setHorizontalHeaderLabels(["Trade", "Company Name", "Phone", "Email", "Website", "Address"])

        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(3, 200)
        self.table.setColumnWidth(4, 190)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        root.addWidget(self.table)

        # ── Export row ──
        exp_row = QHBoxLayout()
        self.export_csv_btn = QPushButton("Export CSV")
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.export_txt_btn = QPushButton("Export TXT")
        self.export_txt_btn.clicked.connect(self.export_txt)
        self.clear_btn = QPushButton("Clear Results")
        self.clear_btn.clicked.connect(self.clear_results)
        exp_row.addWidget(self.export_csv_btn)
        exp_row.addWidget(self.export_txt_btn)
        exp_row.addWidget(self.clear_btn)
        exp_row.addStretch()
        root.addLayout(exp_row)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready — enter a location and click Search")

    # ── Search logic ──────────────────────────────────────────────────────────

    def start_search(self):
        loc = self.loc_input.text().strip()
        if not loc:
            QMessageBox.warning(self, "Missing Location", "Please enter a location.")
            return
        trades = []
        if self.chk_hvac.isChecked(): trades.append("HVAC")
        if self.chk_elec.isChecked(): trades.append("Electrical")
        if self.chk_dirt.isChecked(): trades.append("Excavating")
        if not trades:
            QMessageBox.warning(self, "No Trades", "Select at least one trade.")
            return

        self.all_rows.clear()
        self.model.removeRows(0, self.model.rowCount())
        self._reset_stats()
        self.search_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        limit    = int(self.per_combo.currentData())
        radius_m = int(self.radius_combo.currentData())
        enrich   = self.chk_enrich.isChecked()

        self.worker = SearchWorker(loc, trades, limit, radius_m, enrich)
        self.worker.progress.connect(self._on_progress)
        self.worker.result.connect(self._on_result)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def stop_search(self):
        if self.worker:
            self.worker.stop()
        self.stop_btn.setEnabled(False)
        self.status.showMessage("Stopping...")

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.status.showMessage(msg)

    def _on_result(self, c: Contractor):
        self.all_rows.append(c)
        color = TRADE_COLORS.get(c.trade, TEXT)
        trade_item = QStandardItem(c.trade)
        trade_item.setForeground(QBrush(QColor(color)))
        trade_item.setFont(QFont("Segoe UI", 11, QFont.Bold))
        items = [
            trade_item,
            QStandardItem(c.name),
            QStandardItem(c.phone),
            QStandardItem(c.email),
            QStandardItem(c.website),
            QStandardItem(c.address),
        ]
        for it in items[1:]:
            it.setForeground(QBrush(QColor(TEXT)))
        self.model.appendRow(items)
        self._update_stats()

    def _on_finished(self, ok: bool, err: str):
        self.progress_bar.setValue(100)
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if ok:
            self.status.showMessage(
                f"Done — {len(self.all_rows)} contractors found  |  "
                f"HVAC: {self._count('HVAC')}  Electrical: {self._count('Electrical')}  "
                f"Excavating: {self._count('Excavating')}"
            )
        else:
            QMessageBox.critical(self, "Search Error", err)
            self.status.showMessage(f"Error: {err}")

    # ── Filter ────────────────────────────────────────────────────────────────

    def apply_filter(self):
        trade_filter = self.filter_combo.currentText()
        name_query   = self.name_filter.text().strip()
        # Rebuild model rows visibility via proxy filter
        if trade_filter == "All Trades" and not name_query:
            self.proxy.setFilterFixedString("")
            return
        # Use a combined approach: filter model directly
        self.model.removeRows(0, self.model.rowCount())
        for c in self.all_rows:
            if trade_filter != "All Trades" and c.trade != trade_filter:
                continue
            if name_query and name_query.lower() not in c.name.lower():
                continue
            color = TRADE_COLORS.get(c.trade, TEXT)
            trade_item = QStandardItem(c.trade)
            trade_item.setForeground(QBrush(QColor(color)))
            trade_item.setFont(QFont("Segoe UI", 11, QFont.Bold))
            items = [
                trade_item,
                QStandardItem(c.name),
                QStandardItem(c.phone),
                QStandardItem(c.email),
                QStandardItem(c.website),
                QStandardItem(c.address),
            ]
            for it in items[1:]:
                it.setForeground(QBrush(QColor(TEXT)))
            self.model.appendRow(items)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def _count(self, trade: str) -> int:
        return sum(1 for c in self.all_rows if c.trade == trade)

    def _update_stats(self):
        self.stat_hvac.set_value(self._count("HVAC"))
        self.stat_elec.set_value(self._count("Electrical"))
        self.stat_dirt.set_value(self._count("Excavating"))
        self.stat_total.set_value(len(self.all_rows))

    def _reset_stats(self):
        for s in [self.stat_hvac, self.stat_elec, self.stat_dirt, self.stat_total]:
            s.set_value(0)

    def clear_results(self):
        self.all_rows.clear()
        self.model.removeRows(0, self.model.rowCount())
        self._reset_stats()
        self.progress_bar.setValue(0)
        self.status.showMessage("Cleared — ready for new search")

    # ── Export ────────────────────────────────────────────────────────────────

    def export_csv(self):
        if not self.all_rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "contractors.csv", "CSV Files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["trade","name","phone","email","website","address","place_id"])
            w.writeheader()
            for c in self.all_rows:
                w.writerow(asdict(c))
        self.status.showMessage(f"Exported {len(self.all_rows)} rows → {path}")

    def export_txt(self):
        if not self.all_rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save TXT", "contractors.txt", "Text Files (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for trade in ["HVAC", "Electrical", "Excavating"]:
                group = [c for c in self.all_rows if c.trade == trade]
                if not group:
                    continue
                f.write(f"{trade.upper()} CONTRACTORS\n{'─'*40}\n")
                for i, c in enumerate(group, 1):
                    f.write(f"{i}. {c.name}\n")
                    f.write(f"   Phone:   {c.phone or 'N/A'}\n")
                    f.write(f"   Email:   {c.email or 'N/A'}\n")
                    f.write(f"   Website: {c.website or 'N/A'}\n")
                    f.write(f"   Address: {c.address or 'N/A'}\n\n")
        self.status.showMessage(f"Exported → {path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setApplicationName("Contractor Finder")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
