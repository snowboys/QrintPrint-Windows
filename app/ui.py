# -*- coding: utf-8 -*-
"""QrintPrint 主窗口与各打印页签。"""

import os
import time

from PIL import Image
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGraphicsView, QGridLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QStackedWidget, QVBoxLayout,
    QWidget, QFontComboBox,
)

from . import __version__, theme
from .canvas import (CanvasScene, CanvasView, ImageCanvasItem,
                     BarcodeCanvasItem, TextCanvasItem, render_canvas_image)
from .config import Config, resource_path
from .device import DeviceManager
from .mcp_server import McpServer, QrintPrintAgentApi
from .render import (BARCODE_KINDS, DITHER_ALGORITHMS, is_1d_barcode,
                     pil_to_qimage, prepare_bitmap, render_barcode_image,
                     render_text_image, validate_barcode)
from .storage import HistoryStore, TemplateStore


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _eyebrow(text):
    """分组小标题（字距拉开的全大写风格标签）。"""
    lbl = QLabel(text)
    lbl.setObjectName("eyebrow")
    return lbl


def _divider():
    """竖向发丝分隔线。"""
    d = QFrame()
    d.setObjectName("railDivider")
    d.setFrameShape(QFrame.Shape.VLine)
    d.setFixedWidth(1)
    return d


def _field(text):
    lbl = QLabel(text)
    lbl.setObjectName("fieldLabel")
    return lbl


def _primary(button):
    button.setObjectName("primary")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _back_button(main):
    """编辑页顶部的返回首页按钮。"""
    b = QPushButton("← 返回首页")
    b.setObjectName("backBtn")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(lambda: main.show_page(0))
    return b


# ---------------------------------------------------------------------------
# 通用控件
# ---------------------------------------------------------------------------

class PreviewLabel(QWidget):
    """打印预览 —— 界面的主角：把 384 点宽位图画成一张温白色小票纸。

    小票带柔和投影与撕纸齿边，底部用等宽字体标注点阵尺寸，
    与冷灰的机器控制台形成“冷机身 / 暖纸张”的对比。
    """

    CAPTION_H = 26
    PAD = 14          # 纸张内边距
    SCALLOP = 6       # 撕纸齿半径

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qimg = None
        self._info = ""
        self.setMinimumSize(240, 240)

    def set_image(self, pil_img, info=""):
        self._qimg = pil_to_qimage(pil_img) if pil_img is not None else None
        self._info = info
        self.update()

    def clear(self):
        self._qimg = None
        self._info = ""
        self.update()

    # ---- 绘制 ----

    def _scalloped_paper(self, x, y, w, h):
        """构造带上下撕纸齿的纸张路径。"""
        r = self.SCALLOP
        path = QPainterPath()
        n = max(1, int(w // (r * 2)))
        step = w / n
        path.moveTo(x, y + r)
        # 上边缘：向下的半圆齿
        cx = x
        for i in range(n):
            path.arcTo(cx, y, step, r * 2, 180, -180)
            cx += step
        path.lineTo(x + w, y + h - r)
        # 下边缘：向上的半圆齿
        cx = x + w
        for i in range(n):
            path.arcTo(cx - step, y + h - r * 2, step, r * 2, 0, -180)
            cx -= step
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = self.rect()
        area = full.adjusted(10, 10, -10, -10 - self.CAPTION_H)

        if self._qimg is None:
            self._paint_empty(p, area)
            return

        iw, ih = self._qimg.width(), self._qimg.height()
        avail_w = area.width() - self.PAD * 2
        avail_h = area.height() - self.PAD * 2 - self.SCALLOP * 2
        if avail_w <= 0 or avail_h <= 0 or iw == 0 or ih == 0:
            return
        scale = min(avail_w / iw, avail_h / ih)
        w = max(1, int(iw * scale))
        h = max(1, int(ih * scale))
        paper_w = w + self.PAD * 2
        paper_h = h + self.PAD * 2 + self.SCALLOP * 2
        px = area.x() + (area.width() - paper_w) / 2
        py = area.y() + (area.height() - paper_h) / 2

        # 柔和投影（多层半透明模拟模糊）
        for i, alpha in ((6, 22), (3, 30), (1, 26)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(28, 36, 50, alpha))
            p.drawRoundedRect(QRectF(px - 1, py + i, paper_w + 2,
                                     paper_h), 6, 6)

        # 纸张本体（撕纸齿边）
        paper_path = self._scalloped_paper(px, py, paper_w, paper_h)
        p.setPen(QPen(QColor(theme.PAPER_EDGE), 1))
        p.setBrush(QColor(theme.PAPER))
        p.drawPath(paper_path)

        # 打印像素
        img_x = px + self.PAD
        img_y = py + self.SCALLOP + self.PAD
        p.drawImage(QRectF(img_x, img_y, w, h), self._qimg)

        # 底部等宽尺寸标注
        if self._info:
            p.setFont(theme.mono_font(9))
            p.setPen(QColor(theme.INK_FAINT))
            cap = QRectF(full.x(), full.bottom() - self.CAPTION_H,
                         full.width(), self.CAPTION_H)
            p.drawText(cap, Qt.AlignmentFlag.AlignCenter, self._info)

    def _paint_empty(self, p, area):
        pw = min(area.width() - 20, 150)
        ph = min(area.height() - 20, 240)
        if pw <= 0 or ph <= 0:
            return
        x = area.x() + (area.width() - pw) / 2
        y = area.y() + (area.height() - ph) / 2
        pen = QPen(QColor(theme.BORDER))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(QColor(theme.PAPER))
        p.drawRoundedRect(QRectF(x, y, pw, ph), 10, 10)
        p.setPen(QColor(theme.INK_FAINT))
        p.setFont(QFont(theme.ui_font_family(), 10))
        p.drawText(QRectF(x, y, pw, ph), Qt.AlignmentFlag.AlignCenter,
                   "暂无预览\n\n排版后将在此显示\n即将打印的内容")


class StatusLights(QWidget):
    """底部状态行：电量 / 纸张 / 温度三个状态芯片。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        for key, name in (("battery", "电量"), ("paper", "纸张"),
                          ("thermal", "温度")):
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(f"background:{theme.IDLE};border-radius:4px;")
            text = QLabel(name)
            text.setStyleSheet(
                f"color:{theme.INK_SOFT};font-size:12px;font-weight:600;")
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
                if "过热" in p:
                    state["thermal"] = False
                if "电量" in p or "低电" in p:
                    state["battery"] = False
        if battery_pct is not None:
            state["battery"] = battery_pct >= 15
        colors = {None: theme.IDLE, True: theme.OK, False: theme.FAULT}
        for key, (dot, _) in self.labels.items():
            dot.setStyleSheet(
                f"background:{colors[state[key]]};border-radius:4px;")
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
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(10)
        root.addLayout(left, 3)

        back_row = QHBoxLayout()
        back_row.addWidget(_back_button(main))
        back_row.addStretch(1)
        left.addLayout(back_row)

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
        right.setSpacing(10)
        root.addLayout(right, 2)
        self.preview = PreviewLabel()
        cap = QLabel("实时预览 · 与实际打印一致")
        cap.setObjectName("caption")
        right.addWidget(cap)
        right.addWidget(self.preview, 1)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.print_btn = _primary(QPushButton("打印"))
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
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(_back_button(main))
        top.addSpacing(6)
        self.open_btn = QPushButton("打开图片…")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self._open)
        self.path_label = QLabel("未选择图片")
        self.path_label.setObjectName("hint")
        top.addWidget(self.open_btn)
        top.addWidget(self.path_label, 1)
        root.addLayout(top)

        opts = QHBoxLayout()
        opts.setSpacing(10)
        opts.addWidget(_field("抖动算法"))
        self.dither_combo = QComboBox()
        for key, (name, _) in DITHER_ALGORITHMS.items():
            self.dither_combo.addItem(name, key)
        self.dither_combo.currentIndexChanged.connect(self._schedule)
        opts.addWidget(self.dither_combo)
        opts.addWidget(_field("阈值"))
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(0, 255)
        self.threshold_slider.setValue(128)
        self.threshold_slider.setFixedWidth(160)
        self.threshold_slider.valueChanged.connect(self._schedule)
        self.threshold_label = QLabel("128")
        self.threshold_label.setFont(theme.mono_font(10))
        self.threshold_label.setStyleSheet(f"color:{theme.INK};")
        self.threshold_label.setFixedWidth(30)
        self.threshold_slider.valueChanged.connect(
            lambda v: self.threshold_label.setText(str(v)))
        opts.addWidget(self.threshold_slider)
        opts.addWidget(self.threshold_label)
        opts.addStretch(1)
        root.addLayout(opts)

        body = QHBoxLayout()
        body.setSpacing(18)
        self.preview = PreviewLabel()
        body.addWidget(self.preview, 1)
        right = QVBoxLayout()
        right.setSpacing(10)
        tip = QLabel("提示\n· 透明区域按白色处理\n· 建议图片宽度 ≤ 384px\n"
                     "· 照片用 Floyd-Steinberg 效果最佳")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        right.addWidget(tip)
        right.addStretch(1)
        self.print_btn = _primary(QPushButton("打印"))
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
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        back_row = QHBoxLayout()
        back_row.addWidget(_back_button(main))
        back_row.addStretch(1)
        root.addLayout(back_row)
        form = QFormLayout()
        form.setSpacing(10)
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(BARCODE_KINDS)
        self.kind_combo.currentIndexChanged.connect(self._schedule)
        self.kind_combo.currentIndexChanged.connect(self._sync_fields)
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
        self.text_check = QCheckBox("在条码下方显示数字 / 文本")
        for w in (self.ec_combo, self.border_spin, self.text_check):
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._schedule)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self._schedule)
            else:
                w.valueChanged.connect(self._schedule)

        self.ec_row = ("纠错级别 (QR)", self.ec_combo)
        self.border_row = ("静区 (QR)", self.border_spin)
        form.addRow("类型", self.kind_combo)
        form.addRow("内容", self.content_edit)
        form.addRow(self.ec_row[0], self.ec_combo)
        form.addRow(self.border_row[0], self.border_spin)
        form.addRow("显示数字 (一维码)", self.text_check)
        root.addLayout(form)
        self._sync_fields()

        self.validation = QLabel("")
        self.validation.setWordWrap(True)
        self.validation.setFont(theme.mono_font(10))
        root.addWidget(self.validation)

        body = QHBoxLayout()
        body.setSpacing(18)
        self.preview = PreviewLabel()
        body.addWidget(self.preview, 1)
        right = QVBoxLayout()
        right.addStretch(1)
        self.print_btn = _primary(QPushButton("打印"))
        self.print_btn.clicked.connect(self._print)
        right.addWidget(self.print_btn)
        body.addLayout(right, 0)
        root.addLayout(body, 1)

    def _params(self):
        one_d = is_1d_barcode(self.kind_combo.currentText())
        return {
            "kind": "barcode",
            "barcode_kind": self.kind_combo.currentText(),
            "data": self.content_edit.text(),
            "error_correction": self.ec_combo.currentText(),
            "border": self.border_spin.value(),
            "write_text": one_d and self.text_check.isChecked(),
            "dither": "none",
            "threshold": 160,
        }

    def _sync_fields(self):
        """按类型启用/禁用 QR 专属项与一维码专属项。"""
        one_d = is_1d_barcode(self.kind_combo.currentText())
        self.ec_combo.setEnabled(not one_d)
        self.border_spin.setEnabled(not one_d)
        self.text_check.setEnabled(one_d)

    def _schedule(self):
        self._timer.start()

    def _refresh(self):
        p = self._params()
        ok, msg = validate_barcode(p["barcode_kind"], p["data"])
        if not ok:
            self.validation.setStyleSheet(f"color:{theme.FAULT};")
            self.validation.setText(f"✗ {msg}")
            self.preview.clear()
            self._gray = None
            self.print_btn.setEnabled(False)
            return
        self.validation.setStyleSheet(f"color:{theme.OK};")
        self.validation.setText(f"✓ {msg}（{p['barcode_kind']}）")
        img, err = render_barcode_image(
            p["barcode_kind"], p["data"], p["error_correction"],
            p["border"], p["write_text"])
        if err:
            self.validation.setStyleSheet(f"color:{theme.FAULT};")
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
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        bar1 = QHBoxLayout()
        bar1.setSpacing(8)
        bar1.addWidget(_back_button(main))
        bar1.addSpacing(6)
        for text, slot in (
                ("添加文字", lambda: self.scene.add_text_item()),
                ("添加图片", self._add_image),
                ("添加条码", self._add_barcode),
                ("删除选中", self.scene.delete_selected),
                ("置顶", self._raise_item),
                ("置底", self._lower_item),
                ("清空", self.scene.clear)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            bar1.addWidget(b)
        bar1.addStretch(1)
        root.addLayout(bar1)

        bar2 = QHBoxLayout()
        bar2.setSpacing(8)
        bar2.addWidget(_field("画布高度"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(120, 2000)
        self.height_spin.setValue(560)
        self.height_spin.setSuffix(" 点")
        self.height_btn = QPushButton("应用")
        self.height_btn.clicked.connect(
            lambda: self.scene.set_canvas_height(self.height_spin.value()))
        bar2.addWidget(self.height_spin)
        bar2.addWidget(self.height_btn)
        bar2.addSpacing(18)
        bar2.addWidget(_field("模板"))
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
        self.preview_label = QLabel("画布即打印预览 · 384 点宽")
        self.preview_label.setObjectName("caption")
        bottom.addWidget(self.preview_label)
        bottom.addStretch(1)
        self.print_btn = _primary(QPushButton("打印画布"))
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
        self.load_template_by_id(tid)

    def load_template_by_id(self, tid):
        """按模板 id 加载到画布，并同步模板下拉框；成功返回 True。"""
        data = self.main.template_store.load(tid)
        if not data:
            return False
        self.scene.load_canvas(data["canvas"])
        self.height_spin.setValue(self.scene.canvas_height)
        self._refresh_templates()
        idx = self.template_combo.findData(tid)
        if idx >= 0:
            self.template_combo.setCurrentIndex(idx)
        self.main.status_message(f"已加载模板「{data['name']}」")
        return True

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
        self.kind_combo.currentIndexChanged.connect(self._sync_fields)
        self.data_edit = QLineEdit(item.data)
        self.ec_combo = QComboBox()
        self.ec_combo.addItems(["L", "M", "Q", "H"])
        self.ec_combo.setCurrentText(item.error_correction)
        self.border_spin = QSpinBox()
        self.border_spin.setRange(0, 8)
        self.border_spin.setValue(item.border)
        self.text_check = QCheckBox("在条码下方显示数字 / 文本")
        self.text_check.setChecked(bool(getattr(item, "write_text", False)))
        form.addRow("类型", self.kind_combo)
        form.addRow("内容", self.data_edit)
        form.addRow("纠错级别 (QR)", self.ec_combo)
        form.addRow("静区 (QR)", self.border_spin)
        form.addRow("显示数字 (一维码)", self.text_check)
        lay.addLayout(form)
        self._sync_fields()
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
            "write_text": is_1d_barcode(kind) and self.text_check.isChecked(),
        }
        self.accept()

    def _sync_fields(self):
        one_d = is_1d_barcode(self.kind_combo.currentText())
        self.ec_combo.setEnabled(not one_d)
        self.border_spin.setEnabled(not one_d)
        self.text_check.setEnabled(one_d)

    def result_params(self):
        return self._params


class PrinterPickerDialog(QDialog):
    """选择打印机：只列出名称以 “Qring” 开头的已配对蓝牙设备。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择打印机")
        self.setMinimumWidth(420)
        self._port = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(8)
        hint = QLabel("从已配对的蓝牙设备中选择你的 Qring 打印机")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._reload)
        head.addWidget(hint, 1)
        head.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)

        self.list = QListWidget()
        self.list.setMinimumHeight(180)
        self.list.itemSelectionChanged.connect(self._sync_ok)
        self.list.itemDoubleClicked.connect(self._on_double)
        root.addWidget(self.list, 1)

        self.empty = QLabel("")
        self.empty.setObjectName("hint")
        self.empty.setWordWrap(True)
        self.empty.hide()
        root.addWidget(self.empty)

        self.btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                     QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = self.btns.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setText("连接")
        _primary(self.ok_btn)
        self.btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.btns.accepted.connect(self._accept)
        self.btns.rejected.connect(self.reject)
        root.addWidget(self.btns)

        self._reload()

    def _reload(self):
        self.list.clear()
        printers = DeviceManager.list_qring_printers()
        for p in printers:
            has_port = bool(p.get("port"))
            sub = p["port"] if has_port else "未生成串口（请在系统蓝牙中重新连接）"
            item = QListWidgetItem(f"{p['name']}\n{sub}")
            item.setData(Qt.ItemDataRole.UserRole, p.get("port"))
            if not has_port:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setForeground(QColor(theme.INK_FAINT))
            self.list.addItem(item)

        if self.list.count() == 0:
            self.empty.setText(
                "未发现 Qring 打印机。\n请先在 Windows「蓝牙和其他设备」中"
                "配对打印机，然后点「刷新」。")
            self.empty.show()
        else:
            self.empty.hide()
            # 默认选中第一个可用项
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.flags() & Qt.ItemFlag.ItemIsEnabled:
                    self.list.setCurrentRow(i)
                    break
        self._sync_ok()

    def _current_port(self):
        it = self.list.currentItem()
        if it is None or not (it.flags() & Qt.ItemFlag.ItemIsEnabled):
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def _sync_ok(self):
        self.ok_btn.setEnabled(self._current_port() is not None)

    def _on_double(self, item):
        if item.flags() & Qt.ItemFlag.ItemIsEnabled:
            self._accept()

    def _accept(self):
        port = self._current_port()
        if not port:
            return
        self._port = port
        self.accept()

    def selected_port(self):
        return self._port


# ---------------------------------------------------------------------------
# 打印历史页签
# ---------------------------------------------------------------------------

class HistoryTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        self.list = QListWidget()
        self.list.setIconSize(QSize(140, 70))
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(lambda _: self._preview())
        root.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, slot in (("重新打印", self._reprint),
                           ("查看预览", self._preview),
                           ("删除", self._delete),
                           ("清空", self._clear)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
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
        rep.setObjectName("primary")
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

# ---------------------------------------------------------------------------
# 首页：连接卡片 + 功能入口 + 状态行
# ---------------------------------------------------------------------------

class ConnectCard(QFrame):
    """大号可点击连接卡片：打印机图标 + 状态标题 + 引导副标题 + 状态胶囊。"""

    clicked = Signal()

    _PILL_STYLES = {
        "off":   (theme.INSET_DEEP, theme.INK_SOFT),
        "ok":    (theme.ACCENT_SOFT, theme.ACCENT_STRONG),
        "warn":  ("#FBE7E3", theme.FAULT),
        "amber": ("#FBEFD9", theme.WARN),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("connectCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(88)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 16)
        lay.setSpacing(16)

        self.icon = QLabel("🖨")
        self.icon.setObjectName("connIcon")
        self.icon.setFixedSize(46, 46)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        txt = QVBoxLayout()
        txt.setSpacing(4)
        self.title = QLabel("未连接打印机")
        self.title.setObjectName("cardTitle")
        self.sub = QLabel("点击选择打印机")
        self.sub.setObjectName("cardSub")
        txt.addWidget(self.title)
        txt.addWidget(self.sub)

        self.pill = QLabel("未连接")
        self.pill.setObjectName("connPill")

        lay.addWidget(self.icon)
        lay.addLayout(txt, 1)
        lay.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()

    def set_state(self, kind, title, sub, pill_text):
        self.title.setText(title)
        self.sub.setText(sub)
        self.set_pill(kind, pill_text)

    def set_pill(self, kind, text):
        bg, fg = self._PILL_STYLES.get(kind, self._PILL_STYLES["off"])
        self.pill.setStyleSheet(
            f"QLabel#connPill{{background:{bg};color:{fg};border-radius:12px;"
            f"padding:5px 14px;font-size:12px;font-weight:700;}}")
        self.pill.setText(text)


class TileCard(QFrame):
    """首页功能入口卡片：图标 + 标题 + 小字说明。"""

    clicked = Signal()

    def __init__(self, icon, title, subtitle, parent=None):
        super().__init__(parent)
        self.setObjectName("homeTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(150, 108)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(5)
        self.icon = QLabel(icon)
        self.icon.setObjectName("tileIcon")
        self.title = QLabel(title)
        self.title.setObjectName("tileTitle")
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("tileSub")
        v.addWidget(self.icon)
        v.addWidget(self.title)
        v.addWidget(self.sub)
        v.addStretch(1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()


class HomeTab(QWidget):
    """首页：连接卡片 + 四个功能入口 + 底部状态行。"""

    def __init__(self, main):
        super().__init__()
        self.main = main

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(16)

        self.connect_card = ConnectCard()
        self.connect_card.clicked.connect(main._on_connect_clicked)
        root.addWidget(self.connect_card)

        grid = QGridLayout()
        grid.setSpacing(14)
        tiles = [
            # (图标, 标题, 小字, 打开的编辑页)
            ("🖼", "图片打印", "选择图片", 5),
            ("📝", "文字打印", "TXT文本", 4),
            ("▮▮▮", "打印条码", "条形码/二维码", 6),
            ("🛠", "自定义打印", "高级设置", 7),
        ]
        for i, (icon, title, sub, page) in enumerate(tiles):
            card = TileCard(icon, title, sub)
            card.clicked.connect(lambda _=False, idx=page: main.open_editor(idx))
            grid.addWidget(card, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid, 1)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_row.addWidget(_eyebrow("设备状态"))
        status_row.addSpacing(6)
        self.lights = StatusLights()
        status_row.addWidget(self.lights)
        status_row.addStretch(1)
        root.addLayout(status_row)


class TemplateTab(QWidget):
    """模板：展示「自定义打印」保存的模板列表，可打开编辑 / 重命名 / 删除。"""

    def __init__(self, main):
        super().__init__()
        self.main = main

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        self.list = QListWidget()
        self.list.setIconSize(QSize(140, 70))
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(lambda _: self._open_current())
        root.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        for text, slot in (("打开编辑", self._open_current),
                           ("重命名", self._rename),
                           ("删除", self._delete)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        root.addLayout(row)

    def refresh(self):
        self.list.clear()
        for t in self.main.template_store.list_templates():
            ts = time.strftime("%Y-%m-%d %H:%M",
                               time.localtime(t["updated"]))
            item = QListWidgetItem(f"{t['name']}\n{ts}")
            thumb = t.get("thumb")
            if thumb and os.path.exists(thumb):
                item.setIcon(QPixmap(thumb))
            item.setData(Qt.ItemDataRole.UserRole, t["id"])
            self.list.addItem(item)
        if self.list.count() == 0:
            hint = QListWidgetItem(
                "还没有模板\n在「自定义打印」里排版内容并点「保存」，"
                "模板会出现在这里")
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            hint.setForeground(QColor(theme.INK_FAINT))
            self.list.addItem(hint)

    def _current_tid(self):
        it = self.list.currentItem()
        if it is None:
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def _open_current(self):
        tid = self._current_tid()
        if not tid:
            QMessageBox.information(self, "模板", "请先选择一个模板")
            return
        if self.main.canvas_tab.load_template_by_id(tid):
            self.main.show_page(7)

    def _rename(self):
        tid = self._current_tid()
        if not tid:
            return
        old = self.main.template_store.load(tid)
        name, ok = QInputDialog.getText(self, "重命名模板", "新名称",
                                        text=old["name"] if old else "")
        if ok and name.strip():
            self.main.template_store.rename(tid, name.strip())
            self.refresh()

    def _delete(self):
        tid = self._current_tid()
        if not tid:
            return
        if QMessageBox.question(self, "删除模板",
                                "确定删除该模板？") == \
                QMessageBox.StandardButton.Yes:
            self.main.template_store.delete(tid)
            self.refresh()


class MyTab(QWidget):
    """我的：设备信息 + 打印设置。"""

    def __init__(self, main):
        super().__init__()
        self.main = main

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(16)

        info_box = QGroupBox("设备信息")
        form = QFormLayout(info_box)
        form.setSpacing(12)
        self.device_name = QLabel("—")
        self.device_model = QLabel("—")
        self.device_status = QLabel("未连接")
        form.addRow(_field("设备名称"), self.device_name)
        form.addRow(_field("设备型号"), self.device_model)
        form.addRow(_field("连接状态"), self.device_status)
        root.addWidget(info_box)

        set_box = QGroupBox("打印设置")
        sform = QFormLayout(set_box)
        sform.setSpacing(12)
        self.thickness_spin = QSpinBox()
        self.thickness_spin.setRange(0, 7)
        self.thickness_spin.setValue(int(main.config.get("thickness", 1)))
        self.feed_before_spin = QSpinBox()
        self.feed_before_spin.setRange(0, 255)
        self.feed_before_spin.setValue(int(main.config.get("feed_before", 10)))
        self.feed_after_spin = QSpinBox()
        self.feed_after_spin.setRange(0, 512)
        self.feed_after_spin.setValue(int(main.config.get("feed_after", 100)))
        sform.addRow(_field("浓度"), self.thickness_spin)
        sform.addRow(_field("进纸"), self.feed_before_spin)
        sform.addRow(_field("出纸"), self.feed_after_spin)
        root.addWidget(set_box)
        root.addStretch(1)

        # 版本与作者
        foot = QVBoxLayout()
        foot.setSpacing(2)
        self.version_label = QLabel(f"版本 {__version__}")
        self.version_label.setStyleSheet(
            f"color:{theme.INK_FAINT};font-size:12px;font-weight:600;")
        self.author_label = QLabel(
            '<a style="color:%s;text-decoration:none;" '
            'href="https://github.com/snowboys/QrintPrint-Windows">'
            "snowboys · GitHub</a>" % theme.ACCENT)
        self.author_label.setOpenExternalLinks(True)
        self.author_label.setStyleSheet("font-size:12px;")
        foot.addWidget(self.version_label)
        foot.addWidget(self.author_label)
        root.addLayout(foot)

    def set_device(self, name, model, status, connected):
        self.device_name.setText(name or "—")
        self.device_model.setText(model or "—")
        self.device_status.setText(status or "未连接")
        self.device_status.setStyleSheet(
            f"color:{theme.OK if connected else theme.INK_SOFT};"
            f"font-weight:700;")


class McpDialog(QDialog):
    """MCP 本地服务控制与客户端配置。"""

    def __init__(self, main, parent=None):
        super().__init__(parent or main)
        self.main = main
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("MCP Agent 接入")
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        head = QHBoxLayout()
        title = QLabel("MCP Agent 接入")
        title.setStyleSheet(
            f"color:{theme.INK};font-size:17px;font-weight:800;")
        self.state_label = QLabel()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.state_label)
        root.addLayout(head)

        form = QFormLayout()
        form.setSpacing(12)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(int(main.config.get("mcp_port", 8765)))
        self.port_spin.valueChanged.connect(self._port_changed)
        self.endpoint_edit = QLineEdit()
        self.endpoint_edit.setReadOnly(True)
        self.endpoint_edit.setText(main.mcp_server.endpoint)
        bind_label = QLabel("127.0.0.1 · 仅本机")
        bind_label.setStyleSheet(f"color:{theme.INK_SOFT};")
        form.addRow(_field("监听端口"), self.port_spin)
        form.addRow(_field("MCP 端点"), self.endpoint_edit)
        form.addRow(_field("访问范围"), bind_label)
        root.addLayout(form)

        copy_row = QHBoxLayout()
        self.copy_endpoint_btn = QPushButton("复制端点")
        self.copy_config_btn = QPushButton("复制 Codex 配置")
        self.copy_endpoint_btn.clicked.connect(self._copy_endpoint)
        self.copy_config_btn.clicked.connect(self._copy_codex_config)
        copy_row.addWidget(self.copy_endpoint_btn)
        copy_row.addWidget(self.copy_config_btn)
        copy_row.addStretch(1)
        root.addLayout(copy_row)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        self.toggle_btn = QPushButton()
        self.toggle_btn.clicked.connect(self._toggle)
        actions.addWidget(close_btn)
        actions.addWidget(self.toggle_btn)
        root.addLayout(actions)

        main.mcpStateChanged.connect(self._on_state_changed)
        self._refresh()

    def _refresh(self):
        running = self.main.mcp_server.is_running()
        self.endpoint_edit.setText(self.main.mcp_server.endpoint)
        self.port_spin.setEnabled(not running)
        self.toggle_btn.setText("停止 MCP" if running else "启动 MCP")
        self.toggle_btn.setObjectName("" if running else "primary")
        self.toggle_btn.style().unpolish(self.toggle_btn)
        self.toggle_btn.style().polish(self.toggle_btn)
        if running:
            self.state_label.setText("● 运行中")
            self.state_label.setStyleSheet(
                f"color:{theme.OK};font-size:12px;font-weight:700;")
        else:
            self.state_label.setText("● 已停止")
            self.state_label.setStyleSheet(
                f"color:{theme.INK_FAINT};font-size:12px;font-weight:700;")

    def _toggle(self):
        if self.main.mcp_server.is_running():
            self.main.mcp_server.stop()
            self._refresh()
            return
        port = self.port_spin.value()
        self.main.config.set("mcp_port", port)
        if not self.main.mcp_server.start(port):
            QMessageBox.critical(
                self, "MCP 启动失败",
                "无法启动本地 MCP 服务：\n" + self.main.mcp_server.last_error)
        self._refresh()

    def _port_changed(self, port):
        if self.main.mcp_server.is_running():
            return
        self.main.mcp_server.port = int(port)
        self.endpoint_edit.setText(self.main.mcp_server.endpoint)

    def _copy_endpoint(self):
        QApplication.clipboard().setText(self.main.mcp_server.endpoint)
        self.main.status_message("MCP 端点已复制")

    def _copy_codex_config(self):
        endpoint = self.main.mcp_server.endpoint
        config = (
            "[mcp_servers.qrintprint]\n"
            f'url = "{endpoint}"\n'
            'default_tools_approval_mode = "writes"\n'
            "tool_timeout_sec = 180\n")
        QApplication.clipboard().setText(config)
        self.main.status_message("Codex MCP 配置已复制")

    def _on_state_changed(self, _running, _detail):
        self._refresh()


class MainWindow(QMainWindow):
    mcpStateChanged = Signal(bool, str)
    mcpPrintSucceeded = Signal(object, object, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("错题小印 · Qring Printer")
        self.resize(1080, 760)
        self.setMinimumSize(940, 620)

        self.config = Config()
        self.template_store = TemplateStore()
        self.history_store = HistoryStore()
        self.device = DeviceManager(self.config)
        self.mcp_api = QrintPrintAgentApi(
            self.device, self.config,
            on_print_success=lambda preview, params, title:
                self.mcpPrintSucceeded.emit(preview, params, title))
        self.mcp_server = McpServer(
            self.mcp_api,
            port=int(self.config.get("mcp_port", 8765)),
            server_version=__version__,
            state_callback=lambda running, detail:
                self.mcpStateChanged.emit(running, detail))

        self._build_ui()
        self._connect_device_signals()
        self.mcpStateChanged.connect(self._on_mcp_state)
        self.mcpPrintSucceeded.connect(self._record_mcp_print)

        self._pending_print = None
        self._printers = []          # 最近一次扫描到的 Qring 设备
        self._prime_printer_cache()

        QTimer.singleShot(400, self.device.auto_reconnect)

    # ---- UI 构建 ----

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        root.addWidget(self._build_header())

        self.pages = QStackedWidget()
        self.home_tab = HomeTab(self)
        self.template_tab = TemplateTab(self)
        self.history_tab = HistoryTab(self)
        self.my_tab = MyTab(self)
        self.text_tab = TextTab(self)
        self.image_tab = ImageTab(self)
        self.barcode_tab = BarcodeTab(self)
        self.canvas_tab = CanvasTab(self)

        # 0 首页 / 1 模板 / 2 历史 / 3 我的 / 4-7 各编辑页
        for w in (self.home_tab, self.template_tab, self.history_tab,
                  self.my_tab, self.text_tab, self.image_tab,
                  self.barcode_tab, self.canvas_tab):
            self.pages.addWidget(w)
        root.addWidget(self.pages, 1)

        # 打印参数与设备状态引用（我的页 / 首页）
        self.thickness_spin = self.my_tab.thickness_spin
        self.feed_before_spin = self.my_tab.feed_before_spin
        self.feed_after_spin = self.my_tab.feed_after_spin
        self.lights = self.home_tab.lights
        self.connect_card = self.home_tab.connect_card

        self.pages.setCurrentIndex(0)

        self.statusBar().showMessage("就绪")

    def _build_header(self):
        """顶栏：品牌（错题小印 / Qring Printer）+ 主导航。"""
        head = QFrame()
        head.setObjectName("headerBar")
        lay = QHBoxLayout(head)
        lay.setContentsMargins(18, 10, 18, 10)
        lay.setSpacing(14)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        pix = QPixmap(resource_path("QrintPrint.ico"))
        if not pix.isNull():
            logo.setPixmap(pix.scaled(
                30, 30, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        bv = QVBoxLayout()
        bv.setSpacing(0)
        self.brand_title = QLabel("错题小印")
        self.brand_title.setObjectName("brandTitle")
        self.brand_sub = QLabel("Qring Printer")
        self.brand_sub.setObjectName("brandSub")
        bv.addWidget(self.brand_title)
        bv.addWidget(self.brand_sub)
        brand.addWidget(logo)
        brand.addLayout(bv)
        lay.addLayout(brand)
        lay.addStretch(1)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        for i, text in enumerate(("首页", "模板", "历史", "我的")):
            b = QPushButton(text)
            b.setObjectName("navTab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.show_page(idx))
            self.nav_group.addButton(b, i)
            self.nav_buttons.append(b)
            lay.addWidget(b)
        self.nav_buttons[0].setChecked(True)
        lay.addSpacing(4)
        self.mcp_btn = QPushButton("MCP")
        self.mcp_btn.setObjectName("mcpButton")
        self.mcp_btn.setProperty("running", False)
        self.mcp_btn.setFixedWidth(64)
        self.mcp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mcp_btn.setToolTip("管理 AI agent 的 MCP 接入")
        self.mcp_btn.clicked.connect(self._open_mcp_dialog)
        lay.addWidget(self.mcp_btn)
        return head

    def _open_mcp_dialog(self):
        McpDialog(self, self).exec()

    def _on_mcp_state(self, running, detail):
        self.mcp_btn.setProperty("running", bool(running))
        self.mcp_btn.setToolTip(
            f"MCP 运行中 · {self.mcp_server.endpoint}"
            if running else "管理 AI agent 的 MCP 接入")
        self.mcp_btn.style().unpolish(self.mcp_btn)
        self.mcp_btn.style().polish(self.mcp_btn)
        if detail:
            self.status_message(detail)

    def show_page(self, index):
        """切换主页面；首页/模板/历史/我的同步导航选中态。"""
        self.pages.setCurrentIndex(index)
        for b in self.nav_buttons:
            b.setChecked(False)
        if index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        if index == 1:  # 模板
            self.template_tab.refresh()
        if index == 2:  # 历史
            self.history_tab.refresh()

    def open_editor(self, index):
        """从首页入口打开对应编辑页。"""
        self.show_page(index)

    def _connect_device_signals(self):
        self.device.stateChanged.connect(self._on_state)
        self.device.statusChanged.connect(self._on_status)
        self.device.message.connect(self.status_message)
        self.device.printFinished.connect(self._on_print_finished)

    # ---- 设备操作 ----

    def _prime_printer_cache(self):
        """后台记录一次已配对 Qring 设备，供状态胶囊反查设备名。"""
        try:
            self._printers = DeviceManager.list_qring_printers()
        except Exception:
            self._printers = []

    def _port_name(self, port):
        """由 COM 口反查 Qring 设备名；查不到则返回原始 port。"""
        for p in self._printers:
            if p.get("port") and p["port"] == port:
                return p["name"]
        return port or ""

    def _on_connect_clicked(self):
        if self.device.is_connected():
            self.device.disconnect()
        else:
            self._open_printer_picker()

    def _open_printer_picker(self):
        dlg = PrinterPickerDialog(self)
        # 弹窗内可能刷新过列表，同步到主窗缓存
        if dlg.exec():
            self._printers = DeviceManager.list_qring_printers()
            port = dlg.selected_port()
            if port:
                self.device.connect(port)

    def _toggle_connect(self):
        # 兼容旧调用（自动重连失败重试等）
        self._on_connect_clicked()

    def _on_state(self, connected, port):
        if connected:
            name = self._port_name(port) or port
            self.connect_card.set_state(
                "ok", name, "点击切换设备", "已连接")
            self.my_tab.set_device(name, "Qring 热敏打印机", "已连接", True)
        else:
            self.connect_card.set_state(
                "off", "未连接打印机", "点击选择打印机", "未连接")
            self.lights.set_status(None, None)
            self.my_tab.set_device("—", "—", "未连接", False)

    def _on_status(self, st):
        self.lights.set_status(st.get("problems"), st.get("battery_pct"))
        if st.get("ok") is False:
            self.connect_card.set_pill(
                "warn", "⚠ " + "、".join(st["problems"]))

    def status_message(self, msg):
        self.statusBar().showMessage(str(msg), 8000)

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
                if self.pages.currentIndex() == 2:
                    self.history_tab.refresh()
        else:
            self.status_message(f"打印失败：{msg}")
            QMessageBox.warning(self, "打印", msg)

    def _record_mcp_print(self, preview, params, title):
        """MCP 打印完成后在 Qt 主线程写入历史。"""
        self.history_store.add(
            params.get("kind", "print"), title, params, preview)
        self.status_message(f"MCP 打印成功：{title}")
        if self.pages.currentIndex() == 2:
            self.history_tab.refresh()

    def shutdown(self):
        self.mcp_server.stop()
        self.device.shutdown()
