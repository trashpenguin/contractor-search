from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class StatCard(QFrame):
    def __init__(self, label: str, color: str):
        super().__init__()
        self.setStyleSheet("background:#1a1d27;border:1px solid #2a2d3e;border-radius:6px;")
        self.setFixedWidth(80)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 5)
        lay.setSpacing(1)
        self.num = QLabel("0")
        self.num.setStyleSheet(f"color:{color};border:none;font-size:18px;font-weight:700;")
        short = (
            label.replace("Construction Staking", "C.Stake")
            .replace("Geotechnical Contractor", "Geotech.")
            .replace("Fire Hydrant Contractor", "F.Hydrant")
            .replace("Fire Suppression Company", "F.Supprs.")
            .replace("Pre Cast Company", "PreCast")
        )
        lbl = QLabel(short.upper())
        lbl.setStyleSheet("color:#64748b;font-size:7px;font-weight:700;border:none;")
        lbl.setWordWrap(True)
        lay.addWidget(self.num)
        lay.addWidget(lbl)

    def set(self, n: int):
        self.num.setText(str(n))


class TradeSelector(QWidget):
    """Compact dropdown button that opens a searchable trade checkbox panel."""

    selectionChanged = Signal(list)

    def __init__(self, trades: dict[str, str], parent=None):
        """trades: {trade_name: hex_color}"""
        super().__init__(parent)
        self._trades = trades
        self._checkboxes: dict[str, QCheckBox] = {}
        self._panel: QFrame | None = None
        self._build()

    # ── public API ────────────────────────────────────────────────────────────

    def selected(self) -> list[str]:
        return [t for t, cb in self._checkboxes.items() if cb.isChecked()]

    # ── internals ─────────────────────────────────────────────────────────────

    def _build(self):
        # Pre-create checkboxes immediately so _checkboxes is always populated
        # even before the panel is first opened.
        for t, col in self._trades.items():
            cb = QCheckBox(t, self)
            cb.setChecked(True)
            cb.setStyleSheet(
                f"QCheckBox{{color:{col};font-weight:700;font-size:12px;padding:3px 4px;}}"
                f"QCheckBox:hover{{background:#1e2436;border-radius:4px;}}"
            )
            cb.stateChanged.connect(self._on_changed)
            self._checkboxes[t] = cb

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._btn = QPushButton()
        self._btn.setFixedHeight(34)
        self._btn.setMinimumWidth(220)
        self._btn.setStyleSheet("text-align:left;padding-left:10px;")
        self._btn.clicked.connect(self._toggle)
        self._refresh_label()
        lay.addWidget(self._btn)

    def _refresh_label(self):
        sel = self.selected()
        n = len(sel)
        total = len(self._trades)
        if n == 0:
            txt = "No trades selected  ▾"
        elif n == total:
            txt = f"All {total} trades selected  ▾"
        else:
            names = ", ".join(sel[:2])
            extra = f"  +{n - 2} more" if n > 2 else ""
            txt = f"{names}{extra}  ▾"
        self._btn.setText(txt)

    def _toggle(self):
        if self._panel and self._panel.isVisible():
            self._panel.hide()
            return
        if not self._panel:
            self._panel = self._build_panel()
        # Position panel directly below the button
        pos = self.mapToGlobal(QPoint(0, self.height()))
        self._panel.move(pos)
        self._panel.show()
        self._panel.raise_()
        self._panel._search.setFocus()
        self._panel._search.clear()
        # Ensure all items visible on fresh open
        for cb in self._checkboxes.values():
            cb.setVisible(True)

    def _build_panel(self) -> QFrame:
        panel = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        panel.setStyleSheet(
            "QFrame{background:#1a1d27;border:1px solid #334155;border-radius:8px;}"
            "QCheckBox{color:#e2e8f0;font-size:12px;padding:2px 4px;}"
            "QCheckBox:hover{background:#1e2436;border-radius:4px;}"
            "QLineEdit{background:#0f1117;border:1px solid #334155;"
            "border-radius:4px;color:#e2e8f0;padding:4px 8px;font-size:12px;}"
            "QPushButton{background:#1e293b;color:#94a3b8;border:1px solid #334155;"
            "border-radius:4px;font-size:10px;padding:2px 8px;}"
            "QPushButton:hover{background:#334155;color:#e2e8f0;}"
        )
        panel.setMinimumWidth(280)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        # Search input
        search = QLineEdit()
        search.setPlaceholderText("Search trades...")
        search.setFixedHeight(30)
        lay.addWidget(search)
        panel._search = search

        # All / None row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        all_btn = QPushButton("Select All")
        none_btn = QPushButton("Select None")
        all_btn.setFixedHeight(24)
        none_btn.setFixedHeight(24)
        btn_row.addWidget(all_btn)
        btn_row.addWidget(none_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        # Scrollable checkbox list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(250)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")

        list_w = QWidget()
        list_w.setStyleSheet("background:transparent;")
        list_lay = QVBoxLayout(list_w)
        list_lay.setContentsMargins(2, 2, 2, 2)
        list_lay.setSpacing(2)

        for cb in self._checkboxes.values():
            list_lay.addWidget(cb)

        list_lay.addStretch()
        scroll.setWidget(list_w)
        lay.addWidget(scroll)

        # Wire search filter
        def _filter(text: str):
            for t, cb in self._checkboxes.items():
                cb.setVisible(text.strip().lower() in t.lower())

        search.textChanged.connect(_filter)

        # Wire all/none
        all_btn.clicked.connect(lambda: [cb.setChecked(True) for cb in self._checkboxes.values()])
        none_btn.clicked.connect(lambda: [cb.setChecked(False) for cb in self._checkboxes.values()])

        return panel

    def _on_changed(self):
        self._refresh_label()
        self.selectionChanged.emit(self.selected())
