from __future__ import annotations

import csv
import os
import tempfile
import webbrowser
from dataclasses import asdict

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QLabel, QTextEdit, QVBoxLayout


class ExportMixin:
    def export_sheets(self):
        if not self.rows:
            return
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".csv", mode="w", newline="", encoding="utf-8"
        )
        fields = ["trade", "source", "name", "phone", "email", "website", "address"]
        w = csv.DictWriter(tmp, fieldnames=fields)
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
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "contractors.csv", "CSV (*.csv)")
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
        path, _ = QFileDialog.getSaveFileName(self, "Save TXT", "contractors.txt", "Text (*.txt)")
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
