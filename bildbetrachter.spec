# -*- mode: python ; coding: utf-8 -*-

import sys


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

if sys.platform == "darwin":
    executable = EXE(
        pyz,
        analysis.scripts,
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
        exclude_binaries=True,
    )
    collection = COLLECT(
        executable,
        analysis.binaries,
        analysis.zipfiles,
        analysis.datas,
        name="BildBlick",
    )
    app = BUNDLE(
        collection,
        name="BildBlick.app",
        icon="assets/BildBlick.icns",
        bundle_identifier="de.oppi0815.bildblick",
        info_plist={
            "CFBundleName": "BildBlick",
            "CFBundleDisplayName": "BildBlick",
            "CFBundleShortVersionString": "1.16.0",
            "CFBundleVersion": "1.16.0",
            "LSApplicationCategoryType": "public.app-category.photography",
            "NSHighResolutionCapable": True,
        },
    )
else:
    exe = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.zipfiles,
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
        onefile=True,
    )
