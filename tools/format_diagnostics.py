"""Emit formatter changes for remote diagnostics, then require clean formatting."""
import json
import subprocess
from pathlib import Path

paths = subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines()
changes = {path: Path(path).read_text(encoding="utf-8") for path in paths if path.endswith(".py")}
for path, content in changes.items():
    print("FORMAT_FILE=" + json.dumps({"path": path, "content": content}))
raise SystemExit(bool(changes))
