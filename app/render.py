# -*- coding: utf-8 -*-
"""
渲染管线：所有内容最终渲染为 384 点宽的灰度图，
再按抖动算法转成 1bit 光栅字节（bit 1 = 黑，MSB first）。

包含：
  - 文字排版（字体 / 字号 / 加粗·斜体·下划线 / 字间距 / 行间距 / 对齐）
  - 图片抖动：Floyd-Steinberg 误差扩散 / Ordered 4x4 / Bayer 8x8 / 阈值二值化
  - 一维码（Code128/Code39/EAN13/EAN8/UPCA/ITF/Codabar）与二维码 QR
  - PIL -> QImage 转换、缩略图
"""

import math
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .driver import WIDTH_DOTS, WIDTH_BYTES


# ---------------------------------------------------------------------------
# 常量与工具
# ---------------------------------------------------------------------------

WIDTH = WIDTH_DOTS

_FONT_ROOT = r"C:\Windows\Fonts"

# 常见中英文字体映射：正常 / 加粗 / 斜体 / 加粗斜体
_FONT_FILES = {
    "微软雅黑":       ("msyh.ttc",  "msyhbd.ttc",  None,        None),
    "Microsoft YaHei": ("msyh.ttc", "msyhbd.ttc",  None,        None),
    "宋体":           ("simsun.ttc", "simsun.ttc", None,        None),
    "SimSun":         ("simsun.ttc", "simsun.ttc", None,        None),
    "黑体":           ("simhei.ttf", "simhei.ttf", None,        None),
    "SimHei":         ("simhei.ttf", "simhei.ttf", None,        None),
    "楷体":           ("simkai.ttf", "simkai.ttf", None,        None),
    "KaiTi":          ("simkai.ttf", "simkai.ttf", None,        None),
    "仿宋":           ("simfang.ttf", "simfang.ttf", None,      None),
    "FangSong":       ("simfang.ttf", "simfang.ttf", None,      None),
    "Arial":          ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "Courier New":    ("cour.ttf",  "courbd.ttf",  "couri.ttf", "courbi.ttf"),
    "Consolas":       ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"),
    "Segoe UI":       ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "Tahoma":         ("tahoma.ttf", "tahomabd.ttf", None,       None),
    "Verdana":        ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "Georgia":        ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "微软雅黑 Light":  ("msyhl.ttc",  "msyhbd.ttc",  None,       None),
}


def _font_file(family, bold, italic):
    """返回 (字体文件路径或 None, 是否需要描边加粗, 是否需要斜体变换)。"""
    entry = _FONT_FILES.get(family)
    want = (3 if bold and italic else
            2 if italic else
            1 if bold else 0)
    use_stroke = False
    use_shear = False
    if entry:
        path = entry[want] or entry[0]
        if want in (1, 3) and not entry[want]:
            use_stroke = True
        if want in (2, 3) and not entry[want]:
            use_shear = True
        return (os.path.join(_FONT_ROOT, path), use_stroke, use_shear)
    # 未知字体：直接尝试 family 名
    for ext in (".ttf", ".ttc", ".otf"):
        p = os.path.join(_FONT_ROOT, family + ext)
        if os.path.exists(p):
            return p, bold and False, italic
    return None, True, True


def load_font(family, size, bold=False, italic=False):
    """返回 (font, use_stroke, use_shear)。找不到字体时回退微软雅黑。"""
    path, use_stroke, use_shear = _font_file(family, bold, italic)
    candidates = []
    if path:
        candidates.append(path)
    candidates.append(os.path.join(_FONT_ROOT, "msyh.ttc"))
    for p in candidates:
        if p and os.path.exists(p):
            try:
                return ImageFont.truetype(p, size), use_stroke, use_shear
            except OSError:
                continue
    return ImageFont.load_default(), False, False


def flatten_white(img):
    """RGBA/LA/P -> 白底合成为灰度图。"""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return img.convert("L")


def fit_width(img, width=WIDTH, keep_aspect=True):
    """等比缩放灰度图到目标宽度。"""
    img = flatten_white(img)
    if img.width == width:
        return img
    h = max(1, round(img.height * width / img.width))
    return img.resize((width, h), Image.LANCZOS)


# ---------------------------------------------------------------------------
# 抖动算法
# ---------------------------------------------------------------------------

def _gray_rows(img):
    """灰度图 -> 二维整数列表。"""
    img = flatten_white(img)
    data = list(img.getdata())
    w = img.width
    return [data[i:i + w] for i in range(0, len(data), w)], img.width, img.height


def _pack_bits(rows):
    """0/1 二维列表 -> 光栅字节（bit1=黑，MSB first）。"""
    height = len(rows)
    width = len(rows[0])
    row_bytes = (width + 7) // 8
    out = bytearray(row_bytes * height)
    for y, row in enumerate(rows):
        base = y * row_bytes
        for x, v in enumerate(row):
            if v:
                out[base + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out)


def dither_threshold(gray, threshold=128):
    """阈值二值化。"""
    return [[1 if v < threshold else 0 for v in row] for row in gray]


def dither_floyd(gray, threshold=128):
    """Floyd-Steinberg 误差扩散（经典正向扫描）。"""
    h = len(gray)
    if h == 0:
        return []
    w = len(gray[0])
    cur = [0.0] * w
    nxt = [0.0] * w
    out = []
    for y in range(h):
        row = gray[y]
        line = [0] * w
        for x in range(w):
            v = row[x] + cur[x]
            black = v < threshold
            line[x] = 1 if black else 0
            err = v - (0.0 if black else 255.0)
            if x + 1 < w:
                cur[x + 1] += err * 7.0 / 16.0
            if y + 1 < h:
                if x > 0:
                    nxt[x - 1] += err * 3.0 / 16.0
                nxt[x] += err * 5.0 / 16.0
                if x + 1 < w:
                    nxt[x + 1] += err * 1.0 / 16.0
        out.append(line)
        cur, nxt = nxt, [0.0] * w
    return out


def _bayer_matrix(n):
    """递归生成 n x n Bayer 阈值矩阵（n 为 2 的幂）。"""
    if n == 1:
        return [[0]]
    half = _bayer_matrix(n // 2)
    out = []
    for row in half:
        out.append([4 * v for v in row] + [4 * v + 2 for v in row])
    for row in half:
        out.append([4 * v + 3 for v in row] + [4 * v + 1 for v in row])
    return out


_ORDERED4 = _bayer_matrix(4)
_BAYER8 = _bayer_matrix(8)


def dither_matrix(gray, matrix, threshold=128):
    """有序抖动：阈值矩阵按像素位置取模。"""
    n = len(matrix)
    scale = 255.0 / (n * n)
    rows_out = []
    for y, row in enumerate(gray):
        trow = matrix[y % n]
        th = [(m + 0.5) * scale for m in trow]
        line = [0] * len(row)
        for x, v in enumerate(row):
            line[x] = 1 if v < th[x % n] else 0
        rows_out.append(line)
    return rows_out


DITHER_ALGORITHMS = {
    "none":    ("阈值二值化", dither_threshold),
    "floyd":   ("Floyd-Steinberg 误差扩散", dither_floyd),
    "ordered": ("Ordered 4×4 有序抖动", lambda g, t: dither_matrix(g, _ORDERED4, t)),
    "bayer":   ("Bayer 8×8 抖动", lambda g, t: dither_matrix(g, _BAYER8, t)),
}


def prepare_bitmap(gray_img, threshold=128, dither="none"):
    """
    灰度图 -> (光栅字节, 行字节数, 高度, 预览 1bit 灰度图)
    预览图与打印输出完全一致。
    """
    img = fit_width(gray_img, WIDTH)
    rows, w, h = _gray_rows(img)
    func = DITHER_ALGORITHMS.get(dither, DITHER_ALGORITHMS["none"])[1]
    bits = func(rows, threshold)
    packed = _pack_bits(bits)
    preview = Image.new("L", (w, h), 255)
    preview.putdata([0 if b else 255 for row in bits for b in row])
    return packed, WIDTH_BYTES, h, preview


# ---------------------------------------------------------------------------
# 文字渲染
# ---------------------------------------------------------------------------

def _render_line(text, font, size, char_spacing, stroke):
    """渲染单行 -> (行图, 行高)。斜体在此之外做剪切变换。"""
    asc, desc = font.getmetrics()
    line_h = asc + desc
    widths = [font.getlength(ch) for ch in text]
    total = int(sum(widths) + char_spacing * max(0, len(text) - 1)) + 8
    img = Image.new("L", (max(8, total), line_h + 8), 255)
    d = ImageDraw.Draw(img)
    x = 4
    y = 4 - desc + (line_h - (asc + desc)) // 2  # 保持垂直居中
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=font, fill=0,
               stroke_width=stroke, stroke_fill=0)
        x += int(w) + char_spacing
    return img, line_h + 8


def render_text_image(text, font_family="微软雅黑", font_size=24, bold=False,
                      italic=False, underline=False, char_spacing=0,
                      line_spacing=8, margin=8, align="left",
                      max_width=None):
    """
    渲染多行文字为 384 点宽灰度图。
    max_width 用于画布中按条目宽度换行。
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    usable = (max_width or WIDTH) - 2 * margin
    font, use_stroke, use_shear = load_font(font_family, font_size, bold, italic)
    stroke = max(0, font_size // 24) if use_stroke else 0

    # 逐字符换行
    lines = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        cur_w = 0
        for ch in para:
            w = int(font.getlength(ch)) + char_spacing
            if cur and cur_w + w > usable:
                lines.append(cur)
                cur = ch
                cur_w = int(font.getlength(ch))
            else:
                cur += ch
                cur_w += w
        lines.append(cur)

    # 逐行渲染（含斜体剪切）
    rendered = []
    total_h = 0
    for ln in lines:
        img, h = _render_line(ln, font, font_size, char_spacing, stroke)
        if use_shear and ln:
            shear = 0.22
            w2 = int(img.width + shear * img.height)
            img = img.transform((w2, img.height), Image.AFFINE,
                                (1, shear, 0, 0, 1, 0),
                                resample=Image.BICUBIC, fillcolor=255)
        rendered.append(img)
        total_h += h

    total_h += max(0, line_spacing) * max(0, len(rendered) - 1)
    canvas = Image.new("L", (WIDTH, margin * 2 + total_h), 255)
    d = ImageDraw.Draw(canvas)
    y = margin
    asc, desc = font.getmetrics()
    for i, (img, h) in enumerate(zip(rendered, [img.height for img in rendered])):
        x = margin
        if align == "center":
            x = margin + max(0, (usable - img.width) // 2)
        elif align == "right":
            x = margin + max(0, usable - img.width)
        canvas.paste(img, (x, y))
        if underline and img.width > 0:
            bar_y = y + asc + max(2, font_size // 12)
            d.line([(x, bar_y), (x + img.width - 1, bar_y)],
                   fill=0, width=max(2, font_size // 10))
        y += h + (line_spacing if i < len(rendered) - 1 else 0)
    return canvas


# ---------------------------------------------------------------------------
# 条码 / 二维码
# ---------------------------------------------------------------------------

BARCODE_KINDS = [
    "QRCode",
    "Code128",
    "Code39",
    "EAN13",
    "EAN8",
    "UPCA",
    "ITF",
    "Codabar",
    "EAN14",
    "JAN",
    "ISBN13",
    "ISBN10",
    "ISSN",
    "GS1-128",
    "PZN",
]

_BARCODE_NAME = {
    "QRCode": None,
    "Code128": "code128",
    "Code39": "code39",
    "EAN13": "ean13",
    "EAN8": "ean8",
    "UPCA": "upca",
    "ITF": "itf",
    "Codabar": "codabar",
    "EAN14": "ean14",
    "JAN": "jan",
    "ISBN13": "isbn13",
    "ISBN10": "isbn10",
    "ISSN": "issn",
    "GS1-128": "gs1_128",
    "PZN": "pzn",
}


def is_1d_barcode(kind):
    """是否为一维码（QRCode 之外的都是一维码，可显示数字）。"""
    return kind != "QRCode"


def validate_barcode(kind, data):
    """返回 (是否有效, 提示)。只校验、不渲染。"""
    data = (data or "").strip()
    if not data:
        return False, "内容为空"
    if kind == "QRCode":
        n = len(data.encode("utf-8"))
        if n > 2331:
            return False, f"内容过长（{n} 字节 > 2331）"
        return True, "内容有效"
    name = _BARCODE_NAME.get(kind)
    try:
        import barcode
        cls = barcode.get_barcode_class(name)
        cls(data)  # 构造即校验
        return True, "内容有效"
    except Exception as exc:
        return False, _barcode_hint(kind, data, exc)


def _barcode_hint(kind, data, exc):
    msg = str(exc)
    if kind in ("EAN13", "EAN8", "UPCA", "JAN"):
        return "需为对应位数的数字（可自动补校验位）"
    if kind == "EAN14":
        return "EAN14 需要 13~14 位数字（可自动补校验位）"
    if kind in ("ISBN13", "ISBN10"):
        return "请输入 ISBN 数字（10 位 / 13 位，可含校验位）"
    if kind == "ISSN":
        return "ISSN 需要 8 位数字"
    if kind == "PZN":
        return "PZN 需要 6~7 位数字"
    if kind == "GS1-128":
        return "GS1-128 需按应用标识符(AI)拼接的数字串"
    if kind == "ITF":
        return "ITF 需要偶数位数字"
    if kind == "Code39":
        return "Code39 允许 A-Z 0-9 及 - . 空格 $ / + %"
    return f"内容不合法：{msg or exc.__class__.__name__}"


def render_1d_image(kind, data, write_text=False):
    """一维码 -> (灰度图或 None, 错误信息)。"""
    data = (data or "").strip()
    name = _BARCODE_NAME.get(kind)
    try:
        import barcode
        from barcode.writer import ImageWriter
        cls = barcode.get_barcode_class(name)
        bc = cls(data, writer=ImageWriter())
        opts = {
            "module_width": 0.25,
            "module_height": 12.0,
            "quiet_zone": 6.5,
            "font_size": 11,
            "text_distance": 3.0,
            "write_text": write_text,
            "center_text": True,
            "background": "white",
            "foreground": "black",
        }
        img = bc.render(opts).convert("L")
    except Exception as exc:
        return None, _barcode_hint(kind, data, exc)

    img = ImageOps.expand(img, border=4, fill=255)
    img = _fit_centered(img, WIDTH)
    return img, None


def render_qr_image(data, error_correction="M", border=2):
    """二维码 -> (灰度图或 None, 错误信息)。自动选择 box_size 贴近 384 宽。"""
    data = (data or "").strip()
    if not data:
        return None, "内容为空"
    import qrcode
    ec_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }
    try:
        qr = qrcode.QRCode(version=None, error_correction=ec_map.get(
            error_correction, qrcode.constants.ERROR_CORRECT_M),
            box_size=10, border=border)
        qr.add_data(data)
        qr.make(fit=True)
        mods = qr.modules_count
        box = max(1, WIDTH // (mods + 2 * border))
        qr2 = qrcode.QRCode(version=qr.version,
                            error_correction=ec_map.get(
                                error_correction,
                                qrcode.constants.ERROR_CORRECT_M),
                            box_size=box, border=border)
        qr2.add_data(data)
        qr2.make(fit=False)
        img = qr2.make_image(fill_color="black", back_color="white").convert("L")
    except Exception as exc:
        msg = str(exc) or exc.__class__.__name__
        if "DataOverflow" in msg or "too long" in msg.lower():
            msg = "内容超出二维码容量，请精简或降低纠错级别"
        return None, f"二维码生成失败：{msg}"
    return _fit_centered(img, WIDTH), None


def render_barcode_image(kind, data, error_correction="M", border=2,
                         write_text=False):
    """条码统一入口 -> (灰度图或 None, 错误信息)。"""
    if kind == "QRCode":
        return render_qr_image(data, error_correction, border)
    return render_1d_image(kind, data, write_text)


def _fit_centered(img, width):
    """缩放（只缩不放）并居中贴到 width 宽的白色画布。"""
    if img.width > width:
        h = max(1, round(img.height * width / img.width))
        img = img.resize((width, h), Image.LANCZOS)
    canvas = Image.new("L", (width, img.height), 255)
    canvas.paste(img, ((width - img.width) // 2, 0))
    return canvas


# ---------------------------------------------------------------------------
# Qt 转换 / 缩略图
# ---------------------------------------------------------------------------

def pil_to_qimage(img):
    """PIL 图 -> QImage（RGBA8888，拷贝数据）。"""
    from PySide6.QtGui import QImage
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return qimg.copy()


def make_thumbnail(img, max_w=180):
    """生成缩略图（保持比例）。"""
    img = flatten_white(img)
    if img.width > max_w:
        h = max(1, round(img.height * max_w / img.width))
        img = img.resize((max_w, h), Image.LANCZOS)
    return img
