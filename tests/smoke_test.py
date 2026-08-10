# -*- coding: utf-8 -*-
"""无打印机冒烟测试：渲染管线 / 画布 / 存储。"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from PIL import Image, ImageDraw  # noqa: E402

from app import render  # noqa: E402


def test_text():
    t = render.render_text_image(
        "你好 QrintPrint 小印\n加粗/斜体/下划线测试 abc123",
        font_size=24, bold=True, italic=True, underline=True,
        char_spacing=2, line_spacing=10, align="center")
    assert t.mode == "L" and t.width == 384
    print("text ok", t.size)


def test_dither():
    img = Image.new("L", (300, 220), 255)
    d = ImageDraw.Draw(img)
    d.ellipse((30, 30, 140, 140), fill=90)
    d.rectangle((160, 30, 270, 180), fill=160)
    for algo in ("none", "floyd", "ordered", "bayer"):
        packed, rb, h, prev = render.prepare_bitmap(img, 128, algo)
        assert rb == 48 and h == prev.height and len(packed) == rb * h
        print("dither", algo, "ok", h, len(packed))


def test_barcodes():
    cases = [
        ("QRCode", "https://example.com/x"),
        ("Code128", "ABC-123"),
        ("Code39", "CODE39"),
        ("EAN13", "690123456789"),
        ("EAN8", "69012345"),
        ("UPCA", "012345678905"),
        ("ITF", "123456"),
        ("Codabar", "A1234B"),
    ]
    for kind, data in cases:
        ok, msg = render.validate_barcode(kind, data)
        im, err = render.render_barcode_image(kind, data)
        assert ok and not err and im is not None, (kind, msg, err)
        print("barcode", kind, "ok", im.size)
    ok, _ = render.validate_barcode("EAN13", "123")
    assert not ok
    im, err = render.render_barcode_image("QRCode", "x" * 3000, "H")
    assert im is None and err
    print("validation negatives ok")


def test_canvas():
    from app.canvas import CanvasScene, render_canvas_image
    sc = CanvasScene()
    sc.add_text_item(30, 30, 320, 80)
    sc.add_barcode_item("QRCode", "CANVAS-TEST", 30, 140, 200, 200)
    data = sc.serialize_canvas()
    assert len(data["items"]) == 2
    sc2 = CanvasScene()
    sc2.load_canvas(data)
    assert len([i for i in sc2.items()]) == 2
    out = render_canvas_image(sc2)
    assert out.width == 384
    print("canvas ok", out.size)


def test_storage():
    from app.storage import HistoryStore, TemplateStore
    from app.canvas import CanvasScene, render_canvas_image
    ts = TemplateStore()
    sc = CanvasScene()
    sc.add_text_item(0, 0, 200, 60)
    data = sc.serialize_canvas()
    tid = ts.save("冒烟测试模板", data, render_canvas_image(sc))
    assert ts.list_templates() and ts.rename(tid, "改名模板")
    assert ts.load(tid)["name"] == "改名模板"
    hs = HistoryStore()
    job = hs.add("text", "冒烟测试历史", {"kind": "text"},
                 render_canvas_image(sc))
    assert hs.list_jobs()[0]["id"] == job["id"]
    hs.delete(job["id"])
    ts.delete(tid)
    print("storage ok")


if __name__ == "__main__":
    test_text()
    test_dither()
    test_barcodes()
    test_canvas()
    test_storage()
    print("ALL OK")
