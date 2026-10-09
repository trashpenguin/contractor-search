import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_APPLICATION = None


@pytest.fixture(scope="session", autouse=True)
def application():
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    yield _APPLICATION
    _APPLICATION.closeAllWindows()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APPLICATION.processEvents()
