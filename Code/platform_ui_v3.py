# -*- coding: utf-8 -*-
"""
航道断面算量自动化平台 v3.7.0 - 前端UI
基于 React 设计转写，现代化深色主题
前后端分离架构：前端 PyQt6 + 后端 FastAPI

v3.7.0 更新：
- 新增"分层+回淤"合并功能，一次性完成分层算量和回淤计算
- 设计断面线(DMX)作为回淤下边界，更新断面线作为上边界
- 优化参数界面，支持合并任务的参数配置
"""

import sys
import os
import traceback
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QGroupBox, QMessageBox, QProgressBar, QTabWidget, QFrame,
    QScrollArea, QCheckBox, QStatusBar, QSplitter, QSizePolicy,
    QSpacerItem, QGridLayout, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize, QPropertyAnimation, QEasingCurve, QPoint
from PyQt6.QtGui import QFont, QColor, QPalette, QPixmap, QPainter, QPen, QBrush, QLinearGradient, QIcon

# 尝试导入引擎模块（程序化调用，使用绝对路径）
try:
    # 使用绝对路径导入Code目录下的engine_cad_v3.py
    import sys
    from pathlib import Path
    code_dir = Path(__file__).parent  # Code目录
    if str(code_dir) not in sys.path:
        sys.path.insert(0, str(code_dir))
    import engine_cad_v3 as engine_cad
    ENGINE_AVAILABLE = True
    print(f"[INFO] 引擎模块已加载: {engine_cad.__file__}")
except ImportError as e:
    ENGINE_AVAILABLE = False
    print(f"[WARN] 引擎模块加载失败: {e}")

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
#TabBar {
    background-color: #1A1A1A;
    border-bottom: 1px solid #2A2A2A;
}

QTabBar::tab {
    background-color: transparent;
    color: #707070;
    padding: 16px 24px;
    font-size: 14px;
    font-weight: 500;
    border: none;
}

QTabBar::tab:selected {
    color: #E4E3E0;
    background-color: #141414;
}

QTabBar::tab:hover:!selected {
    color: #E4E3E0;
    background-color: rgba(20, 20, 20, 0.5);
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
    selection-background-color: #E4E3E0;
    selection-color: #0F0F0F;
}

QLineEdit:focus {
    border: 1px solid #E4E3E0;
}

QLineEdit:disabled {
    background-color: #0D0D0D;
    color: #555555;
}

/* 下拉框 */
QComboBox {
    background-color: #1A1A1A;
    border: 1px solid #2A2A2A;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 14px;
    color: #E4E3E0;
}

QComboBox:focus {
    border: 1px solid #E4E3E0;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #E4E3E0;
    margin-right: 10px;
}

QComboBox QAbstractItemView {
    background-color: #1A1A1A;
    border: 1px solid #2A2A2A;
    selection-background-color: #2A2A2A;
    color: #E4E3E0;
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

QPushButton:pressed {
    background-color: #1A1A1A;
}

QPushButton:disabled {
    background-color: #2A2A2A;
    color: #555555;
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

/* 次要按钮 */
#SecondaryButton {
    background-color: transparent;
    border: 1px solid #2A2A2A;
    color: #E4E3E0;
}

#SecondaryButton:hover {
    border-color: #E4E3E0;
}

/* 文件行 */
#FileRow {
    background-color: #1A1A1A;
    border: 1px solid #2A2A2A;
    border-radius: 8px;
}

#FileRow:hover {
    border-color: #333333;
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

QCheckBox::indicator:hover {
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

QScrollBar::handle:vertical:hover {
    background: #333333;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* 状态栏 */
QStatusBar {
    background-color: #1A1A1A;
    border-top: 1px solid #2A2A2A;
    color: #707070;
    font-size: 11px;
    font-family: 'Consolas', sans-serif;
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
        'desc': '将两个断面线图层合并，生成上/下包络线'
    },
    'autopaste': {
        'name': '批量粘贴',
        'desc': '将源断面图批量粘贴到目标图纸'
    },
    'autohatch': {
        'name': '快速填充',
        'desc': '自动识别封闭区域并填充，计算面积'
    },
    'autosection': {
        'name': '分层算量',
        'desc': '计算指定高程分层线以下的面积，支持区分设计/超挖'
    },
    'backfill': {
        'name': '回淤计算',
        'desc': '计算DMX与设计断面线之间的回淤面积'
    },
    'autosection_backfill': {
        'name': '分层+回淤',
        'desc': '分层算量与回淤计算合并，一次运行完成两项计算'
    }
}

# ==================== 启动画面 ====================
class SplashScreen(QWidget):
    """启动画面 - 显示Logo和加载进度"""
    
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(500, 600)
        
        self.logo_pixmap = None
        icon_path = Path(__file__).parent.parent / "new_logo.ico"
        if icon_path.exists():
            try:
                self.logo_pixmap = QPixmap(str(icon_path))
            except Exception as e:
                print(f"[WARN] Logo加载失败: {e}")
                self.logo_pixmap = None
        else:
            logo_path = Path(__file__).parent.parent / "logo.ico"
            if logo_path.exists():
                try:
                    self.logo_pixmap = QPixmap(str(logo_path))
                except Exception as e:
                    print(f"[WARN] 备用Logo加载失败: {e}")
                    self.logo_pixmap = None
        
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
        subtitle = QLabel("WATERWAY SECTION AUTOMATION PLATFORM v3.7.0")
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
    """文件选择行组件"""
    
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
        label.setStyleSheet("font-size: 12px; font-family: 'Consolas'; opacity: 0.4; text-transform: uppercase;")
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
        
        self.clear_btn = QPushButton("清除")
        self.clear_btn.setFixedSize(80, 36)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #FF5555;
                font-size: 13px;
                border: 1px solid #FF5555;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: rgba(255, 85, 85, 0.1);
            }
        """)
        self.clear_btn.setVisible(True)
        self.clear_btn.clicked.connect(self.clear_file)
        layout.addSpacing(8)
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
    """参数输入组件"""
    
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
        
        # 输入框容器
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


# ==================== 下拉选择组件 ====================
class ParamSelectWidget(QWidget):
    """下拉选择组件"""
    
    def __init__(self, label: str, options: List[tuple], default: str = "", parent=None):
        super().__init__(parent)
        self.setup_ui(label, options, default)
        
    def setup_ui(self, label: str, options: List[tuple], default: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(10)
        
        # 标签
        label_widget = QLabel(label.upper())
        label_widget.setStyleSheet("font-size: 13px; font-family: 'Consolas'; opacity: 0.5; letter-spacing: 0.1em;")
        layout.addWidget(label_widget)
        
        # 下拉框
        self.combo = QComboBox()
        self.combo.setMinimumHeight(44)
        for value, text in options:
            self.combo.addItem(text, value)
        
        # 设置默认值
        if default:
            idx = self.combo.findData(default)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        
        layout.addWidget(self.combo)
        
    def get_value(self) -> str:
        return self.combo.currentData()
        
    def set_value(self, value: str):
        idx = self.combo.findData(value)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)


# ==================== 复选框组件 ====================
class ParamCheckboxWidget(QWidget):
    """复选框参数组件"""
    
    def __init__(self, label: str, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setup_ui(label, checked)
        
    def setup_ui(self, label: str, checked: bool):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 12)
        layout.setSpacing(0)
        
        self.checkbox = QCheckBox(label)
        self.checkbox.setChecked(checked)
        self.checkbox.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.checkbox)
        
    def is_checked(self) -> bool:
        return self.checkbox.isChecked()
        
    def set_checked(self, checked: bool):
        self.checkbox.setChecked(checked)


# ==================== 引擎调用封装 ====================
class EngineBridge:
    """引擎调用桥接器 - 程序化调用engine_cad模块"""
    
    def __init__(self):
        self.status = "online" if ENGINE_AVAILABLE else "offline"
        
    def check_health(self) -> bool:
        """检查引擎是否可用"""
        return ENGINE_AVAILABLE
        
    def run_task(self, task_type: str, params: Dict, log_func) -> Dict:
        """执行任务 - 直接调用engine_cad模块"""
        if not ENGINE_AVAILABLE:
            return {'success': False, 'error': '引擎模块不可用', 'results': []}
        
        results = []
        
        try:
            if task_type == 'autoline':
                engine_cad.run_autoline(params, log_func)
            elif task_type == 'autopaste':
                engine_cad.run_autopaste(params, log_func)
            elif task_type == 'autohatch':
                engine_cad.run_autohatch(params, log_func)
            elif task_type == 'autosection':
                engine_cad.run_autosection(params, log_func)
            elif task_type == 'backfill':
                engine_cad.run_backfill(params, log_func)
            elif task_type == 'autosection_backfill':
                engine_cad.run_autosection_backfill(params, log_func)
            else:
                return {'success': False, 'error': f'未知任务类型: {task_type}', 'results': []}
            
            # 检查输出文件 - 通过扫描输出目录获取最新生成的文件
            output_dir = params.get('输出目录')
            files = params.get('files', [])
            
            # 获取输入文件路径
            input_path = ''
            if task_type == 'autopaste':
                input_path = params.get('目标文件名', '')
            elif files:
                input_path = files[0] if isinstance(files[0], str) else files[0].get('path', '')
            
            if input_path:
                base_dir = output_dir if output_dir else os.path.dirname(input_path)
                base_name = os.path.splitext(os.path.basename(input_path))[0]
                
                # 扫描输出目录中匹配的文件
                try:
                    if os.path.exists(base_dir):
                        for f in os.listdir(base_dir):
                            if f.startswith(base_name):
                                # 根据任务类型过滤
                                if task_type == 'autoline' and '合并' in f and f.endswith('.dxf'):
                                    results.append({'name': f, 'path': os.path.join(base_dir, f)})
                                elif task_type == 'autopaste' and '已粘贴断面' in f and f.endswith('.dxf'):
                                    results.append({'name': f, 'path': os.path.join(base_dir, f)})
                                elif task_type == 'autohatch' and ('填充完成' in f or '面积明细' in f):
                                    results.append({'name': f, 'path': os.path.join(base_dir, f)})
                                elif task_type == 'autosection' and ('分层' in f or '面积' in f):
                                    results.append({'name': f, 'path': os.path.join(base_dir, f)})
                                elif task_type == 'backfill' and '回淤' in f:
                                    results.append({'name': f, 'path': os.path.join(base_dir, f)})
                                elif task_type == 'autosection_backfill' and ('分层回淤' in f or '合并' in f):
                                    results.append({'name': f, 'path': os.path.join(base_dir, f)})
                except Exception as e:
                    log_func(f"[WARN] 扫描输出目录失败: {e}")
            
            return {'success': True, 'results': results}
            
        except Exception as e:
            traceback.print_exc()
            return {'success': False, 'error': str(e), 'results': []}


# ==================== 主窗口 ====================
class HydraulicCADPlatform(QMainWindow):
    """主窗口 - 航道断面算量自动化平台 v3.5"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("航道断面算量自动化平台 v3.7.0")
        
        icon_path = Path(__file__).parent.parent / "new_logo.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(icon_path))
            
        self.setMinimumSize(1280, 800)
        self.resize(1280, 800)
        
        # 引擎桥接器（程序化调用）
        self.engine = EngineBridge()
        
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
        self.check_backend_status()
        
    def init_ui(self):
        """初始化用户界面"""
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
        
        self.apply_styles()
        
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
        icon_path = Path(__file__).parent.parent / "new_logo.ico"
        if icon_path.exists():
            logo_label = QLabel()
            pixmap = QPixmap(str(icon_path)).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pixmap)
            left_section.addWidget(logo_label)
        else:
            logo_path = Path(__file__).parent.parent / "logo.ico"
            if logo_path.exists():
                logo_label = QLabel()
                pixmap = QPixmap(str(logo_path)).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                logo_label.setPixmap(pixmap)
                left_section.addWidget(logo_label)
        
        # 标题区域
        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        
        title = QLabel("航道断面算量自动化平台")
        title.setObjectName("TitleLabel")
        title_layout.addWidget(title)
        
        # 后端状态
        status_layout = QHBoxLayout()
        status_layout.setSpacing(8)
        
        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(8, 8)
        self.status_indicator.setStyleSheet("background-color: #FFFF00; border-radius: 4px;")
        status_layout.addWidget(self.status_indicator)
        
        self.status_label = QLabel("后端状态: 检测中...")
        self.status_label.setStyleSheet("font-size: 11px; font-family: 'Consolas'; opacity: 0.5; text-transform: uppercase; letter-spacing: 0.1em;")
        status_layout.addWidget(self.status_label)
        
        status_layout.addStretch()
        title_layout.addLayout(status_layout)
        
        left_section.addLayout(title_layout)
        header_layout.addLayout(left_section)
        header_layout.addStretch()
        
        # 右侧按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        db_btn = QPushButton("📦")
        db_btn.setFixedSize(40, 40)
        db_btn.setStyleSheet("background-color: #242424; border: 1px solid #333; border-radius: 8px;")
        btn_layout.addWidget(db_btn)
        
        settings_btn = QPushButton("⚙️")
        settings_btn.setFixedSize(40, 40)
        settings_btn.setStyleSheet("background-color: #242424; border: 1px solid #333; border-radius: 8px;")
        btn_layout.addWidget(settings_btn)
        
        header_layout.addLayout(btn_layout)
        parent_layout.addWidget(header)
        
    def create_left_panel(self) -> QWidget:
        """创建左侧面板"""
        panel = QWidget()
        panel.setStyleSheet("background-color: #141414;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 标签页选择 - 占据主要空间但不是全部
        self.tab_bar = QTabWidget()
        self.tab_bar.setStyleSheet("""
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
        """)
        
        # 添加标签页 - v3.7更新
        tabs = [
            ("autoline", "断面合并"),
            ("autopaste", "批量粘贴"),
            ("autohatch", "快速填充"),
            ("autosection", "分层算量"),
            ("backfill", "回淤计算"),
            ("autosection_backfill", "分层+回淤")
        ]
        
        for task_id, task_name in tabs:
            tab_widget = self.create_tab_content(task_id)
            self.tab_bar.addTab(tab_widget, task_name)
            
        self.tab_bar.currentChanged.connect(self.on_tab_changed)
        layout.addWidget(self.tab_bar, 1)
        
        # 底部执行按钮区域 - 类似v3.0的设计
        button_container = QWidget()
        button_container.setFixedHeight(100)
        button_container.setStyleSheet("""
            QWidget {
                background-color: rgba(26, 26, 26, 0.5);
                border-top: 1px solid #2A2A2A;
            }
        """)
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(24, 20, 24, 24)
        
        self.execute_btn = QPushButton("▶ 执行任务")
        self.execute_btn.setObjectName("PrimaryButton")
        self.execute_btn.setMinimumHeight(56)
        self.execute_btn.clicked.connect(self.execute_task)
        button_layout.addWidget(self.execute_btn)
        
        layout.addWidget(button_container)
        
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
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
        """)
        
        # 滚动内容
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)
        
        # 文件选择区域
        file_section = QWidget()
        file_layout = QVBoxLayout(file_section)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(12)
        
        file_title = QLabel("📄 文件选择")
        file_title.setStyleSheet("font-size: 12px; font-family: 'Consolas'; opacity: 0.4; text-transform: uppercase; letter-spacing: 0.15em;")
        file_layout.addWidget(file_title)
        
        if task_type == "autopaste":
            self.source_file_row = FileRowWidget("源文件")
            self.source_file_row.fileSelected.connect(self._on_source_file_selected)
            self.source_file_row.fileCleared.connect(self._on_source_file_cleared)
            file_layout.addWidget(self.source_file_row)
            
            self.target_file_row = FileRowWidget("目标文件")
            self.target_file_row.fileSelected.connect(self._on_target_file_selected)
            self.target_file_row.fileCleared.connect(self._on_target_file_cleared)
            file_layout.addWidget(self.target_file_row)
        else:
            self.file_row = FileRowWidget("待处理 DXF")
            self.file_row.fileSelected.connect(self._on_file_selected)
            self.file_row.fileCleared.connect(self._on_file_cleared)
            file_layout.addWidget(self.file_row)
            
        layout.addWidget(file_section)
        
        # 参数配置区域
        param_section = QWidget()
        param_layout = QVBoxLayout(param_section)
        param_layout.setContentsMargins(0, 0, 0, 0)
        param_layout.setSpacing(16)
        
        param_title = QLabel("ℹ️ 参数设置")
        param_title.setStyleSheet("font-size: 12px; font-family: 'Consolas'; opacity: 0.4; text-transform: uppercase; letter-spacing: 0.15em;")
        param_layout.addWidget(param_title)
        
        # 参数网格
        param_grid = QGridLayout()
        param_grid.setSpacing(12)
        
        # 根据任务类型添加参数
        if task_type == "autoline":
            self._create_autoline_params(param_grid)
        elif task_type == "autopaste":
            self._create_autopaste_params(param_grid)
        elif task_type == "autohatch":
            self._create_autohatch_params(param_grid)
        elif task_type == "autosection":
            self._create_autosection_params(param_grid)
        elif task_type == "backfill":
            self._create_backfill_params(param_grid)
        elif task_type == "autosection_backfill":
            self._create_autosection_backfill_params(param_grid)
        
        param_layout.addLayout(param_grid)
        layout.addWidget(param_section)
        
        layout.addStretch()
        
        scroll_area.setWidget(widget)
        container_layout.addWidget(scroll_area, 1)
        
        return container
    
    def _create_autoline_params(self, param_grid):
        """断面合并参数"""
        self.param_layer_a = ParamInputWidget("图层 A 名称", "")
        self.param_layer_b = ParamInputWidget("图层 B 名称", "")
        self.param_envelope_type = ParamSelectWidget(
            "包络线类型",
            [('lower', '下包络线（取最小Y）'), ('upper', '上包络线（取最大Y）')],
            default='lower'
        )
        self.param_output_layer = ParamInputWidget("输出图层名", "")
        self.param_output_dir = ParamInputWidget("输出目录（留空则同目录）", "", is_path=True)
        
        param_grid.addWidget(self.param_layer_a, 0, 0)
        param_grid.addWidget(self.param_layer_b, 0, 1)
        param_grid.addWidget(self.param_envelope_type, 1, 0, 1, 2)
        param_grid.addWidget(self.param_output_layer, 2, 0)
        param_grid.addWidget(self.param_output_dir, 2, 1)
    
    def _create_autopaste_params(self, param_grid):
        """批量粘贴参数 - v2简化版，全自动匹配，只需输出图层名"""
        # 提示信息
        hint_label = QLabel("✨ v2全自动匹配：自动检测源文件小矩形基点+桩号，目标文件L1脊梁线基点+桩号")
        hint_label.setStyleSheet("font-size: 12px; color: #50FA7B; padding: 8px; background-color: rgba(80, 250, 123, 0.1); border-radius: 4px;")
        param_grid.addWidget(hint_label, 0, 0, 1, 2)
        
        # 使用独立的变量名，避免与其他模块冲突
        self.param_paste_layer = ParamInputWidget("输出图层名", "0-已粘贴断面")
        self.param_paste_output_dir = ParamInputWidget("输出目录（留空则同目录）", "", is_path=True)
        
        param_grid.setSpacing(16)
        param_grid.addWidget(self.param_paste_layer, 1, 0)
        param_grid.addWidget(self.param_paste_output_dir, 1, 1)
    
    def _create_autohatch_params(self, param_grid):
        """快速填充参数"""
        self.param_hatch_layer = ParamInputWidget("填充层名称", "")
        self.param_text_height = ParamInputWidget("标注字高", "3.0")
        self.param_hatch_output_dir = ParamInputWidget("输出目录（留空则同目录）", "", is_path=True)
        
        param_grid.addWidget(self.param_hatch_layer, 0, 0)
        param_grid.addWidget(self.param_text_height, 0, 1)
        param_grid.addWidget(self.param_hatch_output_dir, 1, 0, 1, 2)
    
    def _create_autosection_params(self, param_grid):
        """分层算量参数 - v3.5更新"""
        self.param_elevation = ParamInputWidget("目标高程 (m) [留空则全算量]", "")
        self.param_section_layer = ParamInputWidget("断面线图层", "")
        self.param_pile_layer = ParamInputWidget("桩号图层", "")
        self.param_merge_section = ParamCheckboxWidget("合并断面线", checked=True)
        self.param_aux_layers = ParamInputWidget("辅助断面图层（合并用）", "")
        self.param_calc_mode = ParamSelectWidget(
            "计算模式",
            [('below', '高程线以下'), ('above', '高程线以上')],
            default='below'
        )
        self.param_distinguish_design = ParamCheckboxWidget("区分设计/超挖量", checked=False)
        self.param_section_output_dir = ParamInputWidget("输出目录（留空则同目录）", "", is_path=True)
        
        param_grid.addWidget(self.param_elevation, 0, 0)
        param_grid.addWidget(self.param_section_layer, 0, 1)
        param_grid.addWidget(self.param_pile_layer, 1, 0)
        param_grid.addWidget(self.param_merge_section, 1, 1)
        param_grid.addWidget(self.param_aux_layers, 2, 0)
        param_grid.addWidget(self.param_calc_mode, 2, 1)
        param_grid.addWidget(self.param_distinguish_design, 3, 0, 1, 2)
        param_grid.addWidget(self.param_section_output_dir, 4, 0, 1, 2)
    
    def _create_backfill_params(self, param_grid):
        """回淤计算参数 - v3.5新增"""
        self.param_design_layer = ParamInputWidget("设计断面线图层", "")
        self.param_backfill_section_layer = ParamInputWidget("断面线图层", "")
        self.param_backfill_output_dir = ParamInputWidget("输出目录（留空则同目录）", "", is_path=True)
        
        param_grid.addWidget(self.param_design_layer, 0, 0)
        param_grid.addWidget(self.param_backfill_section_layer, 0, 1)
        param_grid.addWidget(self.param_backfill_output_dir, 1, 0, 1, 2)
    
    def _create_autosection_backfill_params(self, param_grid):
        """分层算量+回淤计算合并参数 - v3.7更新"""
        self.param_combined_elevation = ParamInputWidget("目标高程 (m) [留空则全算量]", "")
        self.param_combined_pile_layer = ParamInputWidget("桩号图层", "0-桩号")
        self.param_combined_design_layer = ParamInputWidget("设计断面线图层 (DMX)", "DMX")
        self.param_combined_update_layer = ParamInputWidget("更新断面线图层", "")
        self.param_combined_merge_section = ParamCheckboxWidget("合并断面线（下包络）", checked=False)
        self.param_combined_calc_mode = ParamSelectWidget(
            "计算模式",
            [('below', '高程线以下'), ('above', '高程线以上')],
            default='below'
        )
        self.param_combined_distinguish_design = ParamCheckboxWidget("区分设计/超挖量", checked=False)
        self.param_combined_output_dir = ParamInputWidget("输出目录（留空则同目录）", "", is_path=True)
        
        param_grid.addWidget(self.param_combined_elevation, 0, 0)
        param_grid.addWidget(self.param_combined_pile_layer, 0, 1)
        param_grid.addWidget(self.param_combined_design_layer, 1, 0)
        param_grid.addWidget(self.param_combined_update_layer, 1, 1)
        param_grid.addWidget(self.param_combined_merge_section, 2, 0)
        param_grid.addWidget(self.param_combined_calc_mode, 2, 1)
        param_grid.addWidget(self.param_combined_distinguish_design, 3, 0, 1, 2)
        param_grid.addWidget(self.param_combined_output_dir, 4, 0, 1, 2)
        
    def create_right_panel(self) -> QWidget:
        """创建右侧面板"""
        panel = QWidget()
        panel.setStyleSheet("background-color: #0D0D0D;")
        panel.setMinimumWidth(400)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 成果输出区域
        result_header = QWidget()
        result_header.setFixedHeight(48)
        result_header.setStyleSheet("background-color: #1A1A1A; border-bottom: 1px solid #2A2A2A;")
        result_header_layout = QHBoxLayout(result_header)
        result_header_layout.setContentsMargins(16, 0, 16, 0)
        
        result_title = QLabel("✓ 成果输出")
        result_title.setStyleSheet("font-size: 12px; font-family: 'Consolas'; opacity: 0.5; text-transform: uppercase; letter-spacing: 0.15em;")
        result_header_layout.addWidget(result_title)
        layout.addWidget(result_header)
        
        self.result_area = QTextEdit()
        self.result_area.setReadOnly(True)
        self.result_area.setPlaceholderText("等待任务完成...")
        self.result_area.setStyleSheet("""
            QTextEdit {
                background-color: rgba(0, 0, 0, 0.3);
                border: none;
                padding: 16px;
                font-size: 14px;
            }
        """)
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
        log_title.setStyleSheet("font-size: 12px; font-family: 'Consolas'; opacity: 0.5; text-transform: uppercase; letter-spacing: 0.15em;")
        log_header_layout.addWidget(log_title)
        
        clear_btn = QPushButton("清除")
        clear_btn.setStyleSheet("font-size: 11px; opacity: 0.3; background: transparent; border: none;")
        clear_btn.clicked.connect(self.clear_log)
        log_header_layout.addWidget(clear_btn)
        
        layout.addWidget(log_header)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: rgba(0, 0, 0, 0.5);
                border: none;
                padding: 16px;
                font-family: 'Consolas', 'Microsoft YaHei UI';
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        layout.addWidget(self.log_area, 1)
        
        return panel
        
    def create_status_bar(self, parent_layout):
        """创建状态栏"""
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #1A1A1A;
                border-top: 1px solid #2A2A2A;
                color: #707070;
                font-size: 11px;
                font-family: 'Consolas';
                padding: 4px 16px;
            }
        """)
        
        self.status_bar.showMessage("引擎版本: v3.7.0 | 核心算法: DXF-SHAPELY")
        
        copyright_label = QLabel("@黄秉俊")
        copyright_label.setStyleSheet("""
            QLabel {
                color: #707070;
                font-size: 11px;
                font-family: 'Consolas';
                padding-right: 8px;
            }
        """)
        self.status_bar.addPermanentWidget(copyright_label)
        
        parent_layout.addWidget(self.status_bar)
        
    def apply_styles(self):
        """应用样式表"""
        self.setStyleSheet(STYLESHEET)
        
    def check_backend_status(self):
        """检查引擎状态"""
        if self.engine.check_health():
            self.status_indicator.setStyleSheet("background-color: #50FA7B; border-radius: 4px;")
            self.status_label.setText("引擎状态: 已就绪")
        else:
            self.status_indicator.setStyleSheet("background-color: #FF5555; border-radius: 4px;")
            self.status_label.setText("引擎状态: 不可用")
        
    def on_tab_changed(self, index):
        """标签页切换"""
        tasks = ["autoline", "autopaste", "autohatch", "autosection", "backfill", "autosection_backfill"]
        self.current_task = tasks[index]
        
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
        if not self.engine.check_health():
            QMessageBox.warning(self, "警告", "引擎模块不可用")
            return
            
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
        
        params = self.collect_params()
        
        self.worker = TaskWorker(self.engine, self.current_task, params)
        self.worker.log_signal.connect(self.add_log)
        self.worker.result_signal.connect(self.on_task_result)
        self.worker.finished.connect(self.on_task_finished)
        self.worker.start()
        
    def collect_params(self) -> Dict:
        """收集参数"""
        params = {}
        
        if self.current_task == "autoline":
            params = {
                '图层A名称': self.param_layer_a.get_value(),
                '图层B名称': self.param_layer_b.get_value(),
                '包络线类型': self.param_envelope_type.get_value(),
                '输出图层名': self.param_output_layer.get_value(),
                '输出目录': self.param_output_dir.get_value(),
                'files': [self.selected_file.get('path')] if self.selected_file else []
            }
        elif self.current_task == "autopaste":
            params = {
                '源文件名': self.source_file.get('path') if self.source_file else '',
                '目标文件名': self.target_file.get('path') if self.target_file else '',
                '输出图层名': self.param_paste_layer.get_value(),
                '输出目录': self.param_paste_output_dir.get_value()
            }
        elif self.current_task == "autohatch":
            params = {
                '填充层名称': self.param_hatch_layer.get_value(),
                '标注字高': self.param_text_height.get_value(),
                '输出目录': self.param_hatch_output_dir.get_value(),
                'files': [self.selected_file.get('path')] if self.selected_file else []
            }
        elif self.current_task == "autosection":
            params = {
                '目标高程': self.param_elevation.get_value(),
                '断面线图层': self.param_section_layer.get_value(),
                '桩号图层': self.param_pile_layer.get_value(),
                '合并断面线': self.param_merge_section.is_checked(),
                '辅助断面图层': self.param_aux_layers.get_value(),
                '计算模式': self.param_calc_mode.get_value(),
                '区分设计超挖': self.param_distinguish_design.is_checked(),
                '输出目录': self.param_section_output_dir.get_value(),
                'files': [self.selected_file.get('path')] if self.selected_file else []
            }
        elif self.current_task == "backfill":
            params = {
                '断面线图层': self.param_backfill_section_layer.get_value(),
                '设计断面线图层': self.param_design_layer.get_value(),
                '输出目录': self.param_backfill_output_dir.get_value(),
                'files': [self.selected_file.get('path')] if self.selected_file else []
            }
        elif self.current_task == "autosection_backfill":
            params = {
                '目标高程': self.param_combined_elevation.get_value(),
                '桩号图层': self.param_combined_pile_layer.get_value(),
                '设计断面线图层': self.param_combined_design_layer.get_value(),
                '更新断面线图层': self.param_combined_update_layer.get_value(),
                '合并断面线': self.param_combined_merge_section.is_checked(),
                '计算模式': self.param_combined_calc_mode.get_value(),
                '区分设计超挖': self.param_combined_distinguish_design.is_checked(),
                '输出目录': self.param_combined_output_dir.get_value(),
                'files': [self.selected_file.get('path')] if self.selected_file else []
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
    
    # ==================== 文件选择回调 ====================
    def _on_file_selected(self, file_info):
        """单个文件选择回调"""
        self.selected_file = file_info
        self._update_execute_button()
        self.add_log(f"已选择文件: {file_info.get('name', '')}", "info")
        
    def _on_file_cleared(self):
        """单个文件清除回调"""
        self.selected_file = None
        self._update_execute_button()
        
    def _on_source_file_selected(self, file_info):
        """源文件选择回调"""
        self.source_file = file_info
        self._update_execute_button()
        self.add_log(f"已选择源文件: {file_info.get('name', '')}", "info")
        
    def _on_source_file_cleared(self):
        """源文件清除回调"""
        self.source_file = None
        self._update_execute_button()
        
    def _on_target_file_selected(self, file_info):
        """目标文件选择回调"""
        self.target_file = file_info
        self._update_execute_button()
        self.add_log(f"已选择目标文件: {file_info.get('name', '')}", "info")
        
    def _on_target_file_cleared(self):
        """目标文件清除回调"""
        self.target_file = None
        self._update_execute_button()
        
    def _update_execute_button(self):
        """更新执行按钮状态"""
        if self.executing:
            return
            
        if self.current_task == "autopaste":
            # 批量粘贴需要源文件和目标文件
            can_execute = self.source_file is not None and self.target_file is not None
        else:
            # 其他任务只需要单个文件
            can_execute = self.selected_file is not None
            
        self.execute_btn.setEnabled(can_execute)
        
        if can_execute:
            self.execute_btn.setStyleSheet("""
                QPushButton {
                    background-color: #E4E3E0;
                    color: #0F0F0F;
                    font-size: 18px;
                    font-weight: bold;
                    padding: 16px 32px;
                    border-radius: 12px;
                }
                QPushButton:hover {
                    background-color: #FFFFFF;
                }
            """)
        else:
            self.execute_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2A2A2A;
                    color: #555555;
                    font-size: 18px;
                    font-weight: bold;
                    padding: 16px 32px;
                    border-radius: 12px;
                }
            """)


# ==================== 后台任务线程 ====================
class TaskWorker(QThread):
    """后台任务执行线程"""
    
    log_signal = pyqtSignal(str, str)
    result_signal = pyqtSignal(dict)
    
    def __init__(self, engine: EngineBridge, task_type: str, params: Dict):
        super().__init__()
        self.engine = engine
        self.task_type = task_type
        self.params = params
        
    def run(self):
        self.log_signal.emit(f"开始执行任务: {TOOL_CONFIG[self.task_type]['name']}", "info")
        
        def log_func(msg):
            self.log_signal.emit(msg, "info")
        
        try:
            result = self.engine.run_task(self.task_type, self.params, log_func)
            if result:
                self.result_signal.emit(result)
                self.log_signal.emit("任务执行完成", "success")
            else:
                self.result_signal.emit({'success': False, 'error': '引擎执行失败'})
        except Exception as e:
            error_msg = f"任务执行异常: {str(e)}"
            self.log_signal.emit(error_msg, "error")
            self.log_signal.emit(traceback.format_exc(), "error")
            self.result_signal.emit({'success': False, 'error': error_msg})


# ==================== 主入口 ====================
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    
    splash = SplashScreen()
    splash.show()
    
    window = HydraulicCADPlatform()
    
    def show_main():
        splash.close()
        window.show()
        
    QTimer.singleShot(3000, show_main)
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()