# -*- coding: utf-8 -*-
"""离屏 UI 冒烟测试：主窗口、各页签预览、画布渲染、历史列表。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from app.canvas import render_canvas_image  # noqa: E402
from app.ui import MainWindow  # noqa: E402


def main():
    w = MainWindow()
    w.show()
    app.processEvents()

    # 文字页签预览
    w.text_tab.update_preview()
    assert w.text_tab.preview._qimg is not None
    print("text preview ok", w.text_tab.preview._qimg.size())

    # 条码页签预览（含校验）
    w.barcode_tab.content_edit.setText("690123456789")
    w.barcode_tab.kind_combo.setCurrentText("EAN13")
    w.barcode_tab._refresh()
    assert w.barcode_tab.preview._qimg is not None
    assert w.barcode_tab.print_btn.isEnabled()
    print("barcode preview ok")

    # 图片页签：生成临时图并预览
    tmp = os.path.join(w.config.DATA_DIR if hasattr(w.config, "DATA_DIR")
                       else os.path.dirname(w.config.path), "smoke.png")
    img = Image.new("RGB", (300, 200), (200, 120, 40))
    img.save(tmp)
    w.image_tab._path = tmp
    w.image_tab.dither_combo.setCurrentIndex(1)  # floyd
    w.image_tab.update_preview()
    assert w.image_tab.preview._qimg is not None
    print("image preview ok")

    # 画布页签：条目 + 渲染 + 模板保存
    sc = w.canvas_tab.scene
    sc.add_text_item(30, 30, 320, 90)
    sc.add_barcode_item("QRCode", "UI-SMOKE", 30, 150, 220, 220)
    out = render_canvas_image(sc)
    assert out.width == 384
    tid = w.template_store.save("UI冒烟模板", sc.serialize_canvas(), out)
    assert w.template_store.list_templates()
    w.template_store.delete(tid)
    print("canvas ok", out.size)

    # 历史页签刷新
    w.history_tab.refresh()
    assert w.history_tab.list.count() >= 0
    print("history list ok")

    w.shutdown()
    print("UI OK")


if __name__ == "__main__":
    main()
