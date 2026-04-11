# -*- coding: utf-8 -*-
"""
航道断面算量自动化平台 v3.0 - 独立版前端UI
无需后端服务，直接调用 engine_cad 模块
现代化深色主题设计
"""

import sys
import os
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QGroupBox, QMessageBox, QProgressBar, QTabWidget, QFrame,
    QScrollArea, QCheckBox, QStatusBar, QSplitter, QSizePolicy,
    QSpacerItem, QGridLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QPalette, QPixmap, QPainter, QPen, QBrush, QLinearGradient

# ==================== 导入核心模块 ====================
try:
    # 尝试导入 engine_cad
    import engine_cad
    ENGINE_AVAILABLE = True
except ImportError:
    ENGINE_AVAILABLE = False
    print("[警告] engine_cad 模块未找到")

# ==================== 样式表 ====================
STYLESHEET = """
/* 全局样式 */
QMainWindow, QWidget {
    background-color: #0F0F0F;
    color: #E4E3E0;
    font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
}

/* 主容器 */
#MainContainer {
    background-color: #141414;
    border: 1px solid #2A2A2A;
    border-radius: 16px;
}

/* 顶部导航栏 */
#Header {
    background-color: #1A1A1A;
    border-bottom: 1px solid #2A2A2A;
    border-top-left-radius: 16px;
    border-top-right-radius: 16px;
}

/* 标题 */
#TitleLabel {
    font-size: 22px;
    font-weight: bold;
    font-style: italic;
}

/* 标签页 */
QTabWidget::pane {
    border: none;
    background-color: #141414;
}
QTabBar::tab {
    background-color: #1A1A1A;
    color: #707070;
    padding: 16px 24px;
    font-size: 14px;
    font-weight: 500;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #E4E3E0;
    background-color: #141414;
    border-bottom: 2px solid #E4E3E0;
}
QTabBar::tab:hover:!selected {
    color: #E4E3E0;
}

/* 输入框 */
QLineEdit {
    background-color: #1A1A1A;
    border: 1px solid #2A2A2A;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 14px;
    font-family: 'Consolas', 'Microsoft YaHei UI';
    color: #E4E3E0;
}
QLineEdit:focus {
    border: 1px solid #E4E3E0;
}

/* 按钮 */
QPushButton {
    background-color: #2A2A2A;
    color: #E4E3E0;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #333333;
}

/* 主按钮 */
#PrimaryButton {
    background-color: #E4E3E0;
    color: #0F0F0F;
    font-size: 18px;
    font-weight: bold;
    padding: 16px 32px;
    border-radius: 12px;
}
#PrimaryButton:hover {
    background-color: #FFFFFF;
}
#PrimaryButton:disabled {
    background-color: #2A2A2A;
    color: #555555;
}

/* 文件行 */
#FileRow {
    background-color: #1A1A1A;
    border: 1px solid #2A2A2A;
    border-radius: 8px;
}

/* 日志区域 */
QTextEdit {
    background-color: rgba(0, 0, 0, 0.4);
    border: none;
    border-radius: 8px;
    padding: 8px;
    font-family: 'Consolas', 'Microsoft YaHei UI';
    font-size: 13px;
    color: #E4E3E0;
}

/* 复选框 */
QCheckBox {
    spacing: 8px;
    font-size: 14px;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 4px;
    border: 2px solid #333333;
    background-color: #0F0F0F;
}
QCheckBox::indicator:checked {
    background-color: #E4E3E0;
    border-color: #E4E3E0;
}

/* 滚动条 */
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #2A2A2A;
    border-radius: 3px;
    min-height: 20px;
}

/* 状态栏 */
QStatusBar {
    background-color: #1A1A1A;
    border-top: 1px solid #2A2A2A;
    color: #707070;
    font-size: 11px;
}

/* 进度条 */
QProgressBar {
    background-color: #2A2A2A;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #E4E3E0;
    border-radius: 4px;
}
"""

# ==================== 工具配置 ====================
TOOL_CONFIG = {
    'autoline': {
        'name': '断面合并',
        'desc': '将两个断面线图层合并，生成下包络线',
        'function': 'run_autoline'
    },
    'autopaste': {
        'name': '批量粘贴',
        'desc': '将源断面图批量粘贴到目标图纸',
        'function': 'run_autopaste'
    },
    'autohatch': {
        'name': '快速填充',
        'desc': '自动识别封闭区域并填充，计算面积',
        'function': 'run_autohatch'
    },
    'autoclassify': {
        'name': '分类算量',
        'desc': '自动区分设计量和超挖量，按地层分类统计',
        'function': 'run_autoclassify'
    },
    'autocut': {
        'name': '分层算量',
        'desc': '计算指定高程分层线以上的填充面积',
        'function': 'run_autocut'
    }
}

# ==================== 启动画面 ====================
class SplashScreen(QWidget):
    """启动画面"""
    
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(500, 600)
        
        # 加载 Logo
        self.logo_pixmap = None
        logo_path = Path(r"C:\Users\训教\Downloads\Gemini_Generated_Image_3db1n53db1n53db1.png")
        if logo_path.exists():
            self.logo_pixmap = QPixmap(str(logo_path))
        
        self.progress = 0
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 60, 40, 40)
        layout.setSpacing(20)
        
        # Logo
        if self.logo_pixmap:
            logo_label = QLabel()
            logo_label.setPixmap(self.logo_pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(logo_label)
        
        # 标题
        title = QLabel("航道断面算量自动化平台")
        title.setStyleSheet("font-size: 28px; font-weight: bold; font-style: italic; letter-spacing: 0.15em;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # 副标题
        subtitle = QLabel("WATERWAY SECTION AUTOMATION PLATFORM")
        subtitle.setStyleSheet("font-size: 10px; opacity: 0.3; letter-spacing: 0.3em; font-family: 'Consolas';")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        
        layout.addSpacing(40)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        layout.addWidget(self.progress_bar)
        
        # 启动动画
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress)
        self.timer.start(30)
        
    def update_progress(self):
        self.progress += 1
        self.progress_bar.setValue(self.progress)
        if self.progress >= 100:
            self.timer.stop()
            self.close()


# ==================== 文件选择行 ====================
class FileRowWidget(QFrame):
    """文件选择行"""
    
    fileSelected = pyqtSignal(dict)
    fileCleared = pyqtSignal()
    
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.label_text = label
        self.file_info = None
        self.setup_ui()
        
    def setup_ui(self):
        self.setObjectName("FileRow")
        self.setFixedHeight(64)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        
        # 标签
        label = QLabel(self.label_text)
        label.setFixedWidth(80)
        label.setStyleSheet("font-size: 12px; font-family: 'Consolas'; opacity: 0.4;")
        layout.addWidget(label)
        
        # 文件信息
        self.file_label = QLabel("未选择文件")
        self.file_label.setStyleSheet("font-size: 14px; font-family: 'Consolas'; opacity: 0.3; font-style: italic;")
        layout.addWidget(self.file_label, 1)
        
        # 按钮
        self.select_btn = QPushButton("选择")
        self.select_btn.setFixedSize(80, 36)
        self.select_btn.setStyleSheet("""
            QPushButton {
                background-color: #E4E3E0;
                color: #0F0F0F;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #FFFFFF;
            }
        """)
        self.select_btn.clicked.connect(self.select_file)
        layout.addWidget(self.select_btn)
        
        self.clear_btn = QPushButton("✕")
        self.clear_btn.setFixedSize(36, 36)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #FF5555;
                font-size: 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: rgba(255, 85, 85, 0.1);
            }
        """)
        self.clear_btn.setVisible(False)
        self.clear_btn.clicked.connect(self.clear_file)
        layout.addWidget(self.clear_btn)
        
    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择 DXF 文件", "", "DXF Files (*.dxf)")
        if file_path:
            self.file_info = {
                'name': os.path.basename(file_path),
                'path': file_path,
                'size': os.path.getsize(file_path)
            }
            self.file_label.setText(f"✓ {self.file_info['name']}")
            self.file_label.setStyleSheet("font-size: 14px; font-family: 'Consolas'; color: #50FA7B;")
            self.select_btn.setVisible(False)
            self.clear_btn.setVisible(True)
            self.fileSelected.emit(self.file_info)
            
    def clear_file(self):
        self.file_info = None
        self.file_label.setText("未选择文件")
        self.file_label.setStyleSheet("font-size: 14px; font-family: 'Consolas'; opacity: 0.3; font-style: italic;")
        self.select_btn.setVisible(True)
        self.clear_btn.setVisible(False)
        self.fileCleared.emit()


# ==================== 参数输入组件 ====================
class ParamInputWidget(QWidget):
    """参数输入"""
    
    def __init__(self, label: str, value: str = "", is_path: bool = False, parent=None):
        super().__init__(parent)
        self.is_path = is_path
        self.setup_ui(label, value)
        
    def setup_ui(self, label: str, value: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(10)
        
        # 标签
        label_widget = QLabel(label.upper())
        label_widget.setStyleSheet("font-size: 13px; font-family: 'Consolas'; opacity: 0.5; letter-spacing: 0.1em;")
        layout.addWidget(label_widget)
        
        # 输入框
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)
        
        self.line_edit = QLineEdit(value)
        self.line_edit.setMinimumHeight(44)
        input_layout.addWidget(self.line_edit, 1)
        
        if self.is_path:
            browse_btn = QPushButton("📁")
            browse_btn.setFixedSize(40, 44)
            browse_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1A1A1A;
                    border: 1px solid #2A2A2A;
                    border-radius: 8px;
                    font-size: 16px;
                }
                QPushButton:hover {
                    border-color: #E4E3E0;
                }
            """)
            browse_btn.clicked.connect(self.browse_path)
            input_layout.addWidget(browse_btn)
        
        layout.addLayout(input_layout)
        
    def browse_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.line_edit.setText(dir_path)
            
    def get_value(self) -> str:
        return self.line_edit.text()
        
    def set_value(self, value: str):
        self.line_edit.setText(value)


# ==================== 主窗口 ====================
class HydraulicCADPlatform(QMainWindow):
    """主窗口 - 独立版"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("航道断面算量自动化平台 v3.0")
        self.setMinimumSize(1280, 800)
        self.resize(1280, 800)
        
        # 当前任务类型
        self.current_task = "autoline"
        
        # 文件信息
        self.selected_file = None
        self.source_file = None
        self.target_file = None
        
        # 执行状态
        self.executing = False
        
        # 结果列表
        self.results = []
        
        self.init_ui()
        
    def init_ui(self):
        """初始化界面"""
        central_widget = QWidget()
        central_widget.setObjectName("MainContainer")
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 顶部导航栏
        self.create_header(main_layout)
        
        # 主体内容区
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 左侧面板 (60%)
        left_panel = self.create_left_panel()
        content_layout.addWidget(left_panel, 6)
        
        # 右侧面板 (40%)
        right_panel = self.create_right_panel()
        content_layout.addWidget(right_panel, 4)
        
        main_layout.addWidget(content, 1)
        
        # 底部状态栏
        self.create_status_bar(main_layout)
        
        self.setStyleSheet(STYLESHEET)
        
    def create_header(self, parent_layout):
        """创建顶部导航栏"""
        header = QWidget()
        header.setObjectName("Header")
        header.setFixedHeight(80)
        
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 16, 24, 16)
        
        # Logo 和标题
        left_section = QHBoxLayout()
        left_section.setSpacing(16)
        
        # Logo
        logo_path = Path(r"C:\Users\训教\Downloads\Gemini_Generated_Image_3db1n53db1n53db1.png")
        if logo_path.exists():
            logo_label = QLabel()
            pixmap = QPixmap(str(logo_path)).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pixmap)
            left_section.addWidget(logo_label)
        
        # 标题
        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        
        title = QLabel("航道断面算量自动化平台")
        title.setObjectName("TitleLabel")
        title_layout.addWidget(title)
        
        # 引擎状态
        status_layout = QHBoxLayout()
        status_layout.setSpacing(8)
        
        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(8, 8)
        if ENGINE_AVAILABLE:
            self.status_indicator.setStyleSheet("background-color: #50FA7B; border-radius: 4px;")
            status_text = "引擎状态: 已就绪"
        else:
            self.status_indicator.setStyleSheet("background-color: #FF5555; border-radius: 4px;")
            status_text = "引擎状态: 未加载"
        
        status_layout.addWidget(self.status_indicator)
        
        self.status_label = QLabel(status_text)
        self.status_label.setStyleSheet("font-size: 11px; font-family: 'Consolas'; opacity: 0.5;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        title_layout.addLayout(status_layout)
        
        left_section.addLayout(title_layout)
        header_layout.addLayout(left_section)
        header_layout.addStretch()
        
        parent_layout.addWidget(header)
        
    def create_left_panel(self) -> QWidget:
        """创建左侧面板"""
        panel = QWidget()
        panel.setStyleSheet("background-color: #141414;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 标签页
        self.tab_bar = QTabWidget()
        
        tabs = [
            ("autoline", "断面合并"),
            ("autopaste", "批量粘贴"),
            ("autohatch", "快速填充"),
            ("autoclassify", "分类算量"),
            ("autocut", "分层算量")
        ]
        
        for task_id, task_name in tabs:
            tab_widget = self.create_tab_content(task_id)
            self.tab_bar.addTab(tab_widget, task_name)
            
        self.tab_bar.currentChanged.connect(self.on_tab_changed)
        layout.addWidget(self.tab_bar, 1)
        
        return panel
        
    def create_tab_content(self, task_type: str) -> QWidget:
        """创建标签页内容"""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)
        
        # 文件选择
        file_section = QWidget()
        file_layout = QVBoxLayout(file_section)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(12)
        
        file_title = QLabel("📄 文件选择")
        file_title.setStyleSheet("font-size: 12px; font-family: 'Consolas'; opacity: 0.4;")
        file_layout.addWidget(file_title)
        
        if task_type == "autopaste":
            self.source_file_row = FileRowWidget("源文件")
            self.source_file_row.fileSelected.connect(lambda f: setattr(self, 'source_file', f))
            self.source_file_row.fileCleared.connect(lambda: setattr(self, 'source_file', None))
            file_layout.addWidget(self.source_file_row)
            
            self.target_file_row = FileRowWidget("目标文件")
            self.target_file_row.fileSelected.connect(lambda f: setattr(self, 'target_file', f))
            self.target_file_row.fileCleared.connect(lambda: setattr(self, 'target_file', None))
            file_layout.addWidget(self.target_file_row)
        else:
            self.file_row = FileRowWidget("待处理 DXF")
            self.file_row.fileSelected.connect(lambda f: setattr(self, 'selected_file', f))
            self.file_row.fileCleared.connect(lambda: setattr(self, 'selected_file', None))
            file_layout.addWidget(self.file_row)
            
        layout.addWidget(file_section)
        
        # 参数配置
        param_section = QWidget()
        param_layout = QVBoxLayout(param_section)
        param_layout.setContentsMargins(0, 0, 0, 0)
        param_layout.setSpacing(16)
        
        param_title = QLabel("ℹ️ 参数设置")
        param_title.setStyleSheet("font-size: 12px; font-family: 'Consolas'; opacity: 0.4;")
        param_layout.addWidget(param_title)
        
        param_grid = QGridLayout()
        param_grid.setSpacing(12)
        
        if task_type == "autoline":
            self.param_layer_a = ParamInputWidget("图层 A 名称", "断面线 1")
            self.param_layer_b = ParamInputWidget("图层 B 名称", "断面线 2")
            self.param_output_layer = ParamInputWidget("输出图层名", "合并断面线")
            self.param_output_dir = ParamInputWidget("输出目录", "C:/Outputs", is_path=True)
            self.param_output_name = ParamInputWidget("输出文件名", "断面合并结果")
            
            param_grid.addWidget(self.param_layer_a, 0, 0)
            param_grid.addWidget(self.param_layer_b, 0, 1)
            param_grid.addWidget(self.param_output_layer, 1, 0, 1, 2)
            param_grid.addWidget(self.param_output_dir, 2, 0)
            param_grid.addWidget(self.param_output_name, 2, 1)
            
        elif task_type == "autopaste":
            self.param_src_x0 = ParamInputWidget("源端 0 点 X", "86.8540")
            self.param_src_y0 = ParamInputWidget("源端 0 点 Y", "-15.0622")
            self.param_src_bx = ParamInputWidget("源端基点 X", "86.0030")
            self.param_src_by = ParamInputWidget("源端基点 Y", "-35.2980")
            self.param_spacing = ParamInputWidget("断面间距", "-148.4760")
            self.param_dst_y = ParamInputWidget("目标桩号 Y", "-1470.5289")
            self.param_dst_by = ParamInputWidget("目标基点 Y", "-1363.5000")
            self.param_paste_output_dir = ParamInputWidget("输出目录", "C:/Outputs", is_path=True)
            self.param_paste_output_name = ParamInputWidget("输出文件名", "批量粘贴结果")
            
            param_grid.addWidget(self.param_src_x0, 0, 0)
            param_grid.addWidget(self.param_src_y0, 0, 1)
            param_grid.addWidget(self.param_src_bx, 1, 0)
            param_grid.addWidget(self.param_src_by, 1, 1)
            param_grid.addWidget(self.param_spacing, 2, 0, 1, 2)
            param_grid.addWidget(self.param_dst_y, 3, 0)
            param_grid.addWidget(self.param_dst_by, 3, 1)
            param_grid.addWidget(self.param_paste_output_dir, 4, 0)
            param_grid.addWidget(self.param_paste_output_name, 4, 1)
            
        elif task_type == "autohatch":
            self.param_hatch_layer = ParamInputWidget("填充层名称", "AA_填充算量层")
            self.param_text_height = ParamInputWidget("标注字高", "3.0")
            self.param_hatch_output_dir = ParamInputWidget("输出目录", "C:/Outputs", is_path=True)
            self.param_hatch_output_name = ParamInputWidget("输出文件名", "快速填充结果")
            
            param_grid.addWidget(self.param_hatch_layer, 0, 0)
            param_grid.addWidget(self.param_text_height, 0, 1)
            param_grid.addWidget(self.param_hatch_output_dir, 1, 0)
            param_grid.addWidget(self.param_hatch_output_name, 1, 1)
            
        elif task_type == "autoclassify":
            self.param_class_layer_a = ParamInputWidget("断面线图层 1", "DMX")
            self.param_class_layer_b = ParamInputWidget("断面线图层 2", "断面线")
            self.param_station_layer = ParamInputWidget("桩号图层", "0-桩号")
            self.param_merge_checkbox = QCheckBox("合并断面线图层")
            self.param_merge_checkbox.setChecked(True)
            self.param_class_output_dir = ParamInputWidget("输出目录", "C:/Outputs", is_path=True)
            self.param_class_output_name = ParamInputWidget("输出文件名", "分类算量结果")
            
            param_grid.addWidget(self.param_class_layer_a, 0, 0)
            param_grid.addWidget(self.param_class_layer_b, 0, 1)
            param_grid.addWidget(self.param_station_layer, 1, 0)
            param_grid.addWidget(self.param_merge_checkbox, 1, 1)
            param_grid.addWidget(self.param_class_output_dir, 2, 0)
            param_grid.addWidget(self.param_class_output_name, 2, 1)
            
        elif task_type == "autocut":
            self.param_elevation = ParamInputWidget("分层线高程 (m)", "-5")
            self.param_cut_output_dir = ParamInputWidget("输出目录", "C:/Outputs", is_path=True)
            self.param_cut_output_name = ParamInputWidget("输出文件名", "分层算量结果")
            
            param_grid.addWidget(self.param_elevation, 0, 0, 1, 2)
            param_grid.addWidget(self.param_cut_output_dir, 1, 0)
            param_grid.addWidget(self.param_cut_output_name, 1, 1)
        
        param_layout.addLayout(param_grid)
        layout.addWidget(param_section)
        
        layout.addStretch()
        
        scroll_area.setWidget(widget)
        container_layout.addWidget(scroll_area, 1)
        
        # 执行按钮
        self.execute_btn = QPushButton("▶ 执行任务")
        self.execute_btn.setObjectName("PrimaryButton")
        self.execute_btn.setFixedHeight(56)
        self.execute_btn.clicked.connect(self.execute_task)
        container_layout.addWidget(self.execute_btn)
        
        return container
        
    def create_right_panel(self) -> QWidget:
        """创建右侧面板"""
        panel = QWidget()
        panel.setStyleSheet("background-color: #0D0D0D;")
        panel.setMinimumWidth(400)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 成果输出
        result_header = QWidget()
        result_header.setFixedHeight(48)
        result_header.setStyleSheet("background-color: #1A1A1A; border-bottom: 1px solid #2A2A2A;")
        result_header_layout = QHBoxLayout(result_header)
        result_header_layout.setContentsMargins(16, 0, 16, 0)
        
        result_title = QLabel("✓ 成果输出")
        result_title.setStyleSheet("font-size: 12px; font-family: 'Consolas'; opacity: 0.5;")
        result_header_layout.addWidget(result_title)
        layout.addWidget(result_header)
        
        self.result_area = QTextEdit()
        self.result_area.setReadOnly(True)
        self.result_area.setPlaceholderText("等待任务完成...")
        self.result_area.setFixedHeight(250)
        layout.addWidget(self.result_area)
        
        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #2A2A2A; border: none; max-height: 1px;")
        layout.addWidget(separator)
        
        # 日志区域
        log_header = QWidget()
        log_header.setFixedHeight(48)
        log_header.setStyleSheet("background-color: #1A1A1A; border-bottom: 1px solid #2A2A2A;")
        log_header_layout = QHBoxLayout(log_header)
        log_header_layout.setContentsMargins(16, 0, 16, 0)
        
        log_title = QLabel("⌨ 运行控制台")
        log_title.setStyleSheet("font-size: 12px; font-family: 'Consolas'; opacity: 0.5;")
        log_header_layout.addWidget(log_title)
        
        clear_btn = QPushButton("清除")
        clear_btn.setStyleSheet("font-size: 11px; opacity: 0.3; background: transparent; border: none;")
        clear_btn.clicked.connect(self.clear_log)
        log_header_layout.addWidget(clear_btn)
        
        layout.addWidget(log_header)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area, 1)
        
        return panel
        
    def create_status_bar(self, parent_layout):
        """创建状态栏"""
        self.status_bar = QStatusBar()
        
        self.status_bar.showMessage("引擎版本: v2.0 | 核心算法: DXF-SHAPELY")
        
        copyright_label = QLabel("@黄秉俊")
        copyright_label.setStyleSheet("color: #707070; font-size: 11px; font-family: 'Consolas';")
        self.status_bar.addPermanentWidget(copyright_label)
        
        parent_layout.addWidget(self.status_bar)
        
    def on_tab_changed(self, index):
        """标签页切换"""
        self.current_task = ["autoline", "autopaste", "autohatch", "autoclassify", "autocut"][index]
        
    def add_log(self, message: str, level: str = "info"):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "info": "ℹ️",
            "success": "✅",
            "error": "❌",
            "warning": "⚠️"
        }.get(level, "ℹ️")
        
        self.log_area.append(f"<span style='opacity: 0.5;'>[{timestamp}]</span> {prefix} {message}")
        
    def clear_log(self):
        """清除日志"""
        self.log_area.clear()
        
    def execute_task(self):
        """执行任务"""
        if not ENGINE_AVAILABLE:
            QMessageBox.warning(self, "警告", "engine_cad 模块未加载，无法执行任务")
            return
            
        # 检查文件
        if self.current_task == "autopaste":
            if not self.source_file or not self.target_file:
                QMessageBox.warning(self, "警告", "请选择源文件和目标文件")
                return
        else:
            if not self.selected_file:
                QMessageBox.warning(self, "警告", "请选择要处理的 DXF 文件")
                return
                
        self.executing = True
        self.execute_btn.setText("⏳ 计算中...")
        self.execute_btn.setEnabled(False)
        
        # 收集参数
        params = self.collect_params()
        
        # 在后台线程执行
        self.worker = TaskWorker(self.current_task, params)
        self.worker.log_signal.connect(self.add_log)
        self.worker.result_signal.connect(self.on_task_result)
        self.worker.finished.connect(self.on_task_finished)
        self.worker.start()
        
    def collect_params(self) -> Dict:
        """收集参数"""
        params = {}
        
        if self.current_task == "autoline":
            params = {
                'layerA': self.param_layer_a.get_value(),
                'layerB': self.param_layer_b.get_value(),
                'outputLayer': self.param_output_layer.get_value(),
                'outputDir': self.param_output_dir.get_value(),
                'outputName': self.param_output_name.get_value(),
                'file': self.selected_file['path'] if self.selected_file else None
            }
        elif self.current_task == "autopaste":
            params = {
                'srcX0': float(self.param_src_x0.get_value()),
                'srcY0': float(self.param_src_y0.get_value()),
                'srcBX': float(self.param_src_bx.get_value()),
                'srcBY': float(self.param_src_by.get_value()),
                'spacing': float(self.param_spacing.get_value()),
                'dstY': float(self.param_dst_y.get_value()),
                'dstBY': float(self.param_dst_by.get_value()),
                'outputDir': self.param_paste_output_dir.get_value(),
                'outputName': self.param_paste_output_name.get_value(),
                'sourceFile': self.source_file['path'] if self.source_file else None,
                'targetFile': self.target_file['path'] if self.target_file else None
            }
        elif self.current_task == "autohatch":
            params = {
                'layer': self.param_hatch_layer.get_value(),
                'textHeight': float(self.param_text_height.get_value()),
                'outputDir': self.param_hatch_output_dir.get_value(),
                'outputName': self.param_hatch_output_name.get_value(),
                'file': self.selected_file['path'] if self.selected_file else None
            }
        elif self.current_task == "autoclassify":
            params = {
                'layerA': self.param_class_layer_a.get_value(),
                'layerB': self.param_class_layer_b.get_value(),
                'stationLayer': self.param_station_layer.get_value(),
                'mergeSection': self.param_merge_checkbox.isChecked(),
                'outputDir': self.param_class_output_dir.get_value(),
                'outputName': self.param_class_output_name.get_value(),
                'file': self.selected_file['path'] if self.selected_file else None
            }
        elif self.current_task == "autocut":
            params = {
                'elevation': float(self.param_elevation.get_value()),
                'outputDir': self.param_cut_output_dir.get_value(),
                'outputName': self.param_cut_output_name.get_value(),
                'file': self.selected_file['path'] if self.selected_file else None
            }
            
        return params
        
    def on_task_result(self, result: Dict):
        """任务结果"""
        if result.get('success'):
            self.results = result.get('results', [])
            self.result_area.clear()
            for r in self.results:
                self.result_area.append(f"📄 {r.get('name', '未知文件')}\n   路径: {r.get('path', '默认路径')}\n")
        else:
            self.add_log(result.get('error', '未知错误'), 'error')
            
    def on_task_finished(self):
        """任务完成"""
        self.executing = False
        self.execute_btn.setText("▶ 执行任务")
        self.execute_btn.setEnabled(True)


# ==================== 后台任务线程 ====================
class TaskWorker(QThread):
    """后台任务执行线程"""
    
    log_signal = pyqtSignal(str, str)
    result_signal = pyqtSignal(dict)
    
    def __init__(self, task_type: str, params: Dict):
        super().__init__()
        self.task_type = task_type
        self.params = params
        
    def run(self):
        self.log_signal.emit(f"开始执行任务: {TOOL_CONFIG[self.task_type]['name']}", "info")
        
        try:
            # 获取函数名
            func_name = TOOL_CONFIG[self.task_type]['function']
            
            if hasattr(engine_cad, func_name):
                func = getattr(engine_cad, func_name)
                result = func(self.params)
                
                if result:
                    self.result_signal.emit({'success': True, 'results': result})
                    self.log_signal.emit("任务执行完成", "success")
                else:
                    self.result_signal.emit({'success': False, 'error': '执行返回空结果'})
            else:
                self.log_signal.emit(f"函数 {func_name} 不存在", "error")
                self.result_signal.emit({'success': False, 'error': f'函数 {func_name} 不存在'})
                
        except Exception as e:
            self.log_signal.emit(f"任务执行异常: {str(e)}", "error")
            self.result_signal.emit({'success': False, 'error': str(e)})


# ==================== 主入口 ====================
def main():
    # 高DPI支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    
    # 显示启动画面
    splash = SplashScreen()
    splash.show()
    
    # 创建主窗口
    window = HydraulicCADPlatform()
    
    # 3秒后关闭启动画面并显示主窗口
    def show_main():
        splash.close()
        window.show()
        
    QTimer.singleShot(3000, show_main)
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()