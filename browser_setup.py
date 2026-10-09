"""Browser setup shared by source launches and frozen Windows builds."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path


def driver_command(package: str) -> tuple[list[str], dict]:
    driver = importlib.import_module(f"{package}._impl._driver")
    node, cli = driver.compute_driver_executable()
    return [str(node), str(cli), "install", "chromium"], driver.get_driver_env()


def browsers_ready() -> bool:
    for package in ("playwright", "patchright"):
        try:
            api = importlib.import_module(f"{package}.sync_api")
            factory = getattr(api, f"sync_{package}")
            with factory() as runtime:
                if not Path(runtime.chromium.executable_path).is_file():
                    return False
        except Exception:
            return False
    return True


def install_browsers(line_callback) -> bool:
    for package in ("playwright", "patchright"):
        try:
            command, environment = driver_command(package)
            kwargs = (
                {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
            )
            with subprocess.Popen(
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **kwargs,
            ) as process:
                for line in process.stdout:
                    line_callback(line.rstrip())
                if process.wait() != 0:
                    line_callback(f"{package} browser installation failed.")
                    return False
        except Exception as exc:
            line_callback(f"{package} setup failed: {exc}")
            return False
    return browsers_ready()
