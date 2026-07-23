# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Product Image Batch desktop app.

Build (on Windows) with:
    pyinstaller build\\product_image_batch.spec --noconfirm

Produces  dist\\ProductImageBatch\\ProductImageBatch.exe  (one-dir mode).

One-dir (not one-file) is deliberate: one-file re-extracts to a temp dir on
every launch, making startup noticeably slower. One-dir keeps the .exe next to
its dependencies for the fastest possible start — which is what we want.

API keys are NOT bundled. Only the *template* config and .env.example are
shipped; real keys are read at runtime from %APPDATA%\\ProductImageBatch\\.env,
created from the template on first launch.
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# The spec runs from the project root when invoked as `pyinstaller build/...spec`.
ROOT = Path(os.getcwd())
ICON = ROOT / "build" / "app_icon.ico"
VERSION_FILE = ROOT / "build" / "version_info.txt"

# Ship the config templates and the .env template (NOT a real .env).
datas = [
    (str(ROOT / "config" / "providers.yaml"), "config"),
    (str(ROOT / "config" / "prompt_rewrite.yaml"), "config"),
    (str(ROOT / "config" / "settings.default.json"), "config"),
    (str(ROOT / ".env.example"), "."),
    (str(ROOT / "product_image_batch" / "gui" / "resources" / "app_icon.ico"),
     "product_image_batch/gui/resources"),
]

# PySide6 plugins (platforms, imageformats, styles) must come along; PyInstaller's
# PySide6 hook handles most, but be explicit about optional bits.
hiddenimports = (
    collect_submodules("product_image_batch.core.providers")
    + ["PySide6.QtSvg", "PIL._tkinter_finder"]
)

block_cipher = None

a = Analysis(
    [str(ROOT / "product_image_batch" / "gui" / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim heavy libs we don't ship to keep the folder smaller / faster.
    excludes=["tkinter", "pytest", "respx", "pandas.tests"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ProductImageBatch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # GUI app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ProductImageBatch",
)
