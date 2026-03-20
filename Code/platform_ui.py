#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
航道断面算量自动化平台 v2.0 @黄秉俊
整合五个核心工具: 断面线合并, 批量粘贴, 快速填充, 分类算量, 分层算量
前端UI + engine_cad后端内核
"""

import sys
import os
import traceback
import datetime
from pathlib import Path

# --- 路径兼容处理 ---
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

if base_path not in sys.path:
    sys.path.insert(0, base_path)

# --- 核心 UI 库 ---
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QGroupBox, QMessageBox, QProgressBar, QTabWidget, QListWidget,
    QListWidgetItem, QFormLayout, QCheckBox, QStatusBar, QSplitter,
    QFrame, QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplashScreen
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QIcon, QFont, QPainter, QPen, QBrush, QColor, QPixmap
from PyQt6.QtWidgets import QCheckBox


class CheckableCheckBox(QCheckBox):
    """带可见勾选标记的CheckBox - 通过文本提示"""
    
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._original_text = text
        self.stateChanged.connect(self._update_text)
        self._update_text(self.isChecked())
    
    def _update_text(self, state):
        """根据勾选状态更新文本"""
        if state == Qt.CheckState.Checked.value:
            self.setText(f"✓ {self._original_text}")
            self.setStyleSheet("color: #00B4FF; font-weight: bold;")
        else:
            self.setText(f"○ {self._original_text}")
            self.setStyleSheet("color: #CCCCCC; font-weight: normal;")

# --- 依赖库检测 ---
try:
    import ezdxf
    import shapely
    import numpy
    import pandas as pd
    from shapely.geometry import LineString, Point, box, Polygon
    from shapely.ops import unary_union, linemerge, polygonize
    print("[OK] 核心依赖库加载成功")
except ImportError as e:
    print(f"[WARN] 缺少依赖库：{e}")

# ================= 现代样式表 =================
MODERN_STYLESHEET = """
QMainWindow {
    background-color: #1E1E1E;
    color: #D4D4D4;
    font-family: 'Microsoft YaHei UI', 'Segoe UI';
}

QTabWidget::pane {
    border: 1px solid #333;
    background: #252526;
    border-radius: 4px;
}

QTabBar::tab {
    background: #2D2D2D;
    color: #999;
    padding: 18px 36px;
    font-size: 14px;
    font-weight: 500;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 3px;
    border: 1px solid #333;
    border-bottom: none;
}

QTabBar::tab:selected {
    background: #333333;
    color: #0078D4;
    border-bottom: 3px solid #0078D4;
    font-weight: 600;
}

QTabBar::tab:hover {
    background: #3C3C3C;
    color: #CCC;
}

QGroupBox {
    font-size: 12px;
    font-weight: 600;
    color: #569CD6;
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 10px;
    background: #252526;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px 0 8px;
}

QLabel {
    color: #CCCCCC;
    font-size: 13px;
}

QLineEdit, QComboBox {
    background-color: #2D2D2D;
    color: #FFFFFF;
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 13px;
    min-height: 28px;
}

QLineEdit:focus, QComboBox:focus {
    border: 2px solid #0078D4;
    background-color: #333333;
}

QPushButton {
    background-color: #333333;
    color: #CCCCCC;
    border: 1px solid #3C3C3C;
    border-radius: 6px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 500;
    min-height: 36px;
}

QPushButton:hover {
    background-color: #3C3C3C;
    border-color: #0078D4;
    color: #FFFFFF;
}

QPushButton:pressed {
    background-color: #0078D4;
    color: #FFFFFF;
}

QPushButton:disabled {
    background-color: #252526;
    color: #666666;
}

QPushButton#PrimaryActionBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                                stop:0 #0078D4, stop:0.5 #0066CC, stop:1 #005A9E);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    min-height: 44px;
    padding: 12px 24px;
}

QPushButton#PrimaryActionBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #108FE4, stop:0.5 #0078D4, stop:1 #0066CC);
}

QPushButton#SecondaryActionBtn {
    background-color: #3C3C3C;
    color: #CCCCCC;
    border: 1px solid #0078D4;
    border-radius: 6px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 500;
}

QListWidget {
    background-color: #252526;
    color: #CCCCCC;
    border: 2px dashed #3C3C3C;
    border-radius: 6px;
    padding: 8px;
}

QListWidget::item {
    background-color: #2D2D2D;
    border: 1px solid #333;
    border-radius: 4px;
    padding: 10px;
    margin: 2px;
}

QListWidget::item:selected {
    background-color: #0078D4;
    color: white;
}

QProgressBar {
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    background-color: #252526;
    text-align: center;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #0078D4, stop:1 #00B4FF);
}

QCheckBox {
    font-size: 13px;
    color: #CCCCCC;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border: 2px solid #666;
    border-radius: 4px;
    background: #2D2D2D;
}

QCheckBox::indicator:hover {
    border: 2px solid #0078D4;
    background: #3C3C3C;
}

QCheckBox::indicator:checked {
    background: #0078D4;
    border-color: #0078D4;
}

QCheckBox::indicator:unchecked {
    background: #2D2D2D;
    border-color: #666;
}

QCheckBox::indicator:unchecked:hover {
    border-color: #0078D4;
}

QTableWidget {
    background-color: #252526;
    color: #CCCCCC;
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    gridline-color: #333;
    font-size: 12px;
}

QTableWidget::item {
    padding: 6px;
    border-bottom: 1px solid #333;
}

QHeaderView::section {
    background-color: #2D2D2D;
    color: #CCCCCC;
    padding: 8px;
    border: 1px solid #333;
    font-weight: 600;
}

QTextEdit {
    background-color: #1e1e1e;
    color: #00ff00;
    font-family: 'Consolas', 'Microsoft YaHei UI';
    font-size: 12px;
    border: 2px solid #333;
    border-radius: 5px;
}

QStatusBar {
    background-color: #252526;
    color: #888888;
    border-top: 1px solid #333;
}
"""

# ================= 工具配置 =================
TOOL_CONFIG = {
    'autoline': {
        'name': '断面线合并',
        'has_excel': False,
        'desc': '将两个断面线图层合并，生成下包络线。在每个X坐标处取两条断面线的最低Y值。'
    },
    'autopaste': {
        'name': '批量粘贴',
        'has_excel': False,
        'desc': '将源断面图批量粘贴到目标图纸。源端0点为源图纸中断面桩号0的坐标，断面间距为相邻断面的Y间距。'
    },
    'autohatch': {
        'name': '快速填充',
        'has_excel': True,
        'excel_suffix': '_面积明细表.xlsx',
        'desc': '自动识别封闭区域并填充，计算面积。识别断面线形成的封闭区域，自动添加填充图案并标注面积数值。'
    },
    'autoclassify': {
        'name': '分类算量',
        'has_excel': True,
        'excel_suffix': '_分类汇总.xlsx',
        'desc': '自动区分设计量和超挖量，按地层分类统计。从超挖线构建虚拟断面框，用开挖线最低Y判定设计区/超挖区。'
    },
    'autocut': {
        'name': '分层算量',
        'has_excel': True,
        'excel_suffix': '_分层算量.xlsx',
        'desc': '计算指定高程分层线以上的填充面积。读取DXF文件中的填充区域，根据分层线高程位置分割填充，统计分层线以上的面积并导出Excel。'
    }
}

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
            self.log_out.emit(f"[SYSTEM] 开始执行 {TOOL_CONFIG[self.task_type]['name']} 任务...")
            self.progress_updated.emit(10, "初始化引擎...")
            
            def log_func(msg):
                msg = msg.replace('✅', '[OK]').replace('❌', '[ERROR]').replace('⚠️', '[WARN]')
                msg = msg.replace('⏳', '[WAIT]').replace('✨', '[DONE]').replace('🔍', '[SCAN]')
                msg = msg.replace('🎨', '[PAINT]').replace('🚀', '[GO]').replace('📊', '[STATS]')
                msg = msg.replace('💡', '[TIP]').replace('📐', '[CALC]').replace('♻️', '[RECYCLE]')
                self.log_out.emit(msg)
            
            self.progress_updated.emit(30, "加载 DXF 文件...")
            
            import engine_cad
            
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
            
            self.progress_updated.emit(90, "生成结果文件...")
            
            output_files = []
            excel_file = None
            file_list = self.params.get('files', [])
            for input_file in file_list:
                if input_file and os.path.exists(input_file):
                    base_name = os.path.splitext(input_file)[0]
                    for suffix in ['_RESULT.dxf', '_算量汇总.xlsx', '_bottom_merged.dxf', 
                                  '_填充完成.dxf', '_面积明细表.xlsx', '_分类汇总.xlsx',
                                  '_5m以上分类统计.xlsx', '_分层算量.xlsx']:
                        output_file = base_name + suffix
                        if os.path.exists(output_file):
                            output_files.append(output_file)
                            if suffix.endswith('.xlsx') and excel_file is None:
                                excel_file = output_file
            
            self.progress_updated.emit(100, "任务完成")
            self.log_out.emit("[SYSTEM] 任务执行完成")
            if excel_file:
                self.log_out.emit(f"[TIP] 处理完成，可查看 Excel摘要 获取结果概览")
            self.task_completed.emit(True, {'output_files': output_files, 'excel_file': excel_file})
            
        except Exception as e:
            error_msg = f"[ERROR] 任务执行崩溃:\n{traceback.format_exc()}"
            self.log_out.emit(error_msg)
            self.task_completed.emit(False, {'error': str(e)})
    
    def run_autocut(self, LOG):
        """执行分层算量"""
        try:
            from stat_above_5m import process_dxf
            file_list = self.params.get('files', [])
            
            for input_path in file_list:
                LOG(f"--- [WAIT] 正在处理: {os.path.basename(input_path)} ---")
                results = process_dxf(input_path)
                
                if results:
                    import pandas as pd
                    df = pd.DataFrame(results)
                    cols = ['断面名称', 'Y中心', '分层线Y'] + [c for c in df.columns if c not in ['断面名称', 'Y中心', '分层线Y', '总面积']] + ['总面积']
                    df = df[[c for c in cols if c in df.columns]]
                    
                    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                    output_path = input_path.replace('.dxf', f'_分层算量_{timestamp}.xlsx')
                    df.to_excel(output_path, index=False)
                    
                    LOG(f"[OK] Excel已生成: {os.path.basename(output_path)}")
                    LOG(f"[STATS] 共处理 {len(results)} 个断面")
                else:
                    LOG(f"[WARN] 未找到有效数据")
                LOG(f"[OK] 处理完成！")
                
        except Exception as e:
            LOG(f"[ERROR] 分层算量执行错误: {e}")


# ================= 主界面 =================
class HydraulicCADPlatform(QMainWindow):
    """主窗口 - 航道断面算量自动化平台 v2.0"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("航道断面算量自动化平台 v2.0 @黄秉俊")
        
        icon_path = "D:\\tunnel_build\\new_logo.ico"
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.resize(1400, 800)
        self.current_task_type = 'autoline'
        self.selected_files = []
        self.worker_thread = None
        self.setStyleSheet(MODERN_STYLESHEET)
        
        # 使用字典存储每个工具类型的控件，避免覆盖
        self.file_list_widgets = {}
        self.log_texts = {}
        self.result_tables = {}
        self.process_btns = {}
        self.stop_btns = {}
        
        self.init_ui()
        
    def init_ui(self):
        """初始化用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # 1. 功能区标签
        self.ribbon_tabs = QTabWidget()
        self.ribbon_tabs.addTab(self.create_tool_tab('autoline'), "断面线合并")
        self.ribbon_tabs.addTab(self.create_tool_tab('autopaste'), "批量粘贴")
        self.ribbon_tabs.addTab(self.create_tool_tab('autohatch'), "快速填充")
        self.ribbon_tabs.addTab(self.create_tool_tab('autoclassify'), "分类算量")
        self.ribbon_tabs.addTab(self.create_tool_tab('autocut'), "分层算量")
        self.ribbon_tabs.currentChanged.connect(self.on_tab_changed)
        main_layout.addWidget(self.ribbon_tabs)
        
        # 2. 底部状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.status_bar.addWidget(self.progress_bar)
        self.file_count_label = QLabel("文件：0")
        self.status_bar.addWidget(self.file_count_label)

    def create_tool_tab(self, tool_type):
        """创建工具标签页"""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setSpacing(15)
        
        # 左侧：参数面板
        left_panel = self.create_param_panel(tool_type)
        layout.addWidget(left_panel, 1)
        
        # 中间：文件处理区
        center_panel = self.create_center_panel(tool_type)
        layout.addWidget(center_panel, 2)
        
        # 右侧：结果区（日志+Excel摘要）
        right_panel = self.create_result_panel(tool_type)
        layout.addWidget(right_panel, 2)
        
        return page
    
    def create_param_panel(self, tool_type):
        """创建参数面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 快捷操作按钮
        btn_group = QGroupBox("快捷操作")
        btn_layout = QHBoxLayout(btn_group)
        
        quick_start_btn = QPushButton("快速开始指南")
        quick_start_btn.setObjectName("SecondaryActionBtn")
        quick_start_btn.clicked.connect(self.show_quick_start)
        btn_layout.addWidget(quick_start_btn)
        
        param_help_btn = QPushButton("参数说明")
        param_help_btn.setObjectName("SecondaryActionBtn")
        param_help_btn.clicked.connect(self.show_param_help)
        btn_layout.addWidget(param_help_btn)
        
        example_btn = QPushButton("查看示例")
        example_btn.setObjectName("SecondaryActionBtn")
        example_btn.clicked.connect(self.show_example)
        btn_layout.addWidget(example_btn)
        
        layout.addWidget(btn_group)
        
        # 参数配置区
        if tool_type == 'autoline':
            layout.addWidget(self.create_autoline_params())
        elif tool_type == 'autopaste':
            layout.addWidget(self.create_autopaste_params())
        elif tool_type == 'autohatch':
            layout.addWidget(self.create_autohatch_params())
        elif tool_type == 'autoclassify':
            layout.addWidget(self.create_autoclassify_params())
        elif tool_type == 'autocut':
            layout.addWidget(self.create_autocut_params())
        
        layout.addStretch()
        return panel
    
    def create_autoline_params(self):
        """断面线合并参数"""
        group = QGroupBox("参数配置")
        form = QFormLayout(group)
        self.autoline_layer_a = QLineEdit("断面线 1")
        form.addRow("图层 A 名称:", self.autoline_layer_a)
        self.autoline_layer_b = QLineEdit("断面线 2")
        form.addRow("图层 B 名称:", self.autoline_layer_b)
        self.autoline_output_layer = QLineEdit()
        self.autoline_output_layer.setPlaceholderText("留空则默认为'合并断面线'")
        form.addRow("合并后图层名:", self.autoline_output_layer)
        return group
    
    def create_autopaste_params(self):
        """批量粘贴参数"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        group = QGroupBox("坐标参数配置")
        form = QFormLayout(group)
        self.autopaste_src_x0 = QLineEdit("86.8540")
        form.addRow("源端 0 点 X:", self.autopaste_src_x0)
        self.autopaste_src_y0 = QLineEdit("-15.0622")
        form.addRow("源端 0 点 Y:", self.autopaste_src_y0)
        self.autopaste_src_bx = QLineEdit("86.0030")
        form.addRow("源端基点 X:", self.autopaste_src_bx)
        self.autopaste_src_by = QLineEdit("-35.2980")
        form.addRow("源端基点 Y:", self.autopaste_src_by)
        self.autopaste_spacing = QLineEdit("-148.4760")
        form.addRow("断面间距:", self.autopaste_spacing)
        self.autopaste_dst_y = QLineEdit("-1470.5289")
        form.addRow("目标桩号 Y:", self.autopaste_dst_y)
        self.autopaste_dst_by = QLineEdit("-1363.5000")
        form.addRow("目标基点 Y:", self.autopaste_dst_by)
        layout.addWidget(group)
        
        # 参数复制/粘贴按钮
        param_btn_layout = QHBoxLayout()
        copy_params_btn = QPushButton("复制参数")
        copy_params_btn.setObjectName("SecondaryActionBtn")
        copy_params_btn.clicked.connect(self.copy_autopaste_params)
        param_btn_layout.addWidget(copy_params_btn)
        
        paste_params_btn = QPushButton("粘贴参数")
        paste_params_btn.setObjectName("SecondaryActionBtn")
        paste_params_btn.clicked.connect(self.paste_autopaste_params)
        param_btn_layout.addWidget(paste_params_btn)
        param_btn_layout.addStretch()
        layout.addLayout(param_btn_layout)
        
        return widget
    
    def copy_autopaste_params(self):
        """复制批量粘贴参数到剪贴板"""
        params = [
            self.autopaste_src_x0.text(),
            self.autopaste_src_y0.text(),
            self.autopaste_src_bx.text(),
            self.autopaste_src_by.text(),
            self.autopaste_spacing.text(),
            self.autopaste_dst_y.text(),
            self.autopaste_dst_by.text()
        ]
        params_str = ",".join(params)
        QApplication.clipboard().setText(params_str)
        self.status_label.setText("参数已复制到剪贴板")
    
    def paste_autopaste_params(self):
        """从剪贴板粘贴批量粘贴参数"""
        try:
            params_str = QApplication.clipboard().text()
            params = params_str.split(",")
            if len(params) >= 7:
                self.autopaste_src_x0.setText(params[0].strip())
                self.autopaste_src_y0.setText(params[1].strip())
                self.autopaste_src_bx.setText(params[2].strip())
                self.autopaste_src_by.setText(params[3].strip())
                self.autopaste_spacing.setText(params[4].strip())
                self.autopaste_dst_y.setText(params[5].strip())
                self.autopaste_dst_by.setText(params[6].strip())
                self.status_label.setText("参数已粘贴")
            else:
                QMessageBox.warning(self, "警告", "剪贴板内容格式不正确，需要7个参数用逗号分隔")
        except Exception as e:
            QMessageBox.warning(self, "警告", f"粘贴参数失败: {e}")
    
    def create_autohatch_params(self):
        """快速填充参数"""
        group = QGroupBox("填充设置")
        form = QFormLayout(group)
        self.autohatch_layer = QLineEdit("AA_填充算量层")
        form.addRow("填充层名称:", self.autohatch_layer)
        self.autohatch_text_height = QLineEdit("3.0")
        form.addRow("标注字高:", self.autohatch_text_height)
        return group
    
    def create_autoclassify_params(self):
        """分类算量参数"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 合并设置（放在最上面）
        merge_group = QGroupBox("合并设置")
        merge_form = QFormLayout(merge_group)
        self.autoclassify_merge = CheckableCheckBox("合并断面线图层（取最低Y值）")
        self.autoclassify_merge.setChecked(True)
        self.autoclassify_merge.stateChanged.connect(self.on_autoclassify_merge_changed)
        merge_form.addRow(self.autoclassify_merge)
        layout.addWidget(merge_group)
        
        # 图层名称设置
        self.autoclassify_layer_group = QGroupBox("图层名称设置")
        self.autoclassify_layer_form = QFormLayout(self.autoclassify_layer_group)
        
        # 断面线图层A
        self.autoclassify_layer_a = QLineEdit("DMX")
        self.autoclassify_layer_form.addRow("断面线图层 A:", self.autoclassify_layer_a)
        
        # 断面线图层B
        self.autoclassify_layer_b = QLineEdit("20260305")
        self.autoclassify_layer_form.addRow("断面线图层 B:", self.autoclassify_layer_b)
        
        # 合并后图层名
        self.autoclassify_merged_name = QLineEdit()
        self.autoclassify_merged_name.setPlaceholderText("留空则默认为'合并断面线'")
        self.autoclassify_layer_form.addRow("合并后图层名:", self.autoclassify_merged_name)
        
        # 桩号图层
        self.autoclassify_station = QLineEdit("0-桩号")
        self.autoclassify_layer_form.addRow("桩号图层:", self.autoclassify_station)
        
        layout.addWidget(self.autoclassify_layer_group)
        
        # 标注设置
        calc_group = QGroupBox("标注设置")
        calc_form = QFormLayout(calc_group)
        self.autoclassify_text_height = QLineEdit("2.5")
        calc_form.addRow("标注字高:", self.autoclassify_text_height)
        layout.addWidget(calc_group)
        
        return widget
    
    def on_autoclassify_merge_changed(self, state):
        """合并选项变化时动态调整界面"""
        is_checked = state == Qt.CheckState.Checked.value
        
        # 显示/隐藏图层B和合并后名称（包括标签）
        self.autoclassify_layer_b.setVisible(is_checked)
        self.autoclassify_merged_name.setVisible(is_checked)
        
        # 隐藏/显示对应的标签
        label_b = self.autoclassify_layer_form.labelForField(self.autoclassify_layer_b)
        label_merged = self.autoclassify_layer_form.labelForField(self.autoclassify_merged_name)
        if label_b:
            label_b.setVisible(is_checked)
        if label_merged:
            label_merged.setVisible(is_checked)
        
        # 更新标签
        if is_checked:
            self.autoclassify_layer_form.labelForField(self.autoclassify_layer_a).setText("断面线图层 A:")
        else:
            self.autoclassify_layer_form.labelForField(self.autoclassify_layer_a).setText("断面线图层:")
    
    def create_autocut_params(self):
        """分层算量参数"""
        group = QGroupBox("分层线设置")
        form = QFormLayout(group)
        self.autocut_elevation = QLineEdit("-5")
        form.addRow("分层线高程(m):", self.autocut_elevation)
        self.autocut_layer = QLineEdit("5m分层线")
        form.addRow("分层线图层:", self.autocut_layer)
        self.autocut_hatch_layer = QLineEdit("AA_分类填充")
        form.addRow("填充图层:", self.autocut_hatch_layer)
        return group
    
    def create_center_panel(self, tool_type):
        """创建中央文件处理面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 批量粘贴需要特殊的文件处理区（源文件+目标文件）
        if tool_type == 'autopaste':
            return self.create_autopaste_center_panel()
        
        # 文件选择区
        file_group = QGroupBox("文件处理区")
        file_layout = QVBoxLayout(file_group)
        
        drag_label = QLabel("拖放 DXF 文件到此区域 或 点击下方按钮选择文件")
        drag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drag_label.setStyleSheet("font-size: 12px; color: #888; padding: 6px;")
        file_layout.addWidget(drag_label)
        
        file_list_widget = QListWidget()
        file_list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        file_list_widget.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        file_list_widget.setMinimumHeight(75)
        file_layout.addWidget(file_list_widget, 1)
        # 存储到字典
        self.file_list_widgets[tool_type] = file_list_widget
        
        file_btn_layout = QHBoxLayout()
        select_btn = QPushButton("选择 DXF 文件")
        select_btn.setObjectName("SecondaryActionBtn")
        select_btn.clicked.connect(self.select_files)
        file_btn_layout.addWidget(select_btn)
        
        clear_btn = QPushButton("清空列表")
        clear_btn.clicked.connect(self.clear_files)
        file_btn_layout.addWidget(clear_btn)
        file_btn_layout.addStretch()
        file_layout.addLayout(file_btn_layout)
        
        # 输出设置
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("输出目录:"))
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("留空则输出到输入文件同目录")
        output_layout.addWidget(self.output_dir_edit, 1)
        output_btn = QPushButton("浏览")
        output_btn.setMaximumWidth(60)
        output_btn.clicked.connect(self.select_output_dir)
        output_layout.addWidget(output_btn)
        file_layout.addLayout(output_layout)
        
        layout.addWidget(file_group)
        
        # 处理控制区
        control_group = QGroupBox("处理控制")
        control_layout = QVBoxLayout(control_group)
        
        self.process_btn = QPushButton("开始处理")
        self.process_btn.setObjectName("PrimaryActionBtn")
        self.process_btn.clicked.connect(lambda: self.start_processing(tool_type))
        control_layout.addWidget(self.process_btn)
        
        stop_open_layout = QHBoxLayout()
        self.stop_btn = QPushButton("停止处理")
        self.stop_btn.setObjectName("SecondaryActionBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_processing)
        stop_open_layout.addWidget(self.stop_btn)
        
        open_result_btn = QPushButton("打开结果文件夹")
        open_result_btn.setObjectName("SecondaryActionBtn")
        open_result_btn.clicked.connect(self.open_result_folder)
        stop_open_layout.addWidget(open_result_btn)
        control_layout.addLayout(stop_open_layout)
        
        layout.addWidget(control_group)
        return panel
    
    def create_autopaste_center_panel(self):
        """创建批量粘贴专用的中央面板（源文件+目标文件）"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 源文件选择区
        src_group = QGroupBox("源文件（需复制的断面图）")
        src_layout = QVBoxLayout(src_group)
        
        self.autopaste_src_label = QLabel("选择要复制的源断面图文件")
        self.autopaste_src_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.autopaste_src_label.setStyleSheet("font-size: 12px; color: #888; padding: 4px;")
        src_layout.addWidget(self.autopaste_src_label)
        
        self.autopaste_src_list = QListWidget()
        self.autopaste_src_list.setMinimumHeight(60)
        src_layout.addWidget(self.autopaste_src_list)
        
        src_btn_layout = QHBoxLayout()
        src_select_btn = QPushButton("选择源文件")
        src_select_btn.setObjectName("SecondaryActionBtn")
        src_select_btn.clicked.connect(self.select_autopaste_src_files)
        src_btn_layout.addWidget(src_select_btn)
        
        src_clear_btn = QPushButton("清空")
        src_clear_btn.clicked.connect(lambda: self.autopaste_src_list.clear())
        src_btn_layout.addWidget(src_clear_btn)
        src_btn_layout.addStretch()
        src_layout.addLayout(src_btn_layout)
        
        layout.addWidget(src_group)
        
        # 目标文件选择区
        dst_group = QGroupBox("目标文件（需粘贴到的图纸）")
        dst_layout = QVBoxLayout(dst_group)
        
        self.autopaste_dst_label = QLabel("选择目标图纸文件")
        self.autopaste_dst_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.autopaste_dst_label.setStyleSheet("font-size: 12px; color: #888; padding: 4px;")
        dst_layout.addWidget(self.autopaste_dst_label)
        
        self.autopaste_dst_list = QListWidget()
        self.autopaste_dst_list.setMinimumHeight(60)
        dst_layout.addWidget(self.autopaste_dst_list)
        
        dst_btn_layout = QHBoxLayout()
        dst_select_btn = QPushButton("选择目标文件")
        dst_select_btn.setObjectName("SecondaryActionBtn")
        dst_select_btn.clicked.connect(self.select_autopaste_dst_files)
        dst_btn_layout.addWidget(dst_select_btn)
        
        dst_clear_btn = QPushButton("清空")
        dst_clear_btn.clicked.connect(lambda: self.autopaste_dst_list.clear())
        dst_btn_layout.addWidget(dst_clear_btn)
        dst_btn_layout.addStretch()
        dst_layout.addLayout(dst_btn_layout)
        
        layout.addWidget(dst_group)
        
        # 处理控制区
        control_group = QGroupBox("处理控制")
        control_layout = QVBoxLayout(control_group)
        
        self.autopaste_process_btn = QPushButton("开始粘贴")
        self.autopaste_process_btn.setObjectName("PrimaryActionBtn")
        self.autopaste_process_btn.clicked.connect(lambda: self.start_processing('autopaste'))
        control_layout.addWidget(self.autopaste_process_btn)
        
        stop_open_layout = QHBoxLayout()
        self.autopaste_stop_btn = QPushButton("停止处理")
        self.autopaste_stop_btn.setObjectName("SecondaryActionBtn")
        self.autopaste_stop_btn.setEnabled(False)
        self.autopaste_stop_btn.clicked.connect(self.stop_processing)
        stop_open_layout.addWidget(self.autopaste_stop_btn)
        
        open_result_btn = QPushButton("打开结果文件夹")
        open_result_btn.setObjectName("SecondaryActionBtn")
        open_result_btn.clicked.connect(self.open_result_folder)
        stop_open_layout.addWidget(open_result_btn)
        control_layout.addLayout(stop_open_layout)
        
        layout.addWidget(control_group)
        return panel
    
    def select_autopaste_src_files(self):
        """选择批量粘贴的源文件"""
        paths, _ = QFileDialog.getOpenFileNames(self, "选择源断面图文件", "", "DXF Files (*.dxf)")
        if paths:
            self.autopaste_src_list.clear()
            for p in paths:
                file_name = os.path.basename(p)
                item = QListWidgetItem(file_name)
                item.setData(Qt.ItemDataRole.UserRole, p)
                self.autopaste_src_list.addItem(item)
            self.status_label.setText(f"已选择 {len(paths)} 个源文件")
    
    def select_autopaste_dst_files(self):
        """选择批量粘贴的目标文件"""
        paths, _ = QFileDialog.getOpenFileNames(self, "选择目标图纸文件", "", "DXF Files (*.dxf)")
        if paths:
            self.autopaste_dst_list.clear()
            for p in paths:
                file_name = os.path.basename(p)
                item = QListWidgetItem(file_name)
                item.setData(Qt.ItemDataRole.UserRole, p)
                self.autopaste_dst_list.addItem(item)
            self.status_label.setText(f"已选择 {len(paths)} 个目标文件")
    
    def create_result_panel(self, tool_type):
        """创建结果面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 结果标签页
        self.result_tabs = QTabWidget()
        
        # 处理日志（默认在前）
        self.log_tab = QWidget()
        log_layout = QVBoxLayout(self.log_tab)
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setFont(QFont("Consolas", 10))
        log_layout.addWidget(log_text)
        # 存储到字典
        self.log_texts[tool_type] = log_text
        
        log_btn_layout = QHBoxLayout()
        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.clicked.connect(log_text.clear)
        log_btn_layout.addWidget(clear_log_btn)
        log_btn_layout.addStretch()
        log_layout.addLayout(log_btn_layout)
        
        self.result_tabs.addTab(self.log_tab, "处理日志")
        
        # Excel摘要（仅支持Excel的工具显示）
        config = TOOL_CONFIG.get(tool_type, {})
        if config.get('has_excel', False):
            self.excel_tab = QWidget()
            excel_layout = QVBoxLayout(self.excel_tab)
            result_table = QTableWidget()
            result_table.setColumnCount(0)
            result_table.setRowCount(0)
            result_table.horizontalHeader().setStretchLastSection(True)
            excel_layout.addWidget(result_table)
            # 存储到字典
            self.result_tables[tool_type] = result_table
            self.result_tabs.addTab(self.excel_tab, "Excel摘要")
        
        layout.addWidget(self.result_tabs)
        return panel

    def on_tab_changed(self, index):
        """标签页切换"""
        tab_names = ['autoline', 'autopaste', 'autohatch', 'autoclassify', 'autocut']
        if 0 <= index < len(tab_names):
            self.current_task_type = tab_names[index]
    
    def select_files(self):
        """选择文件"""
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 DXF 文件", "", "DXF Files (*.dxf)")
        if paths:
            self.selected_files.clear()
            self.selected_files.extend(paths)
            # 使用当前工具对应的文件列表控件
            file_list_widget = self.file_list_widgets.get(self.current_task_type)
            if file_list_widget:
                file_list_widget.clear()
                for p in paths:
                    file_name = os.path.basename(p)
                    file_size = os.path.getsize(p) / 1024
                    item = QListWidgetItem(f"📄 {file_name} ({file_size:.1f} KB)")
                    item.setData(Qt.ItemDataRole.UserRole, p)
                    file_list_widget.addItem(item)
            self.file_count_label.setText(f"文件：{len(self.selected_files)}")
            self.status_label.setText(f"已导入 {len(self.selected_files)} 个文件")
            
            # 在日志中显示导入信息
            log_text = self.log_texts.get(self.current_task_type)
            if log_text:
                log_text.append(f"[SYSTEM] ====== 已导入 {len(paths)} 个文件 ======")
                for i, p in enumerate(paths, 1):
                    file_name = os.path.basename(p)
                    file_size = os.path.getsize(p) / 1024
                    log_text.append(f"  [{i}] {file_name} ({file_size:.1f} KB)")
                log_text.append(f"[SYSTEM] 参数配置完成后，点击「开始处理」执行任务")
    
    def clear_files(self):
        """清空文件列表"""
        self.selected_files.clear()
        # 使用当前工具对应的文件列表控件
        file_list_widget = self.file_list_widgets.get(self.current_task_type)
        if file_list_widget:
            file_list_widget.clear()
        self.file_count_label.setText("文件：0")
        self.status_label.setText("文件列表已清空")
    
    def select_output_dir(self):
        """选择输出目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.output_dir_edit.setText(dir_path)
    
    def show_quick_start(self):
        """显示快速开始指南"""
        config = TOOL_CONFIG.get(self.current_task_type, {})
        msg = f"""<h3>{config.get('name', '')} - 快速开始指南</h3>
<ol>
<li><b>选择文件</b>：点击"选择 DXF 文件"按钮，选择要处理的DXF文件</li>
<li><b>配置参数</b>：在左侧参数面板设置相关参数</li>
<li><b>开始处理</b>：点击"开始处理"按钮执行任务</li>
<li><b>查看结果</b>：处理完成后在右侧查看日志和Excel摘要</li>
</ol>
<p><b>功能说明：</b>{config.get('desc', '')}</p>"""
        QMessageBox.information(self, "快速开始指南", msg)
    
    def show_param_help(self):
        """显示参数说明"""
        config = TOOL_CONFIG.get(self.current_task_type, {})
        if self.current_task_type == 'autoline':
            msg = """<h3>断面线合并 - 参数说明</h3>
<p><b>图层 A 名称：</b>第一个断面线所在的图层名称</p>
<p><b>图层 B 名称：</b>第二个断面线所在的图层名称</p>
<p><b>算法原理：</b>在每个X坐标处，取两条断面线的最低Y值，生成下包络线。</p>"""
        elif self.current_task_type == 'autopaste':
            msg = """<h3>批量粘贴 - 参数说明</h3>
<p><b>源端0点X/Y：</b>源图纸中断面桩号0的坐标</p>
<p><b>源端基点X/Y：</b>源图纸中参考基点坐标</p>
<p><b>断面间距：</b>相邻断面的Y间距</p>
<p><b>目标桩号Y：</b>目标图纸中桩号位置</p>
<p><b>目标基点Y：</b>目标图纸中参考基点</p>"""
        else:
            msg = f"<h3>{config.get('name', '')} - 参数说明</h3><p>请参考界面上的参数提示。</p>"
        QMessageBox.information(self, "参数说明", msg)
    
    def show_example(self):
        """显示示例"""
        config = TOOL_CONFIG.get(self.current_task_type, {})
        msg = f"""<h3>{config.get('name', '')} - 示例</h3>
<p>示例功能正在开发中，敬请期待！</p>
<p>您可以参考以下步骤：</p>
<ol>
<li>准备一个符合格式要求的DXF文件</li>
<li>按照快速开始指南操作</li>
<li>查看处理日志了解执行过程</li>
</ol>"""
        QMessageBox.information(self, "查看示例", msg)
    
    def start_processing(self, tool_type):
        """开始处理"""
        # 批量粘贴使用独立的文件列表
        if tool_type == 'autopaste':
            src_files = []
            for i in range(self.autopaste_src_list.count()):
                item = self.autopaste_src_list.item(i)
                src_files.append(item.data(Qt.ItemDataRole.UserRole))
            
            dst_files = []
            for i in range(self.autopaste_dst_list.count()):
                item = self.autopaste_dst_list.item(i)
                dst_files.append(item.data(Qt.ItemDataRole.UserRole))
            
            if not src_files:
                QMessageBox.warning(self, "警告", "请先选择源文件")
                return
            if not dst_files:
                QMessageBox.warning(self, "警告", "请先选择目标文件")
                return
            
            # 设置批量粘贴的第一个目标文件作为输出
            self.selected_files = dst_files[:1]
        
        elif not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择 DXF 文件")
            return
        
        # 清空日志和表格（使用当前工具对应的控件）
        log_text = self.log_texts.get(tool_type)
        if log_text:
            log_text.clear()
        
        result_table = self.result_tables.get(tool_type)
        if result_table:
            result_table.clear()
            result_table.setRowCount(0)
            result_table.setColumnCount(0)
        
        # 收集参数
        params = {'files': self.selected_files}
        
        if tool_type == 'autoline':
            params['图层A名称'] = self.autoline_layer_a.text()
            params['图层B名称'] = self.autoline_layer_b.text()
        elif tool_type == 'autopaste':
            # 批量粘贴需要传递源文件和目标文件
            src_files = []
            for i in range(self.autopaste_src_list.count()):
                item = self.autopaste_src_list.item(i)
                src_files.append(item.data(Qt.ItemDataRole.UserRole))
            
            dst_files = []
            for i in range(self.autopaste_dst_list.count()):
                item = self.autopaste_dst_list.item(i)
                dst_files.append(item.data(Qt.ItemDataRole.UserRole))
            
            # 使用第一个源文件和第一个目标文件
            params['源文件名'] = src_files[0] if src_files else ''
            params['目标文件名'] = dst_files[0] if dst_files else ''
            params['源端0点X'] = self.autopaste_src_x0.text()
            params['源端0点Y'] = self.autopaste_src_y0.text()
            params['源端基点X'] = self.autopaste_src_bx.text()
            params['源端基点Y'] = self.autopaste_src_by.text()
            params['断面间距'] = self.autopaste_spacing.text()
            params['目标桩号Y'] = self.autopaste_dst_y.text()
            params['目标基点Y'] = self.autopaste_dst_by.text()
        elif tool_type == 'autohatch':
            params['填充层名称'] = self.autohatch_layer.text()
        elif tool_type == 'autoclassify':
            # 断面线图层：合并时使用A和B，不合并时只使用A
            if self.autoclassify_merge.isChecked():
                layer_a = self.autoclassify_layer_a.text().strip()
                layer_b = self.autoclassify_layer_b.text().strip()
                params['断面线图层'] = f"{layer_a},{layer_b}" if layer_b else layer_a
            else:
                params['断面线图层'] = self.autoclassify_layer_a.text().strip()
            params['桩号图层'] = self.autoclassify_station.text()
            params['合并断面线'] = self.autoclassify_merge.isChecked()
        elif tool_type == 'autocut':
            params['分层线高程'] = self.autocut_elevation.text()
            params['分层线图层'] = self.autocut_layer.text()
            params['填充图层'] = self.autocut_hatch_layer.text()
        
        # 更新UI
        self.process_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在处理...")
        
        # 启动线程
        self.worker_thread = ScriptRunner(tool_type, params)
        # 使用当前工具对应的日志控件
        log_text = self.log_texts.get(tool_type)
        if log_text:
            self.worker_thread.log_out.connect(log_text.append)
        self.worker_thread.progress_updated.connect(self.update_progress)
        self.worker_thread.task_completed.connect(self.on_task_completed)
        self.worker_thread.start()
    
    def stop_processing(self):
        """停止处理"""
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.terminate()
            self.worker_thread.wait()
            # 使用当前工具对应的日志控件
            log_text = self.log_texts.get(self.current_task_type)
            if log_text:
                log_text.append("[SYSTEM] 处理已手动停止")
        self.process_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
    
    def update_progress(self, value, message):
        """更新进度"""
        self.progress_bar.setValue(value)
        if message:
            self.status_label.setText(message)
    
    def on_task_completed(self, success, result_data):
        """任务完成"""
        self.process_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        if success:
            self.status_label.setText("处理完成")
            self.progress_bar.setValue(100)
            
            # 更新Excel摘要
            excel_file = result_data.get('excel_file')
            if excel_file and hasattr(self, 'result_table'):
                self.update_excel_preview(excel_file)
            
            # 使用自定义大字体弹窗
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("执行成功")
            msg_box.setText("任务处理完成！")
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setStyleSheet("""
                QMessageBox {
                    font-size: 16px;
                    min-width: 400px;
                    min-height: 150px;
                }
                QMessageBox QLabel {
                    font-size: 18px;
                    min-width: 300px;
                }
                QPushButton {
                    font-size: 14px;
                    padding: 8px 24px;
                    min-width: 100px;
                }
            """)
            msg_box.exec()
        else:
            self.status_label.setText("处理失败")
            error_msg = result_data.get('error', '未知错误')
            # 错误弹窗也放大
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("执行失败")
            msg_box.setText(f"任务处理失败:\n{error_msg}")
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setStyleSheet("""
                QMessageBox {
                    font-size: 16px;
                    min-width: 400px;
                }
                QMessageBox QLabel {
                    font-size: 16px;
                    min-width: 300px;
                }
                QPushButton {
                    font-size: 14px;
                    padding: 8px 24px;
                }
            """)
            msg_box.exec()
    
    def update_excel_preview(self, excel_file):
        """更新Excel预览"""
        try:
            import pandas as pd
            df = pd.read_excel(excel_file, nrows=10)  # 只显示前10行
            
            # 使用当前工具对应的表格控件
            result_table = self.result_tables.get(self.current_task_type)
            if result_table:
                result_table.setColumnCount(len(df.columns))
                result_table.setRowCount(len(df))
                result_table.setHorizontalHeaderLabels(df.columns.tolist())
                
                for i in range(len(df)):
                    for j in range(len(df.columns)):
                        item = QTableWidgetItem(str(df.iat[i, j]))
                        result_table.setItem(i, j, item)
                
                result_table.resizeColumnsToContents()
        except Exception as e:
            # 使用当前工具对应的日志控件
            log_text = self.log_texts.get(self.current_task_type)
            if log_text:
                log_text.append(f"[ERROR] 读取Excel失败: {e}")
    
    def open_result_folder(self):
        """打开结果文件夹"""
        if self.selected_files:
            folder = os.path.dirname(self.selected_files[0])
            if os.path.exists(folder):
                os.startfile(folder)


class SplashScreen(QSplashScreen):
    """启动画面 - 显示大图标3秒"""
    
    def __init__(self):
        super().__init__()
        
        import base64
        
        # 从嵌入资源加载图片
        logo_pixmap = None
        try:
            from platform_resources import SPLASH_IMAGE_BASE64
            img_data = base64.b64decode(SPLASH_IMAGE_BASE64)
            logo_pixmap = QPixmap()
            logo_pixmap.loadFromData(img_data)
            print("[OK] 启动画面图片加载成功")
        except Exception as e:
            print(f"[ERROR] 加载嵌入图片失败: {e}")
        
        if logo_pixmap and not logo_pixmap.isNull():
            # 直接使用原始图片，添加白色背景和版本文字
            margin = 20
            text_height = 50
            
            # 获取原图尺寸
            orig_size = max(logo_pixmap.width(), logo_pixmap.height())
            
            # 计算显示尺寸（适应屏幕）
            screen = QApplication.primaryScreen()
            if screen:
                screen_size = screen.availableGeometry()
                max_display = min(screen_size.width(), screen_size.height()) // 2
            else:
                max_display = 600
            
            # 保持原图比例，但不超过屏幕一半
            if orig_size > max_display:
                display_size = max_display
            else:
                display_size = orig_size + margin * 2 + text_height
            
            # 创建画布
            canvas = QPixmap(display_size, display_size)
            canvas.fill(Qt.GlobalColor.white)
            
            # 缩放图片
            img_size = display_size - margin * 2 - text_height
            scaled_logo = logo_pixmap.scaled(
                img_size, img_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # 居中绘制图片
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            x = (display_size - scaled_logo.width()) // 2
            y = margin + (img_size - scaled_logo.height()) // 2
            painter.drawPixmap(x, y, scaled_logo)
            
            # 绘制底部版本文字
            painter.setPen(QPen(QColor("#333333")))
            font = QFont("Microsoft YaHei UI", 12, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(0, display_size - 40, display_size, 40,
                            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                            "航道断面算量自动化平台 v2.0")
            painter.end()
            
            self.setPixmap(canvas)
        else:
            # 如果图片加载失败，显示错误提示
            canvas = QPixmap(400, 400)
            canvas.fill(Qt.GlobalColor.white)
            painter = QPainter(canvas)
            painter.setPen(QPen(QColor("#FF0000")))
            painter.setFont(QFont("Microsoft YaHei UI", 16))
            painter.drawText(0, 0, 400, 400,
                            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                            "图片加载失败")
            painter.end()
            self.setPixmap(canvas)
        
        # 设置窗口属性
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.FramelessWindowHint
        )

    def mousePressEvent(self, event):
        """点击关闭启动画面"""
        self.close()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # 显示启动画面
    splash = SplashScreen()
    splash.show()
    app.processEvents()
    
    # 创建主窗口（在启动画面显示期间）
    window = HydraulicCADPlatform()
    
    # 使用定时器，3秒后关闭启动画面并显示主窗口
    def show_main_window():
        splash.close()
        window.show()
    
    QTimer.singleShot(3000, show_main_window)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
