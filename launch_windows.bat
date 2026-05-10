@echo off
title Contractor Finder v3.2 — Async + Proxy Rotation
cd /d "%~dp0"
echo =============================================
echo   Contractor Finder v3.2 -- Setup ^& Launch
echo =============================================
echo.

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found. Install from https://python.org
    pause
    exit /b 1
)

echo [1/4] Checking module structure...
IF NOT EXIST "models.py" (
    echo [ERROR] models.py missing. Run from the contractor-search directory.
    pause
    exit /b 1
)
IF NOT EXIST "scrapers\ddg.py" (
    echo [ERROR] scrapers\ package missing. Run from the contractor-search directory.
    pause
    exit /b 1
)
IF NOT EXIST "gui\main_window.py" (
    echo [ERROR] gui\ package missing. Run from the contractor-search directory.
    pause
    exit /b 1
)
echo     OK

echo [2/4] Installing Python packages...
python -m pip install scrapling browserforge curl_cffi playwright patchright PySide6 dnspython msgspec aiohttp python-whois --quiet
IF %ERRORLEVEL% NEQ 0 (
    echo [WARN] pip install returned errors — continuing anyway.
)

echo [3/4] Installing browser backends...
python -m playwright install chromium
python -m patchright install chromium

echo [4/4] Launching Contractor Finder v3.2...
echo.
python contractor_gui.py
pause
