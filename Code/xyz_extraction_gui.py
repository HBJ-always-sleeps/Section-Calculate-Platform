# -*- coding: utf-8 -*-
"""
XYZ提取工具GUI界面 - PyQt6版本（外海模式）

作者: @黄秉俊
日期: 2026-04-19

流程：
1. 加载背景底图桩号位置（自动检测航道中心线图层）
2. 检测断面图开挖线和超挖线
3. 坐标转换
4. 保存XYZ文件（含插值）
5. 可视化验证
"""

import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit, QGroupBox,
    QProgressBar, QMessageBox, QDoubleSpinBox, QFormLayout,
    QGridLayout, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

# 导入外海提取模块
try:
    import extract_waihai_xyz_v2
    import visualize_waihai_xyz_scatter
except ImportError as e:
    print(f"导入模块失败: {e}")


class ExtractionThread(QThread):
    """后台执行提取任务的线程"""
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self._stopped = False
        
    def log(self, message):
        """发送日志信号"""
        self.progress_signal.emit(message)
        
    def run(self):
        try:
            success = True
            
            # 显示配置参数
            self.log("\n" + "=" * 70)
            self.log("  配置参数")
            self.log("=" * 70)
            self.log(f"背景底图: {self.config['background_dxf']}")
            self.log(f"断面图: {self.config['section_dxf']}")
            self.log(f"输出目录: {self.config['output_dir']}")
            self.log(f"水平比例尺: {self.config['scale_x']} 米/单位")
            self.log(f"垂直比例尺: {self.config['scale_y']} 米/单位")
            self.log(f"高程基准: {self.config['elevation_ref']} 米")
            self.log(f"目标高程: {self.config['target_elevation']} 米")
            self.log(f"插值间隔: {self.config['interval_x']} 米")
            
            # 检查文件
            if not os.path.exists(self.config['background_dxf']):
                self.log(f"[FAIL] 背景底图DXF不存在: {self.config['background_dxf']}")
                self.finished_signal.emit(False)
                return
            
            if not os.path.exists(self.config['section_dxf']):
                self.log(f"[FAIL] 断面图DXF不存在: {self.config['section_dxf']}")
                self.finished_signal.emit(False)
                return
            
            if not os.path.exists(self.config['output_dir']):
                self.log(f"[FAIL] 输出目录不存在: {self.config['output_dir']}")
                self.finished_signal.emit(False)
                return
            
            # 设置比例尺参数
            self.log("\n" + "=" * 70)
            self.log("  步骤 [1/2] XYZ提取")
            self.log("=" * 70)
            
            extract_waihai_xyz_v2.SCALE_X = self.config['scale_x']
            extract_waihai_xyz_v2.SCALE_Y = self.config['scale_y']
            extract_waihai_xyz_v2.ELEVATION_REF = self.config['elevation_ref']
            extract_waihai_xyz_v2.TARGET_ELEVATION = self.config['target_elevation']
            extract_waihai_xyz_v2.INTERVAL_X = self.config['interval_x']
            
            try:
                # 调用外海提取脚本
                self.log(f"[OK] 开始提取...")
                
                # 1. 加载背景底图桩号位置
                station_positions = extract_waihai_xyz_v2.load_background_stations(self.config['background_dxf'])
                self.log(f"[OK] 加载桩号位置: {len(station_positions)}个")
                
                # 2. 检测断面图开挖线和超挖线
                import ezdxf
                section_doc = ezdxf.readfile(self.config['section_dxf'])
                section_msp = section_doc.modelspace()
                section_data = extract_waihai_xyz_v2.detect_section_data(section_msp)
                self.log(f"[OK] 检测断面框: {len(section_data['frame_pairs'])}组")
                
                # 3. 坐标转换
                excav_xyz, overbreak_xyz = extract_waihai_xyz_v2.convert_to_world_coords(section_data, station_positions)
                self.log(f"[OK] 开挖线端点: {len(excav_xyz)}组")
                self.log(f"[OK] 超挖线端点: {len(overbreak_xyz)}组")
                
                # 4. 保存XYZ文件（含插值）
                excav_points, overbreak_points = extract_waihai_xyz_v2.save_xyz_files(excav_xyz, overbreak_xyz, self.config['output_dir'])
                self.log(f"[OK] 开挖线插值点: {len(excav_points)}个")
                self.log(f"[OK] 超挖线插值点: {len(overbreak_points)}个")
                
                # 检查输出文件
                kaiwa_path = os.path.join(self.config['output_dir'], '外海_开挖线_xyz.txt')
                chaowa_path = os.path.join(self.config['output_dir'], '外海_超挖线_xyz.txt')
                centerline_path = os.path.join(self.config['output_dir'], '外海_中心线位置.txt')
                
                if os.path.exists(kaiwa_path):
                    self.log(f"[OK] 开挖线XYZ: {kaiwa_path}")
                else:
                    self.log(f"[FAIL] 开挖线XYZ未生成")
                    success = False
                
                if os.path.exists(chaowa_path):
                    self.log(f"[OK] 超挖线XYZ: {chaowa_path}")
                else:
                    self.log(f"[FAIL] 超挖线XYZ未生成")
                    success = False
                
                if os.path.exists(centerline_path):
                    self.log(f"[OK] 中心线位置: {centerline_path}")
                
            except Exception as e:
                self.log(f"[FAIL] XYZ提取异常: {e}")
                import traceback
                self.log(traceback.format_exc())
                success = False
            
            # 可视化
            if self.config['visualize'] and success and not self._stopped:
                self.log("\n" + "=" * 70)
                self.log("  步骤 [2/2] 可视化验证")
                self.log("=" * 70)
                
                try:
                    visualize_waihai_xyz_scatter.main(output_dir=self.config['output_dir'])
                    png_path = os.path.join(self.config['output_dir'], '外海_xyz_scatter_plot.png')
                    if os.path.exists(png_path):
                        self.log(f"[OK] 可视化PNG: {png_path}")
                    else:
                        self.log(f"[WARN] 可视化PNG未生成")
                except Exception as e:
                    self.log(f"[WARN] 可视化异常: {e}")
            
            self.finished_signal.emit(success and not self._stopped)
            
        except Exception as e:
            self.log(f"[ERROR] {str(e)}")
            import traceback
            self.log(traceback.format_exc())
            self.finished_signal.emit(False)
    
    def stop(self):
        """停止执行"""
        self._stopped = True


class XYZExtractionGUI(QMainWindow):
    """XYZ提取工具主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("XYZ提取工具 @黄秉俊")
        self.setMinimumSize(1000, 700)
        self.resize(1100, 800)
        
        # 默认路径（外海）
        self.default_background_dxf = r'D:\断面算量平台\测试文件\外海背景.dxf'
        self.default_section_dxf = r'D:\断面算量平台\测试文件\外海断面图完整.dxf'
        self.default_output_dir = r'D:\断面算量平台\测试文件'
        
        # 默认参数（外海）
        self.default_scale_x = 3.0
        self.default_scale_y = 0.2
        self.default_elevation_ref = 0.0
        self.default_target_elevation = -24.0
        self.default_interval_x = 4.0
        
        self.init_ui()
        
    def init_ui(self):
        """初始化UI界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(10)
        
        # 标题
        title_label = QLabel("航道断面XYZ坐标提取工具")
        title_label.setFont(QFont("微软雅黑", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # 文件选择区域
        file_group = QGroupBox("文件路径设置")
        file_layout = QVBoxLayout(file_group)
        file_layout.setSpacing(8)
        
        # 背景底图DXF
        background_layout = QHBoxLayout()
        background_label = QLabel("背景底图DXF:")
        background_label.setFixedWidth(100)
        self.background_edit = QLineEdit(self.default_background_dxf)
        background_btn = QPushButton("选择...")
        background_btn.setFixedWidth(80)
        background_btn.clicked.connect(self.select_background_dxf)
        background_layout.addWidget(background_label)
        background_layout.addWidget(self.background_edit)
        background_layout.addWidget(background_btn)
        file_layout.addLayout(background_layout)
        
        # 断面图DXF
        section_layout = QHBoxLayout()
        section_label = QLabel("断面图DXF:")
        section_label.setFixedWidth(100)
        self.section_edit = QLineEdit(self.default_section_dxf)
        section_btn = QPushButton("选择...")
        section_btn.setFixedWidth(80)
        section_btn.clicked.connect(self.select_section_dxf)
        section_layout.addWidget(section_label)
        section_layout.addWidget(self.section_edit)
        section_layout.addWidget(section_btn)
        file_layout.addLayout(section_layout)
        
        # 输出目录
        output_layout = QHBoxLayout()
        output_label = QLabel("输出目录:")
        output_label.setFixedWidth(100)
        self.output_edit = QLineEdit(self.default_output_dir)
        output_btn = QPushButton("选择...")
        output_btn.setFixedWidth(80)
        output_btn.clicked.connect(self.select_output_dir)
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(output_btn)
        file_layout.addLayout(output_layout)
        
        layout.addWidget(file_group)
        
        # 参数配置
        config_group = QGroupBox("比例尺参数")
        config_layout = QFormLayout(config_group)
        config_layout.setSpacing(10)
        
        # 水平比例尺
        scale_x_layout = QHBoxLayout()
        self.scale_x_spin = QDoubleSpinBox()
        self.scale_x_spin.setRange(0.1, 100.0)
        self.scale_x_spin.setSingleStep(0.1)
        self.scale_x_spin.setValue(self.default_scale_x)
        self.scale_x_spin.setDecimals(2)
        self.scale_x_spin.setFixedWidth(150)
        scale_x_label = QLabel("米/单位（竖线间距代表X米）")
        scale_x_layout.addWidget(self.scale_x_spin)
        scale_x_layout.addWidget(scale_x_label)
        scale_x_layout.addStretch()
        config_layout.addRow("水平比例尺:", scale_x_layout)
        
        # 垂直比例尺
        scale_y_layout = QHBoxLayout()
        self.scale_y_spin = QDoubleSpinBox()
        self.scale_y_spin.setRange(0.1, 100.0)
        self.scale_y_spin.setSingleStep(0.1)
        self.scale_y_spin.setValue(self.default_scale_y)
        self.scale_y_spin.setDecimals(2)
        self.scale_y_spin.setFixedWidth(150)
        scale_y_label = QLabel("米/单位（小框短边代表Y米）")
        scale_y_layout.addWidget(self.scale_y_spin)
        scale_y_layout.addWidget(scale_y_label)
        scale_y_layout.addStretch()
        config_layout.addRow("垂直比例尺:", scale_y_layout)
        
        # 高程基准
        elev_ref_layout = QHBoxLayout()
        self.elevation_ref_spin = QDoubleSpinBox()
        self.elevation_ref_spin.setRange(-100.0, 100.0)
        self.elevation_ref_spin.setSingleStep(1.0)
        self.elevation_ref_spin.setValue(self.default_elevation_ref)
        self.elevation_ref_spin.setFixedWidth(150)
        elev_ref_label = QLabel("米（小框上长边对应高程）")
        elev_ref_layout.addWidget(self.elevation_ref_spin)
        elev_ref_layout.addWidget(elev_ref_label)
        elev_ref_layout.addStretch()
        config_layout.addRow("高程基准:", elev_ref_layout)
        
        # 目标高程
        target_elev_layout = QHBoxLayout()
        self.target_elevation_spin = QDoubleSpinBox()
        self.target_elevation_spin.setRange(-100.0, 100.0)
        self.target_elevation_spin.setSingleStep(1.0)
        self.target_elevation_spin.setValue(self.default_target_elevation)
        self.target_elevation_spin.setFixedWidth(150)
        target_elev_label = QLabel("米（延长目标高程）")
        target_elev_layout.addWidget(self.target_elevation_spin)
        target_elev_layout.addWidget(target_elev_label)
        target_elev_layout.addStretch()
        config_layout.addRow("目标高程:", target_elev_layout)
        
        # 插值间隔
        interval_layout = QHBoxLayout()
        self.interval_x_spin = QDoubleSpinBox()
        self.interval_x_spin.setRange(0.5, 20.0)
        self.interval_x_spin.setSingleStep(0.5)
        self.interval_x_spin.setValue(self.default_interval_x)
        self.interval_x_spin.setFixedWidth(150)
        interval_label = QLabel("米（XYZ点间隔）")
        interval_layout.addWidget(self.interval_x_spin)
        interval_layout.addWidget(interval_label)
        interval_layout.addStretch()
        config_layout.addRow("插值间隔:", interval_layout)
        
        layout.addWidget(config_group)
        
        # 说明
        desc_group = QGroupBox("说明")
        desc_layout = QVBoxLayout(desc_group)
        desc_label = QLabel(
            "• 航道中心线图层：自动检测（搜索包含\"航道\"和\"中心线\"的图层名）\n"
            "• 测线图层：固定为\"MARTERS测线\"\n"
            "• 桩号图层：固定为\"MARTERS测线\"\n"
            "• 断面框图层：固定为\"XSECTION\"\n"
            "• 桩号标注图层：固定为\"LABELS\""
        )
        desc_label.setStyleSheet("font-size: 11px; color: #666;")
        desc_layout.addWidget(desc_label)
        layout.addWidget(desc_group)
        
        # 可视化选项
        visualize_layout = QHBoxLayout()
        self.visualize_cb = QCheckBox("生成可视化散点图")
        self.visualize_cb.setChecked(True)
        visualize_layout.addWidget(self.visualize_cb)
        visualize_layout.addStretch()
        layout.addLayout(visualize_layout)
        
        # 控制按钮区域
        btn_layout = QHBoxLayout()
        
        self.run_btn = QPushButton("开始提取")
        self.run_btn.setFont(QFont("微软雅黑", 12))
        self.run_btn.setMinimumHeight(40)
        self.run_btn.clicked.connect(self.start_extraction)
        
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setFont(QFont("微软雅黑", 12))
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_extraction)
        
        self.clear_btn = QPushButton("清空日志")
        self.clear_btn.setFont(QFont("微软雅黑", 12))
        self.clear_btn.setMinimumHeight(40)
        self.clear_btn.clicked.connect(self.clear_log)
        
        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.clear_btn)
        
        layout.addLayout(btn_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # 日志输出区域
        log_group = QGroupBox("执行日志")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(150)
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)
        
        layout.addWidget(log_group)
        
        # 当前执行线程
        self.current_thread = None
        
    def select_background_dxf(self):
        """选择背景底图DXF文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景底图DXF文件",
            os.path.dirname(self.background_edit.text()),
            "DXF Files (*.dxf)"
        )
        if path:
            self.background_edit.setText(path)
    
    def select_section_dxf(self):
        """选择断面图DXF文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择断面图DXF文件",
            os.path.dirname(self.section_edit.text()),
            "DXF Files (*.dxf)"
        )
        if path:
            self.section_edit.setText(path)
    
    def select_output_dir(self):
        """选择输出目录"""
        path = QFileDialog.getExistingDirectory(
            self, "选择输出目录",
            self.output_edit.text()
        )
        if path:
            self.output_edit.setText(path)
    
    def start_extraction(self):
        """开始执行提取流程"""
        # 验证路径
        background_path = self.background_edit.text()
        section_path = self.section_edit.text()
        output_dir = self.output_edit.text()
        
        if not os.path.exists(background_path):
            QMessageBox.warning(self, "错误", f"背景底图DXF文件不存在:\n{background_path}")
            return
        
        if not os.path.exists(section_path):
            QMessageBox.warning(self, "错误", f"断面图DXF文件不存在:\n{section_path}")
            return
        
        if not os.path.exists(output_dir):
            QMessageBox.warning(self, "错误", f"输出目录不存在:\n{output_dir}")
            return
        
        # 更新UI状态
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        
        self.log_text.append("=== 开始XYZ提取流程 ===")
        self.log_text.append(f"背景底图: {background_path}")
        self.log_text.append(f"断面图: {section_path}")
        self.log_text.append(f"输出目录: {output_dir}")
        self.log_text.append("")
        
        # 构建配置
        config = {
            'background_dxf': background_path,
            'section_dxf': section_path,
            'output_dir': output_dir,
            'scale_x': self.scale_x_spin.value(),
            'scale_y': self.scale_y_spin.value(),
            'elevation_ref': self.elevation_ref_spin.value(),
            'target_elevation': self.target_elevation_spin.value(),
            'interval_x': self.interval_x_spin.value(),
            'visualize': self.visualize_cb.isChecked(),
        }
        
        # 创建执行线程
        self.current_thread = ExtractionThread(config)
        self.current_thread.progress_signal.connect(self.append_log)
        self.current_thread.finished_signal.connect(self.on_finished)
        self.current_thread.start()
    
    def on_finished(self, success):
        """执行完成回调"""
        self.log_text.append("")
        if success:
            self.log_text.append("=== 所有步骤执行完成 ===")
            self.progress_bar.setValue(100)
            QMessageBox.information(self, "完成", "XYZ提取流程已完成!")
        else:
            self.log_text.append("=== 执行失败 ===")
            QMessageBox.warning(self, "错误", "执行失败，请检查日志")
        
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.current_thread = None
    
    def stop_extraction(self):
        """停止执行"""
        if self.current_thread and self.current_thread.isRunning():
            self.current_thread.stop()
            self.current_thread.wait()
            self.log_text.append("[STOP] 用户中止执行")
        
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.current_thread = None
    
    def append_log(self, text):
        """追加日志文本"""
        self.log_text.append(text)
    
    def clear_log(self):
        """清空日志"""
        self.log_text.clear()


def main():
    app = QApplication(sys.argv)
    window = XYZExtractionGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()