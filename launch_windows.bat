@echo off
title Contractor Finder v3.1 — Async + Proxy Rotation
cd /d "%~dp0"
echo =============================================
echo   Contractor Finder v3.1 -- Setup & Launch
echo =============================================
echo.
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 ( echo [ERROR] Python not found. & pause & exit /b 1 )
echo [1/3] Installing Python packages...
python -m pip install scrapling browserforge curl_cffi playwright patchright PySide6 dnspython msgspec aiohttp --quiet
echo [2/3] Installing browsers...
python -m playwright install chromium
python -m patchright install chromium
echo [3/3] Launching Contractor Finder v3.1...
echo.
python contractor_gui.py
pause
