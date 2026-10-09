from __future__ import annotations

import csv
import os
import tempfile
import webbrowser

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QLabel, QTextEdit, QVBoxLayout

from exporter import _BOARD_HEADERS, _write_board_csv, write_csv
from provenance import email_label
from PySide6.QtWidgets import QMessageBox


class ExportMixin:
    def export_sheets(self):
        if not self.rows:
            return
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".csv", mode="w", newline="", encoding="utf-8"
        )
        w = csv.DictWriter(tmp, fieldnames=_BOARD_HEADERS)
        w.writeheader()
        _write_board_csv(w, self.rows)
        tmp.close()
        dlg = QDialog(self)
        dlg.setWindowTitle("Export to Google Sheets")
        dlg.resize(480, 280)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("<b>CSV ready — import steps:</b>"))
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(
            f"File saved: {tmp.name}\n\n"
            "1. Google Sheets will open in your browser\n"
            "2. File → Import → Upload tab\n"
            f"3. Select: {os.path.basename(tmp.name)}\n"
            "4. Separator: Comma  |  'Replace spreadsheet' → Import data\n\n"
            "Columns match your board:\n"
            "  Name · Follow-up Date · Sub's Phone · Link for file\n"
            "  Bid Deadline · Sub's Email · Job Date · Scope of Work\n"
            "  Project Address · Subcontractor Role · Status"
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
        self._save_csv(path)

    def export_board_csv(self):
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Board CSV", "contractors_board.csv", "CSV (*.csv)"
        )
        if path:
            self._save_csv(path, board=True)

    def _save_csv(self, path, board=False):
        try:
            write_csv(path, list(self.rows), board=board)
        except OSError as error:
            QMessageBox.warning(self, "Export failed", str(error))
            return
        self.statusBar().showMessage(f"Saved {len(self.rows)} rows → {path}")

    def export_txt(self):
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save TXT", "contractors.txt", "Text (*.txt)")
        if not path:
            return
        from collections import defaultdict

        groups: dict = defaultdict(list)
        for c in self.rows:
            groups[c.trade].append(c)

        with open(path, "w", encoding="utf-8") as f:
            for trade, contractors in groups.items():
                f.write(f"\n{'=' * 50}\n{trade.upper()} ({len(contractors)})\n{'=' * 50}\n")
                for i, c in enumerate(contractors, 1):
                    f.write(
                        f"\n{i}. {c.name}\n"
                        f"   Phone:   {c.phone or 'N/A'}\n"
                        f"   Email:   {c.email or 'N/A'}\n"
                        f"   Email status: {email_label(c)}\n"
                        f"   Email source: {c.email_source_url or 'Unconfirmed'}\n"
                        f"   Website: {c.website or 'N/A'}\n"
                        f"   Address: {c.address or 'N/A'}\n"
                    )
        self.statusBar().showMessage(f"Saved → {path}")
