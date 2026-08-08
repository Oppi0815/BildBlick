# -*- mode: python ; coding: utf-8 -*-


analysis = Analysis(
    ["bildbetrachter.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("bildbetrachter.ui", "."),
        ("assets", "assets"),
    ],
    hiddenimports=[
        "PySide6.QtPrintSupport",
        "PySide6.QtPdf",
        "printing",
        "printing.multi_image_print",
        "printing.print_profiles",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="BildBlick",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
