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

REM --- Zip the result so it can be dropped on Google Drive / a USB stick ----
echo.
echo Zipping dist\ProductImageBatch into dist\ProductImageBatch.zip ...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\ProductImageBatch\*' -DestinationPath 'dist\ProductImageBatch.zip' -Force"

echo.
echo ==========================================================================
echo  Done!
echo    App folder : dist\ProductImageBatch\ProductImageBatch.exe
echo    Portable   : dist\ProductImageBatch.zip   ^<-- copy this to Google Drive
echo.
echo  On the other PC: download the zip, right-click ^> Extract All, then
echo  double-click ProductImageBatch.exe (no Python needed).
echo  First run: Settings ^> paste API keys ^> Save, then Start this tab.
echo ==========================================================================
endlocal
