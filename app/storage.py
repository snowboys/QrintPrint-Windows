# -*- coding: utf-8 -*-
"""模板与打印历史的本地持久化（JSON + PNG 缩略图）。"""

import json
import os
import time
import uuid

from .config import (HISTORY_DIR, HISTORY_PREVIEWS_DIR, HISTORY_THUMBS_DIR,
                     TEMPLATES_DIR)
from .render import flatten_white, make_thumbnail


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


class TemplateStore:
    """模板：每个模板一个 <id>.json + <id>.png 缩略图。"""

    def __init__(self, directory=TEMPLATES_DIR):
        self.dir = directory
        os.makedirs(self.dir, exist_ok=True)

    def _path(self, tid):
        return os.path.join(self.dir, tid + ".json")

    def _thumb_path(self, tid):
        return os.path.join(self.dir, tid + ".png")

    def list_templates(self):
        out = []
        for name in os.listdir(self.dir):
            if not name.endswith(".json"):
                continue
            tid = name[:-5]
            data = _read_json(self._path(tid))
            if not data:
                continue
            out.append({
                "id": tid,
                "name": data.get("name", "未命名模板"),
                "updated": data.get("updated", 0),
                "thumb": self._thumb_path(tid) if os.path.exists(
                    self._thumb_path(tid)) else None,
            })
        out.sort(key=lambda t: t["updated"], reverse=True)
        return out

    def save(self, name, canvas_data, thumb_img=None):
        """新建或覆盖同名模板，返回模板 id。"""
        existing = self.find_by_name(name)
        tid = existing["id"] if existing else uuid.uuid4().hex[:12]
        payload = {
            "id": tid,
            "name": name,
            "created": existing["created"] if existing else time.time(),
            "updated": time.time(),
            "canvas": canvas_data,
        }
        _write_json(self._path(tid), payload)
        if thumb_img is not None:
            thumb = make_thumbnail(flatten_white(thumb_img), 220)
            thumb.save(self._thumb_path(tid))
        return tid

    def find_by_name(self, name):
        for t in self.list_templates():
            if t["name"] == name:
                return t
        return None

    def load(self, tid):
        return _read_json(self._path(tid))

    def rename(self, tid, new_name):
        data = self.load(tid)
        if not data:
            return False
        data["name"] = new_name
        data["updated"] = time.time()
        _write_json(self._path(tid), data)
        return True

    def delete(self, tid):
        for p in (self._path(tid), self._thumb_path(tid)):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass


class HistoryStore:
    """打印历史：index.json 索引 + previews/<id>.png 原样预览 + thumbs/<id>.png。"""

    MAX_JOBS = 300

    def __init__(self, directory=HISTORY_DIR):
        self.dir = directory
        self.previews_dir = HISTORY_PREVIEWS_DIR
        self.thumbs_dir = HISTORY_THUMBS_DIR
        for d in (self.dir, self.previews_dir, self.thumbs_dir):
            os.makedirs(d, exist_ok=True)
        self.index_path = os.path.join(self.dir, "index.json")

    def _load_index(self):
        data = _read_json(self.index_path)
        return data if isinstance(data, list) else []

    def _save_index(self, jobs):
        _write_json(self.index_path, jobs)

    def add(self, kind, title, params, preview_img):
        """写入一条历史；返回 job dict。preview_img 为 384 宽灰度图。"""
        jid = uuid.uuid4().hex[:12]
        ts = time.time()
        preview = flatten_white(preview_img)
        preview_path = os.path.join(self.previews_dir, jid + ".png")
        thumb_path = os.path.join(self.thumbs_dir, jid + ".png")
        preview.save(preview_path)
        make_thumbnail(preview, 180).save(thumb_path)
        job = {
            "id": jid,
            "kind": kind,
            "title": title,
            "params": params,
            "ts": ts,
            "preview": preview_path,
            "thumb": thumb_path,
        }
        jobs = self._load_index()
        jobs.insert(0, job)
        for old in jobs[self.MAX_JOBS:]:
            self._remove_files(old)
        self._save_index(jobs[:self.MAX_JOBS])
        return job

    def list_jobs(self):
        jobs = self._load_index()
        jobs.sort(key=lambda j: j.get("ts", 0), reverse=True)
        return jobs

    def get(self, jid):
        for j in self.list_jobs():
            if j["id"] == jid:
                return j
        return None

    def delete(self, jid):
        jobs = self._load_index()
        kept = [j for j in jobs if j["id"] != jid]
        for j in jobs:
            if j["id"] == jid:
                self._remove_files(j)
        self._save_index(kept)

    def clear(self):
        for j in self._load_index():
            self._remove_files(j)
        self._save_index([])

    def _remove_files(self, job):
        for key in ("preview", "thumb"):
            p = job.get(key)
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
