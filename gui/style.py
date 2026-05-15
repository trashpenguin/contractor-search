STYLE = (
    "QMainWindow,QWidget{background:#0f1117;color:#e2e8f0;"
    "font-family:'Segoe UI',Arial;}"
    "QGroupBox{border:1px solid #2a2d3e;border-radius:8px;"
    "margin-top:12px;padding:10px;font-size:11px;color:#94a3b8;}"
    "QGroupBox::title{subcontrol-origin:margin;left:10px;"
    "padding:0 6px;color:#94a3b8;}"
    "QLineEdit,QComboBox{background:#1a1d27;border:1px solid #2a2d3e;"
    "border-radius:6px;padding:5px 10px;color:#e2e8f0;font-size:13px;}"
    "QLineEdit:focus,QComboBox:focus{border-color:#6366f1;}"
    "QComboBox::drop-down{border:none;width:20px;}"
    "QComboBox QAbstractItemView{background:#1a1d27;color:#e2e8f0;"
    "selection-background-color:#6366f1;}"
    "QPushButton{background:#1a1d27;border:1px solid #2a2d3e;"
    "border-radius:6px;padding:6px 16px;color:#e2e8f0;"
    "font-size:13px;font-weight:500;}"
    "QPushButton:hover{background:#2a2d3e;}"
    "QPushButton:disabled{color:#94a3b8;}"
    "QPushButton#searchBtn{background:#6366f1;border:none;"
    "color:white;font-weight:700;font-size:14px;}"
    "QPushButton#searchBtn:hover{background:#4f52c9;}"
    "QPushButton#searchBtn:disabled{background:#3a3d56;color:#94a3b8;}"
    "QPushButton#stopBtn{background:#ef4444;border:none;"
    "color:white;font-weight:600;}"
    "QPushButton#stopBtn:hover{background:#c53030;}"
    "QPushButton#verifyBtn{background:#0ea5e9;border:none;"
    "color:white;font-weight:600;}"
    "QPushButton#verifyBtn:hover{background:#0284c7;}"
    "QPushButton#sheetsBtn{background:#16a34a;border:none;"
    "color:white;font-weight:600;}"
    "QPushButton#sheetsBtn:hover{background:#15803d;}"
    "QCheckBox{color:#e2e8f0;font-size:13px;spacing:6px;}"
    "QCheckBox::indicator{width:15px;height:15px;"
    "border:1px solid #2a2d3e;border-radius:4px;background:#1a1d27;}"
    "QCheckBox::indicator:checked{background:#6366f1;border-color:#6366f1;}"
    "QProgressBar{border:none;border-radius:4px;background:#1a1d27;height:8px;}"
    "QProgressBar::chunk{background:#6366f1;border-radius:4px;}"
    "QTableWidget{background:#1a1d27;border:1px solid #2a2d3e;"
    "border-radius:8px;gridline-color:#2a2d3e;color:#e2e8f0;"
    "font-size:12px;selection-background-color:#2d3050;}"
    "QTableWidget::item{padding:4px 8px;border-bottom:1px solid #2a2d3e;}"
    "QTableWidget::item:selected{background:#2d3050;}"
    "QHeaderView::section{background:#0f1117;color:#94a3b8;"
    "font-size:10px;font-weight:700;padding:7px 8px;"
    "border:none;border-bottom:1px solid #2a2d3e;}"
    "QScrollBar:vertical{background:#1a1d27;width:7px;border-radius:4px;}"
    "QScrollBar::handle:vertical{background:#2a2d3e;"
    "border-radius:4px;min-height:20px;}"
    "QScrollBar:horizontal{background:#1a1d27;height:7px;border-radius:4px;}"
    "QScrollBar::handle:horizontal{background:#2a2d3e;"
    "border-radius:4px;min-width:20px;}"
    "QStatusBar{background:#0f1117;color:#94a3b8;"
    "font-size:12px;padding:4px 10px;}"
    "QTextEdit{background:#1a1d27;border:1px solid #2a2d3e;"
    "border-radius:6px;color:#e2e8f0;}"
)

COLS = [
    "Trade",
    "Source",
    "Company Name",
    "Phone",
    "Email",
    "Email Status",
    "Website",
    "Address",
    "Note",
]

VERIFY_COLORS = {
    "valid": "#10b981",
    "invalid": "#ef4444",
    "unknown": "#94a3b8",
    "guessed": "#f59e0b",
    "": "#94a3b8",
}
VERIFY_ICONS = {"valid": "✅", "invalid": "❌", "unknown": "❓", "guessed": "~", "": ""}
