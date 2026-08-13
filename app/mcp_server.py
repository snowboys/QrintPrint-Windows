# -*- coding: utf-8 -*-
"""QrintPrint 的本地 MCP Streamable HTTP 服务。"""

from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
import time
import uuid
from urllib.parse import urlsplit

from .render import (BARCODE_KINDS, prepare_bitmap, render_barcode_image,
                     render_text_image, validate_barcode)


MCP_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {
    "2024-11-05",
    "2025-03-26",
    MCP_PROTOCOL_VERSION,
}
MAX_REQUEST_BYTES = 1024 * 1024
MAX_PRINT_HEIGHT = 4096
MAX_TRACKED_JOBS = 100


class ToolCallError(ValueError):
    """可安全返回给 MCP 客户端的工具调用错误。"""


def _json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _string(args, name, default=None, required=False, max_length=5000):
    value = args.get(name, default)
    if required and (not isinstance(value, str) or not value.strip()):
        raise ToolCallError(f"{name} 不能为空")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolCallError(f"{name} 必须是字符串")
    if len(value) > max_length:
        raise ToolCallError(f"{name} 最多允许 {max_length} 个字符")
    return value


def _integer(args, name, default, minimum, maximum):
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolCallError(f"{name} 必须是整数")
    if not minimum <= value <= maximum:
        raise ToolCallError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _boolean(args, name, default=False):
    value = args.get(name, default)
    if not isinstance(value, bool):
        raise ToolCallError(f"{name} 必须是布尔值")
    return value


class QrintPrintAgentApi:
    """把设备管理器和渲染管线转换为 MCP 工具。"""

    TOOLS = [
        {
            "name": "get_printer_status",
            "title": "获取打印机状态",
            "description": "Return the current Qring printer connection, health, battery, and queue status.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": "list_printers",
            "title": "扫描打印机",
            "description": "List paired Qring Bluetooth printers and their Windows COM ports.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": "connect_printer",
            "title": "连接打印机",
            "description": "Start an asynchronous connection to a paired Qring printer on a Windows COM port.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "port": {
                        "type": "string",
                        "pattern": "^COM[0-9]+$",
                        "description": "Windows serial port returned by list_printers, for example COM3.",
                    }
                },
                "required": ["port"],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": "disconnect_printer",
            "title": "断开打印机",
            "description": "Disconnect the active Qring printer.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": "print_text",
            "title": "打印文字",
            "description": "Render and queue text for the connected 58 mm thermal printer. This consumes paper.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 5000},
                    "title": {"type": "string", "maxLength": 80},
                    "font_family": {"type": "string", "maxLength": 80, "default": "微软雅黑"},
                    "font_size": {"type": "integer", "minimum": 8, "maximum": 96, "default": 24},
                    "bold": {"type": "boolean", "default": False},
                    "italic": {"type": "boolean", "default": False},
                    "underline": {"type": "boolean", "default": False},
                    "align": {"type": "string", "enum": ["left", "center", "right"], "default": "left"},
                    "char_spacing": {"type": "integer", "minimum": 0, "maximum": 40, "default": 0},
                    "line_spacing": {"type": "integer", "minimum": 0, "maximum": 80, "default": 8},
                    "margin": {"type": "integer", "minimum": 0, "maximum": 30, "default": 8},
                    "threshold": {"type": "integer", "minimum": 0, "maximum": 255, "default": 200},
                    "feed_before": {"type": "integer", "minimum": 0, "maximum": 255},
                    "feed_after": {"type": "integer", "minimum": 0, "maximum": 512},
                    "thickness": {"type": "integer", "minimum": 0, "maximum": 7},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": False,
            },
        },
        {
            "name": "print_barcode",
            "title": "打印条码",
            "description": "Render and queue a QR code or one-dimensional barcode. This consumes paper.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": BARCODE_KINDS, "default": "QRCode"},
                    "data": {"type": "string", "minLength": 1, "maxLength": 2331},
                    "title": {"type": "string", "maxLength": 80},
                    "error_correction": {"type": "string", "enum": ["L", "M", "Q", "H"], "default": "M"},
                    "border": {"type": "integer", "minimum": 0, "maximum": 10, "default": 2},
                    "write_text": {"type": "boolean", "default": False},
                    "feed_before": {"type": "integer", "minimum": 0, "maximum": 255},
                    "feed_after": {"type": "integer", "minimum": 0, "maximum": 512},
                    "thickness": {"type": "integer", "minimum": 0, "maximum": 7},
                },
                "required": ["data"],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": False,
            },
        },
        {
            "name": "get_print_job",
            "title": "查询打印任务",
            "description": "Return the current state and result of a print job created by an MCP tool.",
            "inputSchema": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "minLength": 1}},
                "required": ["job_id"],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
    ]

    def __init__(self, device, config, on_print_success=None):
        self.device = device
        self.config = config
        self.on_print_success = on_print_success
        self._jobs = OrderedDict()
        self._jobs_lock = threading.Lock()

    def list_tools(self):
        return self.TOOLS

    def call_tool(self, name, arguments):
        if not isinstance(arguments, dict):
            raise ToolCallError("arguments 必须是对象")
        handlers = {
            "get_printer_status": self._get_printer_status,
            "list_printers": self._list_printers,
            "connect_printer": self._connect_printer,
            "disconnect_printer": self._disconnect_printer,
            "print_text": self._print_text,
            "print_barcode": self._print_barcode,
            "get_print_job": self._get_print_job,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ToolCallError(f"未知工具：{name}")
        schema = next(tool["inputSchema"] for tool in self.TOOLS
                      if tool["name"] == name)
        unknown = sorted(set(arguments) - set(schema.get("properties", {})))
        if unknown:
            raise ToolCallError("不支持的参数：" + "、".join(unknown))
        return handler(arguments)

    def _get_printer_status(self, _args):
        if hasattr(self.device, "status_snapshot"):
            return self.device.status_snapshot()
        return {
            "connected": bool(self.device.is_connected()),
            "port": getattr(self.device, "port", None),
        }

    def _list_printers(self, _args):
        printers = self.device.list_qring_printers()
        return {"printers": printers, "count": len(printers)}

    def _connect_printer(self, args):
        port = _string(args, "port", required=True, max_length=16).upper()
        if not re.fullmatch(r"COM\d+", port):
            raise ToolCallError("port 必须是 Windows COM 端口，例如 COM3")
        printers = self.device.list_qring_printers()
        allowed_ports = {
            str(item.get("port", "")).upper()
            for item in printers if item.get("port")
        }
        if port not in allowed_ports:
            raise ToolCallError(
                "该端口不属于已配对的 Qring 打印机；请先调用 list_printers")
        current = self._get_printer_status({})
        if current.get("connected") and str(current.get("port", "")).upper() == port:
            return {"status": "connected", "port": port, "message": "打印机已连接"}
        self.device.connect(port)
        return {
            "status": "connecting",
            "port": port,
            "message": "连接已开始，请调用 get_printer_status 查询结果",
        }

    def _disconnect_printer(self, _args):
        if not self.device.is_connected():
            return {"status": "disconnected", "message": "当前没有连接的打印机"}
        self.device.disconnect()
        return {"status": "disconnecting", "message": "正在断开打印机"}

    def _print_text(self, args):
        text = _string(args, "text", required=True, max_length=5000)
        family = _string(args, "font_family", "微软雅黑", max_length=80)
        font_size = _integer(args, "font_size", 24, 8, 96)
        bold = _boolean(args, "bold", False)
        italic = _boolean(args, "italic", False)
        underline = _boolean(args, "underline", False)
        align = _string(args, "align", "left", max_length=8)
        if align not in ("left", "center", "right"):
            raise ToolCallError("align 必须是 left、center 或 right")
        char_spacing = _integer(args, "char_spacing", 0, 0, 40)
        line_spacing = _integer(args, "line_spacing", 8, 0, 80)
        margin = _integer(args, "margin", 8, 0, 30)
        threshold = _integer(args, "threshold", 200, 0, 255)
        title = _string(args, "title", None, max_length=80)
        if not title:
            compact = " ".join(text.strip().split())
            title = compact[:40] or "MCP 文字打印"

        gray = render_text_image(
            text, family, font_size, bold, italic, underline,
            char_spacing, line_spacing, margin, align)
        params = {
            "kind": "text",
            "source": "mcp",
            "text": text,
            "font_family": family,
            "font_size": font_size,
            "bold": bold,
            "italic": italic,
            "underline": underline,
            "align": align,
            "char_spacing": char_spacing,
            "line_spacing": line_spacing,
            "margin": margin,
            "threshold": threshold,
            "dither": "none",
        }
        return self._queue_print(gray, params, title, args)

    def _print_barcode(self, args):
        kind = _string(args, "kind", "QRCode", max_length=20)
        if kind not in BARCODE_KINDS:
            raise ToolCallError("不支持的条码类型")
        data = _string(args, "data", required=True, max_length=2331)
        error_correction = _string(args, "error_correction", "M", max_length=1).upper()
        if error_correction not in ("L", "M", "Q", "H"):
            raise ToolCallError("error_correction 必须是 L、M、Q 或 H")
        border = _integer(args, "border", 2, 0, 10)
        write_text = _boolean(args, "write_text", False)
        valid, message = validate_barcode(kind, data)
        if not valid:
            raise ToolCallError(message)
        gray, error = render_barcode_image(
            kind, data, error_correction, border, write_text)
        if gray is None:
            raise ToolCallError(error or "条码生成失败")
        title = _string(args, "title", None, max_length=80)
        title = title or f"{kind}: {data[:40]}"
        params = {
            "kind": "barcode",
            "source": "mcp",
            "barcode_kind": kind,
            "data": data,
            "error_correction": error_correction,
            "border": border,
            "write_text": write_text,
            "threshold": 128,
            "dither": "none",
        }
        return self._queue_print(gray, params, title, args)

    def _queue_print(self, gray, params, title, args):
        if not self.device.is_connected():
            raise ToolCallError("打印机未连接；请先调用 list_printers 和 connect_printer")
        packed, row_bytes, height, preview = prepare_bitmap(
            gray, params.get("threshold", 128), params.get("dither", "none"))
        if height > MAX_PRINT_HEIGHT:
            raise ToolCallError(
                f"打印内容过长（{height} 点）；单个任务最多 {MAX_PRINT_HEIGHT} 点")

        feed_before = _integer(
            args, "feed_before", int(self.config.get("feed_before", 10)), 0, 255)
        feed_after = _integer(
            args, "feed_after", int(self.config.get("feed_after", 100)), 0, 512)
        thickness = _integer(
            args, "thickness", int(self.config.get("thickness", 1)), 0, 7)
        job_id = uuid.uuid4().hex[:12]
        job = {
            "job_id": job_id,
            "status": "queued",
            "title": title,
            "kind": params.get("kind", "print"),
            "height_dots": height,
            "created_at": time.time(),
            "message": "打印任务已进入队列",
        }
        with self._jobs_lock:
            active = sum(1 for item in self._jobs.values()
                         if item["status"] in ("queued", "printing"))
            if active >= 5:
                raise ToolCallError("打印队列已满，请等待现有任务完成")
            self._jobs[job_id] = job
            self._trim_jobs_locked()

        def completed(ok, message):
            with self._jobs_lock:
                current = self._jobs.get(job_id)
                if current is not None:
                    current["status"] = "succeeded" if ok else "failed"
                    current["message"] = str(message)
                    current["finished_at"] = time.time()
            if ok and self.on_print_success is not None:
                try:
                    self.on_print_success(preview, params, title)
                except Exception:
                    pass

        def started():
            with self._jobs_lock:
                current = self._jobs.get(job_id)
                if current is not None:
                    current["status"] = "printing"
                    current["message"] = "正在打印"
                    current["started_at"] = time.time()

        try:
            self.device.print_job(
                packed, row_bytes, height,
                feed_before=feed_before,
                feed_after=feed_after,
                thickness=thickness,
                result_callback=completed,
                started_callback=started,
                emit_signal=False)
        except Exception as exc:
            completed(False, f"无法启动打印任务：{exc}")
            raise ToolCallError(f"无法启动打印任务：{exc}") from exc
        return self._job_snapshot(job_id)

    def _get_print_job(self, args):
        job_id = _string(args, "job_id", required=True, max_length=64)
        return self._job_snapshot(job_id)

    def _job_snapshot(self, job_id):
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ToolCallError("找不到该打印任务")
            return dict(job)

    def _trim_jobs_locked(self):
        while len(self._jobs) > MAX_TRACKED_JOBS:
            removable = next(
                (jid for jid, item in self._jobs.items()
                 if item["status"] not in ("queued", "printing")), None)
            if removable is None:
                break
            self._jobs.pop(removable, None)


class McpProtocol:
    """无会话状态的 MCP JSON-RPC 处理器。"""

    def __init__(self, agent_api, server_version="1.0.0"):
        self.agent_api = agent_api
        self.server_version = server_version

    def handle(self, request):
        if not isinstance(request, dict):
            return self.error(None, -32600, "Invalid Request")
        request_id = request.get("id")
        has_id = "id" in request
        if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            return self.error(request_id, -32600, "Invalid Request") if has_id else None
        method = request["method"]
        params = request.get("params", {})
        if not isinstance(params, dict):
            return self.error(request_id, -32602, "Invalid params") if has_id else None
        if not has_id:
            return None
        try:
            result = self._dispatch(method, params)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except KeyError as exc:
            return self.error(request_id, -32602, f"Missing parameter: {exc.args[0]}")
        except LookupError:
            return self.error(request_id, -32601, "Method not found")
        except Exception as exc:
            return self.error(request_id, -32603, f"Internal error: {exc}")

    def _dispatch(self, method, params):
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
            return {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "qrintprint-windows",
                    "title": "QrintPrint Windows",
                    "version": self.server_version,
                },
                "instructions": (
                    "Check printer state before printing. Connect a paired Qring printer "
                    "when needed, then poll get_print_job until the job finishes."
                ),
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.agent_api.list_tools()}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not name:
                raise KeyError("name")
            try:
                value = self.agent_api.call_tool(name, arguments)
                return {
                    "content": [{"type": "text", "text": _json_text(value)}],
                    "structuredContent": value,
                    "isError": False,
                }
            except ToolCallError as exc:
                return {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                }
        raise LookupError(method)

    @staticmethod
    def error(request_id, code, message):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def _origin_allowed(value):
    if not value:
        return True
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and parsed.hostname in (
        "127.0.0.1", "localhost", "::1")


def _host_allowed(value):
    if not value:
        return False
    try:
        parsed = urlsplit("//" + value)
    except ValueError:
        return False
    return parsed.hostname in ("127.0.0.1", "localhost", "::1")


class _McpHttpServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, protocol):
        self.protocol = protocol
        super().__init__(address, _McpRequestHandler)


class _McpRequestHandler(BaseHTTPRequestHandler):
    server_version = "QrintPrintMCP/1.0"
    sys_version = ""

    def log_message(self, _format, *_args):
        pass

    def do_GET(self):
        if not self._request_target_allowed():
            return
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._send_json(200, {
                "ok": True,
                "server": "qrintprint-windows",
                "endpoint": "/mcp",
            })
            return
        if path == "/mcp":
            self.send_response(405)
            self.send_header("Allow", "POST")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send_json(404, {"error": "Not found"})

    def do_OPTIONS(self):
        if not self._request_target_allowed():
            return
        origin = self.headers.get("Origin")
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Accept, MCP-Protocol-Version, Mcp-Session-Id")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "Request body too large"})
            return
        body = self.rfile.read(length)
        if not self._request_target_allowed():
            return
        if urlsplit(self.path).path.rstrip("/") != "/mcp":
            self._send_json(404, {"error": "Not found"})
            return
        origin = self.headers.get("Origin")
        content_type = self.headers.get("Content-Type", "application/json")
        if "application/json" not in content_type.lower():
            self._send_json(415, {"error": "Content-Type must be application/json"})
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(200, McpProtocol.error(None, -32700, "Parse error"))
            return
        response = self.server.protocol.handle(payload)
        if response is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send_json(200, response, origin)

    def _request_target_allowed(self):
        if not _host_allowed(self.headers.get("Host")):
            self._send_json(403, {"error": "Host not allowed"})
            return False
        if not _origin_allowed(self.headers.get("Origin")):
            self._send_json(403, {"error": "Origin not allowed"})
            return False
        return True

    def _send_json(self, status, payload, origin=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if origin and _origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)


class McpServer:
    """可由 Qt 按钮启停的本机 HTTP 服务。"""

    def __init__(self, agent_api, port=8765, server_version="1.0.0",
                 state_callback=None):
        self.agent_api = agent_api
        self.port = int(port)
        self.server_version = server_version
        self.state_callback = state_callback
        self.last_error = ""
        self._server = None
        self._thread = None
        self._lock = threading.Lock()

    @property
    def endpoint(self):
        with self._lock:
            server = self._server
            port = server.server_address[1] if server is not None else self.port
        return f"http://127.0.0.1:{port}/mcp"

    def is_running(self):
        with self._lock:
            return self._server is not None and self._thread is not None and self._thread.is_alive()

    def start(self, port=None):
        with self._lock:
            if self._server is not None:
                return True
            if port is not None:
                self.port = int(port)
            protocol = McpProtocol(self.agent_api, self.server_version)
            try:
                server = _McpHttpServer(("127.0.0.1", self.port), protocol)
            except OSError as exc:
                self.last_error = str(exc)
                callback = self.state_callback
            else:
                self.port = int(server.server_address[1])
                thread = threading.Thread(
                    target=server.serve_forever,
                    kwargs={"poll_interval": 0.2},
                    daemon=True,
                    name="qrint-mcp")
                self._server = server
                self._thread = thread
                self.last_error = ""
                callback = self.state_callback
                thread.start()
        if self._server is None:
            if callback is not None:
                callback(False, self.last_error)
            return False
        if callback is not None:
            callback(True, self.endpoint)
        return True

    def stop(self):
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        if self.state_callback is not None:
            self.state_callback(False, "MCP 服务已停止")
