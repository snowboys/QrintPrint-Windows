# -*- mode: python ; coding: utf-8 -*-
"""QrintPrint PyInstaller 打包配置：生成自包含的 dist/QrintPrint/。

用法：
    pyinstaller --noconfirm qrintprint.spec
产物：dist/QrintPrint/QrintPrint.exe（可整体拷贝到任意 Windows 机器运行）
"""

import os

project_root = os.path.abspath(SPECPATH)
vendor_dir = os.path.join(project_root, "vendor")

a = Analysis(
    [os.path.join(project_root, "qrintprint.py")],
    pathex=[project_root, vendor_dir],
    binaries=[],
    datas=[
        # python-barcode 的条码文字需要随包字体，否则一维码文本渲染会失败
        (os.path.join(vendor_dir, "barcode", "fonts", "DejaVuSansMono.ttf"),
         "barcode/fonts"),
    ],
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
    [],
    exclude_binaries=True,
    name="QrintPrint",
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="QrintPrint",
)
