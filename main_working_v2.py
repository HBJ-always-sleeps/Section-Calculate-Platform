#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HydraulicCAD 算量自动化平台 v3.1
优化内容：
- 添加输出目录选择功能
- 修复断面线合并命名问题
- 同步适配 engine_cad.py v2.0
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
    padding: 12px 24px;
    font-size: 13px;
    font-weight: 500;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    border: 1px solid #333;
}

QTabBar::tab:selected {
    background: #333333;
    color: #0078D4;
    border-bottom: 3px solid #0078D4;
}

QGroupBox {
    font-weight: 600;
    color: #569CD6;
    border: 1px solid #3C3C3C;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 15px;
    background: #252526;
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
    padding: 10px 16px;
    font-size: 13px;
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
}

QPushButton#PrimaryActionBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #108FE4, stop:0.5 #0078D4, stop:1 #0066CC);
}

QPushButton#SelectBtn {
    background-color: #3C3C3C;
    color: #CCCCCC;
    border: 1px solid #0078D4;
    border-radius: 6px;
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
    font-size: 14px;
    font-weight: bold;
    color: #FFD700;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #555;
    border-radius: 4px;
    background: #2D2D2D;
}

QCheckBox::indicator:checked {
    background: #0078D4;
    border-color: #0078D4;
}
"""

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
                # 转换表情符号
                msg = msg.replace('✅', '[OK]')
                msg = msg.replace('❌', '[ERROR]')
                msg = msg.replace('⚠️', '[WARN]')
                msg = msg.replace('⏳', '[WAIT]')
                msg = msg.replace('✨', '[DONE]')
                msg = msg.replace('🔍', '[SCAN]')
                msg = msg.replace('🎨', '[PAINT]')
                msg = msg.replace('🚀', '[GO]')
                msg = msg.replace('📊', '[STATS]')
                msg = msg.replace('💡', '[TIP]')
                msg = msg.replace('📐', '[CALC]')
                msg = msg.replace('♻️', '[RECYCLE]')
                msg = msg.replace('📋', '[CLIPBOARD]')
                msg = msg.replace('🔗', '[LINK]')
                msg = msg.replace('⚙️', '[SETTINGS]')
                self.log_out.emit(msg)
            
            self.progress_updated.emit(30, "加载 DXF 文件...")
            
            # 导入 engine_cad 并执行对应任务
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
            else:
                log_func(f"[ERROR] 未知任务类型：{self.task_type}")
                self.task_completed.emit(False, {'error': '未知任务类型'})
                return
            
            self.progress_updated.emit(90, "生成结果文件...")
            
            # 收集输出文件
            output_files = []
            file_list = self.params.get('files', [])
            for input_file in file_list:
                if input_file and os.path.exists(input_file):
                    base_name = os.path.splitext(input_file)[0]
                    for suffix in ['_RESULT.dxf', '_算量汇总.xlsx', '_下包络合并.dxf', 
                                  '_填充完成.dxf', '_面积明细表.xlsx']:
                        output_file = base_name + suffix
                        if os.path.exists(output_file):
                            output_files.append(output_file)
            
            self.progress_updated.emit(100, "任务完成")
            self.log_out.emit("[SYSTEM] 任务执行完成")
            self.task_completed.emit(True, {'output_files': output_files})
            
        except Exception as e:
            error_msg = f"[ERROR] 任务执行崩溃:\n{traceback.format_exc()}"
            self.log_out.emit(error_msg)
            self.task_completed.emit(False, {'error': str(e)})


# ================= 主界面 =================
class HydraulicCADv3(QMainWindow):
    """主窗口 - v3 现代化 UI"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HydraulicCAD 算量自动化平台 v3.1")
        
        # 设置窗口图标
        icon_path = os.path.join(base_path, "new_logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.resize(1400, 900)
        self.current_task_type = 'autoline'
        self.selected_files = []
        self.output_dir = None  # 输出目录
        self.worker_thread = None
        
        # 应用样式
        self.setStyleSheet(MODERN_STYLESHEET)
        
        # 初始化 UI
        self.init_ui()
        
    def init_ui(self):
        """初始化用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)
        
        # 1. 功能区标签
        self.ribbon_tabs = QTabWidget()
        
        # 添加各个功能页面
        self.ribbon_tabs.addTab(self.create_autoline_tab(), "🔗 断面合并")
        self.ribbon_tabs.addTab(self.create_autopaste_tab(), "📋 批量粘贴")
        self.ribbon_tabs.addTab(self.create_autohatch_tab(), "🎨 快速填充")
        self.ribbon_tabs.addTab(self.create_autoclassify_tab(), "📐 分类算量")
        self.ribbon_tabs.addTab(self.create_autocut_tab(), "📏 分层算量")
        
        main_layout.addWidget(self.ribbon_tabs)
        
        # 2. 日志区域
        log_group = QGroupBox("处理日志")
        log_layout = QVBoxLayout(log_group)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("""
            background: #1e1e1e; 
            color: #00ff00; 
            font-family: 'Consolas'; 
            font-size: 12px; 
            border: 2px solid #333; 
            border-radius: 5px;
        """)
        log_layout.addWidget(self.log_area)
        
        # 日志控制按钮
        log_btn_layout = QHBoxLayout()
        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.clicked.connect(self.log_area.clear)
        log_btn_layout.addWidget(clear_log_btn)
        log_btn_layout.addStretch()
        log_layout.addLayout(log_btn_layout)
        
        main_layout.addWidget(log_group)
        
        # 3. 底部状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.status_bar.addWidget(self.progress_bar)
        
        self.file_count_label = QLabel("文件：0")
        self.status_bar.addWidget(self.file_count_label)
        
    def create_file_selector(self, parent):
        """创建文件选择器组件"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 文件列表
        self.file_list_widget = QListWidget()
        self.file_list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list_widget.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        layout.addWidget(self.file_list_widget, 1)
        
        # 文件操作按钮
        btn_layout = QHBoxLayout()
        
        select_btn = QPushButton("📂 选择 DXF 文件")
        select_btn.setObjectName("SelectBtn")
        select_btn.clicked.connect(self.select_files)
        btn_layout.addWidget(select_btn)
        
        clear_btn = QPushButton("🗑️ 清空列表")
        clear_btn.clicked.connect(self.clear_files)
        btn_layout.addWidget(clear_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        return widget
        
    def create_output_selector(self, parent):
        """创建输出目录选择器"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.output_dir_label = QLabel("输出目录：与源文件相同")
        layout.addWidget(self.output_dir_label, 1)
        
        output_btn = QPushButton("📁 选择输出目录")
        output_btn.clicked.connect(self.select_output_dir)
        layout.addWidget(output_btn)
        
        return widget
        
    def select_output_dir(self):
        """选择输出目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.output_dir = dir_path
            self.output_dir_label.setText(f"输出目录：{dir_path}")
        
    def create_autoline_tab(self):
        """创建断面合并页面"""
        page = QWidget()
        layout = QHBoxLayout(page)
        
        # 左侧参数配置
        params_group = QGroupBox("参数配置")
        form = QFormLayout(params_group)
        
        self.autoline_layer_a = QLineEdit("断面线 1")
        form.addRow("图层 A 名称:", self.autoline_layer_a)
        
        self.autoline_layer_b = QLineEdit("断面线 2")
        form.addRow("图层 B 名称:", self.autoline_layer_b)
        
        self.autoline_output_layer = QLineEdit("FINAL_BOTTOM_SURFACE")
        form.addRow("输出图层名:", self.autoline_output_layer)
        
        layout.addWidget(params_group, 0)
        
        # 右侧文件处理和执行
        right_layout = QVBoxLayout()
        right_layout.addWidget(self.create_file_selector(page))
        right_layout.addWidget(self.create_output_selector(page))
        
        # 执行按钮
        self.autoline_run_btn = QPushButton("🚀 开始断面合并")
        self.autoline_run_btn.setObjectName("PrimaryActionBtn")
        self.autoline_run_btn.clicked.connect(self.run_autoline)
        right_layout.addWidget(self.autoline_run_btn)
        
        right_layout.addStretch()
        layout.addLayout(right_layout)
        
        return page
        
    def create_autopaste_tab(self):
        """创建批量粘贴页面"""
        page = QWidget()
        layout = QHBoxLayout(page)
        
        # 左侧参数配置
        params_group = QGroupBox("坐标参数配置")
        form = QFormLayout(params_group)
        
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
        
        layout.addWidget(params_group, 0)
        
        # 右侧文件选择
        right_layout = QVBoxLayout()
        
        # 源文件选择
        src_group = QGroupBox("源文件")
        src_layout = QVBoxLayout(src_group)
        self.autopaste_src_label = QLabel("未选择源文件")
        src_layout.addWidget(self.autopaste_src_label)
        
        self.autopaste_src_path = ""
        src_btn = QPushButton("📂 选取源断面 DXF")
        src_btn.clicked.connect(self.select_autopaste_src)
        src_layout.addWidget(src_btn)
        
        right_layout.addWidget(src_group)
        
        # 目标文件选择
        dst_group = QGroupBox("目标文件")
        dst_layout = QVBoxLayout(dst_group)
        self.autopaste_dst_label = QLabel("未选择目标文件")
        dst_layout.addWidget(self.autopaste_dst_label)
        
        self.autopaste_dst_path = ""
        dst_btn = QPushButton("🎯 选取目标基准 DXF")
        dst_btn.clicked.connect(self.select_autopaste_dst)
        dst_layout.addWidget(dst_btn)
        
        right_layout.addWidget(dst_group)
        
        # 输出目录选择
        right_layout.addWidget(self.create_output_selector(page))
        
        # 执行按钮
        self.autopaste_run_btn = QPushButton("🚀 开始批量粘贴")
        self.autopaste_run_btn.setObjectName("PrimaryActionBtn")
        self.autopaste_run_btn.clicked.connect(self.run_autopaste)
        right_layout.addWidget(self.autopaste_run_btn)
        
        right_layout.addStretch()
        layout.addLayout(right_layout)
        
        return page
        
    def create_autohatch_tab(self):
        """创建快速填充页面"""
        page = QWidget()
        layout = QHBoxLayout(page)
        
        # 左侧参数配置
        params_group = QGroupBox("填充设置")
        form = QFormLayout(params_group)
        
        self.autohatch_layer = QLineEdit("AA_填充算量层")
        form.addRow("填充层名称:", self.autohatch_layer)
        
        self.autohatch_text_height = QLineEdit("3.0")
        form.addRow("标注字高:", self.autohatch_text_height)
        
        layout.addWidget(params_group, 0)
        
        # 右侧文件处理和执行
        right_layout = QVBoxLayout()
        right_layout.addWidget(self.create_file_selector(page))
        right_layout.addWidget(self.create_output_selector(page))
        
        # 执行按钮
        self.autohatch_run_btn = QPushButton("🚀 开始快速填充")
        self.autohatch_run_btn.setObjectName("PrimaryActionBtn")
        self.autohatch_run_btn.clicked.connect(self.run_autohatch)
        right_layout.addWidget(self.autohatch_run_btn)
        
        right_layout.addStretch()
        layout.addLayout(right_layout)
        
        return page
        
    def create_autoclassify_tab(self):
        """创建分类算量页面 - 带跳过超挖复选框"""
        page = QWidget()
        layout = QHBoxLayout(page)
        
        # 左侧参数配置
        params_group = QGroupBox("图层名称设置")
        form = QFormLayout(params_group)
        
        self.autoclassify_design = QLineEdit("开挖线")
        form.addRow("设计线图层:", self.autoclassify_design)
        
        self.autoclassify_over = QLineEdit("超挖框")
        form.addRow("超挖线图层:", self.autoclassify_over)
        
        self.autoclassify_section = QLineEdit("断面线")
        form.addRow("断面线图层:", self.autoclassify_section)
        
        self.autoclassify_geo = QLineEdit("地质分层")
        form.addRow("地层线图层:", self.autoclassify_geo)
        
        self.autoclassify_station = QLineEdit("桩号")
        form.addRow("桩号层名称:", self.autoclassify_station)
        
        layout.addWidget(params_group)
        
        # 右侧文件选择和执行
        right_layout = QVBoxLayout()
        right_layout.addWidget(self.create_file_selector(page))
        right_layout.addWidget(self.create_output_selector(page))
        
        # 跳过超挖复选框
        self.autoclassify_skip_over = QCheckBox("⚠️ 跳过超挖计算（直接对开挖线和断面线围成的区域算量）")
        self.autoclassify_skip_over.setChecked(False)
        right_layout.addWidget(self.autoclassify_skip_over)
        
        # 执行按钮
        self.autoclassify_run_btn = QPushButton("🚀 开始分类算量")
        self.autoclassify_run_btn.setObjectName("PrimaryActionBtn")
        self.autoclassify_run_btn.clicked.connect(self.run_autoclassify)
        right_layout.addWidget(self.autoclassify_run_btn)
        
        right_layout.addStretch()
        layout.addLayout(right_layout)
        
        return page
        
    def create_autocut_tab(self):
        """创建分层算量页面"""
        page = QWidget()
        layout = QHBoxLayout(page)
        
        # 左侧参数配置
        params_group = QGroupBox("分层参数")
        form = QFormLayout(params_group)
        
        self.autocut_elevation = QLineEdit("-5")
        form.addRow("分层线高程(m):", self.autocut_elevation)
        
        layout.addWidget(params_group, 0)
        
        # 右侧文件处理和执行
        right_layout = QVBoxLayout()
        right_layout.addWidget(self.create_file_selector(page))
        right_layout.addWidget(self.create_output_selector(page))
        
        # 执行按钮
        self.autocut_run_btn = QPushButton("🚀 开始分层算量")
        self.autocut_run_btn.setObjectName("PrimaryActionBtn")
        self.autocut_run_btn.clicked.connect(self.run_autocut)
        right_layout.addWidget(self.autocut_run_btn)
        
        right_layout.addStretch()
        layout.addLayout(right_layout)
        
        return page
        
    def select_files(self):
        """选择 DXF 文件"""
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 DXF 文件", "", "DXF Files (*.dxf)")
        if paths:
            self.selected_files.clear()
            self.selected_files.extend(paths)
            
            self.file_list_widget.clear()
            for p in paths:
                file_name = os.path.basename(p)
                file_size = os.path.getsize(p) / 1024
                item = QListWidgetItem(f"{file_name} ({file_size:.1f} KB)")
                item.setData(Qt.ItemDataRole.UserRole, p)
                self.file_list_widget.addItem(item)
            
            self.file_count_label.setText(f"文件：{len(self.selected_files)}")
            self.status_label.setText(f"已选择 {len(self.selected_files)} 个文件")
            
    def clear_files(self):
        """清空文件列表"""
        self.selected_files.clear()
        self.file_list_widget.clear()
        self.file_count_label.setText("文件：0")
        self.status_label.setText("文件列表已清空")
        
    def select_autopaste_src(self):
        """选择批量粘贴源文件"""
        path, _ = QFileDialog.getOpenFileName(self, "选择源断面 DXF", "", "DXF Files (*.dxf)")
        if path:
            self.autopaste_src_path = path
            self.autopaste_src_label.setText(f"源：{os.path.basename(path)}")
            
    def select_autopaste_dst(self):
        """选择批量粘贴目标文件"""
        path, _ = QFileDialog.getOpenFileName(self, "选择目标基准 DXF", "", "DXF Files (*.dxf)")
        if path:
            self.autopaste_dst_path = path
            self.autopaste_dst_label.setText(f"目标：{os.path.basename(path)}")
            
    def run_autoline(self):
        """执行断面合并任务"""
        if not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择 DXF 文件")
            return
            
        self.log_area.clear()
        self.log_area.append("<b>[系统]</b> 正在开启断面合并任务...")
        
        params = {
            '图层 A 名称': self.autoline_layer_a.text(),
            '图层 B 名称': self.autoline_layer_b.text(),
            '输出图层名': self.autoline_output_layer.text(),
            '输出目录': self.output_dir,
            'files': self.selected_files
        }
        
        self.start_task('autoline', params, self.autoline_run_btn)
        
    def run_autopaste(self):
        """执行批量粘贴任务"""
        if not self.autopaste_src_path or not self.autopaste_dst_path:
            QMessageBox.warning(self, "警告", "请选择源文件和目标文件")
            return
            
        self.log_area.clear()
        self.log_area.append("<b>[系统]</b> 正在开启批量粘贴任务...")
        
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
        
        self.start_task('autopaste', params, self.autopaste_run_btn)
        
    def run_autohatch(self):
        """执行快速填充任务"""
        if not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择 DXF 文件")
            return
            
        self.log_area.clear()
        self.log_area.append("<b>[系统]</b> 正在开启快速填充任务...")
        
        params = {
            '填充层名称': self.autohatch_layer.text(),
            '输出目录': self.output_dir,
            'files': self.selected_files
        }
        
        self.start_task('autohatch', params, self.autohatch_run_btn)
        
    def run_autoclassify(self):
        """执行分类算量任务 - 支持跳过超挖计算"""
        if not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择 DXF 文件")
            return
            
        self.log_area.clear()
        
        # 检查是否勾选跳过超挖
        skip_over = self.autoclassify_skip_over.isChecked()
        if skip_over:
            self.log_area.append("<b>[系统]</b> ⚠️ 已启用跳过超挖计算模式")
            self.log_area.append("<b>[系统]</b> 将直接对开挖线和断面线围成的区域进行算量")
        else:
            self.log_area.append("<b>[系统]</b> 正在开启分类算量任务（含超挖计算）...")
        
        params = {
            '设计线': self.autoclassify_design.text(),
            '超挖框': self.autoclassify_over.text(),
            '断面线': self.autoclassify_section.text(),
            '地层层': self.autoclassify_geo.text(),
            '桩号层': self.autoclassify_station.text(),
            'skip_over_excavation': skip_over,
            '输出目录': self.output_dir,
            'files': self.selected_files
        }
        
        self.start_task('autoclassify', params, self.autoclassify_run_btn)
        
    def run_autocut(self):
        """执行分层算量任务"""
        if not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择 DXF 文件")
            return
            
        self.log_area.clear()
        self.log_area.append("<b>[系统]</b> 正在开启分层算量任务...")
        
        params = {
            '分层线高程': self.autocut_elevation.text(),
            '输出目录': self.output_dir,
            'files': self.selected_files
        }
        
        self.start_task('autocut', params, self.autocut_run_btn)
        
    def start_task(self, task_type, params, trigger_btn):
        """启动异步任务"""
        trigger_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在处理...")
        
        self.worker_thread = ScriptRunner(task_type, params)
        self.worker_thread.log_out.connect(self.log_area.append)
        self.worker_thread.progress_updated.connect(self.update_progress)
        self.worker_thread.task_completed.connect(
            lambda success, result: self.on_task_completed(success, result, trigger_btn)
        )
        self.worker_thread.start()
        
    def update_progress(self, value, message):
        """更新进度"""
        self.progress_bar.setValue(value)
        if message:
            self.status_label.setText(message)
            
    def on_task_completed(self, success, result, trigger_btn):
        """任务完成回调"""
        trigger_btn.setEnabled(True)
        
        if success:
            self.status_label.setText("处理完成")
            self.progress_bar.setValue(100)
            QMessageBox.information(self, "成功", "任务处理完成！")
        else:
            self.status_label.setText("处理失败")
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