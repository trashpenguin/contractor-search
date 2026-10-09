"""Install and launch both real Chromium engines on the Windows runner."""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browser_setup import install_browsers  # noqa: E402

if not install_browsers(print):
    raise RuntimeError("Browser installation did not complete")
for package in ("playwright", "patchright"):
    api = importlib.import_module(f"{package}.sync_api")
    with getattr(api, f"sync_{package}")() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<h1>Contractor Finder browser smoke test</h1>")
        assert page.locator("h1").inner_text() == "Contractor Finder browser smoke test"
        browser.close()
