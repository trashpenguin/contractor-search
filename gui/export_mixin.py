from __future__ import annotations

import csv
import os
import tempfile
import webbrowser

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QLabel, QTextEdit, QVBoxLayout

# Column headers matching the Monday.com board layout.
# Blank columns (Follow-up Date, Link for file, etc.) are left empty for
# the user to fill in after import.
_BOARD_HEADERS = [
    "Name",
    "Follow-up Date",
    "Sub's Phone",
    "Link for file",
    "Bid Deadline",
    "Sub's Email",
    "Job Date",
    "Scope of Work",
    "Project Address",
    "Subcontractor Role",
    "Status",
]


def _to_board_row(contractor) -> dict:
    return {
        "Name": contractor.name,
        "Follow-up Date": "",
        "Sub's Phone": contractor.phone,
        "Link for file": "",
        "Bid Deadline": "",
        "Sub's Email": contractor.email,
        "Job Date": "",
        "Scope of Work": "",
        "Project Address": contractor.address,
        "Subcontractor Role": contractor.trade,
        "Status": "NOT STARTED",
    }


def _write_board_csv(writer, rows):
    """Write rows grouped by trade, matching the board's group layout."""
    from collections import defaultdict

    groups: dict = defaultdict(list)
    for c in rows:
        groups[c.trade].append(c)

    for trade, contractors in groups.items():
        # Group header row — mirrors the coloured trade label in the board
        writer.writerow(
            {h: "" for h in _BOARD_HEADERS} | {"Name": f"── {trade} ({len(contractors)})"}
        )
        for c in contractors:
            writer.writerow(_to_board_row(c))
        writer.writerow({h: "" for h in _BOARD_HEADERS})  # blank spacer between groups


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
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_BOARD_HEADERS)
            w.writeheader()
            _write_board_csv(w, self.rows)
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
                        f"   Website: {c.website or 'N/A'}\n"
                        f"   Address: {c.address or 'N/A'}\n"
                    )
        self.statusBar().showMessage(f"Saved → {path}")
