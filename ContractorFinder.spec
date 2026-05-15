# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Contractor Finder
# Build: pyinstaller ContractorFinder.spec --clean --noconfirm
# Output: dist/ContractorFinder/ContractorFinder.exe

from PyInstaller.utils.hooks import collect_all, collect_submodules

# collect_all returns (datas, binaries, hiddenimports)
# playwright and patchright include their Node.js driver executables as data files
pw_d,  pw_b,  pw_h  = collect_all('playwright')
pr_d,  pr_b,  pr_h  = collect_all('patchright')
bf_d,  bf_b,  bf_h  = collect_all('browserforge')
sc_d,  sc_b,  sc_h  = collect_all('scrapling')

a = Analysis(
    ['contractor_gui.py'],
    pathex=[],
    binaries=pw_b + pr_b + bf_b + sc_b,
    datas=pw_d + pr_d + bf_d + sc_d,
    hiddenimports=(
        pw_h + pr_h + bf_h + sc_h
        + collect_submodules('dns')
        + collect_submodules('aiohttp')
        + [
            'curl_cffi',
            'curl_cffi.requests',
            'msgspec',
            'msgspec.json',
            'whois',
            'PySide6.QtCore',
            'PySide6.QtGui',
            'PySide6.QtWidgets',
            'PySide6.QtNetwork',
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim packages that are definitely not needed to keep size down
    excludes=['matplotlib', 'numpy', 'pandas', 'PIL', 'tkinter', 'IPython',
              'jupyter', 'notebook', 'scipy', 'sklearn'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ContractorFinder',
    debug=False,
    strip=False,
    upx=True,           # compress if UPX is installed; skipped silently if not
    console=False,      # no terminal window — set True to debug startup crashes
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ContractorFinder',
)
