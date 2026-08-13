# -*- coding: utf-8 -*-
"""
设备管理器：
  - 端口扫描 / 连接 / 断开 / 冷启动自动重连上次设备
  - 后台状态轮询（电量 / 缺纸 / 开盖 / 过热），打印期间自动暂停
  - 打印前自动体检拦截故障；打印全程串行化
"""

import threading
import time

from PySide6.QtCore import QObject, Signal

from .driver import (CMD_BATTERY, CMD_STATUS, QringError, QringPrinter,
                     SerialTransport)


LOW_BATTERY_BLOCK_PCT = 15


def battery_percent(raw):
    """把原始电量值换算成百分比（启发式：0-100 直接取，否则按电压）。"""
    if raw is None:
        return None
    if 0 <= raw <= 100:
        return raw
    # 常见固件返回电压值（如 408 = 4.08V）
    volts = raw / 100.0
    if volts >= 3.2:
        pct = (volts - 3.3) / (4.2 - 3.3) * 100.0
        return max(0, min(100, int(round(pct))))
    return raw


class DeviceManager(QObject):
    """所有串口操作都放在独立线程；Qt 信号回主线程更新 UI。"""

    stateChanged = Signal(bool, str)        # (connected, port)
    statusChanged = Signal(dict)            # 轮询状态
    message = Signal(str)                   # 提示消息
    printFinished = Signal(bool, str)       # (ok, message)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.printer = None
        self.port = None
        self._io_lock = threading.Lock()
        self._print_lock = threading.Lock()
        self._printing = threading.Event()
        self._stop = threading.Event()
        self._last_status = {
            "ok": None, "problems": ["未连接"], "battery_raw": None,
            "battery_pct": None, "raw": None,
        }
        self._monitor = threading.Thread(target=self._monitor_loop,
                                         daemon=True, name="qrint-monitor")
        self._monitor.start()

    # ------------------------------------------------------------------
    # 端口与连接
    # ------------------------------------------------------------------

    @staticmethod
    def refresh_ports():
        ports = []
        try:
            from serial.tools import list_ports
            for p in list_ports.comports():
                label = p.device
                if p.description and p.description != "n/a":
                    label += f" ({p.description})"
                ports.append((p.device, label))
        except Exception:
            pass
        # 去重并保持顺序
        seen = set()
        out = []
        for dev, label in ports:
            if dev not in seen:
                seen.add(dev)
                out.append((dev, label))
        return out

    @staticmethod
    def _paired_bt_names():
        """从注册表读取已配对经典蓝牙设备：{MAC(大写十六进制): 友好名}。

        仅 Windows 有效；无 winreg / 无权限 / 读取失败均返回 {}。
        """
        names = {}
        try:
            import winreg
        except ImportError:
            return names
        path = (r"SYSTEM\CurrentControlSet\Services"
                r"\BTHPORT\Parameters\Devices")
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        except OSError:
            return names
        try:
            i = 0
            while True:
                try:
                    mac = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    sub = winreg.OpenKey(root, mac)
                    val, _typ = winreg.QueryValueEx(sub, "Name")
                    winreg.CloseKey(sub)
                except OSError:
                    continue
                if isinstance(val, (bytes, bytearray)):
                    name = bytes(val).split(b"\x00")[0].decode(
                        "utf-8", "replace")
                else:
                    name = str(val)
                name = name.strip()
                if name:
                    names[mac.upper()] = name
        finally:
            winreg.CloseKey(root)
        return names

    @staticmethod
    def list_qring_printers():
        """枚举名称以 “Qring” 开头的已配对蓝牙打印机。

        返回 [{"port": "COM3"|None, "name": "Qring_50F0",
                "mac": "5A10350E50F0"}, ...]，按“有端口在前 + 名称”排序。
        已配对但尚未生成虚拟串口的设备 port 为 None。
        任何异常都降级为 []，绝不抛出到 UI。
        """
        try:
            names = DeviceManager._paired_bt_names()
            qring = {mac: nm for mac, nm in names.items()
                     if nm.lower().startswith("qring")}
            if not qring:
                return []
            # COM 口的 hwid 内嵌蓝牙 MAC，用它把设备配到串口
            port_by_mac = {}
            try:
                from serial.tools import list_ports
                for p in list_ports.comports():
                    hwid = (p.hwid or "").upper()
                    for mac in qring:
                        if mac in hwid:
                            port_by_mac.setdefault(mac, p.device)
            except Exception:
                pass
            out = []
            for mac, nm in qring.items():
                out.append({"port": port_by_mac.get(mac),
                            "name": nm, "mac": mac})
            out.sort(key=lambda d: (d["port"] is None, d["name"].lower()))
            return out
        except Exception:
            return []

    def connect(self, port):
        """异步连接指定串口；结果通过 stateChanged/message 信号通知。

        串口 I/O 放在工作线程，蓝牙端口异常（如未连接的 SPP 虚拟口）
        导致写入卡顿时不会冻结界面线程。
        """
        threading.Thread(target=self._connect_worker, args=(port,),
                         daemon=True, name="qrint-connect").start()

    def _connect_worker(self, port):
        with self._io_lock:
            self._close_locked()
            try:
                transport = SerialTransport(port)
                printer = QringPrinter(transport)
                ok, problems, raw = printer.status()
                if raw is None:
                    raise QringError("设备无响应，请确认已配对且打印机已开机")
            except QringError as exc:
                self.message.emit(f"连接失败：{exc}")
                self.stateChanged.emit(False, port)
                return
            except Exception as exc:
                self.message.emit(f"连接失败：{exc}")
                self.stateChanged.emit(False, port)
                return

            self.printer = printer
            self.port = port
            self.config.set("last_port", port)
            self._last_status = {
                "ok": ok, "problems": problems, "battery_raw": None,
                "battery_pct": None, "raw": raw,
            }
            self.statusChanged.emit(self._last_status)
            self.stateChanged.emit(True, port)
            self.message.emit(f"已连接 {port}")

    def auto_reconnect(self):
        """冷启动自动重连上次设备。"""
        if not self.config.get("auto_reconnect", True):
            return
        port = self.config.get("last_port", "COM3")
        if port:
            self.connect(port)

    def disconnect(self):
        """异步断开连接，避免关闭挂起的串口时阻塞界面。"""
        threading.Thread(target=self._disconnect_worker, daemon=True,
                         name="qrint-disconnect").start()

    def _disconnect_worker(self):
        with self._io_lock:
            self._close_locked()
            self.message.emit("已断开连接")
            self.stateChanged.emit(False, self.port or "")

    def is_connected(self):
        return self.printer is not None

    def status_snapshot(self):
        """返回不触发串口 I/O 的当前状态快照，供 UI / MCP 查询。"""
        status = dict(self._last_status)
        status.update({
            "connected": self.printer is not None,
            "port": self.port,
            "printing": self._printing.is_set(),
        })
        return status

    def _close_locked(self):
        if self.printer is not None:
            try:
                self.printer.close()
            except Exception:
                pass
        self.printer = None
        self.port = None

    # ------------------------------------------------------------------
    # 状态轮询（打印期间暂停）
    # ------------------------------------------------------------------

    def _monitor_loop(self):
        interval = max(0.5, float(self.config.get("poll_interval_s", 3.0)))
        while not self._stop.is_set():
            time.sleep(0.4)
            if self._stop.is_set():
                break
            if self._printing.is_set():
                continue
            printer = self.printer
            if printer is None:
                continue
            try:
                with self._io_lock:
                    if self._printing.is_set() or self.printer is not printer:
                        continue
                    ok, problems, raw = printer.status()
                    battery_raw = printer.battery()
                self._last_status = {
                    "ok": ok, "problems": problems,
                    "battery_raw": battery_raw,
                    "battery_pct": battery_percent(battery_raw),
                    "raw": raw,
                }
                self.statusChanged.emit(self._last_status)
            except Exception:
                # 连接丢失：通知 UI，不再反复报错
                if self.printer is not None:
                    with self._io_lock:
                        self._close_locked()
                    self.message.emit("设备连接丢失，请检查蓝牙配对状态")
                    self.stateChanged.emit(False, "")
            time.sleep(interval)

    # ------------------------------------------------------------------
    # 健康检查与打印
    # ------------------------------------------------------------------

    def check_ready(self):
        """打印前体检；返回 (是否可打印, 问题列表)。"""
        printer = self.printer
        if printer is None:
            return False, ["打印机未连接"]
        try:
            with self._io_lock:
                ok, problems, raw = printer.status()
                battery_raw = printer.battery()
        except Exception as exc:
            return False, [f"读取状态失败：{exc}"]
        faults = [p for p in problems if p != "正常" and p != "正在打印"]
        if faults:
            return False, faults
        pct = battery_percent(battery_raw)
        if pct is not None and pct < LOW_BATTERY_BLOCK_PCT:
            return False, [f"电量过低（{pct}%），请先充电"]
        return True, []

    def print_job(self, packed, row_bytes, height, feed_before=None,
                  feed_after=None, thickness=None, timeout=120.0,
                  result_callback=None, started_callback=None,
                  emit_signal=True):
        """
        异步打印光栅数据。成功后 emit printFinished(True, msg)。
        打印期间状态轮询自动暂停，避免查询字节混入数据流。
        """
        if self.printer is None:
            self._report_print_result(
                False, "打印机未连接", result_callback, emit_signal)
            return
        t = threading.Thread(target=self._print_worker,
                             args=(packed, row_bytes, height, feed_before,
                                   feed_after, thickness, timeout,
                                   result_callback, started_callback,
                                   emit_signal),
                             daemon=True, name="qrint-print")
        t.start()

    def _print_worker(self, packed, row_bytes, height, feed_before,
                      feed_after, thickness, timeout, result_callback,
                      started_callback, emit_signal):
        with self._print_lock:
            self._printing.set()
            try:
                if started_callback is not None:
                    try:
                        started_callback()
                    except Exception:
                        pass
                printer = self.printer
                if printer is None:
                    self._report_print_result(
                        False, "打印机未连接", result_callback, emit_signal)
                    return
                ok, problems = self.check_ready()
                if not ok:
                    self._report_print_result(
                        False, "打印前体检拦截：" + "、".join(problems),
                        result_callback, emit_signal)
                    return
                with self._io_lock:
                    printer.enable()
                    if thickness is not None:
                        printer.set_thickness(thickness)
                    printer.wakeup()
                    printer.feed(int(feed_before or 0))
                    printer.print_raster(packed, row_bytes, height)
                    printer.feed(int(feed_after or 0))
                    printer.stop()
                    ok, msg = printer.wait_ack(timeout)
                self._report_print_result(
                    ok, msg, result_callback, emit_signal)
            except Exception as exc:
                self._report_print_result(
                    False, f"打印异常：{exc}", result_callback, emit_signal)
            finally:
                self._printing.clear()

    def _report_print_result(self, ok, message, callback, emit_signal):
        if callback is not None:
            try:
                callback(bool(ok), str(message))
            except Exception:
                pass
        if emit_signal:
            self.printFinished.emit(bool(ok), str(message))

    def shutdown(self):
        self._stop.set()
        with self._io_lock:
            self._close_locked()
        if self._monitor.is_alive():
            self._monitor.join(timeout=2.0)
