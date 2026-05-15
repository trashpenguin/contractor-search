from __future__ import annotations

from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QTableWidgetItem

from constants import SOURCE_COLORS, TRADE_COLORS
from extractor import email_role_warning
from gui.style import VERIFY_COLORS, VERIFY_ICONS


class TableMixin:
    def _add_row(self, c):
        self.rows.append(c)
        self._filter()
        self._update_stats()

    def _fill_row(self, row: int, c):
        bg = QColor("#161925") if row % 2 == 1 else QColor("#1a1d27")
        vc = VERIFY_COLORS.get(c.email_status, "#94a3b8")
        vi = f"{VERIFY_ICONS.get(c.email_status, '')} {c.email_status}".strip()
        note = email_role_warning(c.email) if c.email else ""
        vals = [
            (c.trade, TRADE_COLORS.get(c.trade, "#e2e8f0"), True),
            (c.source, SOURCE_COLORS.get(c.source, "#94a3b8"), True),
            (c.name, "#e2e8f0", False),
            (c.phone, "#10b981" if c.phone else "#94a3b8", False),
            (c.email, "#93c5fd" if c.email else "#94a3b8", False),
            (vi, vc, True),
            (c.website, "#93c5fd", False),
            (c.address, "#e2e8f0", False),
            (note, "#f59e0b" if note else "#94a3b8", False),
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
        src = self.sf2.currentText()
        name = self.nf.text().strip().lower()
        hide_empty = getattr(self, "chk_hide", None)
        hide_empty_checked = hide_empty is not None and hide_empty.isChecked()

        matched = []
        for c in self.rows:
            if trade != "All" and c.trade != trade:
                continue
            if src != "All Sources" and c.source != src:
                continue
            if name and name not in c.name.lower():
                continue
            if hide_empty_checked and c.quality_score == 0:
                continue
            matched.append(c)

        matched.sort(key=lambda c: c.quality_score, reverse=True)

        self.table.setRowCount(0)
        for i, c in enumerate(matched):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._fill_row(row, c)
