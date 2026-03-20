#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HydraulicCAD 算量自动化平台 v3.3
UI 改进内容：
- 参数卡片化：带阴影的卡片包裹参数配置
- 操作下沉：开始按钮固定右下角
- 标签上方对齐：Label 在输入框上方
- 日志可折叠：默认折叠，点击展开
- 圆角与间距优化：6px-8px 圆角，增加内边距
- 色彩主题系统：深灰蓝背景 + 卡片背景 + 品牌蓝交互色
- 批量粘贴双栏布局：坐标映射区 + 文件执行区
"""

import sys
import os
import traceback
import importlib
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

# --- 路径兼容处理 ---
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

if base_path not in sys.path:
    sys.path.insert(0, base_path)

# --- 核心 UI 库 ---
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

# --- 依赖库检测 ---
try:
    import ezdxf
    import shapely
    import numpy
    from shapely.geometry import LineString, Point, box, Polygon
    from shapely.ops import unary_union, linemerge, polygonize
    print("[OK] 核心依赖库加载成功")
except ImportError as e:
    print(f"[WARN] 缺少依赖库：{e}")

# ================= 颜色主题系统 =================
class Theme:
    """统一的颜色主题管理"""
    # 主背景色
    BG_PRIMARY = "#1A1B1E"      # 深冷色调背景
    BG_SECONDARY = "#25262B"    # 输入框背景
    BG_CARD = "#2B2B3B"         # 卡片背景（稍浅的深灰）
    BG_CARD_ALT = "#32333A"     # 卡片备选色
    
    # 交互色
    ACCENT_PRIMARY = "#228BE6"  # 品牌蓝
    ACCENT_HOVER = "#1C7ED6"    # 悬停蓝
    ACCENT_LIGHT = "#3B8BEB"    # 浅蓝
    ACCENT_GRADIENT_START = "#1C7ED6"
    ACCENT_GRADIENT_END = "#228BE6"
    
    # 文字色
    TEXT_PRIMARY = "#FFFFFF"
    TEXT_SECONDARY = "#CCCCCC"
    TEXT_MUTED = "#888888"
    TEXT_HIGHLIGHT = "#4EC9B0"  # 高亮文字（青绿色）
    
    # 状态色
    STATUS_SUCCESS = "#37B24D"  # 绿色
    STATUS_ERROR = "#F03E3E"    # 红色
    STATUS_WARNING = "#F59F00"  # 橙色
    STATUS_INFO = "#228BE6"     # 蓝色
    
    # 边框色
    BORDER_DEFAULT = "#3C3C3C"
    BORDER_FOCUS = "#228BE6"
    BORDER_HOVER = "#3C3C3C"
    
    # 间距系统（调整为原来的0.9倍）
    SPACING_XS = 4
    SPACING_SM = 7
    SPACING_MD = 11
    SPACING_LG = 14
    SPACING_XL = 18
    
    # 圆角
    RADIUS_SM = 4
    RADIUS_MD = 6
    RADIUS_LG = 8
    RADIUS_XL = 12


# ================= 现代样式表 =================
def get_stylesheet():
    """生成现代化样式表"""
    return f"""
/* ===== 全局样式 ===== */
QMainWindow {{
    background-color: {Theme.BG_PRIMARY};
    color: {Theme.TEXT_PRIMARY};
    font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
    font-size: 13px;
}}

QWidget {{
    font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
}}

/* ===== 标签页样式 ===== */
QTabWidget::pane {{
    border: 1px solid {Theme.BORDER_DEFAULT};
    background: {Theme.BG_PRIMARY};
    border-radius: {Theme.RADIUS_LG}px;
    top: -1px;
}}

QTabBar::tab {{
    background: {Theme.BG_SECONDARY};
    color: {Theme.TEXT_MUTED};
    padding: 12px 28px;
    font-size: 13px;
    font-weight: 500;
    border-top-left-radius: {Theme.RADIUS_MD}px;
    border-top-right-radius: {Theme.RADIUS_MD}px;
    margin-right: 2px;
    border: 1px solid {Theme.BORDER_DEFAULT};
    border-bottom: none;
}}

QTabBar::tab:selected {{
    background: {Theme.BG_CARD};
    color: {Theme.ACCENT_PRIMARY};
    border-bottom: 3px solid {Theme.ACCENT_PRIMARY};
}}

QTabBar::tab:hover:!selected {{
    background: {Theme.BG_CARD_ALT};
    color: {Theme.TEXT_SECONDARY};
}}

/* ===== 卡片样式（GroupBox重定义） ===== */
QGroupBox {{
    font-weight: 600;
    font-size: 14px;
    color: {Theme.ACCENT_PRIMARY};
    border: none;
    border-radius: {Theme.RADIUS_LG}px;
    margin-top: 0px;
    padding-top: 0px;
    background: {Theme.BG_CARD};
    padding: {Theme.SPACING_LG}px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 {Theme.SPACING_MD}px;
    background: {Theme.BG_CARD};
    border-radius: {Theme.RADIUS_SM}px;
    left: {Theme.SPACING_MD}px;
}}

/* ===== 输入框样式 ===== */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {Theme.BG_SECONDARY};
    color: {Theme.TEXT_PRIMARY};
    border: 1px solid {Theme.BORDER_DEFAULT};
    border-radius: {Theme.RADIUS_MD}px;
    padding: 10px 14px;
    font-size: 13px;
    min-height: 20px;
    selection-background-color: {Theme.ACCENT_PRIMARY};
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 2px solid {Theme.ACCENT_PRIMARY};
    background-color: #2D2E33;
}}

QLineEdit:hover, QComboBox:hover {{
    border-color: {Theme.BORDER_HOVER};
}}

QComboBox::drop-down {{
    border: none;
    width: 30px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {Theme.TEXT_MUTED};
    margin-right: 10px;
}}

/* ===== 按钮样式 ===== */
QPushButton {{
    background-color: {Theme.BG_CARD_ALT};
    color: {Theme.TEXT_SECONDARY};
    border: 1px solid {Theme.BORDER_DEFAULT};
    border-radius: {Theme.RADIUS_MD}px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 500;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {Theme.BG_CARD};
    border-color: {Theme.ACCENT_PRIMARY};
    color: {Theme.TEXT_PRIMARY};
}}

QPushButton:pressed {{
    background-color: {Theme.ACCENT_PRIMARY};
    color: {Theme.TEXT_PRIMARY};
}}

QPushButton:disabled {{
    background-color: {Theme.BG_SECONDARY};
    color: {Theme.TEXT_MUTED};
    border-color: transparent;
}}

/* 主操作按钮 */
QPushButton#PrimaryActionBtn {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {Theme.ACCENT_GRADIENT_START}, 
                                stop:1 {Theme.ACCENT_GRADIENT_END});
    color: white;
    border: none;
    border-radius: {Theme.RADIUS_LG}px;
    font-size: 15px;
    font-weight: 600;
    min-height: 48px;
    padding: 12px 32px;
}}

QPushButton#PrimaryActionBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #3B9EE6, 
                                stop:1 #228BE6);
}}

QPushButton#PrimaryActionBtn:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #1C7ED6, 
                                stop:1 #1A6BC7);
}}

QPushButton#PrimaryActionBtn:disabled {{
    background: #3C3C3C;
    color: #666666;
}}

/* 选择按钮 */
QPushButton#SelectBtn {{
    background-color: {Theme.BG_CARD_ALT};
    color: {Theme.TEXT_SECONDARY};
    border: 1px solid {Theme.ACCENT_PRIMARY};
    border-radius: {Theme.RADIUS_MD}px;
}}

QPushButton#SelectBtn:hover {{
    background-color: {Theme.ACCENT_PRIMARY};
    color: white;
}}

/* 图标按钮 */
QPushButton#IconBtn {{
    background: transparent;
    border: 1px dashed {Theme.BORDER_DEFAULT};
    border-radius: {Theme.RADIUS_MD}px;
    padding: 16px;
    min-width: 100px;
}}

QPushButton#IconBtn:hover {{
    border-color: {Theme.ACCENT_PRIMARY};
    background: rgba(34, 139, 230, 0.1);
}}

/* ===== 列表样式 ===== */
QListWidget {{
    background-color: transparent;
    color: {Theme.TEXT_SECONDARY};
    border: none;
    padding: {Theme.SPACING_SM}px;
    outline: none;
}}

QListWidget::item {{
    background-color: {Theme.BG_CARD};
    border: 1px solid {Theme.BORDER_DEFAULT};
    border-radius: {Theme.RADIUS_MD}px;
    padding: 10px {Theme.SPACING_MD}px;
    margin: 2px;
}}

QListWidget::item:selected {{
    background-color: {Theme.ACCENT_PRIMARY};
    color: white;
    border-color: {Theme.ACCENT_PRIMARY};
}}

QListWidget::item:hover:!selected {{
    background-color: {Theme.BG_CARD_ALT};
    border-color: {Theme.ACCENT_LIGHT};
}}

/* ===== 进度条样式 ===== */
QProgressBar {{
    border: none;
    border-radius: {Theme.RADIUS_MD}px;
    background-color: {Theme.BG_SECONDARY};
    text-align: center;
    color: {Theme.TEXT_PRIMARY};
    font-weight: 500;
    min-height: 24px;
}}

QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {Theme.ACCENT_PRIMARY}, 
                                stop:1 #00B4FF);
    border-radius: {Theme.RADIUS_MD}px;
}}

/* ===== 滚动条样式 ===== */
QScrollBar:vertical {{
    background: {Theme.BG_SECONDARY};
    width: 10px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    background: {Theme.BG_CARD_ALT};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {Theme.ACCENT_PRIMARY};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* ===== 文本编辑样式 ===== */
QTextEdit {{
    background-color: #1A1A1A;
    color: #00FF00;
    font-family: 'Consolas', 'Microsoft YaHei Mono', monospace;
    font-size: 12px;
    border: 1px solid {Theme.BORDER_DEFAULT};
    border-radius: {Theme.RADIUS_LG}px;
    padding: {Theme.SPACING_MD}px;
}}

/* ===== 复选框样式 ===== */
QCheckBox {{
    font-size: 13px;
    font-weight: 500;
    color: {Theme.TEXT_HIGHLIGHT};
    spacing: {Theme.SPACING_SM}px;
}}

QCheckBox::indicator {{
    width: 20px;
    height: 20px;
    border: 2px solid {Theme.BORDER_DEFAULT};
    border-radius: {Theme.RADIUS_SM}px;
    background: {Theme.BG_SECONDARY};
}}

QCheckBox::indicator:checked {{
    background: {Theme.ACCENT_PRIMARY};
    border-color: {Theme.ACCENT_PRIMARY};
}}

QCheckBox::indicator:hover {{
    border-color: {Theme.ACCENT_LIGHT};
}}

/* ===== 标签样式 ===== */
QLabel {{
    color: {Theme.TEXT_SECONDARY};
    font-size: 13px;
}}

QLabel#TitleLabel {{
    color: {Theme.TEXT_PRIMARY};
    font-size: 15px;
    font-weight: 600;
}}

QLabel#InfoLabel {{
    color: {Theme.TEXT_HIGHLIGHT};
    font-size: 12px;
}}

QLabel#OutputDirLabel {{
    color: {Theme.TEXT_HIGHLIGHT};
    font-size: 12px;
    padding: {Theme.SPACING_SM}px {Theme.SPACING_MD}px;
    background: {Theme.BG_SECONDARY};
    border-radius: {Theme.RADIUS_MD}px;
    border: 1px solid {Theme.BORDER_DEFAULT};
}}

QLabel#StatusLabel {{
    color: {Theme.TEXT_MUTED};
    font-size: 12px;
    padding: {Theme.SPACING_XS}px {Theme.SPACING_SM}px;
}}

/* ===== 状态栏样式 ===== */
QStatusBar {{
    background: {Theme.BG_SECONDARY};
    border-top: 1px solid {Theme.BORDER_DEFAULT};
    color: {Theme.TEXT_SECONDARY};
    font-size: 12px;
    min-height: 32px;
}}

/* ===== 分割线样式 ===== */
QFrame#HSeparator {{
    background: {Theme.BORDER_DEFAULT};
    max-height: 1px;
}}

QFrame#VSeparator {{
    background: {Theme.BORDER_DEFAULT};
    max-width: 1px;
}}

/* ===== 滚动区域样式 ===== */
QScrollArea {{
    border: none;
    background: transparent;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
"""


# ================= 自定义组件 =================
class CardWidget(QFrame):
    """卡片容器组件 - 带阴影效果"""
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("CardWidget")
        self.setStyleSheet(f"""
            QFrame#CardWidget {{
                background-color: {Theme.BG_CARD};
                border-radius: {Theme.RADIUS_LG}px;
                border: 1px solid #3A3A4A;
            }}
        """)
        # 启用阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(Theme.SPACING_LG, Theme.SPACING_LG, Theme.SPACING_LG, Theme.SPACING_LG)
        self._layout.setSpacing(Theme.SPACING_MD)
        
        if title:
            title_label = QLabel(title)
            title_label.setStyleSheet(f"""
                color: {Theme.ACCENT_PRIMARY};
                font-size: 14px;
                font-weight: 600;
                padding-bottom: {Theme.SPACING_SM}px;
            """)
            self._layout.addWidget(title_label)
            
    def layout(self):
        return self._layout


class ParamField(QWidget):
    """参数输入字段 - 标签在输入框上方"""
    def __init__(self, label_text, default_value="", placeholder="", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Theme.SPACING_XS)
        
        # 标签
        label = QLabel(label_text)
        label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px; font-weight: 500;")
        layout.addWidget(label)
        
        # 输入框
        self.line_edit = QLineEdit(default_value)
        self.line_edit.setPlaceholderText(placeholder)
        layout.addWidget(self.line_edit)
        
    def text(self):
        return self.line_edit.text()
        
    def setText(self, value):
        self.line_edit.setText(value)


class CollapsibleLog(QWidget):
    """可折叠的日志面板"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_expanded = False
        self._init_ui()
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 状态栏（始终显示）
        self.status_bar = QFrame()
        self.status_bar.setStyleSheet(f"""
            QFrame {{
                background: {Theme.BG_SECONDARY};
                border-radius: {Theme.RADIUS_MD}px;
                border: 1px solid {Theme.BORDER_DEFAULT};
            }}
        """)
        self.status_bar.setFixedHeight(44)
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(Theme.SPACING_MD, Theme.SPACING_SM, Theme.SPACING_MD, Theme.SPACING_SM)
        
        # 状态图标和文本
        self.status_icon = QLabel("●")
        self.status_icon.setStyleSheet(f"color: {Theme.STATUS_SUCCESS}; font-size: 10px;")
        status_layout.addWidget(self.status_icon)
        
        self.status_text = QLabel("准备就绪")
        self.status_text.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px;")
        status_layout.addWidget(self.status_text)
        
        status_layout.addStretch()
        
        # 展开/折叠按钮
        self.toggle_btn = QPushButton("▼ 日志")
        self.toggle_btn.setFixedHeight(28)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {Theme.TEXT_MUTED};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: {Theme.RADIUS_SM}px;
                padding: 4px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {Theme.BG_CARD};
                color: {Theme.TEXT_SECONDARY};
            }}
        """)
        self.toggle_btn.clicked.connect(self.toggle_expand)
        status_layout.addWidget(self.toggle_btn)
        
        layout.addWidget(self.status_bar)
        
        # 日志内容（默认折叠）
        self.log_container = QFrame()
        self.log_container.setStyleSheet(f"""
            QFrame {{
                background: #1A1A1A;
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-top: none;
                border-radius: 0 0 {Theme.RADIUS_MD}px {Theme.RADIUS_MD}px;
            }}
        """)
        log_layout = QVBoxLayout(self.log_container)
        log_layout.setContentsMargins(Theme.SPACING_MD, Theme.SPACING_SM, Theme.SPACING_MD, Theme.SPACING_MD)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("""
            QTextEdit {
                background: transparent;
                color: #00FF00;
                font-family: 'Consolas', 'Microsoft YaHei Mono', monospace;
                font-size: 12px;
                border: none;
            }
        """)
        self.log_area.setMinimumHeight(150)
        self.log_area.setMaximumHeight(300)
        log_layout.addWidget(self.log_area)
        
        # 清空按钮
        clear_btn = QPushButton("清空日志")
        clear_btn.setFixedHeight(28)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {Theme.TEXT_MUTED};
                border: 1px solid {Theme.BORDER_DEFAULT};
                border-radius: {Theme.RADIUS_SM}px;
                padding: 4px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {Theme.STATUS_ERROR};
                color: white;
            }}
        """)
        clear_btn.clicked.connect(self.log_area.clear)
        log_layout.addWidget(clear_btn, alignment=Qt.AlignmentFlag.AlignRight)
        
        self.log_container.setVisible(False)
        layout.addWidget(self.log_container)
        
    def toggle_expand(self):
        self._is_expanded = not self._is_expanded
        self.log_container.setVisible(self._is_expanded)
        self.toggle_btn.setText("▲ 日志" if self._is_expanded else "▼ 日志")
        
    def set_status(self, text, status="info"):
        """设置状态文本和颜色"""
        self.status_text.setText(text)
        colors = {
            "success": Theme.STATUS_SUCCESS,
            "error": Theme.STATUS_ERROR,
            "warning": Theme.STATUS_WARNING,
            "info": Theme.STATUS_INFO,
            "processing": Theme.ACCENT_PRIMARY
        }
        color = colors.get(status, Theme.TEXT_MUTED)
        self.status_icon.setStyleSheet(f"color: {color}; font-size: 10px;")
        
    def append(self, text):
        """追加日志"""
        self.log_area.append(text)
        # 自动展开显示错误
        if "[ERROR]" in text or "错误" in text:
            if not self._is_expanded:
                self.toggle_expand()
                
    def clear(self):
        """清空日志"""
        self.log_area.clear()


class FileDropList(QListWidget):
    """支持拖拽的文件列表"""
    filesDropped = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()
            
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()
            
    def dropEvent(self, event):
        files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith('.dxf'):
                files.append(file_path)
        if files:
            self.filesDropped.emit(files)


# ================= 核心执行引擎 =================
class ScriptRunner(QThread):
    """异步执行引擎"""
    log_out = pyqtSignal(str)
    progress_updated = pyqtSignal(int, str)
    task_completed = pyqtSignal(bool, dict)
    
    def __init__(self, task_type, params):
        super().__init__()
        self.task_type = task_type
        self.params = params
        
    def run(self):
        try:
            self.log_out.emit(f"[SYSTEM] 开始执行 {self.task_type} 任务...")
            self.progress_updated.emit(10, "初始化引擎...")
            
            def log_func(msg):
                msg = msg.replace('✅', '[OK]').replace('❌', '[ERROR]').replace('⚠️', '[WARN]')
                msg = msg.replace('⏳', '[WAIT]').replace('✨', '[DONE]').replace('🔍', '[SCAN]')
                msg = msg.replace('🎨', '[PAINT]').replace('🚀', '[GO]').replace('📊', '[STATS]')
                msg = msg.replace('💡', '[TIP]').replace('📐', '[CALC]').replace('♻️', '[RECYCLE]')
                msg = msg.replace('📋', '[CLIPBOARD]').replace('🔗', '[LINK]').replace('⚙️', '[SETTINGS]')
                self.log_out.emit(msg)
            
            self.progress_updated.emit(30, "加载引擎...")
            
            # 使用 engine_cad_working 作为核心引擎
            import engine_cad_working as engine_cad
            
            if self.task_type == 'autoline':
                engine_cad.run_autoline(self.params, log_func)
            elif self.task_type == 'autopaste':
                engine_cad.run_autopaste(self.params, log_func)
            elif self.task_type == 'autohatch':
                engine_cad.run_autohatch(self.params, log_func)
            elif self.task_type == 'autoclassify':
                engine_cad.run_autoclassify(self.params, log_func)
            elif self.task_type == 'autocut':
                engine_cad.run_autocut(self.params, log_func)
            elif self.task_type == 'autolabel':
                # autolabel 使用独立模块
                from autolabel import AutoLabel
                autolabel = AutoLabel()
                excel_path = self.params.get('excel_path')
                dxf_path = self.params.get('dxf_path')
                output_path = self.params.get('output_path')
                
                if excel_path and dxf_path:
                    success, result = autolabel.run(excel_path, dxf_path, output_path)
                    if success:
                        log_func(f"[OK] 图纸标注完成！")
                        log_func(f"[OK] 输出文件: {result}")
                    else:
                        log_func(f"[ERROR] 图纸标注失败: {result}")
                else:
                    log_func("[ERROR] 请选择Excel和DXF文件")
            
            self.progress_updated.emit(100, "任务完成")
            self.log_out.emit("[SYSTEM] 任务执行完成")
            self.task_completed.emit(True, {})
            
        except Exception as e:
            error_msg = f"[ERROR] 任务执行崩溃:\n{traceback.format_exc()}"
            self.log_out.emit(error_msg)
            self.task_completed.emit(False, {'error': str(e)})


# ================= 主界面 =================
class HydraulicCADv3(QMainWindow):
    """主窗口 - v3.3 现代化 UI"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HydraulicCAD 算量自动化平台 v3.3")
        
        # 设置窗口图标
        icon_path = os.path.join(base_path, "new_logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.resize(1400, 950)
        self.current_task_type = 'autoline'
        self.selected_files = []
        self.output_dir = None
        self.worker_thread = None
        
        # 应用样式
        self.setStyleSheet(get_stylesheet())
        
        # 初始化 UI
        self.init_ui()
        
    def init_ui(self):
        """初始化用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD)
        main_layout.setSpacing(Theme.SPACING_MD)
        
        # 1. 功能区标签
        self.ribbon_tabs = QTabWidget()
        self.ribbon_tabs.setDocumentMode(True)
        
        # 添加各个功能页面
        self.ribbon_tabs.addTab(self.create_autoline_tab(), "🔗 断面合并")
        self.ribbon_tabs.addTab(self.create_autopaste_tab(), "📋 批量粘贴")
        self.ribbon_tabs.addTab(self.create_autohatch_tab(), "🎨 快速填充")
        self.ribbon_tabs.addTab(self.create_autoclassify_tab(), "📐 分类算量")
        self.ribbon_tabs.addTab(self.create_autocut_tab(), "📏 分层算量")
        self.ribbon_tabs.addTab(self.create_autolabel_tab(), "📝 图纸标注")
        
        main_layout.addWidget(self.ribbon_tabs)
        
        # 2. 可折叠日志区域
        self.collapsible_log = CollapsibleLog()
        main_layout.addWidget(self.collapsible_log)
        
        # 3. 底部状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("StatusLabel")
        self.status_bar.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setValue(0)
        self.status_bar.addWidget(self.progress_bar)
        
        self.file_count_label = QLabel("文件：0")
        self.file_count_label.setObjectName("StatusLabel")
        self.status_bar.addWidget(self.file_count_label)
        
    def create_file_selector(self, parent, with_clear=True, compact=False):
        """创建文件选择器组件"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Theme.SPACING_MD)
        
        # 文件列表
        self.file_list_widget = FileDropList()
        self.file_list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list_widget.filesDropped.connect(self.on_files_dropped)
        self.file_list_widget.setMinimumHeight(120 if not compact else 80)
        layout.addWidget(self.file_list_widget, 1)
        
        # 文件操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(Theme.SPACING_SM)
        
        select_btn = QPushButton("📂 选择 DXF 文件")
        select_btn.setObjectName("SelectBtn")
        select_btn.clicked.connect(self.select_files)
        btn_layout.addWidget(select_btn)
        
        if with_clear:
            clear_btn = QPushButton("🗑️ 清空列表")
            clear_btn.setMinimumWidth(90)
            clear_btn.clicked.connect(self.clear_files)
            btn_layout.addWidget(clear_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        return widget
        
    def on_files_dropped(self, files):
        """处理拖拽文件"""
        self.selected_files.clear()
        self.selected_files.extend(files)
        
        self.file_list_widget.clear()
        for p in files:
            file_name = os.path.basename(p)
            file_size = os.path.getsize(p) / 1024
            item = QListWidgetItem(f"📄 {file_name} ({file_size:.1f} KB)")
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.file_list_widget.addItem(item)
        
        self.file_count_label.setText(f"文件：{len(self.selected_files)}")
        self.status_label.setText(f"已选择 {len(self.selected_files)} 个文件")
        self.collapsible_log.set_status(f"已加载 {len(self.selected_files)} 个文件", "success")
        
    def create_output_selector(self, parent, tab_name="default"):
        """创建输出目录选择器 - 每个标签页独立"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Theme.SPACING_SM)
        
        label = QLabel("📁 输出目录：")
        label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(label, 0)
        
        # 为每个标签页创建独立的输出目录标签
        output_label = QLabel("与源文件相同")
        output_label.setObjectName("OutputDirLabel")
        output_label.setMinimumWidth(200)
        layout.addWidget(output_label, 1)
        
        # 存储到字典中
        if not hasattr(self, 'output_dir_labels'):
            self.output_dir_labels = {}
            self.output_dirs = {}
        self.output_dir_labels[tab_name] = output_label
        self.output_dirs[tab_name] = None
        
        output_btn = QPushButton("选择目录")
        output_btn.setMinimumWidth(70)
        output_btn.clicked.connect(lambda: self.select_output_dir(tab_name))
        layout.addWidget(output_btn)
        
        return widget
        
    def select_output_dir(self, tab_name="default"):
        """选择输出目录 - 每个标签页独立"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.output_dirs[tab_name] = dir_path
            self.output_dir_labels[tab_name].setText(dir_path)
            self.output_dir_labels[tab_name].setStyleSheet(f"color: {Theme.TEXT_HIGHLIGHT}; font-size: 12px;")
            
    def create_action_panel(self, btn_text, btn_callback, btn_id="PrimaryActionBtn"):
        """创建操作面板（右侧固定底部按钮）"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Theme.SPACING_MD)
        
        # 进度条
        progress = QProgressBar()
        progress.setValue(0)
        progress.setTextVisible(True)
        progress.setFormat("%p%")
        layout.addWidget(progress)
        
        # 执行按钮
        run_btn = QPushButton(btn_text)
        run_btn.setObjectName(btn_id)
        run_btn.clicked.connect(btn_callback)
        layout.addWidget(run_btn)
        
        return widget, run_btn, progress
        
    def create_file_card(self, title, file_label_attr, file_path_attr, select_callback, clear_callback, btn_text="📂 选择 DXF 文件"):
        """创建文件选择卡片 - 完全参照批量粘贴的源文件卡片样式"""
        card = CardWidget(title)
        card_layout = card.layout()
        
        # 文件标签
        file_label = QLabel("📁 未选择文件")
        file_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        card_layout.addWidget(file_label)
        
        # 存储引用
        setattr(self, file_label_attr, file_label)
        setattr(self, file_path_attr, "")
        
        # 按钮行 - 完全参照批量粘贴样式
        btn_layout = QHBoxLayout()
        select_btn = QPushButton(btn_text)
        select_btn.setObjectName("SelectBtn")
        select_btn.clicked.connect(select_callback)
        btn_layout.addWidget(select_btn)
        
        clear_btn = QPushButton("清空")
        clear_btn.setMinimumWidth(50)
        clear_btn.clicked.connect(clear_callback)
        btn_layout.addWidget(clear_btn)
        
        card_layout.addLayout(btn_layout)
        
        return card
        
    def create_autoline_tab(self):
        """创建断面合并页面"""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD)
        layout.setSpacing(Theme.SPACING_LG)
        
        # 左侧：参数配置卡片（参照批量粘贴源端基准样式）
        params_card = CardWidget("参数配置")
        params_layout = params_card.layout()
        
        params_grid = QGridLayout()
        params_grid.setSpacing(Theme.SPACING_MD)
        
        self.autoline_layer_a = ParamField("图层 A 名称", "断面线 1")
        self.autoline_layer_b = ParamField("图层 B 名称", "断面线 2")
        self.autoline_output_layer = ParamField("输出图层名", "合并后断面线")
        
        params_grid.addWidget(self.autoline_layer_a, 0, 0)
        params_grid.addWidget(self.autoline_layer_b, 0, 1)
        params_grid.addWidget(self.autoline_output_layer, 1, 0)
        
        params_layout.addLayout(params_grid)
        
        layout.addWidget(params_card, 0)
        
        # 右侧：文件和执行区
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(Theme.SPACING_MD)
        
        # 输入文件卡片（参照批量粘贴源文件卡片样式）
        file_card = CardWidget("输入文件")
        file_layout = file_card.layout()
        
        self.autoline_file_label = QLabel("📁 未选择文件")
        self.autoline_file_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        file_layout.addWidget(self.autoline_file_label)
        
        self.autoline_files = []
        file_btn_layout = QHBoxLayout()
        file_btn = QPushButton("📂 选择 DXF 文件")
        file_btn.setObjectName("SelectBtn")
        file_btn.clicked.connect(self.select_autoline_files)
        file_btn_layout.addWidget(file_btn)
        
        file_clear_btn = QPushButton("清空")
        file_clear_btn.setMinimumWidth(50)
        file_clear_btn.clicked.connect(self.clear_autoline_files)
        file_btn_layout.addWidget(file_clear_btn)
        file_layout.addLayout(file_btn_layout)
        
        right_layout.addWidget(file_card)
        
        # 输出目录
        output_widget = self.create_output_selector(page, "autoline")
        right_layout.addWidget(output_widget)
        
        # 操作面板
        action_panel, self.autoline_run_btn, self.autoline_progress = self.create_action_panel(
            "🚀 开始断面合并", self.run_autoline
        )
        right_layout.addWidget(action_panel)
        
        right_layout.addStretch()
        
        layout.addWidget(right_widget, 1)
        
        return page
        
    def select_autoline_files(self):
        """选择断面合并文件"""
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 DXF 文件", "", "DXF Files (*.dxf)")
        if paths:
            self.autoline_files = paths
            if len(paths) == 1:
                file_size = os.path.getsize(paths[0]) / 1024
                self.autoline_file_label.setText(f"📄 {os.path.basename(paths[0])} ({file_size:.1f} KB)")
            else:
                self.autoline_file_label.setText(f"📁 已选择 {len(paths)} 个文件")
            self.autoline_file_label.setStyleSheet(f"color: {Theme.TEXT_HIGHLIGHT}; font-size: 12px;")
            self.selected_files = paths
            self.file_count_label.setText(f"文件：{len(paths)}")
            
    def clear_autoline_files(self):
        """清空断面合并文件"""
        self.autoline_files = []
        self.selected_files = []
        self.autoline_file_label.setText("📁 未选择文件")
        self.autoline_file_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        self.file_count_label.setText("文件：0")
        
    def create_autopaste_tab(self):
        """创建批量粘贴页面 - 双栏卡片布局"""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD)
        layout.setSpacing(Theme.SPACING_LG)
        
        # ===== 左侧：坐标映射区 =====
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(Theme.SPACING_MD)
        
        # 源端基准卡片
        source_card = CardWidget("源端基准 (Source)")
        source_layout = source_card.layout()
        
        source_grid = QGridLayout()
        source_grid.setSpacing(Theme.SPACING_MD)
        
        self.autopaste_src_x0 = ParamField("基准点 X", "86.8540")
        self.autopaste_src_y0 = ParamField("基准点 Y", "-15.0622")
        self.autopaste_src_bx = ParamField("源端基点 X", "86.0030")
        self.autopaste_src_by = ParamField("源端基点 Y", "-35.2980")
        
        source_grid.addWidget(self.autopaste_src_x0, 0, 0)
        source_grid.addWidget(self.autopaste_src_y0, 0, 1)
        source_grid.addWidget(self.autopaste_src_bx, 1, 0)
        source_grid.addWidget(self.autopaste_src_by, 1, 1)
        
        source_layout.addLayout(source_grid)
        left_layout.addWidget(source_card)
        
        # 目标端基准卡片
        target_card = CardWidget("目标端基准 (Target)")
        target_layout = target_card.layout()
        
        target_grid = QGridLayout()
        target_grid.setSpacing(Theme.SPACING_MD)
        
        self.autopaste_spacing = ParamField("断面间距", "-148.4760")
        self.autopaste_dst_y = ParamField("目标桩号 Y", "-1470.5289")
        self.autopaste_dst_by = ParamField("目标基点 Y", "-1363.5000")
        
        target_grid.addWidget(self.autopaste_spacing, 0, 0)
        target_grid.addWidget(self.autopaste_dst_y, 0, 1)
        target_grid.addWidget(self.autopaste_dst_by, 1, 0)
        
        target_layout.addLayout(target_grid)
        left_layout.addWidget(target_card)
        
        left_layout.addStretch()
        
        layout.addWidget(left_widget, 0)
        
        # ===== 右侧：文件与执行区 =====
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(Theme.SPACING_MD)
        
        # 源文件卡片
        src_card = CardWidget("源文件")
        src_layout = src_card.layout()
        
        self.autopaste_src_label = QLabel("📁 未选择源文件")
        self.autopaste_src_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        src_layout.addWidget(self.autopaste_src_label)
        
        self.autopaste_src_path = ""
        src_btn_layout = QHBoxLayout()
        src_btn = QPushButton("📂 选取源断面 DXF")
        src_btn.setObjectName("SelectBtn")
        src_btn.clicked.connect(self.select_autopaste_src)
        src_btn_layout.addWidget(src_btn)
        
        src_clear_btn = QPushButton("清空")
        src_clear_btn.setMinimumWidth(50)
        src_clear_btn.clicked.connect(self.clear_autopaste_src)
        src_btn_layout.addWidget(src_clear_btn)
        src_layout.addLayout(src_btn_layout)
        
        right_layout.addWidget(src_card)
        
        # 目标文件卡片
        dst_card = CardWidget("目标文件")
        dst_layout = dst_card.layout()
        
        self.autopaste_dst_label = QLabel("📁 未选择目标文件")
        self.autopaste_dst_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        dst_layout.addWidget(self.autopaste_dst_label)
        
        self.autopaste_dst_path = ""
        dst_btn_layout = QHBoxLayout()
        dst_btn = QPushButton("🎯 选取目标基准 DXF")
        dst_btn.setObjectName("SelectBtn")
        dst_btn.clicked.connect(self.select_autopaste_dst)
        dst_btn_layout.addWidget(dst_btn)
        
        dst_clear_btn = QPushButton("清空")
        dst_clear_btn.setMinimumWidth(50)
        dst_clear_btn.clicked.connect(self.clear_autopaste_dst)
        dst_btn_layout.addWidget(dst_clear_btn)
        dst_layout.addLayout(dst_btn_layout)
        
        right_layout.addWidget(dst_card)
        
        # 输出目录
        output_widget = self.create_output_selector(page, "autopaste")
        right_layout.addWidget(output_widget)
        
        # 操作面板
        action_panel, self.autopaste_run_btn, self.autopaste_progress = self.create_action_panel(
            "🚀 开始批量粘贴", self.run_autopaste
        )
        right_layout.addWidget(action_panel)
        
        right_layout.addStretch()
        
        layout.addWidget(right_widget, 1)
        
        return page
        
    def create_autohatch_tab(self):
        """创建快速填充页面"""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD)
        layout.setSpacing(Theme.SPACING_LG)
        
        # 左侧：参数配置卡片（参照批量粘贴源端基准样式）
        params_card = CardWidget("填充设置")
        params_layout = params_card.layout()
        
        params_grid = QGridLayout()
        params_grid.setSpacing(Theme.SPACING_MD)
        
        self.autohatch_layer = ParamField("填充层名称", "AA_填充算量层")
        self.autohatch_text_height = ParamField("标注字高", "3.0")
        
        params_grid.addWidget(self.autohatch_layer, 0, 0)
        params_grid.addWidget(self.autohatch_text_height, 0, 1)
        
        params_layout.addLayout(params_grid)
        
        layout.addWidget(params_card, 0)
        
        # 右侧：文件和执行区
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(Theme.SPACING_MD)
        
        # 输入文件卡片（参照批量粘贴源文件卡片样式）
        file_card = CardWidget("输入文件")
        file_layout = file_card.layout()
        
        self.autohatch_file_label = QLabel("📁 未选择文件")
        self.autohatch_file_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        file_layout.addWidget(self.autohatch_file_label)
        
        self.autohatch_files = []
        file_btn_layout = QHBoxLayout()
        file_btn = QPushButton("📂 选择 DXF 文件")
        file_btn.setObjectName("SelectBtn")
        file_btn.clicked.connect(self.select_autohatch_files)
        file_btn_layout.addWidget(file_btn)
        
        file_clear_btn = QPushButton("清空")
        file_clear_btn.setMinimumWidth(50)
        file_clear_btn.clicked.connect(self.clear_autohatch_files)
        file_btn_layout.addWidget(file_clear_btn)
        file_layout.addLayout(file_btn_layout)
        
        right_layout.addWidget(file_card)
        
        # 输出目录
        output_widget = self.create_output_selector(page, "autohatch")
        right_layout.addWidget(output_widget)
        
        # 操作面板
        action_panel, self.autohatch_run_btn, self.autohatch_progress = self.create_action_panel(
            "🚀 开始快速填充", self.run_autohatch
        )
        right_layout.addWidget(action_panel)
        
        right_layout.addStretch()
        
        layout.addWidget(right_widget, 1)
        
        return page
        
    def select_autohatch_files(self):
        """选择快速填充文件"""
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 DXF 文件", "", "DXF Files (*.dxf)")
        if paths:
            self.autohatch_files = paths
            if len(paths) == 1:
                file_size = os.path.getsize(paths[0]) / 1024
                self.autohatch_file_label.setText(f"📄 {os.path.basename(paths[0])} ({file_size:.1f} KB)")
            else:
                self.autohatch_file_label.setText(f"📁 已选择 {len(paths)} 个文件")
            self.autohatch_file_label.setStyleSheet(f"color: {Theme.TEXT_HIGHLIGHT}; font-size: 12px;")
            self.selected_files = paths
            self.file_count_label.setText(f"文件：{len(paths)}")
            
    def clear_autohatch_files(self):
        """清空快速填充文件"""
        self.autohatch_files = []
        self.selected_files = []
        self.autohatch_file_label.setText("📁 未选择文件")
        self.autohatch_file_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        self.file_count_label.setText("文件：0")
        
    def create_autoclassify_tab(self):
        """创建分类算量页面"""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD)
        layout.setSpacing(Theme.SPACING_LG)
        
        # 左侧：参数配置卡片（参照批量粘贴源端基准样式）
        params_card = CardWidget("图层名称设置")
        params_layout = params_card.layout()
        
        params_grid = QGridLayout()
        params_grid.setSpacing(Theme.SPACING_MD)
        
        # 第一行：断面线图层1
        self.autoclassify_section1 = ParamField("断面线图层1", "DMX")
        params_grid.addWidget(self.autoclassify_section1, 0, 0)
        
        # 第二行：断面线图层2（合并用，勾选时显示）
        self.autoclassify_section2 = ParamField("断面线图层2", "断面线")
        params_grid.addWidget(self.autoclassify_section2, 1, 0)
        
        # 第三行：桩号图层
        self.autoclassify_station = ParamField("桩号图层", "0-桩号")
        params_grid.addWidget(self.autoclassify_station, 2, 0)
        
        # 合并断面线选项 - 控制第二个图层输入框的显示
        self.autoclassify_merge = QCheckBox("合并断面线")
        self.autoclassify_merge.setChecked(True)
        self.autoclassify_merge.stateChanged.connect(self.on_autoclassify_merge_changed)
        params_grid.addWidget(self.autoclassify_merge, 2, 1)
        
        # 初始化：勾选状态显示第二个图层输入框
        self.autoclassify_section2.setVisible(self.autoclassify_merge.isChecked())
        
        params_layout.addLayout(params_grid)
        
        layout.addWidget(params_card, 0)
        
        # 右侧：文件和执行区
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(Theme.SPACING_MD)
        
        # 输入文件卡片（参照批量粘贴源文件卡片样式）
        file_card = CardWidget("输入文件")
        file_layout = file_card.layout()
        
        self.autoclassify_file_label = QLabel("📁 未选择文件")
        self.autoclassify_file_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        file_layout.addWidget(self.autoclassify_file_label)
        
        self.autoclassify_files = []
        file_btn_layout = QHBoxLayout()
        file_btn = QPushButton("📂 选择 DXF 文件")
        file_btn.setObjectName("SelectBtn")
        file_btn.clicked.connect(self.select_autoclassify_files)
        file_btn_layout.addWidget(file_btn)
        
        file_clear_btn = QPushButton("清空")
        file_clear_btn.setMinimumWidth(50)
        file_clear_btn.clicked.connect(self.clear_autoclassify_files)
        file_btn_layout.addWidget(file_clear_btn)
        file_layout.addLayout(file_btn_layout)
        
        right_layout.addWidget(file_card)
        
        # 输出目录
        output_widget = self.create_output_selector(page, "autoclassify")
        right_layout.addWidget(output_widget)
        
        # 操作面板
        action_panel, self.autoclassify_run_btn, self.autoclassify_progress = self.create_action_panel(
            "🚀 开始分类算量", self.run_autoclassify
        )
        right_layout.addWidget(action_panel)
        
        right_layout.addStretch()
        
        layout.addWidget(right_widget, 1)
        
        return page
        
    def select_autoclassify_files(self):
        """选择分类算量文件"""
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 DXF 文件", "", "DXF Files (*.dxf)")
        if paths:
            self.autoclassify_files = paths
            if len(paths) == 1:
                file_size = os.path.getsize(paths[0]) / 1024
                self.autoclassify_file_label.setText(f"📄 {os.path.basename(paths[0])} ({file_size:.1f} KB)")
            else:
                self.autoclassify_file_label.setText(f"📁 已选择 {len(paths)} 个文件")
            self.autoclassify_file_label.setStyleSheet(f"color: {Theme.TEXT_HIGHLIGHT}; font-size: 12px;")
            self.selected_files = paths
            self.file_count_label.setText(f"文件：{len(paths)}")
            
    def clear_autoclassify_files(self):
        """清空分类算量文件"""
        self.autoclassify_files = []
        self.selected_files = []
        self.autoclassify_file_label.setText("📁 未选择文件")
        self.autoclassify_file_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        self.file_count_label.setText("文件：0")
        
    def create_autocut_tab(self):
        """创建分层算量页面"""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD)
        layout.setSpacing(Theme.SPACING_LG)
        
        # 左侧：参数配置卡片（参照批量粘贴源端基准样式）
        params_card = CardWidget("分层参数")
        params_layout = params_card.layout()
        
        params_grid = QGridLayout()
        params_grid.setSpacing(Theme.SPACING_MD)
        
        self.autocut_elevation = ParamField("分层线高程(m)", "-5")
        
        params_grid.addWidget(self.autocut_elevation, 0, 0)
        
        params_layout.addLayout(params_grid)
        
        layout.addWidget(params_card, 0)
        
        # 右侧：文件和执行区
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(Theme.SPACING_MD)
        
        # 输入文件卡片（参照批量粘贴源文件卡片样式）
        file_card = CardWidget("输入文件")
        file_layout = file_card.layout()
        
        self.autocut_file_label = QLabel("📁 未选择文件")
        self.autocut_file_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        file_layout.addWidget(self.autocut_file_label)
        
        self.autocut_files = []
        file_btn_layout = QHBoxLayout()
        file_btn = QPushButton("📂 选择 DXF 文件")
        file_btn.setObjectName("SelectBtn")
        file_btn.clicked.connect(self.select_autocut_files)
        file_btn_layout.addWidget(file_btn)
        
        file_clear_btn = QPushButton("清空")
        file_clear_btn.setMinimumWidth(50)
        file_clear_btn.clicked.connect(self.clear_autocut_files)
        file_btn_layout.addWidget(file_clear_btn)
        file_layout.addLayout(file_btn_layout)
        
        right_layout.addWidget(file_card)
        
        # 输出目录
        output_widget = self.create_output_selector(page, "autocut")
        right_layout.addWidget(output_widget)
        
        # 操作面板
        action_panel, self.autocut_run_btn, self.autocut_progress = self.create_action_panel(
            "🚀 开始分层算量", self.run_autocut
        )
        right_layout.addWidget(action_panel)
        
        right_layout.addStretch()
        
        layout.addWidget(right_widget, 1)
        
        return page
        
    def select_autocut_files(self):
        """选择分层算量文件"""
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 DXF 文件", "", "DXF Files (*.dxf)")
        if paths:
            self.autocut_files = paths
            if len(paths) == 1:
                file_size = os.path.getsize(paths[0]) / 1024
                self.autocut_file_label.setText(f"📄 {os.path.basename(paths[0])} ({file_size:.1f} KB)")
            else:
                self.autocut_file_label.setText(f"📁 已选择 {len(paths)} 个文件")
            self.autocut_file_label.setStyleSheet(f"color: {Theme.TEXT_HIGHLIGHT}; font-size: 12px;")
            self.selected_files = paths
            self.file_count_label.setText(f"文件：{len(paths)}")
            
    def clear_autocut_files(self):
        """清空分层算量文件"""
        self.autocut_files = []
        self.selected_files = []
        self.autocut_file_label.setText("📁 未选择文件")
        self.autocut_file_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        self.file_count_label.setText("文件：0")
        
    def create_autolabel_tab(self):
        """创建图纸标注页面"""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD, Theme.SPACING_MD)
        layout.setSpacing(Theme.SPACING_LG)
        
        # 左侧：功能说明卡片
        info_card = CardWidget("功能说明")
        info_layout = info_card.layout()
        
        info_label = QLabel("""
<h3 style='color: #4EC9B0;'>📝 图纸标注功能</h3>
<br>
<table style='color: #CCCCCC; font-size: 12px; line-height: 1.8;'>
<tr><td style='padding-right: 10px;'>✅</td><td>从Excel工程量表汇总数据</td></tr>
<tr><td style='padding-right: 10px;'>✅</td><td>更新DXF面积标注</td></tr>
<tr><td style='padding-right: 10px;'>✅</td><td>自动验证更新结果</td></tr>
</table>
        """)
        info_label.setStyleSheet("padding: 10px;")
        info_layout.addWidget(info_label)
        
        layout.addWidget(info_card, 0)
        
        # 右侧：文件和执行区
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(Theme.SPACING_MD)
        
        # Excel文件卡片
        excel_card = CardWidget("Excel工程量表")
        excel_layout = excel_card.layout()
        
        self.autolabel_excel_label = QLabel("📁 未选择Excel文件")
        self.autolabel_excel_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        excel_layout.addWidget(self.autolabel_excel_label)
        
        self.autolabel_excel_path = ""
        excel_btn = QPushButton("📂 选取Excel文件")
        excel_btn.setObjectName("SelectBtn")
        excel_btn.clicked.connect(self.select_autolabel_excel)
        excel_layout.addWidget(excel_btn)
        
        right_layout.addWidget(excel_card)
        
        # DXF文件卡片
        dxf_card = CardWidget("DXF断面图")
        dxf_layout = dxf_card.layout()
        
        self.autolabel_dxf_label = QLabel("📁 未选择DXF文件")
        self.autolabel_dxf_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        dxf_layout.addWidget(self.autolabel_dxf_label)
        
        self.autolabel_dxf_path = ""
        dxf_btn = QPushButton("🎯 选取DXF文件")
        dxf_btn.setObjectName("SelectBtn")
        dxf_btn.clicked.connect(self.select_autolabel_dxf)
        dxf_layout.addWidget(dxf_btn)
        
        right_layout.addWidget(dxf_card)
        
        # 输出目录
        output_widget = self.create_output_selector(page, "autolabel")
        right_layout.addWidget(output_widget)
        
        # 操作面板
        action_panel, self.autolabel_run_btn, self.autolabel_progress = self.create_action_panel(
            "🚀 开始图纸标注", self.run_autolabel
        )
        right_layout.addWidget(action_panel)
        
        right_layout.addStretch()
        
        layout.addWidget(right_widget, 1)
        
        return page
        
    def select_files(self):
        """选择 DXF 文件"""
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 DXF 文件", "", "DXF Files (*.dxf)")
        if paths:
            self.selected_files.clear()
            self.selected_files.extend(paths)
            
            # 更新文件标签显示
            if hasattr(self, 'file_label'):
                if len(paths) == 1:
                    file_size = os.path.getsize(paths[0]) / 1024
                    self.file_label.setText(f"📄 {os.path.basename(paths[0])} ({file_size:.1f} KB)")
                else:
                    self.file_label.setText(f"📁 已选择 {len(paths)} 个文件")
                self.file_label.setStyleSheet(f"color: {Theme.TEXT_HIGHLIGHT}; font-size: 12px;")
            
            self.file_count_label.setText(f"文件：{len(self.selected_files)}")
            self.status_label.setText(f"已选择 {len(self.selected_files)} 个文件")
            self.collapsible_log.set_status(f"已加载 {len(self.selected_files)} 个文件", "success")
            
    def clear_files(self):
        """清空文件列表"""
        self.selected_files.clear()
        
        # 更新文件标签显示
        if hasattr(self, 'file_label'):
            self.file_label.setText("📁 未选择文件")
            self.file_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
        
        self.file_count_label.setText("文件：0")
        self.status_label.setText("文件列表已清空")
        self.collapsible_log.set_status("准备就绪", "info")
        
    def select_autopaste_src(self):
        """选择批量粘贴源文件"""
        path, _ = QFileDialog.getOpenFileName(self, "选择源断面 DXF", "", "DXF Files (*.dxf)")
        if path:
            self.autopaste_src_path = path
            file_size = os.path.getsize(path) / 1024
            self.autopaste_src_label.setText(f"📄 {os.path.basename(path)} ({file_size:.1f} KB)")
            self.autopaste_src_label.setStyleSheet(f"color: {Theme.TEXT_HIGHLIGHT}; font-size: 12px;")
            
    def clear_autopaste_src(self):
        """清空源文件"""
        self.autopaste_src_path = ""
        self.autopaste_src_label.setText("📁 未选择源文件")
        self.autopaste_src_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
            
    def select_autopaste_dst(self):
        """选择批量粘贴目标文件"""
        path, _ = QFileDialog.getOpenFileName(self, "选择目标基准 DXF", "", "DXF Files (*.dxf)")
        if path:
            self.autopaste_dst_path = path
            file_size = os.path.getsize(path) / 1024
            self.autopaste_dst_label.setText(f"🎯 {os.path.basename(path)} ({file_size:.1f} KB)")
            self.autopaste_dst_label.setStyleSheet(f"color: {Theme.TEXT_HIGHLIGHT}; font-size: 12px;")
            
    def clear_autopaste_dst(self):
        """清空目标文件"""
        self.autopaste_dst_path = ""
        self.autopaste_dst_label.setText("📁 未选择目标文件")
        self.autopaste_dst_label.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 12px;")
            
    def select_autolabel_excel(self):
        """选择图纸标注Excel文件"""
        path, _ = QFileDialog.getOpenFileName(self, "选择Excel工程量表", "", "Excel Files (*.xlsx *.xls)")
        if path:
            self.autolabel_excel_path = path
            file_size = os.path.getsize(path) / 1024
            self.autolabel_excel_label.setText(f"📊 {os.path.basename(path)} ({file_size:.1f} KB)")
            self.autolabel_excel_label.setStyleSheet(f"color: {Theme.TEXT_HIGHLIGHT}; font-size: 12px;")
            
    def select_autolabel_dxf(self):
        """选择图纸标注DXF文件"""
        path, _ = QFileDialog.getOpenFileName(self, "选择DXF断面图", "", "DXF Files (*.dxf)")
        if path:
            self.autolabel_dxf_path = path
            file_size = os.path.getsize(path) / 1024
            self.autolabel_dxf_label.setText(f"📄 {os.path.basename(path)} ({file_size:.1f} KB)")
            self.autolabel_dxf_label.setStyleSheet(f"color: {Theme.TEXT_HIGHLIGHT}; font-size: 12px;")
        
    def run_autoline(self):
        """执行断面合并任务"""
        if not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择 DXF 文件")
            return
            
        self.collapsible_log.clear()
        self.collapsible_log.append("<b>[系统]</b> 正在开启断面合并任务...")
        self.collapsible_log.set_status("正在处理...", "processing")
        
        params = {
            '图层A名称': self.autoline_layer_a.text(),
            '图层B名称': self.autoline_layer_b.text(),
            '输出图层名': self.autoline_output_layer.text(),
            '输出目录': self.output_dir,
            'files': self.selected_files
        }
        
        self.start_task('autoline', params, self.autoline_run_btn, self.autoline_progress)
        
    def run_autopaste(self):
        """执行批量粘贴任务"""
        if not self.autopaste_src_path or not self.autopaste_dst_path:
            QMessageBox.warning(self, "警告", "请选择源文件和目标文件")
            return
            
        self.collapsible_log.clear()
        self.collapsible_log.append("<b>[系统]</b> 正在开启批量粘贴任务...")
        self.collapsible_log.set_status("正在处理...", "processing")
        
        params = {
            '源端 0 点 X': self.autopaste_src_x0.text(),
            '源端 0 点 Y': self.autopaste_src_y0.text(),
            '源端基点 X': self.autopaste_src_bx.text(),
            '源端基点 Y': self.autopaste_src_by.text(),
            '断面间距': self.autopaste_spacing.text(),
            '目标桩号 Y': self.autopaste_dst_y.text(),
            '目标基点 Y': self.autopaste_dst_by.text(),
            '源文件名': self.autopaste_src_path,
            '目标文件名': self.autopaste_dst_path,
            '输出目录': self.output_dir,
            'files': [self.autopaste_src_path]
        }
        
        self.start_task('autopaste', params, self.autopaste_run_btn, self.autopaste_progress)
        
    def run_autohatch(self):
        """执行快速填充任务"""
        if not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择 DXF 文件")
            return
            
        self.collapsible_log.clear()
        self.collapsible_log.append("<b>[系统]</b> 正在开启快速填充任务...")
        self.collapsible_log.set_status("正在处理...", "processing")
        
        params = {
            '填充层名称': self.autohatch_layer.text(),
            '输出目录': self.output_dir,
            'files': self.selected_files
        }
        
        self.start_task('autohatch', params, self.autohatch_run_btn, self.autohatch_progress)
        
    def on_autoclassify_merge_changed(self, state):
        """合并断面线选项状态变化"""
        # 勾选时显示第二个图层输入框，不勾选时隐藏
        self.autoclassify_section2.setVisible(state == Qt.CheckState.Checked.value)
        
    def run_autoclassify(self):
        """执行分类算量任务"""
        if not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择 DXF 文件")
            return
            
        self.collapsible_log.clear()
        self.collapsible_log.append("<b>[系统]</b> 正在开启分类算量任务...")
        self.collapsible_log.set_status("正在处理...", "processing")
        
        # 根据勾选状态决定断面线图层参数
        if self.autoclassify_merge.isChecked():
            # 勾选：两个图层用逗号连接
            section_layers = f"{self.autoclassify_section1.text()},{self.autoclassify_section2.text()}"
        else:
            # 不勾选：只用第一个图层
            section_layers = self.autoclassify_section1.text()
        
        # 参数名与 engine_cad_working.py run_autoclassify 完全匹配
        params = {
            '断面线图层': section_layers,
            '桩号图层': self.autoclassify_station.text(),
            '合并断面线': self.autoclassify_merge.isChecked(),
            '输出目录': self.output_dir,
            'files': self.selected_files
        }
        
        self.start_task('autoclassify', params, self.autoclassify_run_btn, self.autoclassify_progress)
        
    def run_autocut(self):
        """执行分层算量任务"""
        if not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择 DXF 文件")
            return
            
        self.collapsible_log.clear()
        self.collapsible_log.append("<b>[系统]</b> 正在开启分层算量任务...")
        self.collapsible_log.set_status("正在处理...", "processing")
        
        params = {
            '分层线高程': self.autocut_elevation.text(),
            '输出目录': self.output_dir,
            'files': self.selected_files
        }
        
        self.start_task('autocut', params, self.autocut_run_btn, self.autocut_progress)
        
    def run_autolabel(self):
        """执行图纸标注任务"""
        if not self.autolabel_excel_path or not self.autolabel_dxf_path:
            QMessageBox.warning(self, "警告", "请选择Excel和DXF文件")
            return
            
        self.collapsible_log.clear()
        self.collapsible_log.append("<b>[系统]</b> 正在开启图纸标注任务...")
        self.collapsible_log.set_status("正在处理...", "processing")
        
        params = {
            'excel_path': self.autolabel_excel_path,
            'dxf_path': self.autolabel_dxf_path,
            'output_path': self.output_dir
        }
        
        self.start_task('autolabel', params, self.autolabel_run_btn, self.autolabel_progress)
        
    def start_task(self, task_type, params, trigger_btn, progress_bar):
        """启动异步任务"""
        trigger_btn.setEnabled(False)
        progress_bar.setValue(0)
        self.status_label.setText("正在处理...")
        
        self.worker_thread = ScriptRunner(task_type, params)
        self.worker_thread.log_out.connect(self.collapsible_log.append)
        self.worker_thread.progress_updated.connect(
            lambda value, msg: self.update_progress(value, msg, progress_bar)
        )
        self.worker_thread.task_completed.connect(
            lambda success, result: self.on_task_completed(success, result, trigger_btn, progress_bar)
        )
        self.worker_thread.start()
        
    def update_progress(self, value, message, progress_bar):
        """更新进度"""
        progress_bar.setValue(value)
        if message:
            self.status_label.setText(message)
            self.collapsible_log.set_status(message, "processing")
            
    def on_task_completed(self, success, result, trigger_btn, progress_bar):
        """任务完成回调"""
        trigger_btn.setEnabled(True)
        
        if success:
            self.status_label.setText("处理完成")
            progress_bar.setValue(100)
            self.collapsible_log.set_status("处理完成 ✓", "success")
            QMessageBox.information(self, "成功", "任务处理完成！")
        else:
            self.status_label.setText("处理失败")
            self.collapsible_log.set_status("处理失败 ✗", "error")
            error_msg = result.get('error', '未知错误')
            QMessageBox.critical(self, "错误", f"任务处理失败:\n{error_msg}")


# ================= 应用程序入口 =================
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = HydraulicCADv3()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()