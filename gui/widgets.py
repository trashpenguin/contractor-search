from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class StatCard(QFrame):
    def __init__(self, label: str, color: str):
        super().__init__()
        self.setStyleSheet("background:#1a1d27;border:1px solid #2a2d3e;border-radius:8px;")
        self.setMinimumWidth(90)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(1)
        self.num = QLabel("0")
        self.num.setStyleSheet(f"color:{color};border:none;font-size:22px;font-weight:700;")
        lbl = QLabel(label.upper())
        lbl.setStyleSheet("color:#94a3b8;font-size:9px;font-weight:700;border:none;")
        lay.addWidget(self.num)
        lay.addWidget(lbl)

    def set(self, n: int):
        self.num.setText(str(n))
