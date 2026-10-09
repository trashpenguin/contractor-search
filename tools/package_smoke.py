import subprocess
from pathlib import Path

executable = Path("dist/ContractorFinder/ContractorFinder.exe").resolve()
subprocess.run([str(executable), "--smoke-test"], timeout=60, check=True)
