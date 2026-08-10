# -*- coding: utf-8 -*-
"""
小印 (Qring / BeePrt BY) 热敏打印机驱动。

协议与命令从 qring-spp.py 重构而来（源自 com.zxxk.xiaoyin.App 分析）：
  - 蓝牙 SPP 虚拟串口，默认波特率 115200
  - 单次 write 上限 1024 字节，包间 1ms
  - 光栅位图 GS v 0，384 点宽、MSB first、bit 1 = 黑
  - 查询命令固定流程：清空输入 -> 发送 -> 延时 -> 读响应
"""

import socket
import time


WIDTH_DOTS = 384
WIDTH_BYTES = WIDTH_DOTS // 8
CHUNK = 1024
SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"

CMD_ENABLE     = bytes([0x10, 0xFF, 0xF1, 0x02])
CMD_ENABLE2    = bytes([0x1F, 0xB2, 0x10])
CMD_STOP       = bytes([0x10, 0xFF, 0xF1, 0x45])
CMD_WAKEUP     = bytes(12)
CMD_LABEL_POS  = bytes([0x1D, 0x0C])
CMD_LEARN_GAP  = bytes([0x10, 0xFF, 0x03])

CMD_STATUS     = bytes([0x10, 0xFF, 0x40])
CMD_BATTERY    = bytes([0x10, 0xFF, 0x50, 0xF1])
CMD_BT_NAME    = bytes([0x10, 0xFF, 0x30, 0x11])
CMD_BT_MAC     = bytes([0x10, 0xFF, 0x30, 0x12])
CMD_BT_VERSION = bytes([0x10, 0xFF, 0x30, 0x10])
CMD_FW_VERSION = bytes([0x10, 0xFF, 0x20, 0xF1])
CMD_SN         = bytes([0x10, 0xFF, 0x20, 0xF2])
CMD_MODEL      = bytes([0x10, 0xFF, 0x20, 0xF0])
CMD_INFO       = bytes([0x10, 0xFF, 0x70])

ACK_PRINT_DONE = 0xAA

STATUS_BITS = [
    (0x01, "正在打印"),
    (0x02, "机身异常 / 开盖"),
    (0x04, "缺纸"),
    (0x08, "电量电压低"),
    (0x10, "过热"),
]

UNSOLICITED = {
    0x01: "缺纸",
    0x02: "开盖",
    0x03: "过热",
    0x04: "低电量",
}


class QringError(Exception):
    """驱动层错误（打不开端口、无响应、超时等）。"""


class SerialTransport:
    """Windows / Linux 虚拟串口 (SPP)。"""

    def __init__(self, port, baudrate=115200, timeout=1.0,
                 write_timeout=3.0):
        import serial
        try:
            self.ser = serial.Serial(port, baudrate, timeout=timeout,
                                     write_timeout=write_timeout)
        except (OSError, serial.SerialException) as exc:
            raise QringError(f"无法打开 {port}: {exc}") from exc

    def write(self, data):
        """写入数据；write_timeout 保证驱动卡住时不会无限阻塞。"""
        try:
            self.ser.write(data)
        except Exception as exc:
            raise QringError(f"写入串口失败（设备可能未连接）：{exc}") from exc

    def read(self, n, timeout=1.0):
        old = self.ser.timeout
        self.ser.timeout = timeout
        try:
            return self.ser.read(n)
        finally:
            self.ser.timeout = old

    def flush_input(self):
        try:
            self.ser.reset_input_buffer()
        except OSError:
            pass

    def close(self):
        try:
            self.ser.close()
        except OSError:
            pass


class RfcommTransport:
    """Linux 原生 RFCOMM socket（免 rfcomm bind）。"""

    def __init__(self, mac, channel=1, timeout=10.0):
        self.sock = socket.socket(
            socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
        )
        self.sock.settimeout(timeout)
        self.sock.connect((mac, channel))

    def write(self, data):
        self.sock.sendall(data)

    def read(self, n, timeout=1.0):
        self.sock.settimeout(timeout)
        try:
            return self.sock.recv(n)
        except socket.timeout:
            return b""

    def flush_input(self):
        self.sock.settimeout(0.05)
        try:
            while self.sock.recv(4096):
                pass
        except (socket.timeout, OSError):
            pass

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class QringPrinter:
    """58mm 热敏打印机高层封装。"""

    def __init__(self, transport, verbose=False):
        self.t = transport
        self.verbose = verbose

    # ---------- 底层 ----------

    def _send(self, data):
        """按 SDK 方式分片：每 1024 字节一包，包间 1ms。"""
        if self.verbose and len(data) <= 32:
            print(f"  TX {data.hex(' ').upper()}")
        elif self.verbose:
            print(f"  TX {len(data)} bytes ({data[:16].hex(' ').upper()} ...)")
        for off in range(0, len(data), CHUNK):
            self.t.write(data[off:off + CHUNK])
            time.sleep(0.001)

    def _query(self, cmd, nbytes=64, timeout=1.5):
        """清空输入 -> 发命令 -> 读响应（SDK 的固定套路）。"""
        self.t.flush_input()
        self._send(cmd)
        time.sleep(0.15)
        resp = self.t.read(nbytes, timeout=timeout)
        if self.verbose and resp:
            print(f"  RX {resp.hex(' ').upper()}")
        return resp

    # ---------- 状态查询 ----------

    def status(self):
        """返回 (是否正常, 问题描述列表, 原始状态字节)。"""
        resp = self._query(CMD_STATUS, 1)
        if not resp:
            return False, ["无响应"], None
        b = resp[0]
        problems = [name for mask, name in STATUS_BITS if b & mask]
        return (b == 0), (problems or ["正常"]), b

    def battery(self):
        """读取电量原始值（第 2 字节）；失败返回 None。"""
        resp = self._query(CMD_BATTERY, 2)
        return resp[1] if len(resp) >= 2 else None

    def _query_str(self, cmd):
        resp = self._query(cmd, 64)
        if not resp:
            return None
        return resp.decode("gb2312", errors="replace").strip("\x00").strip()

    def info(self):
        return {
            "型号":     self._query_str(CMD_MODEL),
            "序列号":   self._query_str(CMD_SN),
            "固件版本": self._query_str(CMD_FW_VERSION),
            "蓝牙名称": self._query_str(CMD_BT_NAME),
            "蓝牙版本": self._query_str(CMD_BT_VERSION),
            "MAC":      (lambda r: r.hex(":").upper() if r else None)(
                            self._query(CMD_BT_MAC, 16)),
            "电量":     self.battery(),
        }

    # ---------- 设置 ----------

    def set_thickness(self, level):
        """打印浓度 / 加热强度；APP 文字模式用 1。"""
        self._send(bytes([0x10, 0xFF, 0x10, 0x00, level & 0xFF]))

    def set_shutdown_time(self, seconds):
        """自动关机时间，大端 16 位。"""
        self._send(bytes([0x10, 0xFF, 0x12,
                          (seconds // 256) & 0xFF, seconds % 256]))

    # ---------- 打印原语 ----------

    def enable(self):
        self._send(CMD_ENABLE)
        self._send(CMD_ENABLE2)

    def stop(self):
        self._send(CMD_STOP)

    def wakeup(self):
        self._send(CMD_WAKEUP)

    def feed(self, dots):
        """ESC J n — 走纸 n 点行；n 为单字节，>255 自动拆分。"""
        while dots > 0:
            n = min(dots, 255)
            self._send(bytes([0x1B, 0x4A, n]))
            dots -= n

    def print_raster(self, data, width_bytes, height, mode=0):
        """GS v 0 — 发送光栅位图。"""
        header = bytes([
            0x1D, 0x76, 0x30, mode & 0x03,
            width_bytes % 256, width_bytes // 256,
            height % 256,      height // 256,
        ])
        self._send(header)
        self._send(data)

    def wait_ack(self, timeout=120.0):
        """等待打印完成 ACK (0xAA)，同时处理主动上报的故障帧。"""
        deadline = time.time() + timeout
        buf = b""
        while time.time() < deadline:
            chunk = self.t.read(16, timeout=1.0)
            if not chunk:
                continue
            buf += chunk
            if self.verbose:
                print(f"  RX {chunk.hex(' ').upper()}")
            if ACK_PRINT_DONE in buf:
                return True, "打印完成"
            for i in range(len(buf) - 1):
                if buf[i] == 0xFF and buf[i + 1] in UNSOLICITED:
                    return False, UNSOLICITED[buf[i + 1]]
        return False, "等待 ACK 超时"

    def close(self):
        self.t.close()
