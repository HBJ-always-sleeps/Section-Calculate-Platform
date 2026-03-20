#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HydraulicCAD 算量自动化平台 v2.0
现代化参数中心UI，前后端分离架构
"""

import sys
import os
import traceback
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

# --- 路径兼容处理 (针对 PyInstaller 打包) ---
if getattr(sys, 'frozen', False):
    # 如果是打包后的环境，获取解压后的临时目录
    base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
else:
    # 正常运行环境
    base_path = os.path.dirname(os.path.abspath(__file__))

# 将 base_path 加入系统搜索路径，确保 import scripts 能被识别
if base_path not in sys.path:
    sys.path.insert(0, base_path)

# --- 核心 UI 库 ---
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

# --- 图表库 ---
import matplotlib
matplotlib.use('Qt5Agg')  # 使用 Qt5 后端，与 PyQt6 兼容
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# --- 依赖库检测 ---
try:
    import ezdxf
    import pandas as pd
    import shapely
    import numpy as np
    from shapely.geometry import LineString, MultiLineString, Point, box, Polygon
    from shapely.ops import unary_union, linemerge, polygonize
    import engine_cad
    print("[OK] 所有核心依赖库加载成功")
except ImportError as e:
    print(f"[WARN] 缺少依赖库: {e}")

# ================= 现代样式表 =================
MODERN_STYLESHEET = """
/* 主窗口 */
QMainWindow {
    background-color: #1E1E1E;
    color: #D4D4D4;
    font-family: 'Microsoft YaHei UI', 'Segoe UI';
}

/* 功能区标签页 */
QTabWidget::pane {
    border: 1px solid #333;
    background: #252526;
    border-radius: 4px;
    margin-top: 4px;
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

/* 参数面板 */
QGroupBox {
    font-size: 13px;
    font-weight: 600;
    color: #569CD6;
    border: 1px solid #3C3C3C;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 15px;
    background: #252526;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px 0 8px;
}

/* 输入控件 */
QLineEdit, QComboBox {
    background-color: #2D2D2D;
    color: #FFFFFF;
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 13px;
    min-height: 28px;
    selection-background-color: #0078D4;
}

QLineEdit:focus, QComboBox:focus {
    border: 2px solid #0078D4;
    background-color: #333333;
}

QLineEdit[readOnly="true"] {
    background-color: #252526;
    color: #888;
    border: 1px solid #3C3C3C;
}

/* 按钮 */
QPushButton {
    background-color: #333333;
    color: #CCCCCC;
    border: 1px solid #3C3C3C;
    border-radius: 6px;
    padding: 10px 16px;
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
    padding-top: 11px;
    padding-left: 17px;
}

QPushButton:disabled {
    background-color: #252526;
    color: #666666;
    border-color: #333333;
}

/* 主操作按钮 */
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

QPushButton#PrimaryActionBtn:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #005A9E, stop:0.5 #0066CC, stop:1 #0078D4);
}

/* 次要按钮 */
QPushButton#SecondaryActionBtn {
    background-color: #3C3C3C;
    color: #CCCCCC;
    border: 1px solid #0078D4;
    border-radius: 6px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 500;
}

/* 文件列表区域 */
QListWidget {
    background-color: #252526;
    color: #CCCCCC;
    border: 2px dashed #3C3C3C;
    border-radius: 6px;
    padding: 8px;
    font-size: 13px;
    outline: none;
}

QListWidget::item {
    background-color: #2D2D2D;
    border: 1px solid #333;
    border-radius: 4px;
    padding: 10px;
    margin: 2px;
}

QListWidget::item:hover {
    background-color: #333333;
    border-color: #0078D4;
}

QListWidget::item:selected {
    background-color: #0078D4;
    color: white;
}

/* 进度条 */
QProgressBar {
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    background-color: #252526;
    text-align: center;
    color: #CCCCCC;
    font-size: 12px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #0078D4, stop:1 #00B4FF);
    border-radius: 3px;
}

/* 表格 */
QTableWidget {
    background-color: #252526;
    color: #CCCCCC;
    border: 1px solid #3C3C3C;
    border-radius: 4px;
    gridline-color: #333;
    font-size: 12px;
    selection-background-color: #0078D4;
    selection-color: white;
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
    font-size: 12px;
}

/* 状态栏 */
QStatusBar {
    background-color: #252526;
    color: #888888;
    border-top: 1px solid #333;
    font-size: 12px;
}

/* 分隔线 */
QSplitter::handle {
    background-color: #3C3C3C;
}

QSplitter::handle:hover {
    background-color: #0078D4;
}

/* 滚动条 */
QScrollBar:vertical {
    border: none;
    background: #252526;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #3C3C3C;
    border-radius: 5px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background: #4A4A4A;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* 标签页内容区 */
QTabWidget QWidget {
    background-color: #252526;
}
"""

# ================= 核心执行引擎 =================
class ScriptRunner(QThread):
    """异步执行引擎，保持与 engine_cad.py 的兼容性"""
    log_out = pyqtSignal(str)
    progress_updated = pyqtSignal(int, str)  # (进度百分比, 状态描述)
    task_completed = pyqtSignal(bool, dict)  # (成功, 结果数据)
    
    def __init__(self, task_type, params):
        super().__init__()
        self.task_type = task_type
        self.params = params
        self.result_data = {}
        
    def run(self):
        try:
            self.log_out.emit(f"[SYSTEM] 开始执行 {self.task_type} 任务...")
            self.progress_updated.emit(10, "初始化引擎...")
            
            # 准备日志回调函数
            def log_func(msg):
                # 转换Unicode表情符号为文本表示
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
                self.log_out.emit(msg)
                
            # 调用相应的引擎函数
            self.progress_updated.emit(30, "加载DXF文件...")
            
            if self.task_type == 'autoline':
                engine_cad.run_autoline(self.params, log_func)
                self.result_data['task'] = 'autoline'
                
            elif self.task_type == 'autopaste':
                engine_cad.run_autopaste(self.params, log_func)
                self.result_data['task'] = 'autopaste'
                
            elif self.task_type == 'autosection':
                engine_cad.run_autosection(self.params, log_func)
                self.result_data['task'] = 'autosection'
                
            elif self.task_type == 'adaptive':
                engine_cad.run_adaptive(self.params, log_func)
                self.result_data['task'] = 'adaptive'
                
            else:
                log_func(f"[ERROR] 未知任务类型: {self.task_type}")
                self.progress_updated.emit(100, "任务失败")
                self.task_completed.emit(False, {'error': '未知任务类型'})
                return
            
            self.progress_updated.emit(90, "生成结果文件...")
            
            # 收集生成的文件
            output_files = []
            file_list = self.params.get('files', [])
            for input_file in file_list:
                if input_file and os.path.exists(input_file):
                    base_name = os.path.splitext(input_file)[0]
                    # 检查可能的输出文件
                    for suffix in ['_bottom_merged.dxf', '_RESULT.dxf', '_填充完成.dxf', 
                                  '_算量汇总.xlsx', '_面积明细表.xlsx']:
                        output_file = base_name + suffix
                        if os.path.exists(output_file):
                            output_files.append(output_file)
            
            self.result_data['output_files'] = output_files
            self.result_data['input_files'] = file_list
            
            self.progress_updated.emit(100, "任务完成")
            self.log_out.emit("[SYSTEM] 任务执行完成")
            self.task_completed.emit(True, self.result_data)
            
        except Exception as e:
            error_msg = f"[ERROR] 任务执行崩溃:\n{traceback.format_exc()}"
            self.log_out.emit(error_msg)
            self.progress_updated.emit(100, "任务失败")
            self.task_completed.emit(False, {'error': str(e), 'traceback': traceback.format_exc()})

# ================= 参数输入面板 =================
class ParameterPanel(QWidget):
    """智能参数输入面板，根据任务类型动态显示参数"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_task_type = None
        self.parameter_widgets = {}
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 参数组容器
        self.params_container = QStackedWidget()
        layout.addWidget(self.params_container)
        
        # 创建各个任务的参数面板
        self.create_autoline_panel()
        self.create_autopaste_panel()
        self.create_autosection_panel()
        self.create_adaptive_panel()
        
        # 默认显示第一个面板
        self.params_container.setCurrentIndex(0)
        
        layout.addStretch()
        
    def create_autoline_panel(self):
        """断面合并参数面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 图层参数组
        layer_group = QGroupBox("图层参数")
        layer_form = QFormLayout(layer_group)
        
        # 图层A名称
        layer_a_edit = QLineEdit("断面线1")
        layer_a_edit.setPlaceholderText("请输入图层A名称")
        layer_form.addRow("图层A名称:", layer_a_edit)
        self.parameter_widgets['autoline_图层A名称'] = layer_a_edit
        
        # 图层B名称
        layer_b_edit = QLineEdit("断面线2")
        layer_b_edit.setPlaceholderText("请输入图层B名称")
        layer_form.addRow("图层B名称:", layer_b_edit)
        self.parameter_widgets['autoline_图层B名称'] = layer_b_edit
        
        layout.addWidget(layer_group)
        
        # 输出设置组
        output_group = QGroupBox("输出设置")
        output_form = QFormLayout(output_group)
        
        # 自动保存选项
        auto_save_check = QCheckBox("处理完成后自动保存结果")
        auto_save_check.setChecked(True)
        output_form.addRow(auto_save_check)
        self.parameter_widgets['autoline_auto_save'] = auto_save_check
        
        # 生成日志选项
        gen_log_check = QCheckBox("生成详细处理日志")
        gen_log_check.setChecked(True)
        output_form.addRow(gen_log_check)
        self.parameter_widgets['autoline_gen_log'] = gen_log_check
        
        layout.addWidget(output_group)
        layout.addStretch()
        
        self.params_container.addWidget(panel)
        
    def create_autopaste_panel(self):
        """批量粘贴参数面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 源坐标参数组
        source_group = QGroupBox("源断面坐标参数")
        source_form = QFormLayout(source_group)
        
        # 源端0点坐标
        source_x_edit = QLineEdit("86.8540")
        source_x_edit.setPlaceholderText("源端0点X坐标")
        source_form.addRow("源端0点X:", source_x_edit)
        self.parameter_widgets['autopaste_源端0点X'] = source_x_edit
        
        source_y_edit = QLineEdit("-15.0622")
        source_y_edit.setPlaceholderText("源端0点Y坐标")
        source_form.addRow("源端0点Y:", source_y_edit)
        self.parameter_widgets['autopaste_源端0点Y'] = source_y_edit
        
        # 源端基点坐标
        source_bx_edit = QLineEdit("86.0030")
        source_bx_edit.setPlaceholderText("源端基点X坐标")
        source_form.addRow("源端基点X:", source_bx_edit)
        self.parameter_widgets['autopaste_源端基点X'] = source_bx_edit
        
        source_by_edit = QLineEdit("-35.2980")
        source_by_edit.setPlaceholderText("源端基点Y坐标")
        source_form.addRow("源端基点Y:", source_by_edit)
        self.parameter_widgets['autopaste_源端基点Y'] = source_by_edit
        
        layout.addWidget(source_group)
        
        # 目标坐标参数组
        target_group = QGroupBox("目标坐标参数")
        target_form = QFormLayout(target_group)
        
        # 断面间距
        spacing_edit = QLineEdit("-148.4760")
        spacing_edit.setPlaceholderText("断面间距")
        target_form.addRow("断面间距:", spacing_edit)
        self.parameter_widgets['autopaste_断面间距'] = spacing_edit
        
        # 目标桩号Y
        target_y_edit = QLineEdit("-1470.5289")
        target_y_edit.setPlaceholderText("目标桩号Y坐标")
        target_form.addRow("目标桩号Y:", target_y_edit)
        self.parameter_widgets['autopaste_目标桩号Y'] = target_y_edit
        
        # 目标基点Y
        target_by_edit = QLineEdit("-1363.5000")
        target_by_edit.setPlaceholderText("目标基点Y坐标")
        target_form.addRow("目标基点Y:", target_by_edit)
        self.parameter_widgets['autopaste_目标基点Y'] = target_by_edit
        
        layout.addWidget(target_group)
        
        # 操作按钮组
        button_group = QGroupBox("坐标操作")
        button_layout = QHBoxLayout(button_group)
        
        extract_btn = QPushButton("从文件提取坐标")
        extract_btn.setObjectName("SecondaryActionBtn")
        button_layout.addWidget(extract_btn)
        
        reset_btn = QPushButton("重置为默认值")
        reset_btn.setObjectName("SecondaryActionBtn")
        button_layout.addWidget(reset_btn)
        
        layout.addWidget(button_group)
        layout.addStretch()
        
        self.params_container.addWidget(panel)
        
    def create_autosection_panel(self):
        """分类算量参数面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 图层名称参数组
        layer_group = QGroupBox("图层名称设置")
        layer_form = QFormLayout(layer_group)
        
        # 设计线图层
        design_layer_edit = QLineEdit("开挖线")
        design_layer_edit.setPlaceholderText("设计线图层名称")
        layer_form.addRow("设计线图层:", design_layer_edit)
        self.parameter_widgets['autosection_设计线'] = design_layer_edit
        
        # 超挖线图层
        overcut_layer_edit = QLineEdit("超挖框")
        overcut_layer_edit.setPlaceholderText("超挖线图层名称")
        layer_form.addRow("超挖线图层:", overcut_layer_edit)
        self.parameter_widgets['autosection_超挖框'] = overcut_layer_edit
        
        # 断面线图层
        section_layer_edit = QLineEdit("断面线")
        section_layer_edit.setPlaceholderText("断面线图层名称")
        layer_form.addRow("断面线图层:", section_layer_edit)
        self.parameter_widgets['autosection_断面线'] = section_layer_edit
        
        # 地层线图层
        geo_layer_edit = QLineEdit("地质分层")
        geo_layer_edit.setPlaceholderText("地层线图层名称")
        layer_form.addRow("地层线图层:", geo_layer_edit)
        self.parameter_widgets['autosection_地层层'] = geo_layer_edit
        
        # 桩号层名称
        station_layer_edit = QLineEdit("桩号")
        station_layer_edit.setPlaceholderText("桩号层名称")
        layer_form.addRow("桩号层名称:", station_layer_edit)
        self.parameter_widgets['autosection_桩号层'] = station_layer_edit
        
        layout.addWidget(layer_group)
        
        # 计算参数组
        calc_group = QGroupBox("计算参数")
        calc_form = QFormLayout(calc_group)
        
        # 边界扩展
        margin_x_edit = QLineEdit("20.0")
        margin_x_edit.setPlaceholderText("X方向边界扩展")
        calc_form.addRow("X边界扩展:", margin_x_edit)
        self.parameter_widgets['autosection_margin_x'] = margin_x_edit
        
        margin_y_edit = QLineEdit("25.0")
        margin_y_edit.setPlaceholderText("Y方向边界扩展")
        calc_form.addRow("Y边界扩展:", margin_y_edit)
        self.parameter_widgets['autosection_margin_y'] = margin_y_edit
        
        # 标注文字高度
        text_height_edit = QLineEdit("2.5")
        text_height_edit.setPlaceholderText("标注文字高度")
        calc_form.addRow("标注字高:", text_height_edit)
        self.parameter_widgets['autosection_text_height'] = text_height_edit
        
        layout.addWidget(calc_group)
        layout.addStretch()
        
        self.params_container.addWidget(panel)
        
    def create_adaptive_panel(self):
        """快速算量参数面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 填充设置组
        fill_group = QGroupBox("填充设置")
        fill_form = QFormLayout(fill_group)
        
        # 填充层名称
        fill_layer_edit = QLineEdit("AA_填充算量层")
        fill_layer_edit.setPlaceholderText("填充层名称")
        fill_form.addRow("填充层名称:", fill_layer_edit)
        self.parameter_widgets['adaptive_填充层名称'] = fill_layer_edit
        
        # 填充图案
        fill_pattern_combo = QComboBox()
        fill_pattern_combo.addItems(["ANSI31", "ANSI37", "ANSI38", "SOLID", "HATCH"])
        fill_pattern_combo.setCurrentText("ANSI31")
        fill_form.addRow("填充图案:", fill_pattern_combo)
        self.parameter_widgets['adaptive_fill_pattern'] = fill_pattern_combo
        
        # 填充比例
        fill_scale_edit = QLineEdit("1.0")
        fill_scale_edit.setPlaceholderText("填充比例")
        fill_form.addRow("填充比例:", fill_scale_edit)
        self.parameter_widgets['adaptive_fill_scale'] = fill_scale_edit
        
        # 标注文字高度
        adaptive_text_height_edit = QLineEdit("3.0")
        adaptive_text_height_edit.setPlaceholderText("标注文字高度")
        fill_form.addRow("标注字高:", adaptive_text_height_edit)
        self.parameter_widgets['adaptive_text_height'] = adaptive_text_height_edit
        
        layout.addWidget(fill_group)
        
        # 输出设置组
        adaptive_output_group = QGroupBox("输出设置")
        adaptive_output_form = QFormLayout(adaptive_output_group)
        
        # 生成面积表选项
        gen_table_check = QCheckBox("生成Excel面积明细表")
        gen_table_check.setChecked(True)
        adaptive_output_form.addRow(gen_table_check)
        self.parameter_widgets['adaptive_gen_table'] = gen_table_check
        
        # 自动打开结果选项
        auto_open_check = QCheckBox("处理完成后自动打开结果文件夹")
        auto_open_check.setChecked(True)
        adaptive_output_form.addRow(auto_open_check)
        self.parameter_widgets['adaptive_auto_open'] = auto_open_check
        
        layout.addWidget(adaptive_output_group)
        layout.addStretch()
        
        self.params_container.addWidget(panel)
        
    def set_task_type(self, task_type):
        """切换任务类型，显示对应的参数面板"""
        self.current_task_type = task_type
        
        if task_type == 'autoline':
            self.params_container.setCurrentIndex(0)
        elif task_type == 'autopaste':
            self.params_container.setCurrentIndex(1)
        elif task_type == 'autosection':
            self.params_container.setCurrentIndex(2)
        elif task_type == 'adaptive':
            self.params_container.setCurrentIndex(3)
            
    def get_parameters(self):
        """获取当前参数面板的参数值"""
        params = {}
        
        if self.current_task_type == 'autoline':
            params['图层A名称'] = self.parameter_widgets.get('autoline_图层A名称', QLineEdit()).text()
            params['图层B名称'] = self.parameter_widgets.get('autoline_图层B名称', QLineEdit()).text()
            
        elif self.current_task_type == 'autopaste':
            params['源端0点X'] = self.parameter_widgets.get('autopaste_源端0点X', QLineEdit()).text()
            params['源端0点Y'] = self.parameter_widgets.get('autopaste_源端0点Y', QLineEdit()).text()
            params['源端基点X'] = self.parameter_widgets.get('autopaste_源端基点X', QLineEdit()).text()
            params['源端基点Y'] = self.parameter_widgets.get('autopaste_源端基点Y', QLineEdit()).text()
            params['断面间距'] = self.parameter_widgets.get('autopaste_断面间距', QLineEdit()).text()
            params['目标桩号Y'] = self.parameter_widgets.get('autopaste_目标桩号Y', QLineEdit()).text()
            params['目标基点Y'] = self.parameter_widgets.get('autopaste_目标基点Y', QLineEdit()).text()
            
        elif self.current_task_type == 'autosection':
            params['设计线'] = self.parameter_widgets.get('autosection_设计线', QLineEdit()).text()
            params['超挖框'] = self.parameter_widgets.get('autosection_超挖框', QLineEdit()).text()
            params['断面线'] = self.parameter_widgets.get('autosection_断面线', QLineEdit()).text()
            params['地层层'] = self.parameter_widgets.get('autosection_地层层', QLineEdit()).text()
            params['桩号层'] = self.parameter_widgets.get('autosection_桩号层', QLineEdit()).text()
            
        elif self.current_task_type == 'adaptive':
            params['填充层名称'] = self.parameter_widgets.get('adaptive_填充层名称', QLineEdit()).text()
            
        return params

# ================= 结果预览面板 =================
class ResultPreviewPanel(QWidget):
    """结果预览面板，包含表格和图表"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.result_data = None
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # 结果标签页
        self.result_tabs = QTabWidget()
        
        # Excel摘要标签页
        self.excel_tab = QWidget()
        excel_layout = QVBoxLayout(self.excel_tab)
        
        # Excel数据表格
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(0)
        self.result_table.setRowCount(0)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        excel_layout.addWidget(self.result_table)
        
        self.result_tabs.addTab(self.excel_tab, "Excel摘要")
        
        # 几何预览标签页
        self.geometry_tab = QWidget()
        geometry_layout = QVBoxLayout(self.geometry_tab)
        
        # 图表容器
        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        geometry_layout.addWidget(self.canvas)
        
        self.result_tabs.addTab(self.geometry_tab, "几何预览")
        
        # 处理日志标签页
        self.log_tab = QWidget()
        log_layout = QVBoxLayout(self.log_tab)
        
        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        log_layout.addWidget(self.log_text)
        
        # 日志控制按钮
        log_btn_layout = QHBoxLayout()
        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.clicked.connect(self.log_text.clear)
        log_btn_layout.addWidget(clear_log_btn)
        
        save_log_btn = QPushButton("保存日志")
        save_log_btn.clicked.connect(self.save_log)
        log_btn_layout.addWidget(save_log_btn)
        
        log_btn_layout.addStretch()
        log_layout.addLayout(log_btn_layout)
        
        self.result_tabs.addTab(self.log_tab, "处理日志")
        
        layout.addWidget(self.result_tabs)
        
    def update_excel_preview(self, excel_file_path):
        """更新Excel数据预览"""
        try:
            if not os.path.exists(excel_file_path):
                return False
                
            # 读取Excel文件
            df = pd.read_excel(excel_file_path)
            
            # 更新表格
            self.result_table.setColumnCount(len(df.columns))
            self.result_table.setRowCount(len(df))
            self.result_table.setHorizontalHeaderLabels(df.columns.tolist())
            
            for i in range(len(df)):
                for j in range(len(df.columns)):
                    item = QTableWidgetItem(str(df.iat[i, j]))
                    self.result_table.setItem(i, j, item)
                    
            # 调整列宽
            self.result_table.resizeColumnsToContents()
            
            # 存储数据供图表使用
            self.result_data = df
            
            return True
            
        except Exception as e:
            self.log_text.append(f"[ERROR] 读取Excel文件失败: {e}")
            return False
            
    def update_geometry_preview(self, dxf_file_path):
        """更新几何预览图表"""
        try:
            if not os.path.exists(dxf_file_path):
                return False
                
            # 清空图表
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            
            # 这里可以添加DXF文件解析和绘图逻辑
            # 暂时绘制一个示例图表
            ax.plot([0, 1, 2, 3, 4], [0, 1, 4, 9, 16], 'b-', linewidth=2)
            ax.set_title("几何路径预览")
            ax.set_xlabel("X坐标")
            ax.set_ylabel("Y坐标")
            ax.grid(True, alpha=0.3)
            
            # 更新画布
            self.canvas.draw()
            
            return True
            
        except Exception as e:
            self.log_text.append(f"[ERROR] 绘制几何预览失败: {e}")
            return False
            
    def append_log(self, message):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
    def save_log(self):
        """保存日志到文件"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存日志文件", "", "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.toPlainText())
                self.append_log(f"[OK] 日志已保存到: {file_path}")
            except Exception as e:
                self.append_log(f"[ERROR] 保存日志失败: {e}")
                
    def clear_all(self):
        """清空所有预览内容"""
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        self.figure.clear()
        self.canvas.draw()
        self.log_text.clear()

# ================= 主界面 =================
class HydraulicCADMainWindow(QMainWindow):
    """主窗口 - 现代化参数中心UI"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HydraulicCAD 算量自动化平台 v2.0")
        
        # 设置窗口图标
        icon_path = os.path.join(base_path, "new_logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.resize(1400, 900)
        self.current_task_type = 'autoline'
        self.selected_files = []
        self.worker_thread = None
        
        # 应用样式
        self.setStyleSheet(MODERN_STYLESHEET)
        
        # 初始化UI
        self.init_ui()
        self.init_connections()
        
    def init_ui(self):
        """初始化用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)
        
        # 1. 功能区标签
        self.ribbon_tabs = QTabWidget()
        self.ribbon_tabs.addTab(self.create_placeholder_tab(), "🔗 断面合并")
        self.ribbon_tabs.addTab(self.create_placeholder_tab(), "📋 批量粘贴")
        self.ribbon_tabs.addTab(self.create_placeholder_tab(), "📐 分类算量")
        self.ribbon_tabs.addTab(self.create_placeholder_tab(), "♻️ 快速算量")
        self.ribbon_tabs.addTab(self.create_placeholder_tab(), "⚙️ 系统设置")
        
        main_layout.addWidget(self.ribbon_tabs)
        
        # 2. 主内容区域 - 使用分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：参数面板
        self.param_panel = ParameterPanel()
        splitter.addWidget(self.param_panel)
        
        # 中央：文件处理区
        central_panel = self.create_central_panel()
        splitter.addWidget(central_panel)
        
        # 右侧：结果预览区
        self.result_panel = ResultPreviewPanel()
        splitter.addWidget(self.result_panel)
        
        # 设置分割器比例
        splitter.setSizes([300, 500, 600])
        main_layout.addWidget(splitter, 1)  # 1表示可伸缩
        
        # 3. 底部状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # 状态标签
        self.status_label = QLabel("就绪")
        self.status_bar.addWidget(self.status_label)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setTextVisible(True)
        self.status_bar.addWidget(self.progress_bar)
        
        # 文件计数
        self.file_count_label = QLabel("文件: 0")
        self.status_bar.addWidget(self.file_count_label)
        
    def create_placeholder_tab(self):
        """创建功能区标签页的占位内容"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addStretch()
        
        # 功能区按钮示例
        btn_layout = QHBoxLayout()
        
        quick_start_btn = QPushButton("快速开始指南")
        quick_start_btn.setObjectName("SecondaryActionBtn")
        btn_layout.addWidget(quick_start_btn)
        
        param_help_btn = QPushButton("参数说明")
        param_help_btn.setObjectName("SecondaryActionBtn")
        btn_layout.addWidget(param_help_btn)
        
        example_btn = QPushButton("查看示例")
        example_btn.setObjectName("SecondaryActionBtn")
        btn_layout.addWidget(example_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        return widget
        
    def create_central_panel(self):
        """创建中央文件处理面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # 1. 文件选择区域
        file_group = QGroupBox("文件处理区")
        file_layout = QVBoxLayout(file_group)
        
        # 拖拽提示标签
        drag_label = QLabel("📁 拖放 DXF 文件到此区域 或 点击下方按钮选择文件")
        drag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drag_label.setStyleSheet("font-size: 14px; color: #888; padding: 20px;")
        file_layout.addWidget(drag_label)
        
        # 文件列表
        self.file_list_widget = QListWidget()
        self.file_list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list_widget.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        file_layout.addWidget(self.file_list_widget, 1)  # 1表示可伸缩
        
        # 文件操作按钮
        file_btn_layout = QHBoxLayout()
        
        select_files_btn = QPushButton("📂 选择文件")
        select_files_btn.setObjectName("SecondaryActionBtn")
        select_files_btn.clicked.connect(self.select_files)
        file_btn_layout.addWidget(select_files_btn)
        
        clear_files_btn = QPushButton("🗑️ 清空列表")
        clear_files_btn.setObjectName("SecondaryActionBtn")
        clear_files_btn.clicked.connect(self.clear_files)
        file_btn_layout.addWidget(clear_files_btn)
        
        file_btn_layout.addStretch()
        file_layout.addLayout(file_btn_layout)
        
        layout.addWidget(file_group)
        
        # 2. 处理控制区域
        control_group = QGroupBox("处理控制")
        control_layout = QVBoxLayout(control_group)
        
        # 任务类型选择
        task_layout = QHBoxLayout()
        task_layout.addWidget(QLabel("任务类型:"))
        
        self.task_combo = QComboBox()
        self.task_combo.addItems(["断面合并", "批量粘贴", "分类算量", "快速算量"])
        self.task_combo.currentTextChanged.connect(self.on_task_type_changed)
        task_layout.addWidget(self.task_combo)
        
        task_layout.addStretch()
        control_layout.addLayout(task_layout)
        
        # 处理按钮
        self.process_btn = QPushButton("🚀 开始算量")
        self.process_btn.setObjectName("PrimaryActionBtn")
        self.process_btn.clicked.connect(self.start_processing)
        control_layout.addWidget(self.process_btn)
        
        # 停止按钮
        self.stop_btn = QPushButton("⏹️ 停止处理")
        self.stop_btn.setObjectName("SecondaryActionBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_processing)
        control_layout.addWidget(self.stop_btn)
        
        # 打开结果文件夹按钮
        open_result_btn = QPushButton("📁 打开结果文件夹")
        open_result_btn.setObjectName("SecondaryActionBtn")
        open_result_btn.clicked.connect(self.open_result_folder)
        control_layout.addWidget(open_result_btn)
        
        layout.addWidget(control_group)
        
        layout.addStretch()
        
        return panel
        
    def init_connections(self):
        """初始化信号连接"""
        # 功能区标签切换
        self.ribbon_tabs.currentChanged.connect(self.on_ribbon_tab_changed)
        
    def on_ribbon_tab_changed(self, index):
        """功能区标签切换事件"""
        tab_text = self.ribbon_tabs.tabText(index)
        
        if "断面合并" in tab_text:
            self.task_combo.setCurrentText("断面合并")
            self.current_task_type = 'autoline'
        elif "批量粘贴" in tab_text:
            self.task_combo.setCurrentText("批量粘贴")
            self.current_task_type = 'autopaste'
        elif "分类算量" in tab_text:
            self.task_combo.setCurrentText("分类算量")
            self.current_task_type = 'autosection'
        elif "快速算量" in tab_text:
            self.task_combo.setCurrentText("快速算量")
            self.current_task_type = 'adaptive'
            
        # 更新参数面板
        self.param_panel.set_task_type(self.current_task_type)
        
    def on_task_type_changed(self, task_text):
        """任务类型组合框变化事件"""
        if "断面合并" in task_text:
            self.current_task_type = 'autoline'
            self.ribbon_tabs.setCurrentIndex(0)
        elif "批量粘贴" in task_text:
            self.current_task_type = 'autopaste'
            self.ribbon_tabs.setCurrentIndex(1)
        elif "分类算量" in task_text:
            self.current_task_type = 'autosection'
            self.ribbon_tabs.setCurrentIndex(2)
        elif "快速算量" in task_text:
            self.current_task_type = 'adaptive'
            self.ribbon_tabs.setCurrentIndex(3)
            
        # 更新参数面板
        self.param_panel.set_task_type(self.current_task_type)
        
    def select_files(self):
        """选择文件"""
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter("DXF文件 (*.dxf)")
        
        if file_dialog.exec():
            file_paths = file_dialog.selectedFiles()
            self.add_files(file_paths)
            
    def add_files(self, file_paths):
        """添加文件到列表"""
        for file_path in file_paths:
            if file_path not in self.selected_files:
                self.selected_files.append(file_path)
                
                # 添加到列表控件
                file_name = os.path.basename(file_path)
                file_size = os.path.getsize(file_path) / 1024  # KB
                item_text = f"{file_name} ({file_size:.1f} KB)"
                
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, file_path)
                self.file_list_widget.addItem(item)
                
        # 更新状态栏
        self.file_count_label.setText(f"文件: {len(self.selected_files)}")
        self.status_label.setText(f"已选择 {len(self.selected_files)} 个文件")
        
    def clear_files(self):
        """清空文件列表"""
        self.selected_files.clear()
        self.file_list_widget.clear()
        self.file_count_label.setText("文件: 0")
        self.status_label.setText("文件列表已清空")
        
    def start_processing(self):
        """开始处理"""
        if not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择要处理的DXF文件")
            return
            
        # 获取参数
        params = self.param_panel.get_parameters()
        params['files'] = self.selected_files
        
        # 清空结果预览
        self.result_panel.clear_all()
        
        # 更新UI状态
        self.process_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在处理...")
        
        # 创建并启动工作线程
        self.worker_thread = ScriptRunner(self.current_task_type, params)
        self.worker_thread.log_out.connect(self.result_panel.append_log)
        self.worker_thread.progress_updated.connect(self.update_progress)
        self.worker_thread.task_completed.connect(self.on_task_completed)
        self.worker_thread.start()
        
    def stop_processing(self):
        """停止处理"""
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.terminate()
            self.worker_thread.wait()
            self.result_panel.append_log("[SYSTEM] 处理已手动停止")
            self.status_label.setText("处理已停止")
            
        self.process_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        
    def update_progress(self, value, message):
        """更新进度"""
        self.progress_bar.setValue(value)
        if message:
            self.status_label.setText(message)
            
    def on_task_completed(self, success, result_data):
        """任务完成回调"""
        self.process_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        if success:
            self.status_label.setText("处理完成")
            self.progress_bar.setValue(100)
            
            # 尝试预览结果文件
            output_files = result_data.get('output_files', [])
            for output_file in output_files:
                if output_file.endswith('.xlsx'):
                    self.result_panel.update_excel_preview(output_file)
                    break
                    
            # 显示成功消息
            QMessageBox.information(self, "成功", "任务处理完成！")
            
        else:
            self.status_label.setText("处理失败")
            error_msg = result_data.get('error', '未知错误')
            QMessageBox.critical(self, "错误", f"任务处理失败:\n{error_msg}")
            
    def open_result_folder(self):
        """打开结果文件夹"""
        # 默认为当前工作目录
        folder_path = base_path
        
        # 如果有可能，打开包含结果文件的文件夹
        if hasattr(self, 'worker_thread') and self.worker_thread:
            output_files = self.worker_thread.result_data.get('output_files', [])
            if output_files:
                folder_path = os.path.dirname(output_files[0])
                
        # 打开文件夹
        if os.path.exists(folder_path):
            os.startfile(folder_path)
        else:
            QMessageBox.warning(self, "警告", "结果文件夹不存在")

# ================= 应用程序入口 =================
def main():
    # 针对 Windows 高 DPI 屏幕优化
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # 设置应用程序信息
    app.setApplicationName("HydraulicCAD")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("HydraulicAgentProject")
    
    # 创建并显示主窗口
    window = HydraulicCADMainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()