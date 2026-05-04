@echo off
title Contractor Finder Launcher

:: Change to the folder where THIS .bat file lives
cd /d "%~dp0"

echo =============================================
echo   Contractor Finder -- Setup and Launch
echo =============================================
echo.

:: Check Python
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found.
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

echo [1/3] Installing Python dependencies...
python -m pip install scrapling browserforge curl_cffi playwright PySide6
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)

echo [2/3] Installing Playwright browser (Chromium)...
python -m playwright install chromium
IF %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Playwright browser install failed - continuing anyway...
)

echo [3/3] Launching Contractor Finder GUI...
echo.
python contractor_gui.py

echo.
echo Program exited.
pause