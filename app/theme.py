# -*- coding: utf-8 -*-
"""QrintPrint 视觉主题 —— “热敏小票控制台”。

设计语言：冷色系的机器控制台，环绕一张温白色的小票预览。
所有点阵 / 阈值 / 端口等技术数值使用等宽字体，呼应“逐点成像”的领域。

对外接口：
    apply_theme(app)   在 QApplication 创建后调用，统一字体与样式。
    以及一组供 ui.py / canvas.py 复用的调色板常量。
"""

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# 调色板（机器冷灰 + 靛蓝墨水强调 + 温白小票）
# ---------------------------------------------------------------------------

BG          = "#EDF0F5"   # 应用画布：冷色浅石板
PANEL       = "#FFFFFF"   # 卡片 / 面板
INSET       = "#F4F6FA"   # 内嵌浅底（输入框静止态、工具条）
INSET_DEEP  = "#E9EDF3"   # 更深一点的内嵌
BORDER      = "#DCE1EA"   # 发丝分隔线
BORDER_SOFT = "#E7EBF1"   # 更淡的分隔线

INK         = "#1C2432"   # 主文字（近黑石板，非纯黑）
INK_SOFT    = "#5B6676"   # 次级文字
INK_FAINT   = "#95A0B1"   # 占位 / 三级文字

ACCENT        = "#4B47C4"  # 靛蓝墨水：主操作 / 选中页签 / 焦点
ACCENT_STRONG = "#3D39AD"  # 悬停 / 按下
ACCENT_SOFT   = "#ECEBFB"  # 选区 / 轻填充
ACCENT_LINE   = "#C9C7F2"  # 强调色发丝线

PAPER       = "#FBFAF6"   # 温白小票纸（预览承载面）
PAPER_EDGE  = "#EFEDE4"   # 纸张暗边 / 撕纸齿

# 语义色（与状态灯保持一致，略作校准）
OK    = "#2E9E5B"
FAULT = "#E14B3B"
WARN  = "#E08A2B"
IDLE  = "#AEB6C2"


# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------

# 界面字体：Windows 原生、CJK 友好
UI_FONTS = ["Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑"]
# 技术数值：等宽（Win11 自带 Cascadia，回退 Consolas）
MONO_FONTS = ["Cascadia Mono", "Cascadia Code", "Consolas",
              "Microsoft YaHei UI", "monospace"]


def _first_available(candidates, fallback):
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return fallback


def ui_font_family():
    return _first_available(UI_FONTS, "Segoe UI")


def mono_font_family():
    return _first_available(MONO_FONTS, "Consolas")


def mono_font(point_size=10, bold=False):
    f = QFont(mono_font_family(), point_size)
    f.setBold(bold)
    try:
        f.setStyleHint(QFont.StyleHint.Monospace)
    except Exception:
        pass
    return f


# ---------------------------------------------------------------------------
# 样式表
# ---------------------------------------------------------------------------

def _qss():
    return f"""
/* ---- 基础 ---- */
QWidget {{
    color: {INK};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {BG};
}}
QToolTip {{
    background: {INK};
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 12px;
}}

/* ---- 设备栏容器 ---- */
QFrame#deviceRail {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QFrame#railDivider {{
    background: {BORDER};
    max-width: 1px;
    min-width: 1px;
    border: none;
}}
QLabel#eyebrow {{
    color: {INK_FAINT};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}}
QLabel#brandTitle {{
    color: {INK};
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0.5px;
}}
QLabel#fieldLabel {{
    color: {INK_SOFT};
    font-size: 12px;
}}
QLabel#hint {{
    color: {INK_SOFT};
    font-size: 12px;
}}
QLabel#caption {{
    color: {INK_FAINT};
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
}}

/* ---- 连接状态胶囊 ---- */
QLabel#connPill {{
    border-radius: 12px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 600;
    background: {INSET_DEEP};
    color: {INK_SOFT};
}}

/* ---- 顶栏 ---- */
QFrame#headerBar {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#brandTitle {{
    color: {INK};
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 0.5px;
}}
QLabel#brandSub {{
    color: {INK_FAINT};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}}

/* ---- 主导航按钮 ---- */
QPushButton#navTab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    color: {INK_SOFT};
    font-size: 13px;
    padding: 8px 18px;
}}
QPushButton#navTab:hover {{
    background: transparent;
    color: {INK};
    border-bottom: 2px solid {ACCENT_LINE};
}}
QPushButton#navTab:checked {{
    background: transparent;
    color: {ACCENT};
    font-weight: 700;
    border-bottom: 2px solid {ACCENT};
}}

/* ---- 首页连接卡片 ---- */
QFrame#connectCard {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
QFrame#connectCard:hover {{
    border: 1px solid {ACCENT_LINE};
    background: #FCFCFF;
}}
QLabel#connIcon {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
    border-radius: 23px;
    font-size: 22px;
}}
QLabel#cardTitle {{
    color: {INK};
    font-size: 17px;
    font-weight: 800;
}}
QLabel#cardSub {{
    color: {INK_SOFT};
    font-size: 12px;
}}

/* ---- 首页功能入口 ---- */
QFrame#homeTile {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
QFrame#homeTile:hover {{
    border: 1px solid {ACCENT_LINE};
    background: #FCFCFF;
}}
QLabel#tileIcon {{
    color: {ACCENT};
    font-size: 26px;
}}
QLabel#tileTitle {{
    color: {INK};
    font-size: 15px;
    font-weight: 800;
}}
QLabel#tileSub {{
    color: {INK_FAINT};
    font-size: 12px;
}}

/* ---- 分组卡片（我的页）---- */
QGroupBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
    margin-top: 12px;
    padding: 16px 14px 14px 14px;
    font-weight: 700;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    background: {PANEL};
    color: {INK_SOFT};
    font-size: 12px;
    font-weight: 700;
}}

/* ---- 页签 ---- */
QTabWidget::pane {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 14px;
    top: -1px;
}}
QTabBar {{
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    background: transparent;
    color: {INK_SOFT};
    padding: 9px 20px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 13px;
}}
QTabBar::tab:hover {{
    color: {INK};
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    font-weight: 700;
    border-bottom: 2px solid {ACCENT};
}}

/* ---- 按钮 ---- */
QPushButton {{
    background: {INSET};
    color: {INK};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 7px 15px;
    font-size: 13px;
}}
QPushButton:hover {{
    background: {INSET_DEEP};
    border-color: {ACCENT_LINE};
}}
QPushButton:pressed {{
    background: {INSET_DEEP};
    border-color: {ACCENT};
}}
QPushButton:disabled {{
    color: {INK_FAINT};
    background: {INSET};
    border-color: {BORDER_SOFT};
}}
QPushButton#primary {{
    background: {ACCENT};
    color: #FFFFFF;
    border: 1px solid {ACCENT};
    font-weight: 700;
    padding: 9px 26px;
}}
QPushButton#primary:hover {{
    background: {ACCENT_STRONG};
    border-color: {ACCENT_STRONG};
}}
QPushButton#primary:pressed {{
    background: {ACCENT_STRONG};
}}
QPushButton#primary:disabled {{
    background: {INSET_DEEP};
    color: {INK_FAINT};
    border-color: {BORDER};
}}
QPushButton#backBtn {{
    background: transparent;
    border: none;
    color: {ACCENT};
    font-size: 13px;
    font-weight: 700;
    padding: 6px 10px;
    text-align: left;
}}
QPushButton#backBtn:hover {{
    background: {ACCENT_SOFT};
    border-radius: 8px;
    color: {ACCENT_STRONG};
}}

/* ---- 输入类 ---- */
QLineEdit, QPlainTextEdit, QTextEdit,
QComboBox, QSpinBox, QDoubleSpinBox, QFontComboBox {{
    background: {PANEL};
    color: {INK};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 6px 10px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}
QPlainTextEdit, QTextEdit {{
    padding: 8px 10px;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QFontComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    color: {INK_FAINT};
    background: {INSET};
}}

/* 数值类用等宽字体，强化“点阵 / 阈值”的技术感 */
QSpinBox, QDoubleSpinBox {{
    font-family: "{mono_font_family()}";
}}

QComboBox::drop-down, QFontComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: none;
    border-left: 1px solid {BORDER_SOFT};
}}
QComboBox::down-arrow, QFontComboBox::down-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {INK_SOFT};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {INK};
    outline: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid {BORDER_SOFT};
    border-top-right-radius: 8px;
    background: {INSET};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border-left: 1px solid {BORDER_SOFT};
    border-bottom-right-radius: 8px;
    background: {INSET};
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {ACCENT_SOFT};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {INK_SOFT};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {INK_SOFT};
}}

/* ---- 复选框 ---- */
QCheckBox {{
    spacing: 7px;
    color: {INK};
}}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {BORDER};
    border-radius: 5px;
    background: {PANEL};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT_LINE};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

/* ---- 滑块 ---- */
QSlider::groove:horizontal {{
    height: 5px;
    background: {INSET_DEEP};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: {PANEL};
    border: 2px solid {ACCENT};
}}
QSlider::handle:horizontal:hover {{
    background: {ACCENT_SOFT};
}}

/* ---- 列表（打印历史）---- */
QListWidget {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    color: {INK};
    border-radius: 8px;
    padding: 8px;
    margin: 2px;
}}
QListWidget::item:selected {{
    background: {ACCENT_SOFT};
    color: {INK};
}}
QListWidget::item:hover {{
    background: {INSET};
}}

/* ---- 画布视图 ---- */
QGraphicsView {{
    background: {INSET};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

/* ---- 滚动条 ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {IDLE};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {INK_SOFT};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {IDLE};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {INK_SOFT};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---- 状态栏 ---- */
QStatusBar {{
    background: transparent;
    color: {INK_SOFT};
    font-size: 12px;
}}
QStatusBar::item {{ border: none; }}

/* ---- 菜单 ---- */
QMenu {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{
    padding: 6px 22px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {ACCENT_SOFT};
    color: {INK};
}}
"""


def apply_theme(app: QApplication):
    """统一应用字体 + 调色板 + 样式表。在创建 QApplication 后调用。"""
    app.setStyle("Fusion")

    base = QFont(ui_font_family(), 10)
    app.setFont(base)

    # 让未被 QSS 覆盖到的原生控件也贴近主题
    from PySide6.QtGui import QPalette
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.Base, QColor(PANEL))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(INSET))
    pal.setColor(QPalette.ColorRole.Text, QColor(INK))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(INK))
    pal.setColor(QPalette.ColorRole.Button, QColor(INSET))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(INK))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(INK))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#FFFFFF"))
    app.setPalette(pal)

    app.setStyleSheet(_qss())
