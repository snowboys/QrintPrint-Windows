#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QrintPrint - 58mm 蓝牙热敏打印机 Windows 桌面程序入口

依赖优先从项目内 vendor/ 目录加载，实现自包含部署。
"""

import os
import sys


def _setup_vendor():
    """把项目内 vendor/ 加入 sys.path（若存在），使程序无需安装依赖即可运行。"""
    here = os.path.dirname(os.path.abspath(__file__))
    vendor = os.path.join(here, "vendor")
    if os.path.isdir(vendor) and vendor not in sys.path:
        sys.path.insert(0, vendor)


_setup_vendor()

from app.config import BASE_DIR, DATA_DIR, ensure_dirs  # noqa: E402
from app.theme import apply_theme    # noqa: E402
from app.ui import MainWindow        # noqa: E402
from PySide6.QtCore import QTimer    # noqa: E402
from PySide6.QtGui import QIcon      # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _app_icon():
    # onefile 打包时资源解压到 sys._MEIPASS，其次才是 exe / 源码目录
    roots = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        roots.append(bundle)
    roots.append(BASE_DIR)
    for root in roots:
        for name in ("QrintPrint.ico", os.path.join("img", "QrintPrint.ico")):
            path = os.path.join(root, name)
            if os.path.exists(path):
                return QIcon(path)
    return QIcon()


def main():
    selftest = "--selftest" in sys.argv
    ensure_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName("错题小印")
    app.setOrganizationName("QrintPrint")
    apply_theme(app)
    app.setWindowIcon(_app_icon())

    window = MainWindow()
    window.setWindowIcon(_app_icon())
    window.show()

    if selftest:
        # 自检模式：构建完整主窗口后自动退出，并写入成功标记
        QTimer.singleShot(1500, app.quit)
        exit_code = app.exec()
        window.shutdown()
        try:
            with open(os.path.join(DATA_DIR, "selftest.ok"), "w",
                      encoding="utf-8") as f:
                f.write("ok")
        except OSError:
            pass
        return exit_code

    exit_code = app.exec()
    window.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
