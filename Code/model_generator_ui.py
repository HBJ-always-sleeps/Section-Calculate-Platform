# -*- coding: utf-8 -*-
"""
航道三维地质模型生成器 V18 - 简化GUI版本
布局计算版 - 确保文字完整显示

窗口尺寸: 900x750
布局计算:
- 标题区域: 100px (标题50 + 副标题30 + 间距20)
- 分隔线: 10px
- 输入组: 150px (组标题25 + 2行输入各60px + 内边距)
- 图层组: 100px (组标题25 + 1行输入60px + 内边距)
- 输出组: 130px (组标题25 + 2行输入各45px + 内边距)
- 按钮: 80px
- 进度条: 50px
- 日志: 250px
- 状态栏: 30px
- 总间距: 90px

作者: @黄秉俊
日期: 2026-04-24
"""

import sys
import subprocess
import threading
import shutil
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QGroupBox, QProgressBar, QMessageBox, QGridLayout, QFrame,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont

SCRIPT_DIR = Path(__file__).parent


class WorkerSignals(QObject):
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str, int)
    error = pyqtSignal(str)


class PipelineWorker(threading.Thread):
    def __init__(self, params, signals):
        super().__init__()
        self.params = params
        self.signals = signals

    def run(self):
        try:
            python_exe = sys.executable
            if getattr(sys, 'frozen', False):
                python_exe = r'D:\DevTools\Python\pythoncore-3.14-64\python.exe'

            section_dxf = self.params['section_dxf']
            background_dxf = self.params['background_dxf']
            output_dir = Path(self.params['output_dir'])
            output_prefix = self.params['output_prefix']
            dmx_layer = self.params.get('dmx_layer', 'DMX')

            temp_dir = output_dir / f".temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            temp_dir.mkdir(exist_ok=True)

            # 步骤1: 先生成断面元数据（脊梁点提取需要断面桩号范围）
            self.signals.progress.emit("步骤1: 生成断面元数据...", 10)

            metadata_json = temp_dir / f"{Path(section_dxf).stem}_bim_metadata.json"
            cmd1 = [python_exe, str(SCRIPT_DIR / "bim_model_builder.py"),
                    "--input", section_dxf, "--output", str(metadata_json),
                    "--dmx-layer", dmx_layer]
            result1 = subprocess.run(cmd1, capture_output=True, text=True, encoding='gbk', errors='ignore')
            if result1.returncode != 0:
                self.signals.error.emit(f"断面元数据生成失败: {result1.stderr}")
                self.signals.finished.emit(False, "断面元数据生成失败")
                return

            # 步骤2: 提取脊梁点（使用断面元数据过滤桩号范围）
            self.signals.progress.emit("步骤2: 提取脊梁点...", 25)

            spine_json = temp_dir / f"{Path(background_dxf).stem}_脊梁点.json"
            cmd2 = [python_exe, str(SCRIPT_DIR / "extract_spine_points.py"),
                    "--dxf", background_dxf, "--output", str(spine_json),
                    "--section-json", str(metadata_json)]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, encoding='gbk', errors='ignore')
            if result2.returncode != 0:
                self.signals.error.emit(f"脊梁点提取失败: {result2.stderr}")
                self.signals.finished.emit(False, "脊梁点提取失败")
                return

            self.signals.progress.emit("步骤3: 脊梁点匹配...", 40)

            match_json = temp_dir / "脊梁点_L1匹配结果.json"
            cmd3 = [python_exe, str(SCRIPT_DIR / "match_spine_to_sections.py"),
                    "--spine", str(spine_json), "--metadata", str(metadata_json),
                    "--output", str(match_json)]
            result3 = subprocess.run(cmd3, capture_output=True, text=True, encoding='gbk', errors='ignore')
            if result3.returncode != 0:
                self.signals.error.emit(f"脊梁点匹配失败: {result3.stderr or result3.stdout}")
                self.signals.finished.emit(False, "脊梁点匹配失败")
                return

            self.signals.progress.emit("步骤4: 生成三维地质模型...", 60)

            output_dxf = str(output_dir / f"{output_prefix}.dxf")
            output_obj = str(output_dir / f"{output_prefix}.obj")
            output_mtl = str(output_dir / f"{output_prefix}.mtl")

            cmd4 = [python_exe, str(SCRIPT_DIR / "geology_model_v18.py"),
                    "--metadata", str(metadata_json), "--match", str(match_json),
                    "--backfill-dxf", section_dxf,
                    "--output-dxf", output_dxf,
                    "--output-obj", output_obj,
                    "--output-mtl", output_mtl]

            result4 = subprocess.run(cmd4, capture_output=True, text=True, encoding='gbk', errors='ignore')
            if result4.returncode != 0:
                self.signals.error.emit(f"地质模型生成失败: {result4.stderr}")
                self.signals.finished.emit(False, "地质模型生成失败")
                return

            self.signals.progress.emit("清理临时文件...", 90)
            shutil.rmtree(temp_dir, ignore_errors=True)

            self.signals.progress.emit("完成！", 100)
            self.signals.finished.emit(True, f"模型生成成功！\n\n输出文件:\n{output_obj}\n{output_dxf}")

        except Exception as e:
            import traceback
            self.signals.error.emit(f"异常: {str(e)}\n{traceback.format_exc()}")
            self.signals.finished.emit(False, f"生成失败: {str(e)}")


class GeneratorUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("航道三维地质模型生成器 V18")
        # 窗口尺寸计算: 900宽 x 750高
        self.resize(900, 750)

        self.worker = None
        self.worker_signals = WorkerSignals()
        self.default_test_dir = Path(r"D:\断面算量平台\测试文件")

        self.setup_ui()
        self.connect_signals()
        self.load_defaults()

    def setup_ui(self):
        """设置界面 - 使用最小高度而非固定高度"""
        central = QWidget()
        self.setCentralWidget(central)

        # 主布局: 边距30px, 间距15px
        main = QVBoxLayout(central)
        main.setContentsMargins(30, 30, 30, 30)
        main.setSpacing(15)

        # ===== 标题区域: 约100px =====
        title = QLabel("航道三维地质模型生成器")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 不设置固定高度，让文字自然撑开
        main.addWidget(title)

        subtitle = QLabel("断面DXF + 背景DXF → 三维地质模型")
        subtitle.setFont(QFont("Microsoft YaHei", 12))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-top: 5px;")
        main.addWidget(subtitle)

        # 分隔线
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        main.addWidget(line1)

        main.addSpacing(10)  # 10px间距

        # ===== 输入文件组: 约150px =====
        input_group = QGroupBox("输入文件")
        input_group.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        # 设置组内边距
        input_group.setStyleSheet("QGroupBox { padding-top: 20px; padding-bottom: 10px; margin-top: 10px; }")

        input_grid = QGridLayout(input_group)
        input_grid.setSpacing(12)  # 行间距12px
        input_grid.setContentsMargins(15, 25, 15, 15)

        # 第1行: 断面DXF
        lbl1 = QLabel("断面图 DXF:")
        lbl1.setFont(QFont("Microsoft YaHei", 11))
        lbl1.setMinimumWidth(120)
        input_grid.addWidget(lbl1, 0, 0)

        self.section_edit = QLineEdit()
        self.section_edit.setFont(QFont("Microsoft YaHei", 11))
        self.section_edit.setMinimumHeight(40)  # 最小高度40px,足够显示文字
        self.section_edit.setPlaceholderText("包含DMX、超挖、地质和回淤的断面图")
        self.section_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        input_grid.addWidget(self.section_edit, 0, 1)

        btn1 = QPushButton("选择文件")
        btn1.setFont(QFont("Microsoft YaHei", 11))
        btn1.setMinimumHeight(40)
        btn1.setMinimumWidth(100)
        btn1.clicked.connect(self.select_section)
        input_grid.addWidget(btn1, 0, 2)

        # 第2行: 背景DXF
        lbl2 = QLabel("背景底图 DXF:")
        lbl2.setFont(QFont("Microsoft YaHei", 11))
        lbl2.setMinimumWidth(120)
        input_grid.addWidget(lbl2, 1, 0)

        self.background_edit = QLineEdit()
        self.background_edit.setFont(QFont("Microsoft YaHei", 11))
        self.background_edit.setMinimumHeight(40)
        self.background_edit.setPlaceholderText("包含脊梁点/中心线的背景底图")
        self.background_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        input_grid.addWidget(self.background_edit, 1, 1)

        btn2 = QPushButton("选择文件")
        btn2.setFont(QFont("Microsoft YaHei", 11))
        btn2.setMinimumHeight(40)
        btn2.setMinimumWidth(100)
        btn2.clicked.connect(self.select_background)
        input_grid.addWidget(btn2, 1, 2)

        # 第3行: 断面线图层名
        lbl_dmx = QLabel("断面线图层:")
        lbl_dmx.setFont(QFont("Microsoft YaHei", 11))
        lbl_dmx.setMinimumWidth(120)
        input_grid.addWidget(lbl_dmx, 2, 0)

        self.dmx_layer_edit = QLineEdit("DMX")
        self.dmx_layer_edit.setFont(QFont("Microsoft YaHei", 11))
        self.dmx_layer_edit.setMinimumHeight(40)
        self.dmx_layer_edit.setPlaceholderText("断面图中断面线所在图层名")
        self.dmx_layer_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        input_grid.addWidget(self.dmx_layer_edit, 2, 1)

        main.addWidget(input_group)

        main.addSpacing(10)

        # ===== 输出配置组: 约130px =====
        output_group = QGroupBox("输出配置")
        output_group.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        output_group.setStyleSheet("QGroupBox { padding-top: 20px; padding-bottom: 10px; margin-top: 10px; }")

        output_grid = QGridLayout(output_group)
        output_grid.setSpacing(12)
        output_grid.setContentsMargins(15, 25, 15, 15)

        lbl3 = QLabel("输出目录:")
        lbl3.setFont(QFont("Microsoft YaHei", 11))
        lbl3.setMinimumWidth(120)
        output_grid.addWidget(lbl3, 0, 0)

        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setFont(QFont("Microsoft YaHei", 11))
        self.output_dir_edit.setMinimumHeight(40)
        self.output_dir_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        output_grid.addWidget(self.output_dir_edit, 0, 1)

        btn3 = QPushButton("选择目录")
        btn3.setFont(QFont("Microsoft YaHei", 11))
        btn3.setMinimumHeight(40)
        btn3.setMinimumWidth(100)
        btn3.clicked.connect(self.select_output_dir)
        output_grid.addWidget(btn3, 0, 2)

        lbl4 = QLabel("输出文件名:")
        lbl4.setFont(QFont("Microsoft YaHei", 11))
        lbl4.setMinimumWidth(120)
        output_grid.addWidget(lbl4, 1, 0)

        self.prefix_edit = QLineEdit("Channel_Geology_Model_V18")
        self.prefix_edit.setFont(QFont("Microsoft YaHei", 11))
        self.prefix_edit.setMinimumHeight(40)
        self.prefix_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        output_grid.addWidget(self.prefix_edit, 1, 1)

        main.addWidget(output_group)

        main.addSpacing(15)

        # 分隔线
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        main.addWidget(line2)

        main.addSpacing(10)

        # ===== 按钮区域: 约80px =====
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(20)

        self.run_btn = QPushButton("生成模型")
        self.run_btn.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        self.run_btn.setMinimumHeight(50)
        self.run_btn.clicked.connect(self.run_generation)
        btn_layout.addWidget(self.run_btn, 3)

        self.viewer_btn = QPushButton("打开展示平台")
        self.viewer_btn.setFont(QFont("Microsoft YaHei", 12))
        self.viewer_btn.setMinimumHeight(50)
        self.viewer_btn.clicked.connect(self.open_viewer)
        btn_layout.addWidget(self.viewer_btn, 1)

        main.addLayout(btn_layout)

        main.addSpacing(10)

        # ===== 进度条: 约50px =====
        progress_lbl = QLabel("进度:")
        progress_lbl.setFont(QFont("Microsoft YaHei", 11))
        main.addWidget(progress_lbl)

        self.progress = QProgressBar()
        self.progress.setMinimumHeight(30)
        self.progress.setValue(0)
        self.progress.setFont(QFont("Microsoft YaHei", 10))
        main.addWidget(self.progress)

        main.addSpacing(10)

        # ===== 日志区域: 约250px =====
        log_lbl = QLabel("运行日志:")
        log_lbl.setFont(QFont("Microsoft YaHei", 11))
        main.addWidget(log_lbl)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(200)  # 最小高度200px
        self.log.setFont(QFont("Consolas", 11))
        self.log.setStyleSheet("padding: 5px;")
        main.addWidget(self.log)

        self.statusBar().showMessage("就绪")
        self.statusBar().setFont(QFont("Microsoft YaHei", 10))

    def connect_signals(self):
        self.worker_signals.progress.connect(self.on_progress)
        self.worker_signals.finished.connect(self.on_finished)
        self.worker_signals.error.connect(self.on_error)

    def load_defaults(self):
        section = self.default_test_dir / "内湾段分层图（全航道底图20260331）2018_成套粘贴v2_20260422_113140_分层回淤合并_20260423_090009.dxf"
        if not section.exists():
            section = self.default_test_dir / "内湾段分层图（全航道底图20260331）2018.dxf"
        if section.exists():
            self.section_edit.setText(str(section))

        bg = self.default_test_dir / "内湾背景原始.dxf"
        if not bg.exists():
            bg = self.default_test_dir / "内湾底图.dxf"
        if bg.exists():
            self.background_edit.setText(str(bg))

        self.output_dir_edit.setText(str(self.default_test_dir))

    def select_section(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择断面图", str(self.default_test_dir), "DXF (*.dxf)")
        if path:
            self.section_edit.setText(path)

    def select_background(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择背景底图", str(self.default_test_dir), "DXF (*.dxf)")
        if path:
            self.background_edit.setText(path)

    def select_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", str(self.default_test_dir))
        if path:
            self.output_dir_edit.setText(path)

    def run_generation(self):
        section = self.section_edit.text()
        background = self.background_edit.text()
        output_dir = self.output_dir_edit.text()

        if not section or not Path(section).exists():
            QMessageBox.warning(self, "警告", "请选择有效的断面图")
            return
        if not background or not Path(background).exists():
            QMessageBox.warning(self, "警告", "请选择有效的背景底图")
            return
        if not output_dir:
            QMessageBox.warning(self, "警告", "请选择输出目录")
            return

        # 获取断面线图层名，默认为DMX
        dmx_layer = self.dmx_layer_edit.text().strip()
        if not dmx_layer:
            dmx_layer = "DMX"
        
        params = {
            'section_dxf': section,
            'background_dxf': background,
            'output_dir': output_dir,
            'output_prefix': self.prefix_edit.text(),
            'dmx_layer': dmx_layer
        }

        self.log.clear()
        self.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始生成...")
        self.log.append(f"  断面: {Path(section).name}")
        self.log.append(f"  背景: {Path(background).name}")

        self.run_btn.setEnabled(False)
        self.run_btn.setText("正在生成...")
        self.progress.setValue(0)

        self.worker = PipelineWorker(params, self.worker_signals)
        self.worker.start()

    def on_progress(self, msg, pct):
        self.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        self.progress.setValue(pct)
        self.statusBar().showMessage(msg)

    def on_finished(self, ok, msg):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("生成模型")
        if ok:
            self.progress.setValue(100)
            self.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 成功!")
            QMessageBox.information(self, "成功", msg)
        else:
            self.progress.setValue(0)
            self.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 失败: {msg}")
            QMessageBox.warning(self, "失败", msg)

    def on_error(self, msg):
        self.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 错误: {msg}")

    def open_viewer(self):
        exe = Path(r"D:\断面算量平台\航道三维地质展示平台-便携版\航道三维地质展示平台.exe")
        if exe.exists():
            subprocess.Popen([str(exe)])
        else:
            bat = Path(r"D:\断面算量平台\LocalViewer\启动.bat")
            if bat.exists():
                subprocess.Popen([str(bat)], shell=True)
            else:
                QMessageBox.warning(self, "警告", "展示平台未找到")


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 11))
    ui = GeneratorUI()
    ui.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()