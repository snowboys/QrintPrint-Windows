# -*- coding: utf-8 -*-
"""应用路径与配置持久化。"""

import json
import os
import sys


def _base_dir():
    """数据根目录：源码运行用项目目录，打包后用 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = _base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
HISTORY_PREVIEWS_DIR = os.path.join(HISTORY_DIR, "previews")
HISTORY_THUMBS_DIR = os.path.join(HISTORY_DIR, "thumbs")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")


def ensure_dirs():
    for d in (DATA_DIR, TEMPLATES_DIR, HISTORY_DIR,
              HISTORY_PREVIEWS_DIR, HISTORY_THUMBS_DIR):
        os.makedirs(d, exist_ok=True)


def resource_path(name):
    """定位只读资源（图标等）。

    onefile 打包时资源解压到 sys._MEIPASS，其次是 exe / 源码目录，
    再次是其中的 img/ 子目录。返回第一个存在的路径；都没有则返回
    BASE_DIR 下的候选路径（调用方自行判断是否存在）。
    """
    roots = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        roots.append(bundle)
    roots.append(BASE_DIR)
    for root in roots:
        for rel in (name, os.path.join("img", name)):
            path = os.path.join(root, rel)
            if os.path.exists(path):
                return path
    return os.path.join(BASE_DIR, name)


class Config:
    """简单的 JSON 配置，保存上次端口等设置。"""

    DEFAULTS = {
        "last_port": "COM3",
        "thickness": 1,          # 打印浓度（加热强度）
        "feed_before": 10,       # 打印前进纸点数
        "feed_after": 100,       # 打印后走纸点数
        "poll_interval_s": 3.0,  # 状态轮询间隔
        "auto_reconnect": True,  # 冷启动自动重连上次设备
        "mcp_port": 8765,        # 本机 MCP Streamable HTTP 端口
        "window_geometry": None,
    }

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.data = dict(self.DEFAULTS)
        try:
            with open(path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self.data.update(stored)
        except (OSError, ValueError):
            pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        ensure_dirs()
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
