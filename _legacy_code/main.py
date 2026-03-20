import sys, os, traceback, importlib, math, re
from collections import defaultdict, Counter

# --- 核心 UI 库 ---
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

# --- 方案 A：隧道算量全量基座依赖 ---
# 在此处强行导入，确保 Nuitka 打包时将它们全部封装进 EXE
try:
    import ezdxf
    import pandas as pd
    import shapely
    from shapely.geometry import LineString, MultiLineString, Point, box, Polygon
    from shapely.ops import unary_union, linemerge, polygonize
except ImportError as e:
    # 仅在开发环境调试时可能会触发，打包后不会有问题
    print(f"提示：打包基座缺少部分库，请检查环境: {e}")

# ================= 后续代码保持不变 (ScriptRunner, TunnelRibbonBox 等) =================

# ================= 核心执行引擎 =================
class ScriptRunner(QThread):
    log_out = pyqtSignal(str)
    done = pyqtSignal(bool)

    def __init__(self, module_name, params):
        super().__init__()
        self.module_name = module_name
        self.params = params

    def run(self):
        try:
            module = importlib.import_module(self.module_name)
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
        self.setWindowTitle("隧道断面自动化算量平台 v1.0 by HBJ")
        self.resize(1200, 850)
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # --- 统一全局样式表 (包含所有动效) ---
        self.setStyleSheet("""
            QMainWindow { background-color: #1E1E1E; }
            QWidget { background-color: #1E1E1E; color: #D4D4D4; font-family: 'Microsoft YaHei'; }

            /* 输入框白底黑字 */
            QLineEdit { 
                background-color: #FFFFFF; color: #000000; 
                border: 1px solid #333; border-radius: 4px; padding: 6px; 
            }
            QLineEdit:hover { border: 1px solid #0078D4; }
            QLineEdit:focus { background-color: #F0F8FF; border: 2px solid #0078D4; }

            /* 标签页 */
            QTabWidget::pane { border: 1px solid #444; background: #252526; border-radius: 4px; }
            QTabBar::tab { 
                background: #2D2D2D; color: #999; padding: 12px 20px; font-weight: bold;
                border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
            }
            QTabBar::tab:hover { background: #3E3E3E; color: #FFF; }
            QTabBar::tab:selected { background: #333333; color: #0078D4; border-bottom: 3px solid #0078D4; }

            /* “开始处理”大按钮动效 */
            QPushButton#ActionBtn { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0078D4, stop:1 #005A9E);
                color: white; border: none; border-radius: 8px; font-size: 18px; font-weight: bold;
            }
            QPushButton#ActionBtn:hover { 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2B8AD4, stop:1 #0078D4);
            }
            QPushButton#ActionBtn:pressed { 
                background: #004578; padding-top: 5px; padding-left: 5px; /* 点击沉降感 */
            }
            QPushButton#ActionBtn:disabled { background: #444; color: #888; }

            /* “选择文件”按钮动效 */
            QPushButton#SelectBtn { 
                background-color: #333; color: #CCC; border: 1px solid #555; border-radius: 6px; 
            }
            QPushButton#SelectBtn:hover { background-color: #444; border-color: #0078D4; color: white; }
            QPushButton#SelectBtn:pressed { background-color: #222; }

            QGroupBox { font-weight: bold; border: 1px solid #333; margin-top: 20px; padding-top: 15px; color: #569CD6; }
        """)

        self.ribbon_tabs = QTabWidget()
        self.ribbon_tabs.setMinimumHeight(350) 
        main_layout.addWidget(self.ribbon_tabs)

        # 注入页面
        self.add_ribbon_page("🔗 断面合并", "autoline", [("图层A名称", "断面线1"), ("图层B名称", "断面线2")])
        self.add_ribbon_page("📋 批量粘贴", "autopaste", [
            ("源文件名", "input.dxf"), ("目标文件名", "output.dxf"),
            ("源端0点X", "86.854"), ("源端0点Y", "-15.062"),
            ("源端基点X", "86.003"), ("源端基点Y", "-35.298"),
            ("断面间距", "-148.476"), ("目标桩号Y", "-1470.529"), ("目标基点Y", "-1363.500")
        ])
        self.add_ribbon_page("📐 分类算量", "autosection", [
            ("设计线图层", "开挖线"), ("超挖线图层", "超挖框"), ("断面线图层", "断面线"), ("地层线图层", "地质分层"), ("桩号层名称", "桩号")
        ])
        self.add_ribbon_page("♻️ 快速算量", "adaptive", [("填充层名称", "AA_填充算量层")])

        # 日志区
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("系统就绪，等待操作...")
        self.log_area.setStyleSheet("background: #1e1e1e; color: #00ff00; font-family: 'Consolas'; font-size: 12px; border: 2px solid #333; border-radius: 5px;")
        main_layout.addWidget(self.log_area)

    def add_ribbon_page(self, title, script_name, fields):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        
        params_group = QGroupBox("参数配置")
        form = QFormLayout(params_group)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        
        inputs = {}
        for label, default in fields:
            edit = QLineEdit(default)
            edit.setFixedWidth(250)
            form.addRow(f"{label}:", edit)
            inputs[label] = edit
        layout.addWidget(params_group, 0)
        layout.addSpacing(40)

        action_layout = QVBoxLayout()
        action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        f_lab = QLabel("未选择文件")
        f_lab.setStyleSheet("color: #666;")
        f_list = []
        
        # 1. 选择文件函数
        def sel():
            paths, _ = QFileDialog.getOpenFileNames(self, "选择DXF", "", "DXF Files (*.dxf)")
            if paths: 
                f_list.clear()
                f_list.extend(paths)
                f_lab.setText(f"已选择 {len(paths)} 个文件")
                self.log_area.append(f"📁 已载入文件：\n" + "\n".join([os.path.basename(p) for p in paths]))
        
        btn_sel = QPushButton("📂 选择 DXF 文件")
        btn_sel.setObjectName("SelectBtn")
        btn_sel.setFixedSize(180, 50)
        btn_sel.setCursor(Qt.CursorShape.PointingHandCursor)
        # --- 关键修复：联结信号 ---
        btn_sel.clicked.connect(sel) 
        
        btn_run = QPushButton("🚀 开始处理")
        btn_run.setObjectName("ActionBtn")
        btn_run.setFixedSize(180, 70)
        btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        # 注意：这里不再单独写 setStyleSheet，否则会覆盖全局动效

        def run():
            if not f_list: return QMessageBox.warning(self, "提示", "请先选择文件")
            params = {k: v.text() for k, v in inputs.items()}
            params['files'] = f_list
            btn_run.setEnabled(False)
            self.log_area.clear()
            self.log_area.append(f"<b>[系统]</b> 正在调用核心引擎: <i>{script_name}</i>...")
            
            self.worker = ScriptRunner(f"scripts.{script_name}", params)
            self.worker.log_out.connect(self.log_area.append)
            self.worker.done.connect(lambda: btn_run.setEnabled(True))
            self.worker.start()

        btn_run.clicked.connect(run)
        
        action_layout.addWidget(btn_sel)
        action_layout.addWidget(f_lab)
        action_layout.addSpacing(10)
        action_layout.addWidget(btn_run)
        action_layout.addStretch()
        
        layout.addLayout(action_layout)
        layout.addStretch()
        self.ribbon_tabs.addTab(page, title)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = TunnelRibbonBox()
    window.show()
    sys.exit(app.exec())