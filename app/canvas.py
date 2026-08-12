# -*- coding: utf-8 -*-
"""
自定义画布：384 点宽的 QGraphicsScene。
条目支持拖拽移动、8 向手柄缩放、双击编辑，可序列化为模板。
"""

import os

from PIL import Image
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (QGraphicsRectItem, QGraphicsScene,
                               QGraphicsItem, QGraphicsView)

from .render import (WIDTH, flatten_white, render_barcode_image,
                     render_text_image)


SCENE_W = WIDTH
SCENE_H_DEFAULT = 560
HANDLE = 8          # 手柄边长（点）
MIN_W = 16
MIN_H = 12


class CanvasItem(QGraphicsRectItem):
    """画布条目基类：拖拽 + 8 向缩放手柄 + 选中描边。"""

    kind = "base"

    HANDLE_POS = [
        ("l", "t"), ("c", "t"), ("r", "t"),
        ("r", "c"), ("r", "b"), ("c", "b"),
        ("l", "b"), ("l", "c"),
    ]

    def __init__(self, x, y, w, h):
        super().__init__(0, 0, max(MIN_W, w), max(MIN_H, h))
        self.setPos(x, y)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setZValue(0)
        self._resize_start = None
        self._resize_handle = None

    # ---- 几何约束 ----

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            x = max(0.0, min(SCENE_W - self.rect().width(), value.x()))
            y = max(0.0, value.y())
            value.setX(x)
            value.setY(y)
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.update()
        return super().itemChange(change, value)

    # ---- 内容 ----

    def content_image(self):
        """渲染条目内容为白底灰度图。"""
        raise NotImplementedError

    def draw_content(self, painter, rect):
        img = self.content_image()
        if img is None:
            return
        img = flatten_white(img)
        scale = min(rect.width() / img.width, rect.height() / img.height)
        w = max(1, int(img.width * scale))
        h = max(1, int(img.height * scale))
        img = img.resize((w, h), Image.LANCZOS)
        from .render import pil_to_qimage
        painter.drawImage(QRectF(rect.x() + (rect.width() - w) / 2,
                                 rect.y() + (rect.height() - h) / 2, w, h),
                          pil_to_qimage(img))

    # ---- 绘制 ----

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(QColor(215, 219, 227), 1))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawRect(self.rect())
        self.draw_content(painter, self.rect())
        if self.isSelected():
            accent = QColor(75, 71, 196)  # theme.ACCENT
            painter.setPen(QPen(accent, 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
            painter.setBrush(QBrush(accent))
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            for hx, hy in self._handle_centers():
                painter.drawRect(QRectF(hx - HANDLE / 2, hy - HANDLE / 2,
                                        HANDLE, HANDLE))

    def _handle_centers(self):
        r = self.rect()
        xs = {"l": r.x(), "c": r.x() + r.width() / 2, "r": r.x() + r.width()}
        ys = {"t": r.y(), "c": r.y() + r.height() / 2, "b": r.y() + r.height()}
        return [(xs[hx], ys[hy]) for hx, hy in self.HANDLE_POS]

    def _handle_at(self, pos):
        if not self.isSelected():
            return None
        for i, (cx, cy) in enumerate(self._handle_centers()):
            if abs(pos.x() - cx) <= HANDLE and abs(pos.y() - cy) <= HANDLE:
                return i
        return None

    # ---- 鼠标事件 ----

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            h = self._handle_at(event.pos())
            if h is not None:
                self._resize_handle = h
                self._resize_start = (event.scenePos(), self.rect())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_handle is not None and self._resize_start:
            origin, start_rect = self._resize_start
            dx = event.scenePos().x() - origin.x()
            dy = event.scenePos().y() - origin.y()
            self._apply_resize(start_rect, self._resize_handle, dx, dy)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resize_handle = None
        self._resize_start = None
        super().mouseReleaseEvent(event)

    def _apply_resize(self, r, handle, dx, dy):
        hx, hy = self.HANDLE_POS[handle]
        x0, y0, x1, y1 = r.x(), r.y(), r.x() + r.width(), r.y() + r.height()
        scene_h = self.scene().canvas_height if self.scene() else 1e6
        if "l" in hx:
            x0 = min(x1 - MIN_W, x0 + dx)
        if "r" in hx:
            x1 = max(x0 + MIN_W, min(SCENE_W, x1 + dx))
        if "t" in hy:
            y0 = min(y1 - MIN_H, y0 + dy)
        if "b" in hy:
            y1 = max(y0 + MIN_H, min(scene_h, y1 + dy))
        x0 = max(0.0, x0)
        y0 = max(0.0, y0)
        self.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))

    def mouseDoubleClickEvent(self, event):
        scene = self.scene()
        if scene is not None:
            scene.itemEditRequested.emit(self)
            event.accept()

    # ---- 序列化 ----

    def serialize(self):
        r = self.rect()
        d = {"kind": self.kind, "x": r.x(), "y": r.y(),
             "w": r.width(), "h": r.height(), "z": self.zValue()}
        self._serialize_body(d)
        return d

    def _serialize_body(self, d):
        pass

    def apply_params(self, d):
        raise NotImplementedError

    @classmethod
    def from_dict(cls, d):
        item = cls(d["x"], d["y"], d["w"], d["h"])
        item.setZValue(d.get("z", 0))
        item.apply_params(d)
        return item


class TextCanvasItem(CanvasItem):
    kind = "text"

    def __init__(self, x, y, w, h):
        super().__init__(x, y, w, h)
        self.text = "双击编辑文字"
        self.font_family = "微软雅黑"
        self.font_size = 20
        self.bold = False
        self.italic = False
        self.underline = False
        self.char_spacing = 0
        self.line_spacing = 6
        self.align = "left"

    def content_image(self):
        return render_text_image(
            self.text, self.font_family, self.font_size, self.bold,
            self.italic, self.underline, self.char_spacing,
            self.line_spacing, margin=4, align=self.align,
            max_width=max(8, int(self.rect().width())))

    def _serialize_body(self, d):
        d.update(text=self.text, font_family=self.font_family,
                 font_size=self.font_size, bold=self.bold, italic=self.italic,
                 underline=self.underline, char_spacing=self.char_spacing,
                 line_spacing=self.line_spacing, align=self.align)

    def apply_params(self, d):
        for k in ("text", "font_family", "font_size", "bold", "italic",
                  "underline", "char_spacing", "line_spacing", "align"):
            if k in d:
                setattr(self, k, d[k])


class ImageCanvasItem(CanvasItem):
    kind = "image"

    def __init__(self, x, y, w, h):
        super().__init__(x, y, w, h)
        self.path = ""
        self._img = None

    def set_image_path(self, path):
        self.path = path
        self._img = None

    def content_image(self):
        if self._img is None and self.path and os.path.exists(self.path):
            try:
                self._img = Image.open(self.path)
            except OSError:
                self._img = None
        if self._img is None:
            img = Image.new("L", (80, 40), 230)
            return img
        return self._img

    def _serialize_body(self, d):
        d["path"] = self.path

    def apply_params(self, d):
        self.set_image_path(d.get("path", ""))


class BarcodeCanvasItem(CanvasItem):
    kind = "barcode"

    def __init__(self, x, y, w, h):
        super().__init__(x, y, w, h)
        self.barcode_kind = "QRCode"
        self.data = "QrintPrint"
        self.error_correction = "M"
        self.border = 2
        self.write_text = False

    def content_image(self):
        img, _ = render_barcode_image(
            self.barcode_kind, self.data, self.error_correction,
            self.border, self.write_text)
        return img

    def _serialize_body(self, d):
        d.update(barcode_kind=self.barcode_kind, data=self.data,
                 error_correction=self.error_correction, border=self.border,
                 write_text=self.write_text)

    def apply_params(self, d):
        for k in ("barcode_kind", "data", "error_correction", "border",
                  "write_text"):
            if k in d:
                setattr(self, k, d[k])


ITEM_TYPES = {
    "text": TextCanvasItem,
    "image": ImageCanvasItem,
    "barcode": BarcodeCanvasItem,
}


class CanvasScene(QGraphicsScene):
    """384 点宽画布。"""

    itemEditRequested = Signal(object)

    def __init__(self, height=SCENE_H_DEFAULT, parent=None):
        super().__init__(parent)
        self.canvas_height = height
        self._setup()

    def _setup(self):
        self.setSceneRect(0, 0, SCENE_W, self.canvas_height)
        bg = QBrush(QColor(244, 246, 250))  # theme.INSET
        self.setBackgroundBrush(bg)
        self.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)

    def set_canvas_height(self, h):
        self.canvas_height = max(80, int(h))
        self.setSceneRect(0, 0, SCENE_W, self.canvas_height)

    # ---- 添加条目 ----

    def add_text_item(self, x=40, y=40, w=300, h=80):
        item = TextCanvasItem(x, y, w, h)
        self.addItem(item)
        item.setSelected(True)
        return item

    def add_image_item(self, path, x=40, y=40, w=300, h=220):
        item = ImageCanvasItem(x, y, w, h)
        item.set_image_path(path)
        self.addItem(item)
        item.setSelected(True)
        return item

    def add_barcode_item(self, kind="QRCode", data="QrintPrint",
                         x=40, y=40, w=220, h=220):
        item = BarcodeCanvasItem(x, y, w, h)
        item.barcode_kind = kind
        item.data = data
        self.addItem(item)
        item.setSelected(True)
        return item

    # ---- 序列化 ----

    def serialize_canvas(self):
        items = []
        for it in self.items():
            if isinstance(it, CanvasItem):
                items.append(it.serialize())
        items.sort(key=lambda d: d.get("z", 0))
        return {"width": SCENE_W, "height": self.canvas_height, "items": items}

    def load_canvas(self, data):
        self.clear()
        self.canvas_height = max(80, int(data.get("height", SCENE_H_DEFAULT)))
        self._setup()
        for d in data.get("items", []):
            cls = ITEM_TYPES.get(d.get("kind"))
            if cls is None:
                continue
            item = cls.from_dict(d)
            self.addItem(item)

    def delete_selected(self):
        for it in list(self.selectedItems()):
            if isinstance(it, CanvasItem):
                self.removeItem(it)

    def selected_canvas_item(self):
        for it in self.selectedItems():
            if isinstance(it, CanvasItem):
                return it
        return None


class CanvasView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(self.renderHints() |
                            self.renderHints().SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._zoom = 1.0

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
            self._zoom = max(0.15, min(6.0, self._zoom * factor))
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            scene = self.scene()
            if isinstance(scene, CanvasScene):
                scene.delete_selected()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.scene().clearSelection()
            return
        super().keyPressEvent(event)


def render_canvas_image(scene):
    """把画布渲染成 384 宽白底灰度图（打印用）。"""
    items = [it for it in scene.items() if isinstance(it, CanvasItem)]
    items.sort(key=lambda it: it.zValue())
    height = scene.canvas_height
    bottom = 0
    for it in items:
        bottom = max(bottom, it.y() + it.rect().height())
    height = max(height, int(bottom) + 8)
    img = Image.new("L", (SCENE_W, height), 255)
    for it in items:
        content = it.content_image()
        if content is None:
            continue
        content = flatten_white(content)
        r = it.rect()
        scale = min(r.width() / content.width, r.height() / content.height)
        if scale <= 0:
            continue
        w = max(1, int(content.width * scale))
        h = max(1, int(content.height * scale))
        content = content.resize((w, h), Image.LANCZOS)
        img.paste(content, (int(r.x() + (r.width() - w) / 2),
                            int(r.y() + (r.height() - h) / 2)))
    return img
