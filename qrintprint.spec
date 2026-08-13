# -*- mode: python ; coding: utf-8 -*-
"""Build QrintPrint as a self-contained Windows executable."""

import os

from PyInstaller.utils.hooks import collect_data_files


project_root = os.path.abspath(SPECPATH)
icon_path = os.path.join(project_root, "QrintPrint.ico")

# python-barcode uses this font when human-readable text is enabled.
datas = collect_data_files("barcode", includes=["fonts/*.ttf"])
datas.append((icon_path, "."))

a = Analysis(
    [os.path.join(project_root, "qrintprint.py")],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "serial",
        "serial.tools.list_ports",
        "barcode",
        "barcode.writer",
        "qrcode",
        "PIL",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="QrintPrint",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)
