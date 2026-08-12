# -*- mode: python ; coding: utf-8 -*-
"""QrintPrint PyInstaller 打包配置：生成自包含的单文件 dist/QrintPrint.exe。

用法：
    pyinstaller --noconfirm qrintprint.spec
产物：dist/QrintPrint.exe（单个可执行文件，图标/字体等资源全部内置，
      拷贝这一个文件到任意 Windows 机器双击即可运行）
"""

import os

project_root = os.path.abspath(SPECPATH)
vendor_dir = os.path.join(project_root, "vendor")
icon_path = os.path.join(project_root, "QrintPrint.ico")

a = Analysis(
    [os.path.join(project_root, "qrintprint.py")],
    pathex=[project_root, vendor_dir],
    binaries=[],
    datas=[
        # python-barcode 的条码文字需要随包字体，否则一维码文本渲染会失败
        (os.path.join(vendor_dir, "barcode", "fonts", "DejaVuSansMono.ttf"),
         "barcode/fonts"),
        # 窗口/任务栏图标，运行期从解压目录读取
        (icon_path, "."),
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

# 单文件（onefile）：把二进制与数据全部塞进 EXE，不再生成 _internal 文件夹
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
