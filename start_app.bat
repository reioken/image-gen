@echo off
REM ==========================================================================
REM  Double-click launcher for the SOURCE version (needs Python installed).
REM  Put this file in the project folder and double-click it to start the GUI.
REM  For a no-Python portable version, build the .exe with build_exe.bat.
REM ==========================================================================

cd /d "%~dp0"

REM Use the venv if it exists, otherwise the system Python.
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

REM Ensure dependencies are present (quiet; skips if already installed).
%PY% -m pip install -r requirements.txt >nul 2>&1

%PY% -m product_image_batch.gui.app
if errorlevel 1 (
    echo.
    echo The app exited with an error. Press any key to close.
    pause >nul
)
