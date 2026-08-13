# -*- coding: utf-8 -*-

import json
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.mcp_server import McpProtocol, McpServer, QrintPrintAgentApi


class FakeConfig:
    def __init__(self):
        self.values = {"feed_before": 10, "feed_after": 100, "thickness": 1}

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeDevice:
    def __init__(self, connected=True):
        self.connected = connected
        self.port = "COM7" if connected else None
        self.started = []

    def is_connected(self):
        return self.connected

    def status_snapshot(self):
        return {
            "connected": self.connected,
            "port": self.port,
            "printing": False,
            "ok": True if self.connected else None,
            "problems": ["正常"] if self.connected else ["未连接"],
        }

    def list_qring_printers(self):
        return [{"port": "COM7", "name": "Qring_TEST", "mac": "001122334455"}]

    def connect(self, port):
        self.port = port

    def disconnect(self):
        self.connected = False

    def print_job(self, packed, row_bytes, height, **kwargs):
        self.started.append((packed, row_bytes, height, kwargs))
        if kwargs.get("started_callback"):
            kwargs["started_callback"]()

        def finish():
            time.sleep(0.01)
            kwargs["result_callback"](True, "打印完成")

        threading.Thread(target=finish, daemon=True).start()


class McpProtocolTests(unittest.TestCase):
    def setUp(self):
        self.device = FakeDevice()
        self.api = QrintPrintAgentApi(self.device, FakeConfig())
        self.protocol = McpProtocol(self.api, "test")

    def request(self, method, params=None, request_id=1):
        return self.protocol.handle({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        })

    def test_initialize_and_tool_discovery(self):
        response = self.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        })
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", response["result"]["capabilities"])

        tools = self.request("tools/list")["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(names, {
            "get_printer_status", "list_printers", "connect_printer",
            "disconnect_printer", "print_text", "print_barcode",
            "get_print_job",
        })

    def test_unknown_method_uses_json_rpc_method_not_found(self):
        response = self.request("unknown/method")
        self.assertEqual(response["error"]["code"], -32601)

    def test_tool_validation_is_returned_as_tool_error(self):
        response = self.request("tools/call", {
            "name": "connect_printer",
            "arguments": {"port": "C:/not-a-port"},
        })
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn("COM", result["content"][0]["text"])

    def test_connect_is_limited_to_discovered_qring_ports(self):
        response = self.request("tools/call", {
            "name": "connect_printer",
            "arguments": {"port": "COM8"},
        })
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn("Qring", result["content"][0]["text"])

    def test_print_text_returns_trackable_async_job(self):
        response = self.request("tools/call", {
            "name": "print_text",
            "arguments": {"text": "MCP test", "font_family": "missing-font"},
        })
        result = response["result"]
        self.assertFalse(result["isError"])
        job = result["structuredContent"]
        self.assertEqual(job["status"], "printing")
        self.assertEqual(len(self.device.started), 1)

        deadline = time.time() + 1
        while time.time() < deadline:
            query = self.request("tools/call", {
                "name": "get_print_job",
                "arguments": {"job_id": job["job_id"]},
            })["result"]["structuredContent"]
            if query["status"] == "succeeded":
                break
            time.sleep(0.01)
        self.assertEqual(query["status"], "succeeded")
        self.assertEqual(query["message"], "打印完成")


class McpHttpTests(unittest.TestCase):
    def setUp(self):
        api = QrintPrintAgentApi(FakeDevice(), FakeConfig())
        self.server = McpServer(api, port=0, server_version="test")
        self.assertTrue(self.server.start())

    def tearDown(self):
        self.server.stop()

    def post(self, payload, headers=None):
        request = Request(
            self.server.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST")
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_http_initialize_round_trip(self):
        status, response = self.post({
            "jsonrpc": "2.0",
            "id": 42,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        })
        self.assertEqual(status, 200)
        self.assertEqual(response["id"], 42)
        self.assertEqual(response["result"]["serverInfo"]["name"], "qrintprint-windows")

    def test_non_local_origin_is_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            self.post(
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"Origin": "https://example.com"})
        self.assertEqual(caught.exception.code, 403)

    def test_non_local_host_is_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            self.post(
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"Host": "printer.example.com"})
        self.assertEqual(caught.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
