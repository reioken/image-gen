@echo off
REM ==========================================================================
REM  Build the standalone Windows .exe for Product Image Batch.
REM
REM  Run this on a WINDOWS machine (PyInstaller cannot cross-compile a Windows
REM  .exe from Linux/macOS). From the project root:
REM
REM      build_exe.bat
REM
REM  Result:  dist\ProductImageBatch\ProductImageBatch.exe   (one-dir mode)
REM  Share the whole dist\ProductImageBatch\ folder, or zip it.
REM ==========================================================================

setlocal

REM --- Create / activate a virtual environment ------------------------------
if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

REM --- Install dependencies (engine + GUI + PyInstaller) --------------------
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

REM --- Build using the spec file -------------------------------------------
pyinstaller build\product_image_batch.spec --noconfirm
if errorlevel 1 (
    echo.
    echo BUILD FAILED. See the output above.
    exit /b 1
)

echo.
echo ==========================================================================
echo  Done:  dist\ProductImageBatch\ProductImageBatch.exe
echo  Launch it, open Settings, paste your API keys (stored in
echo  %%APPDATA%%\ProductImageBatch\.env), then start generating.
echo ==========================================================================
endlocal
