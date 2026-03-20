# -*- coding: utf-8 -*-
"""
autoclassify_gui.py - 断面分类算量工具（带前端界面）
"""
import sys
import os
import datetime
import threading

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QGroupBox, QCheckBox, QMessageBox, QProgressBar, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject

# 导入核心处理函数
from autoclassify import process_autoclassify

class WorkerSignals(QObject):
    """线程信号"""
    finished = pyqtSignal(tuple)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

class WorkerThread(threading.Thread):
    """处理线程"""
    def __init__(self, input_path, timestamp, section_layers, station_layer, merge_section):
        super().__init__()
        self.input_path = input_path
        self.timestamp = timestamp
        self.section_layers = section_layers
        self.station_layer = station_layer
        self.merge_section = merge_section
        self.signals = WorkerSignals()
    
    def run(self):
        try:
            # 重定向日志
            import autoclassify
            original_log = autoclassify.log
            def gui_log(msg):
                self.signals.log.emit(msg)
            autoclassify.log = gui_log
            
            result = process_autoclassify(
                self.input_path, 
                self.timestamp,
                section_layers=self.section_layers,
                station_layer=self.station_layer,
                merge_section=self.merge_section
            )
            
            autoclassify.log = original_log
            self.signals.finished.emit(result if result else (None, None))
        except Exception as e:
            self.signals.error.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("断面分类算量工具 v1.1")
        self.setMinimumSize(650, 600)
        
        # 创建主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 输入文件选择
        input_group = QGroupBox("输入文件")
        input_layout = QHBoxLayout(input_group)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("选择DXF文件...")
        input_layout.addWidget(self.input_edit)
        input_btn = QPushButton("浏览...")
        input_btn.clicked.connect(self.select_input_file)
        input_layout.addWidget(input_btn)
        layout.addWidget(input_group)
        
        # 输出目录选择
        output_group = QGroupBox("输出目录（默认与输入文件同目录）")
        output_layout = QHBoxLayout(output_group)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("留空则输出到输入文件同目录")
        output_layout.addWidget(self.output_edit)
        output_btn = QPushButton("浏览...")
        output_btn.clicked.connect(self.select_output_dir)
        output_layout.addWidget(output_btn)
        layout.addWidget(output_group)
        
        # 参数配置
        param_group = QGroupBox("参数配置")
        param_layout = QVBoxLayout(param_group)
        
        # 断面线图层
        section_layout = QHBoxLayout()
        section_layout.addWidget(QLabel("断面线图层:"))
        self.section_edit = QLineEdit("DMX, 20260305")
        self.section_edit.setPlaceholderText("用逗号分隔多个图层")
        section_layout.addWidget(self.section_edit)
        param_layout.addLayout(section_layout)
        
        # 桩号图层
        station_layout = QHBoxLayout()
        station_layout.addWidget(QLabel("桩号图层:"))
        self.station_edit = QLineEdit("0-桩号")
        station_layout.addWidget(self.station_edit)
        param_layout.addLayout(station_layout)
        
        # 合并断面线选项
        merge_layout = QHBoxLayout()
        self.merge_checkbox = QCheckBox("合并断面线图层")
        self.merge_checkbox.setChecked(True)
        self.merge_checkbox.setToolTip("勾选：合并多个断面线图层，取最低Y值\n不勾选：仅使用第一个图层（DMX）作为最终断面线")
        merge_layout.addWidget(self.merge_checkbox)
        merge_layout.addStretch()
        param_layout.addLayout(merge_layout)
        
        layout.addWidget(param_group)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 不确定进度
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 日志输出
        log_group = QGroupBox("处理日志")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group)
        
        # 按钮
        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("开始处理")
        self.run_btn.clicked.connect(self.start_processing)
        btn_layout.addWidget(self.run_btn)
        
        self.clear_btn = QPushButton("清空日志")
        self.clear_btn.clicked.connect(self.log_text.clear)
        btn_layout.addWidget(self.clear_btn)
        
        layout.addLayout(btn_layout)
        
        # 状态
        self.is_processing = False
    
    def select_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择DXF文件", "", "DXF文件 (*.dxf);;所有文件 (*)"
        )
        if file_path:
            self.input_edit.setText(file_path)
    
    def select_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.output_edit.setText(dir_path)
    
    def log_message(self, msg):
        self.log_text.append(f"[*] {msg}")
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def start_processing(self):
        if self.is_processing:
            return
        
        input_path = self.input_edit.text().strip()
        if not input_path:
            QMessageBox.warning(self, "错误", "请选择输入文件")
            return
        
        if not os.path.exists(input_path):
            QMessageBox.warning(self, "错误", "输入文件不存在")
            return
        
        # 获取参数
        section_layers = [s.strip() for s in self.section_edit.text().split(',') if s.strip()]
        station_layer = self.station_edit.text().strip() or None
        merge_section = self.merge_checkbox.isChecked()
        
        # 时间戳
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        self.is_processing = True
        self.run_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        
        self.log_message(f"开始处理: {input_path}")
        self.log_message(f"断面线图层: {section_layers}")
        self.log_message(f"桩号图层: {station_layer}")
        self.log_message(f"合并断面线: {'是' if merge_section else '否'}")
        
        # 创建工作线程
        self.worker = WorkerThread(input_path, timestamp, section_layers, station_layer, merge_section)
        self.worker.signals.log.connect(self.log_message)
        self.worker.signals.finished.connect(self.on_finished)
        self.worker.signals.error.connect(self.on_error)
        self.worker.start()
    
    def on_finished(self, result):
        self.is_processing = False
        self.run_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        output_dxf, output_xlsx = result
        if output_dxf:
            self.log_message(f"\n[OK] 处理完成！")
            self.log_message(f"   DXF: {output_dxf}")
            self.log_message(f"   Excel: {output_xlsx}")
            QMessageBox.information(self, "完成", f"处理完成！\n\n输出文件：\n{output_dxf}\n{output_xlsx}")
        else:
            self.log_message("处理完成，但未生成输出文件")
    
    def on_error(self, error_msg):
        self.is_processing = False
        self.run_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.log_message(f"错误: {error_msg}")
        QMessageBox.critical(self, "错误", f"处理失败：\n{error_msg}")

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()