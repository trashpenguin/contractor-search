import sys
from unittest.mock import MagicMock

# Stub out heavy optional deps before any local imports
for mod in [
    "scrapling",
    "aiohttp",
    "patchright",
    "playwright",
    "PySide6",
    "PySide6.QtWidgets",
    "PySide6.QtCore",
    "PySide6.QtGui",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

import compat  # noqa: E402

compat.HAS_SCRAPLING = False
compat.Adaptor = None
