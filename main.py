# -*- coding: utf-8 -*-
import sys
import os
import traceback
import importlib
import math
import re
from collections import defaultdict, Counter

# --- 路径兼容处理 (针对 Nuitka / PyInstaller 打包) ---
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

# --- 依赖基座强行导入 (供 Nuitka 打包参考，确保这些库被包含进二进制) ---
try:
    import ezdxf
    import pandas as pd
    import shapely
    import numpy # 算量脚本通常伴随 numpy
    from shapely.geometry import LineString, MultiLineString, Point, box, Polygon
    from shapely.ops import unary_union, linemerge, polygonize
except ImportError as e:
    print(f"提示：环境库缺少: {e}")

# ================= 核心执行引擎 =================
class ScriptRunner(QThread):
    log_out = pyqtSignal(str)
    done = pyqtSignal(bool)

    def __init__(self, module_name, params):
        super().__init__()
        self.module_name = module_name # 传入形如 "scripts.autopaste"
        self.params = params

    def run(self):
        try:
            # 方案 B 下，直接动态导入编译进包内的模块
            # 注意：打包后 reload 可能无效，但在生产环境下无需 reload
            module = importlib.import_module(self.module_name)
            
            if not getattr(sys, 'frozen', False):
                importlib.reload(module) 
                
            if hasattr(module, 'run_task'):
                module.run_task(self.params, self.log_out.emit)
                self.log_out.emit("\n✅ 处理任务已完成")
            else:
                self.log_out.emit("⚠️ 脚本缺少 run_task 函数")
            self.done.emit(True)
        except Exception:
            self.log_out.emit(f"❌ 运行崩溃:\n{traceback.format_exc()}")
            self.done.emit(False)

# ================= 主界面 =================
class TunnelRibbonBox(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("航道算量自动化平台 by HBJ")
        
        # 智能加载图标
        icon_path = os.path.join(base_path, "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.resize(1200, 850)
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # --- 全局样式表 ---
        self.setStyleSheet("""
            QMainWindow { background-color: #1E1E1E; }
            QWidget { background-color: #1E1E1E; color: #D4D4D4; font-family: 'Microsoft YaHei'; }
            QLineEdit { background-color: #FFFFFF; color: #000000; border: 1px solid #333; border-radius: 4px; padding: 6px; }
            QLineEdit:focus { background-color: #F0F8FF; border: 2px solid #0078D4; }
            QTabWidget::pane { border: 1px solid #444; background: #252526; border-radius: 4px; }
            QTabBar::tab { background: #2D2D2D; color: #999; padding: 12px 20px; font-weight: bold; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }
            QTabBar::tab:selected { background: #333333; color: #0078D4; border-bottom: 3px solid #0078D4; }
            QPushButton#ActionBtn { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0078D4, stop:1 #005A9E);
                color: white; border: none; border-radius: 8px; font-size: 18px; font-weight: bold;
            }
            QPushButton#ActionBtn:disabled { background: #444; color: #888; }
            QPushButton#ActionBtn:pressed { padding-top: 5px; padding-left: 5px; }
            QPushButton#SelectBtn { background-color: #333; color: #CCC; border: 1px solid #555; border-radius: 6px; font-size: 12px;}
            QPushButton#SelectBtn:hover { background-color: #444; border-color: #0078D4; color: white; }
            QGroupBox { font-weight: bold; border: 1px solid #333; margin-top: 20px; padding-top: 15px; color: #569CD6; }
        """)

        self.ribbon_tabs = QTabWidget()
        self.ribbon_tabs.setMinimumHeight(400) 
        main_layout.addWidget(self.ribbon_tabs)

        # 1. 断面合并
        self.add_ribbon_page("🔗 断面合并", "autoline", [("图层A名称", "断面线1"), ("图层B名称", "断面线2")])
        
        # 2. 批量粘贴
        self.add_ribbon_page_special("📋 批量粘贴", "autopaste", [
            ("源端0点X", "86.8540"), ("源端0点Y", "-15.0622"),
            ("源端基点X", "86.0030"), ("源端基点Y", "-35.2980"),
            ("断面间距", "-148.4760"), ("目标桩号Y", "-1470.5289"), ("目标基点Y", "-1363.5000")
        ])

        # 3. 分类算量
        self.add_ribbon_page("📐 分类算量", "autosection", [
            ("设计线图层", "开挖线"), ("超挖线图层", "超挖框"), ("断面线图层", "断面线"), ("地层线图层", "地质分层"), ("桩号层名称", "桩号")
        ])

        # 4. 快速算量
        self.add_ribbon_page("♻️ 快速算量", "adaptive", [("填充层名称", "AA_填充算量层")])

        # 日志区
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background: #1e1e1e; color: #00ff00; font-family: 'Consolas'; font-size: 12px; border: 2px solid #333; border-radius: 5px;")
        main_layout.addWidget(self.log_area)

    def add_ribbon_page(self, title, script_name, fields):
        page = QWidget()
        layout = QHBoxLayout(page)
        params_group = QGroupBox("参数配置")
        form = QFormLayout(params_group)
        inputs = {}
        for label, default in fields:
            edit = QLineEdit(default)
            edit.setFixedWidth(250)
            form.addRow(f"{label}:", edit)
            inputs[label] = edit
        layout.addWidget(params_group, 0)
        
        action_layout = QVBoxLayout()
        f_lab = QLabel("未选择文件")
        f_list = []
        
        def sel():
            paths, _ = QFileDialog.getOpenFileNames(self, "选择DXF", "", "DXF Files (*.dxf)")
            if paths: 
                f_list.clear(); f_list.extend(paths)
                f_lab.setText(f"已选择 {len(paths)} 个文件")

        btn_sel = QPushButton("📂 选择 DXF 文件")
        btn_sel.setObjectName("SelectBtn")
        btn_sel.setFixedSize(180, 40)
        btn_sel.clicked.connect(sel)
        
        btn_run = QPushButton("🚀 开始处理")
        btn_run.setObjectName("ActionBtn")
        btn_run.setFixedSize(180, 60)

        def run():
            if not f_list: return QMessageBox.warning(self, "提示", "请先选择文件")
            params = {k: v.text() for k, v in inputs.items()}
            params['files'] = f_list
            self.execute_script(script_name, params, btn_run)

        btn_run.clicked.connect(run)
        action_layout.addWidget(btn_sel); action_layout.addWidget(f_lab); action_layout.addSpacing(10); action_layout.addWidget(btn_run); action_layout.addStretch()
        layout.addLayout(action_layout); layout.addStretch()
        self.ribbon_tabs.addTab(page, title)

    def add_ribbon_page_special(self, title, script_name, fields):
        page = QWidget()
        layout = QHBoxLayout(page)
        params_group = QGroupBox("坐标参数配置")
        form = QFormLayout(params_group)
        inputs = {}
        for label, default in fields:
            edit = QLineEdit(default)
            edit.setFixedWidth(250)
            form.addRow(f"{label}:", edit)
            inputs[label] = edit
        layout.addWidget(params_group, 0)

        action_layout = QVBoxLayout()
        f_src_path = [""]
        lab_src = QLabel("未选择源文件")
        def sel_src():
            p, _ = QFileDialog.getOpenFileName(self, "选择源断面 DXF", "", "DXF Files (*.dxf)")
            if p: f_src_path[0] = p; lab_src.setText(f"源: {os.path.basename(p)}")

        btn_src = QPushButton("📂 选取：源文件 (Source)")
        btn_src.setObjectName("SelectBtn")
        btn_src.setFixedSize(200, 35)
        btn_src.clicked.connect(sel_src)

        f_dst_path = [""]
        lab_dst = QLabel("未选择目标文件")
        def sel_dst():
            p, _ = QFileDialog.getOpenFileName(self, "选择目标基准 DXF", "", "DXF Files (*.dxf)")
            if p: f_dst_path[0] = p; lab_dst.setText(f"目: {os.path.basename(p)}")

        btn_dst = QPushButton("🎯 选取：目标文件 (Target)")
        btn_dst.setObjectName("SelectBtn")
        btn_dst.setFixedSize(200, 35)
        btn_dst.clicked.connect(sel_dst)

        btn_run = QPushButton("🚀 开始批量粘贴")
        btn_run.setObjectName("ActionBtn")
        btn_run.setFixedSize(200, 60)

        def run():
            if not f_src_path[0] or not f_dst_path[0]: 
                return QMessageBox.warning(self, "提示", "请确保已选取源文件和目标文件")
            params = {k: v.text() for k, v in inputs.items()}
            params['源文件名'] = f_src_path[0]
            params['目标文件名'] = f_dst_path[0]
            params['files'] = [f_src_path[0]]
            self.execute_script(script_name, params, btn_run)

        btn_run.clicked.connect(run)
        action_layout.addWidget(btn_src); action_layout.addWidget(lab_src)
        action_layout.addSpacing(10)
        action_layout.addWidget(btn_dst); action_layout.addWidget(lab_dst)
        action_layout.addSpacing(20)
        action_layout.addWidget(btn_run); action_layout.addStretch()
        
        layout.addLayout(action_layout); layout.addStretch()
        self.ribbon_tabs.addTab(page, title)

    def execute_script(self, script_name, params, trigger_btn):
        trigger_btn.setEnabled(False)
        self.log_area.clear()
        self.log_area.append(f"<b>[系统]</b> 正在开启核心引擎任务: <i>{script_name}</i>...")
        
        # 传递 "scripts.xxx" 进行加载
        self.worker = ScriptRunner(f"scripts.{script_name}", params)
        self.worker.log_out.connect(self.log_area.append)
        self.worker.done.connect(lambda: trigger_btn.setEnabled(True))
        self.worker.start()

if __name__ == "__main__":
    # 针对 Windows 高 DPI 屏幕优化
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = TunnelRibbonBox()
    window.show()
    sys.exit(app.exec())