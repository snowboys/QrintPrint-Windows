# -*- coding: utf-8 -*-
"""仿真打印机测试：体检 -> 光栅 -> ACK，验证打印期间无查询字节混入。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

from app import render  # noqa: E402
from app.config import Config  # noqa: E402
from app.device import DeviceManager  # noqa: E402
from app.driver import (CMD_BATTERY, CMD_ENABLE, CMD_STATUS,  # noqa: E402
                        QringPrinter)


class FakeTransport:
    """记录写入字节；按命令返回状态/电量/打印 ACK。"""

    def __init__(self):
        self.written = bytearray()
        self.saw_raster = False
        self.status = b"\x00"
        self.battery = b"\x00\x50"

    def write(self, data):
        self.written += data
        if b"\x1D\x76\x30" in data:
            self.saw_raster = True

    def flush_input(self):
        pass

    def read(self, n, timeout=1.0):
        if self.saw_raster:
            return b"\xAA"
        if self.written.endswith(CMD_STATUS):
            return self.status
        if self.written.endswith(CMD_BATTERY):
            return self.battery
        return b""

    def close(self):
        pass


def main():
    app = QCoreApplication([])
    mgr = DeviceManager(Config())
    fake = FakeTransport()
    mgr.printer = QringPrinter(fake)
    mgr.port = "SIM"

    results = []
    end_first = [0]

    def on_done(ok, msg):
        results.append((ok, msg))
        end_first[0] = len(fake.written)  # ACK 收到瞬间的字节数

    mgr.printFinished.connect(on_done)

    gray = render.render_text_image("SIM 打印测试 123", font_size=28)
    packed, rb, h, _ = render.prepare_bitmap(gray, 200, "none")
    mgr.print_job(packed, rb, h, feed_before=5, feed_after=20, thickness=1)

    QTimer.singleShot(6000, app.quit)
    app.exec()

    assert results == [(True, "打印完成")], results

    # 体检会先发一次状态查询；此后（enable 之后）不得再出现查询命令
    first_segment = bytes(fake.written)
    idx = first_segment.find(CMD_ENABLE)
    assert idx >= 0
    tail = first_segment[idx:end_first[0]]
    assert CMD_STATUS not in tail
    assert CMD_BATTERY not in tail
    assert b"\x1D\x76\x30" in fake.written  # 光栅头
    print("print bytes:", len(fake.written), "| raster header present, "
          "no query bytes during print")

    # 故障拦截：缺纸时打印应被体检拦截
    fake.saw_raster = False
    fake.status = b"\x04"
    results.clear()
    mgr.print_job(packed, rb, h)
    QTimer.singleShot(6000, app.quit)
    app.exec()
    assert results and not results[0][0], results
    assert "体检拦截" in results[0][1]
    print("fault block ok:", results[0][1])

    mgr.shutdown()
    print("DEVICE SIM OK")


if __name__ == "__main__":
    main()
