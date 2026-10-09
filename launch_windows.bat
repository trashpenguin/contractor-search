@echo off
title Contractor Finder v3.4
cd /d "%~dp0"
echo =============================================
echo   Contractor Finder v3.4 -- Setup ^& Launch
echo =============================================
echo.

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found. Install from https://python.org
    pause
    exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python 3.11 or later is required.
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
python -m pip install -r requirements.txt
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Package installation failed. Resolve the error above and retry.
    pause
    exit /b 1
)

echo [3/4] Installing browser backends...
python -m playwright install chromium
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Playwright browser installation failed.
    pause
    exit /b 1
)
python -m patchright install chromium
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Patchright browser installation failed.
    pause
    exit /b 1
)

echo [4/4] Launching Contractor Finder v3.4...
echo.
python contractor_gui.py
pause
