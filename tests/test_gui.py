"""Exercise real Qt objects; network work stays outside these UI regressions."""
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from models import Contractor


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(application):
    with patch("gui.main_window.SEARCH_HISTORY.load", return_value=[]):
        with patch("gui.main_window._settings.get", return_value=""):
            window = MainWindow()
    yield window
    window.close()
    application.processEvents()


def test_verification_resolves_record_id_after_filtering(window):
    first = Contractor("HVAC", "Alpha", email="alpha@company.com")
    second = Contractor("HVAC", "Zeta", email="zeta@company.com", email_method="guessed")
    window.rows = [first, second]
    window.nf.setText("Zeta")
    window._filter()
    window._on_verify(first.record_id, "valid", "domain accepts email")
    window._on_verify(second.record_id, "invalid", "domain rejects email")
    assert first.email_status == "valid"
    assert second.email_status == "invalid"
    assert window.table.rowCount() == 1
    assert "Guessed" in window.table.item(0, 5).text()
    assert window.table.item(0, 5).data(Qt.UserRole) == second.record_id


def test_clear_refuses_running_worker(window):
    class Running:
        def isRunning(self):
            return True
        def stop(self):
            pass
    row = Contractor("HVAC", "Alpha")
    window.rows = [row]
    window.worker = Running()
    window.clear()
    assert window.rows == [row]
    window.worker = None
