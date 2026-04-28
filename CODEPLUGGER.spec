# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for CODEPLUGGER.

Build:
    pyinstaller CODEPLUGGER.spec

Output: dist/CODEPLUGGER/   (folder containing the executable + all data)
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect all uvicorn + starlette submodules (they use dynamic imports)
hidden_imports = (
    collect_submodules("uvicorn")
    + collect_submodules("starlette")
    + collect_submodules("fastapi")
    + collect_submodules("pydantic")
    + collect_submodules("anyio")
    + collect_submodules("email_validator")
    + [
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "h11",
        "httptools",
        "cryptography",
        "cffi",
    ]
)

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # Web UI static files
        ("web/static", "web/static"),
        # Bundled repeater database
        ("data/repeaters.db", "data"),
        # BrandMeister talkgroup catalog
        ("Talkgroups BrandMeister.csv", "."),
        # pdfplumber / pdfminer data files
        *collect_data_files("pdfminer"),
        *collect_data_files("pdfplumber"),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL.ImageQt"],
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
    name="CODEPLUGGER",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # keep console so errors are visible during alpha
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CODEPLUGGER",
)
