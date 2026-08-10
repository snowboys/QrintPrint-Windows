# -*- coding: utf-8 -*-
"""QrintPrint 主窗口与各打印页签。"""

import os
import time

from PIL import Image
from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGraphicsView, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget, QFontComboBox,
)

from .canvas import (CanvasScene, CanvasView, ImageCanvasItem,
                     BarcodeCanvasItem, TextCanvasItem, render_canvas_image)
from .config import Config
from .device import DeviceManager
from .render import (BARCODE_KINDS, DITHER_ALGORITHMS, pil_to_qimage,
                     prepare_bitmap, render_barcode_image, render_text_image,
                     validate_barcode)
from .storage import HistoryStore, TemplateStore


# ---------------------------------------------------------------------------
# 通用控件
# ---------------------------------------------------------------------------

class PreviewLabel(QWidget):
    """打印预览：按比例缩放显示 384 点宽位图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qimg = None
        self._info = ""
        self.setMinimumSize(240, 240)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(235, 235, 235))
        self.setPalette(pal)

    def set_image(self, pil_img, info=""):
        self._qimg = pil_to_qimage(pil_img) if pil_img is not None else None
        self._info = info
        self.update()

    def clear(self):
        self._qimg = None
        self._info = ""
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        if self._qimg is None:
            p.setPen(QColor(160, 160, 160))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无预览")
            return
        area = self.rect().adjusted(8, 8, -8, -8)
        p.fillRect(area, QColor(255, 255, 255))
        scale = min(area.width() / self._qimg.width(),
                    area.height() / self._qimg.height())
        w = int(self._qimg.width() * scale)
        h = int(self._qimg.height() * scale)
        x = area.x() + (area.width() - w) // 2
        y = area.y() + (area.height() - h) // 2
        p.drawImage(QRectF(x, y, w, h), self._qimg)
        if self._info:
            p.setPen(QColor(120, 120, 120))
            p.drawText(QRectF(area), Qt.AlignmentFlag.AlignBottom |
                       Qt.AlignmentFlag.AlignHCenter, self._info)


class StatusLights(QWidget):
    """电量 / 缺纸 / 开盖 / 过热状态灯。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        for key, name in (("battery", "电量"), ("paper", "缺纸"),
                          ("cover", "开盖"), ("thermal", "过热")):
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(3)
            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet("background:#9e9e9e;border-radius:6px;")
            text = QLabel(name)
            bl.addWidget(dot)
            bl.addWidget(text)
            lay.addWidget(box)
            self.labels[key] = (dot, text)
        self.set_status(None, None)

    def set_status(self, problems, battery_pct):
        state = {k: None for k in self.labels}
        if problems:
            for p in problems:
                if "缺纸" in p:
                    state["paper"] = False
                if "开盖" in p or "异常" in p:
                    state["cover"] = False
                if "过热" in p:
                    state["thermal"] = False
                if "电量" in p or "低电" in p:
                    state["battery"] = False
        if battery_pct is not None:
            state["battery"] = battery_pct >= 15
        colors = {None: "#9e9e9e", True: "#3fae4f", False: "#e04a3a"}
        for key, (dot, _) in self.labels.items():
            dot.setStyleSheet(
                f"background:{colors[state[key]]};border-radius:6px;")
        if battery_pct is not None:
            self.labels["battery"][1].setText(f"电量 {battery_pct}%")
        else:
            self.labels["battery"][1].setText("电量")


# ---------------------------------------------------------------------------
# 文字打印页签
# ---------------------------------------------------------------------------

class TextTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._last_gray = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.update_preview)

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        root.addLayout(left, 3)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("在这里输入要打印的文字…\n支持多行，自动换行。")
        self.editor.setPlainText("欢迎使用 QrintPrint 小印\n热敏打印机 58mm")
        self.editor.textChanged.connect(self._schedule)
        left.addWidget(self.editor, 1)

        form = QFormLayout()
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentText("微软雅黑")
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 96)
        self.size_spin.setValue(24)
        self.bold_cb = QCheckBox("加粗")
        self.italic_cb = QCheckBox("斜体")
        self.underline_cb = QCheckBox("下划线")
        self.char_spin = QSpinBox()
        self.char_spin.setRange(0, 40)
        self.line_spin = QSpinBox()
        self.line_spin.setRange(0, 80)
        self.line_spin.setValue(8)
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 30)
        self.margin_spin.setValue(8)
        self.align_combo = QComboBox()
        self.align_combo.addItems(["左对齐", "居中", "右对齐"])

        style_row = QHBoxLayout()
        style_row.addWidget(self.bold_cb)
        style_row.addWidget(self.italic_cb)
        style_row.addWidget(self.underline_cb)
        style_row.addStretch(1)

        form.addRow("字体", self.font_combo)
        form.addRow("字号", self.size_spin)
        form.addRow("字间距", self.char_spin)
        form.addRow("行间距", self.line_spin)
        form.addRow("边距", self.margin_spin)
        form.addRow("对齐", self.align_combo)
        left.addLayout(style_row)
        left.addLayout(form)

        for w in (self.font_combo, self.size_spin, self.bold_cb, self.italic_cb,
                  self.underline_cb, self.char_spin, self.line_spin,
                  self.margin_spin, self.align_combo):
            if hasattr(w, "textChanged"):
                w.textChanged.connect(self._schedule)
            elif hasattr(w, "currentTextChanged"):
                w.currentTextChanged.connect(self._schedule)
            elif hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(self._schedule)
            elif hasattr(w, "toggled"):
                w.toggled.connect(self._schedule)
            elif hasattr(w, "valueChanged"):
                w.valueChanged.connect(self._schedule)

        right = QVBoxLayout()
        root.addLayout(right, 2)
        self.preview = PreviewLabel()
        right.addWidget(QLabel("实时预览（与实际打印一致）"))
        right.addWidget(self.preview, 1)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.print_btn = QPushButton("打印")
        self.print_btn.clicked.connect(self._print)
        btn_row.addWidget(self.print_btn)
        right.addLayout(btn_row)

    def _schedule(self):
        self._timer.start()

    def _params(self):
        align = {0: "left", 1: "center", 2: "right"}[self.align_combo.currentIndex()]
        return {
            "kind": "text",
            "threshold": 200,
            "dither": "none",
            "text": self.editor.toPlainText(),
            "font_family": self.font_combo.currentText(),
            "font_size": self.size_spin.value(),
            "bold": self.bold_cb.isChecked(),
            "italic": self.italic_cb.isChecked(),
            "underline": self.underline_cb.isChecked(),
            "char_spacing": self.char_spin.value(),
            "line_spacing": self.line_spin.value(),
            "margin": self.margin_spin.value(),
            "align": align,
        }

    def _gray(self):
        p = self._params()
        return render_text_image(
            p["text"], p["font_family"], p["font_size"], p["bold"],
            p["italic"], p["underline"], p["char_spacing"],
            p["line_spacing"], p["margin"], p["align"])

    def update_preview(self):
        try:
            gray = self._gray()
            _, _, h, preview = prepare_bitmap(gray, 200, "none")
            self._last_gray = gray
            self.preview.set_image(preview, f"384 × {h} 点")
        except Exception as exc:
            self.preview.clear()
            self.main.status_message(f"文字预览失败：{exc}")

    def _print(self):
        self.main.print_page(self._gray(), self._params(), self._title())

    def _title(self):
        t = self.editor.toPlainText().strip().replace("\n", " ")
        return (t[:20] + "…") if len(t) > 20 else (t or "文字打印")


# ---------------------------------------------------------------------------
# 图片打印页签
# ---------------------------------------------------------------------------

class ImageTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._path = ""
        self._last_gray = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.update_preview)

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.open_btn = QPushButton("打开图片…")
        self.open_btn.clicked.connect(self._open)
        self.path_label = QLabel("未选择图片")
        self.path_label.setStyleSheet("color:#777;")
        top.addWidget(self.open_btn)
        top.addWidget(self.path_label, 1)
        root.addLayout(top)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("抖动算法"))
        self.dither_combo = QComboBox()
        for key, (name, _) in DITHER_ALGORITHMS.items():
            self.dither_combo.addItem(name, key)
        self.dither_combo.currentIndexChanged.connect(self._schedule)
        opts.addWidget(self.dither_combo)
        opts.addWidget(QLabel("阈值"))
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(0, 255)
        self.threshold_slider.setValue(128)
        self.threshold_slider.setFixedWidth(160)
        self.threshold_slider.valueChanged.connect(self._schedule)
        self.threshold_label = QLabel("128")
        self.threshold_slider.valueChanged.connect(
            lambda v: self.threshold_label.setText(str(v)))
        opts.addWidget(self.threshold_slider)
        opts.addWidget(self.threshold_label)
        opts.addStretch(1)
        root.addLayout(opts)

        body = QHBoxLayout()
        self.preview = PreviewLabel()
        body.addWidget(self.preview, 1)
        right = QVBoxLayout()
        tip = QLabel("提示：\n· 透明区域按白色处理\n· 建议图片宽度 ≤ 384px\n"
                     "· 照片用 Floyd-Steinberg 效果最佳")
        tip.setStyleSheet("color:#666;")
        tip.setWordWrap(True)
        right.addWidget(tip)
        right.addStretch(1)
        self.print_btn = QPushButton("打印")
        self.print_btn.setEnabled(False)
        self.print_btn.clicked.connect(self._print)
        right.addWidget(self.print_btn)
        body.addLayout(right, 0)
        root.addLayout(body, 1)

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if path:
            self._path = path
            self.path_label.setText(os.path.basename(path))
            self.print_btn.setEnabled(True)
            self.update_preview()

    def _schedule(self):
        self._timer.start()

    def _params(self):
        return {
            "kind": "image",
            "path": self._path,
            "dither": self.dither_combo.currentData(),
            "threshold": self.threshold_slider.value(),
        }

    def _gray(self):
        if not self._path:
            return None
        img = Image.open(self._path)
        return img.convert("L") if img.mode == "L" else img

    def update_preview(self):
        gray = self._gray()
        if gray is None:
            self.preview.clear()
            return
        p = self._params()
        try:
            _, _, h, preview = prepare_bitmap(
                gray, p["threshold"], p["dither"])
            self._last_gray = gray
            self.preview.set_image(preview, f"384 × {h} 点")
        except Exception as exc:
            self.preview.clear()
            self.main.status_message(f"图片预览失败：{exc}")

    def _print(self):
        gray = self._gray()
        if gray is None:
            return
        self.main.print_page(gray, self._params(), os.path.basename(self._path))


# ---------------------------------------------------------------------------
# 条码打印页签
# ---------------------------------------------------------------------------

class BarcodeTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._gray = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(BARCODE_KINDS)
        self.kind_combo.currentIndexChanged.connect(self._schedule)
        self.content_edit = QLineEdit()
        self.content_edit.setPlaceholderText("输入条码 / 二维码内容")
        self.content_edit.setText("QrintPrint-2026")
        self.content_edit.textChanged.connect(self._schedule)
        self.ec_combo = QComboBox()
        self.ec_combo.addItems(["L", "M", "Q", "H"])
        self.ec_combo.setCurrentText("M")
        self.border_spin = QSpinBox()
        self.border_spin.setRange(0, 8)
        self.border_spin.setValue(2)
        self.text_cb = QCheckBox("一维码下方显示数字")
        self.text_cb.setChecked(True)
        for w in (self.ec_combo, self.border_spin, self.text_cb):
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._schedule)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self._schedule)
            else:
                w.valueChanged.connect(self._schedule)

        form.addRow("类型", self.kind_combo)
        form.addRow("内容", self.content_edit)
        form.addRow("纠错级别 (QR)", self.ec_combo)
        form.addRow("静区 (QR)", self.border_spin)
        form.addRow("", self.text_cb)
        root.addLayout(form)

        self.validation = QLabel("")
        self.validation.setWordWrap(True)
        root.addWidget(self.validation)

        body = QHBoxLayout()
        self.preview = PreviewLabel()
        body.addWidget(self.preview, 1)
        self.print_btn = QPushButton("打印")
        self.print_btn.clicked.connect(self._print)
        body.addWidget(self.print_btn, 0)
        root.addLayout(body, 1)

    def _params(self):
        return {
            "kind": "barcode",
            "barcode_kind": self.kind_combo.currentText(),
            "data": self.content_edit.text(),
            "error_correction": self.ec_combo.currentText(),
            "border": self.border_spin.value(),
            "write_text": self.text_cb.isChecked(),
            "dither": "none",
            "threshold": 160,
        }

    def _schedule(self):
        self._timer.start()

    def _refresh(self):
        p = self._params()
        ok, msg = validate_barcode(p["barcode_kind"], p["data"])
        if not ok:
            self.validation.setStyleSheet("color:#c0392b;")
            self.validation.setText(f"✗ {msg}")
            self.preview.clear()
            self._gray = None
            self.print_btn.setEnabled(False)
            return
        self.validation.setStyleSheet("color:#27ae60;")
        self.validation.setText(f"✓ {msg}（{p['barcode_kind']}）")
        img, err = render_barcode_image(
            p["barcode_kind"], p["data"], p["error_correction"],
            p["border"], p["write_text"])
        if err:
            self.validation.setStyleSheet("color:#c0392b;")
            self.validation.setText(f"✗ {err}")
            self._gray = None
            self.print_btn.setEnabled(False)
            return
        self._gray = img
        _, _, h, preview = prepare_bitmap(img, 160, "none")
        self.preview.set_image(preview, f"384 × {h} 点")
        self.print_btn.setEnabled(True)

    def _print(self):
        if self._gray is None:
            return
        p = self._params()
        self.main.print_page(self._gray, p,
                             f"{p['barcode_kind']}: {p['data'][:20]}")


# ---------------------------------------------------------------------------
# 自定义画布页签
# ---------------------------------------------------------------------------

class CanvasTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.scene = CanvasScene()
        self.scene.itemEditRequested.connect(self._edit_item)
        self.view = CanvasView(self.scene)

        root = QVBoxLayout(self)
        bar1 = QHBoxLayout()
        for text, slot in (
                ("添加文字", lambda: self.scene.add_text_item()),
                ("添加图片", self._add_image),
                ("添加条码", self._add_barcode),
                ("删除选中", self.scene.delete_selected),
                ("置顶", self._raise_item),
                ("置底", self._lower_item),
                ("清空", self.scene.clear)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bar1.addWidget(b)
        bar1.addStretch(1)
        root.addLayout(bar1)

        bar2 = QHBoxLayout()
        bar2.addWidget(QLabel("画布高度"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(120, 2000)
        self.height_spin.setValue(560)
        self.height_spin.setSuffix(" 点")
        self.height_btn = QPushButton("应用")
        self.height_btn.clicked.connect(
            lambda: self.scene.set_canvas_height(self.height_spin.value()))
        bar2.addWidget(self.height_spin)
        bar2.addWidget(self.height_btn)
        bar2.addWidget(QLabel("   模板"))
        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(180)
        self.save_tpl_btn = QPushButton("保存")
        self.rename_tpl_btn = QPushButton("重命名")
        self.delete_tpl_btn = QPushButton("删除")
        self.load_tpl_btn = QPushButton("加载")
        self.save_tpl_btn.clicked.connect(self._save_template)
        self.rename_tpl_btn.clicked.connect(self._rename_template)
        self.delete_tpl_btn.clicked.connect(self._delete_template)
        self.load_tpl_btn.clicked.connect(self._load_template)
        bar2.addWidget(self.template_combo)
        for b in (self.save_tpl_btn, self.rename_tpl_btn,
                  self.delete_tpl_btn, self.load_tpl_btn):
            bar2.addWidget(b)
        bar2.addStretch(1)
        root.addLayout(bar2)

        root.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.preview_label = QLabel("画布即打印预览（384 点宽）")
        self.preview_label.setStyleSheet("color:#666;")
        bottom.addWidget(self.preview_label)
        bottom.addStretch(1)
        self.print_btn = QPushButton("打印画布")
        self.print_btn.clicked.connect(self._print)
        bottom.addWidget(self.print_btn)
        root.addLayout(bottom)

        self._refresh_templates()

    # ---- 条目操作 ----

    def _add_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if path:
            self.scene.add_image_item(path)

    def _add_barcode(self):
        kind, ok = QInputDialog.getItem(
            self, "添加条码", "类型", BARCODE_KINDS, 0, False)
        if not ok:
            return
        data, ok2 = QInputDialog.getText(self, "添加条码", "内容",
                                         text="QrintPrint-2026")
        if ok2:
            self.scene.add_barcode_item(kind, data)

    def _raise_item(self):
        it = self.scene.selected_canvas_item()
        if it is not None:
            zs = [x.zValue() for x in self.scene.items()]
            it.setZValue(max(zs) + 1 if zs else 1)

    def _lower_item(self):
        it = self.scene.selected_canvas_item()
        if it is not None:
            it.setZValue(min(x.zValue() for x in self.scene.items()) - 1)

    def _edit_item(self, item):
        if isinstance(item, TextCanvasItem):
            dlg = TextEditDialog(item, self)
        elif isinstance(item, ImageCanvasItem):
            dlg = ImageEditDialog(item, self)
        elif isinstance(item, BarcodeCanvasItem):
            dlg = BarcodeEditDialog(item, self)
        else:
            return
        if dlg.exec():
            item.apply_params(dlg.result_params())
            item.update()

    # ---- 模板 ----

    def _refresh_templates(self):
        self.template_combo.clear()
        self._templates = self.main.template_store.list_templates()
        for t in self._templates:
            self.template_combo.addItem(t["name"], t["id"])

    def _current_template_id(self):
        i = self.template_combo.currentIndex()
        return self._templates[i]["id"] if 0 <= i < len(self._templates) else None

    def _save_template(self):
        name, ok = QInputDialog.getText(self, "保存模板", "模板名称")
        if not ok or not name.strip():
            return
        data = self.scene.serialize_canvas()
        thumb = render_canvas_image(self.scene)
        self.main.template_store.save(name.strip(), data, thumb)
        self._refresh_templates()
        self.main.status_message(f"模板「{name.strip()}」已保存")

    def _load_template(self):
        tid = self._current_template_id()
        if not tid:
            QMessageBox.information(self, "模板", "没有可加载的模板")
            return
        data = self.main.template_store.load(tid)
        if data:
            self.scene.load_canvas(data["canvas"])
            self.height_spin.setValue(self.scene.canvas_height)
            self.main.status_message(f"已加载模板「{data['name']}」")

    def _rename_template(self):
        tid = self._current_template_id()
        if not tid:
            return
        old = self.main.template_store.load(tid)
        name, ok = QInputDialog.getText(self, "重命名模板", "新名称",
                                        text=old["name"] if old else "")
        if ok and name.strip():
            self.main.template_store.rename(tid, name.strip())
            self._refresh_templates()

    def _delete_template(self):
        tid = self._current_template_id()
        if not tid:
            return
        if QMessageBox.question(self, "删除模板", "确定删除该模板？") == \
                QMessageBox.StandardButton.Yes:
            self.main.template_store.delete(tid)
            self._refresh_templates()

    # ---- 打印 ----

    def _print(self):
        gray = render_canvas_image(self.scene)
        self.main.print_page(
            gray,
            {"kind": "canvas", "dither": "none", "threshold": 160,
             "canvas": self.scene.serialize_canvas()},
            "自定义画布")


# ---------------------------------------------------------------------------
# 编辑对话框
# ---------------------------------------------------------------------------

class TextEditDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑文字")
        self._params = None
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(item.text)
        self.editor.setMaximumHeight(120)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentText(item.font_family)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 96)
        self.size_spin.setValue(item.font_size)
        self.bold_cb = QCheckBox("加粗")
        self.bold_cb.setChecked(item.bold)
        self.italic_cb = QCheckBox("斜体")
        self.italic_cb.setChecked(item.italic)
        self.underline_cb = QCheckBox("下划线")
        self.underline_cb.setChecked(item.underline)
        self.char_spin = QSpinBox()
        self.char_spin.setRange(0, 40)
        self.char_spin.setValue(item.char_spacing)
        self.line_spin = QSpinBox()
        self.line_spin.setRange(0, 80)
        self.line_spin.setValue(item.line_spacing)
        self.align_combo = QComboBox()
        self.align_combo.addItems(["左对齐", "居中", "右对齐"])
        self.align_combo.setCurrentIndex({"left": 0, "center": 1,
                                          "right": 2}.get(item.align, 0))
        form.addRow("文字", self.editor)
        form.addRow("字体", self.font_combo)
        form.addRow("字号", self.size_spin)
        form.addRow("样式", self._style_row())
        form.addRow("字间距", self.char_spin)
        form.addRow("行间距", self.line_spin)
        form.addRow("对齐", self.align_combo)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _style_row(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        for cb in (self.bold_cb, self.italic_cb, self.underline_cb):
            lay.addWidget(cb)
        return w

    def _accept(self):
        self._params = {
            "text": self.editor.toPlainText(),
            "font_family": self.font_combo.currentText(),
            "font_size": self.size_spin.value(),
            "bold": self.bold_cb.isChecked(),
            "italic": self.italic_cb.isChecked(),
            "underline": self.underline_cb.isChecked(),
            "char_spacing": self.char_spin.value(),
            "line_spacing": self.line_spin.value(),
            "align": {0: "left", 1: "center", 2: "right"}[
                self.align_combo.currentIndex()],
        }
        self.accept()

    def result_params(self):
        return self._params


class ImageEditDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setWindowTitle("更换图片")
        self._params = {"path": item.path}
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.path_label = QLabel(item.path or "未选择")
        btn = QPushButton("选择图片…")
        btn.clicked.connect(self._pick)
        row.addWidget(self.path_label, 1)
        row.addWidget(btn)
        lay.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if path:
            self._params["path"] = path
            self.path_label.setText(path)

    def result_params(self):
        return self._params


class BarcodeEditDialog(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑条码")
        self._params = None
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(BARCODE_KINDS)
        self.kind_combo.setCurrentText(item.barcode_kind)
        self.data_edit = QLineEdit(item.data)
        self.ec_combo = QComboBox()
        self.ec_combo.addItems(["L", "M", "Q", "H"])
        self.ec_combo.setCurrentText(item.error_correction)
        self.border_spin = QSpinBox()
        self.border_spin.setRange(0, 8)
        self.border_spin.setValue(item.border)
        self.text_cb = QCheckBox("一维码下方显示数字")
        self.text_cb.setChecked(item.write_text)
        form.addRow("类型", self.kind_combo)
        form.addRow("内容", self.data_edit)
        form.addRow("纠错级别 (QR)", self.ec_combo)
        form.addRow("静区 (QR)", self.border_spin)
        form.addRow("", self.text_cb)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _accept(self):
        kind = self.kind_combo.currentText()
        data = self.data_edit.text()
        ok, msg = validate_barcode(kind, data)
        if not ok:
            QMessageBox.warning(self, "条码校验", msg)
            return
        self._params = {
            "barcode_kind": kind,
            "data": data,
            "error_correction": self.ec_combo.currentText(),
            "border": self.border_spin.value(),
            "write_text": self.text_cb.isChecked(),
        }
        self.accept()

    def result_params(self):
        return self._params


# ---------------------------------------------------------------------------
# 打印历史页签
# ---------------------------------------------------------------------------

class HistoryTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        root = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setIconSize(QSize(140, 70))
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(lambda _: self._preview())
        root.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, slot in (("重新打印", self._reprint),
                           ("查看预览", self._preview),
                           ("删除", self._delete),
                           ("清空", self._clear)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        root.addLayout(row)

    def refresh(self):
        self.list.clear()
        for job in self.main.history_store.list_jobs():
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(job["ts"]))
            item = QListWidgetItem(f"{job['title']}\n{ts}  ·  {job['kind']}")
            thumb = job.get("thumb")
            if thumb and os.path.exists(thumb):
                item.setIcon(QPixmap(thumb))
            item.setData(Qt.ItemDataRole.UserRole, job["id"])
            self.list.addItem(item)

    def _current_job(self):
        it = self.list.currentItem()
        if it is None:
            return None
        return self.main.history_store.get(
            it.data(Qt.ItemDataRole.UserRole))

    def _reprint(self):
        job = self._current_job()
        if not job:
            return
        self.main.reprint_job(job)

    def _preview(self):
        job = self._current_job()
        if not job:
            return
        dlg = HistoryPreviewDialog(job, self.main, self)
        dlg.exec()

    def _delete(self):
        job = self._current_job()
        if not job:
            return
        if QMessageBox.question(self, "删除", "删除这条打印历史？") == \
                QMessageBox.StandardButton.Yes:
            self.main.history_store.delete(job["id"])
            self.refresh()

    def _clear(self):
        if not self.main.history_store.list_jobs():
            return
        if QMessageBox.question(self, "清空", "清空全部打印历史？") == \
                QMessageBox.StandardButton.Yes:
            self.main.history_store.clear()
            self.refresh()


class HistoryPreviewDialog(QDialog):
    def __init__(self, job, main, parent=None):
        super().__init__(parent)
        self.job = job
        self.main = main
        self.setWindowTitle(job["title"])
        self.resize(480, 620)
        lay = QVBoxLayout(self)
        self.preview = PreviewLabel()
        lay.addWidget(self.preview, 1)
        p = job.get("preview")
        if p and os.path.exists(p):
            img = Image.open(p)
            self.preview.set_image(img, f"{img.width} × {img.height} 点")
        btns = QDialogButtonBox()
        rep = btns.addButton("重新打印", QDialogButtonBox.
                             ButtonRole.AcceptRole)
        cancel = btns.addButton("关闭", QDialogButtonBox.
                                ButtonRole.RejectRole)
        rep.clicked.connect(self._reprint)
        cancel.clicked.connect(self.reject)
        lay.addWidget(btns)

    def _reprint(self):
        self.main.reprint_job(self.job)


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QrintPrint · 小印热敏打印")
        self.resize(1080, 760)

        self.config = Config()
        self.template_store = TemplateStore()
        self.history_store = HistoryStore()
        self.device = DeviceManager(self.config)

        self._build_ui()
        self._connect_device_signals()

        self._pending_print = None
        self.refresh_ports()

        QTimer.singleShot(400, self.device.auto_reconnect)

    # ---- UI 构建 ----

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        # 设备栏
        dev = QHBoxLayout()
        dev.addWidget(QLabel("蓝牙端口"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(240)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self._toggle_connect)
        self.lights = StatusLights()
        self.conn_state = QLabel("未连接")
        self.conn_state.setStyleSheet("color:#e04a3a;")
        dev.addWidget(self.port_combo)
        dev.addWidget(self.refresh_btn)
        dev.addWidget(self.connect_btn)
        dev.addSpacing(16)
        dev.addWidget(self.lights)
        dev.addSpacing(16)
        dev.addWidget(self.conn_state)
        dev.addStretch(1)

        # 打印设置
        dev.addWidget(QLabel("浓度"))
        self.thickness_spin = QSpinBox()
        self.thickness_spin.setRange(0, 7)
        self.thickness_spin.setValue(int(self.config.get("thickness", 1)))
        dev.addWidget(self.thickness_spin)
        dev.addWidget(QLabel("进纸"))
        self.feed_before_spin = QSpinBox()
        self.feed_before_spin.setRange(0, 255)
        self.feed_before_spin.setValue(int(self.config.get("feed_before", 10)))
        dev.addWidget(self.feed_before_spin)
        dev.addWidget(QLabel("出纸"))
        self.feed_after_spin = QSpinBox()
        self.feed_after_spin.setRange(0, 512)
        self.feed_after_spin.setValue(int(self.config.get("feed_after", 100)))
        dev.addWidget(self.feed_after_spin)
        root.addLayout(dev)

        # 页签
        self.tabs = QTabWidget()
        self.text_tab = TextTab(self)
        self.image_tab = ImageTab(self)
        self.barcode_tab = BarcodeTab(self)
        self.canvas_tab = CanvasTab(self)
        self.history_tab = HistoryTab(self)
        self.tabs.addTab(self.text_tab, "文字打印")
        self.tabs.addTab(self.image_tab, "图片打印")
        self.tabs.addTab(self.barcode_tab, "条码打印")
        self.tabs.addTab(self.canvas_tab, "自定义画布")
        self.tabs.addTab(self.history_tab, "打印历史")
        self.tabs.currentChanged.connect(self._tab_changed)
        root.addWidget(self.tabs, 1)

        self.statusBar().showMessage("就绪")

    def _connect_device_signals(self):
        self.device.stateChanged.connect(self._on_state)
        self.device.statusChanged.connect(self._on_status)
        self.device.message.connect(self.status_message)
        self.device.printFinished.connect(self._on_print_finished)

    # ---- 设备操作 ----

    def refresh_ports(self):
        current = self.port_combo.currentText().split(" ")[0]
        self.port_combo.clear()
        ports = DeviceManager.refresh_ports()
        if not ports:
            ports = [("COM3", "COM3 (默认)")]
        found = {p[0] for p in ports}
        for dev, label in ports:
            self.port_combo.addItem(label, dev)
        if "COM3" not in found:
            self.port_combo.addItem("COM3 (默认)", "COM3")
        idx = self.port_combo.findData(current)
        if idx < 0:
            idx = self.port_combo.findData(self.config.get("last_port", "COM3"))
        if idx >= 0:
            self.port_combo.setCurrentIndex(idx)

    def _toggle_connect(self):
        if self.device.is_connected():
            self.device.disconnect()
        else:
            port = self.port_combo.currentData()
            if port:
                self.connect_btn.setEnabled(False)
                self.device.connect(port)

    def _on_state(self, connected, port):
        self.connect_btn.setEnabled(True)
        if connected:
            self.connect_btn.setText("断开")
            self.conn_state.setText(f"已连接 {port}")
            self.conn_state.setStyleSheet("color:#3fae4f;")
        else:
            self.connect_btn.setText("连接")
            self.conn_state.setText("未连接")
            self.conn_state.setStyleSheet("color:#e04a3a;")
            self.lights.set_status(None, None)

    def _on_status(self, st):
        self.lights.set_status(st.get("problems"), st.get("battery_pct"))
        if st.get("ok") is False:
            self.conn_state.setText("故障：" + "、".join(st["problems"]))
            self.conn_state.setStyleSheet("color:#e67e22;")

    def status_message(self, msg):
        self.statusBar().showMessage(str(msg), 8000)

    def _tab_changed(self, index):
        if index == 4:  # 历史
            self.history_tab.refresh()

    # ---- 打印 ----

    def _save_settings(self):
        self.config.set("thickness", self.thickness_spin.value())
        self.config.set("feed_before", self.feed_before_spin.value())
        self.config.set("feed_after", self.feed_after_spin.value())

    def print_page(self, gray, params, title, preview_gray=None):
        """统一打印入口：灰度图 + 参数 -> 光栅 -> 打印。"""
        if gray is None:
            return
        self._save_settings()
        dither = params.get("dither", "none")
        threshold = params.get("threshold", 128)
        try:
            packed, row_bytes, height, preview = prepare_bitmap(
                gray, threshold, dither)
        except Exception as exc:
            QMessageBox.critical(self, "打印", f"生成打印数据失败：{exc}")
            return
        if not self.device.is_connected():
            QMessageBox.warning(
                self, "未连接打印机",
                "请先在顶部选择蓝牙端口并点击「连接」。\n"
                "Windows 需先在系统蓝牙中配对打印机，配对后会出现虚拟 COM 口。")
            return
        self._pending_print = (preview, params, title)
        self.status_message("正在打印…")
        self.device.print_job(
            packed, row_bytes, height,
            feed_before=self.feed_before_spin.value(),
            feed_after=self.feed_after_spin.value(),
            thickness=self.thickness_spin.value())

    def reprint_job(self, job):
        params = job.get("params", {})
        preview_path = job.get("preview")
        if not preview_path or not os.path.exists(preview_path):
            QMessageBox.warning(self, "重新打印", "该条目的预览数据已丢失")
            return
        gray = Image.open(preview_path)
        self.print_page(gray, params, job.get("title", "历史打印"))

    def _on_print_finished(self, ok, msg):
        if ok:
            self.status_message(f"打印成功：{msg}")
            if self._pending_print:
                preview, params, title = self._pending_print
                self._pending_print = None
                kind = params.get("kind", "print")
                self.history_store.add(kind, title, params, preview)
                if self.tabs.currentIndex() == 4:
                    self.history_tab.refresh()
        else:
            self.status_message(f"打印失败：{msg}")
            QMessageBox.warning(self, "打印", msg)

    def shutdown(self):
        self.device.shutdown()
