@echo off
title Build ContractorFinder.exe
cd /d "%~dp0"
echo =============================================
echo   Contractor Finder -- PyInstaller Build
echo =============================================
echo.

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found. Install from https://python.org
    pause
    exit /b 1
)

echo [1/3] Installing build tools...
python -m pip install pyinstaller pyinstaller-hooks-contrib --quiet
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)

echo [2/3] Installing app dependencies...
python -m pip install -r requirements.txt --quiet

echo [3/3] Building exe...
pyinstaller ContractorFinder.spec --clean --noconfirm
IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed. Check output above for details.
    echo Tip: change console=False to console=True in ContractorFinder.spec
    echo      to see startup errors when debugging.
    pause
    exit /b 1
)

echo.
echo =============================================
echo   Build complete!
echo   Output: dist\ContractorFinder\ContractorFinder.exe
echo   Zip the dist\ContractorFinder\ folder to share.
echo =============================================
pause
