import subprocess
from pathlib import Path

executable = Path("dist/ContractorFinder/ContractorFinder.exe").resolve()
try:
    subprocess.run([str(executable), "--smoke-test"], timeout=60, check=True)
except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
    log = Path.home() / "contractor_finder.log"
    if log.exists():
        print(log.read_text(encoding="utf-8", errors="replace"))
    raise
