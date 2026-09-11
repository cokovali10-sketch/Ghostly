@echo off
REM Ghostly Analytics - Build EXE Script
REM Builds a single-file executable using PyInstaller

echo.
echo ============================================
echo   Ghostly Analytics - EXE Builder
echo ============================================
echo.

REM Check if PyInstaller is installed
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller>=6.0.0
)

REM Clean previous builds
echo Cleaning previous builds...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

REM Build the EXE
echo.
echo Building Ghostly Analytics EXE...
echo.

pyinstaller ^
    --onefile ^
    --name "Ghostly" ^
    --add-data "ghostly/templates;ghostly/templates" ^
    --add-data "ghostly/static;ghostly/static" ^
    --hidden-import "ghostly" ^
    --hidden-import "ghostly.core" ^
    --hidden-import "ghostly.core.server" ^
    --hidden-import "ghostly.api" ^
    --hidden-import "ghostly.dashboard" ^
    --hidden-import "aiohttp" ^
    --hidden-import "aiosqlite" ^
    --console ^
    --clean ^
    launch.py

if %errorlevel% neq 0 (
    echo.
    echo BUILD FAILED!
    echo Check the output above for errors.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Build complete!
echo   EXE location: dist\Ghostly.exe
echo ============================================
echo.

REM Ask if user wants to test the EXE
set /p TEST_EXE="Would you like to test the EXE? (y/n): "
if /i "%TEST_EXE%"=="y" (
    echo Starting Ghostly EXE...
    start "" "dist\Ghostly.exe"
)

pause
