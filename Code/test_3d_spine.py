# -*- coding: utf-8 -*-
"""
三维脊梁线测试 - 展示前5个断面的三维位置

关键概念：
1. L1垂直线和水平线的交点 = 基点
2. 所有基点在同一直线上排序 = 航道中心线
3. 断面间平行
4. 航道中心线平行于XY平面

作者: @黄秉俊
日期: 2026-03-28
"""

import ezdxf
import os
import math
import re
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import numpy as np

class Spine3DVisualizer:
    """三维脊梁线可视化器"""
    
    STATION_PATTERN = re.compile(r'(\d+\+\d+)')
    
    def __init__(self, dxf_path):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        
    def extract_spine_data(self):
        """提取L1脊梁线数据"""
        print("\n=== 提取L1脊梁线数据 ===")
        
        # 分析L1图层
        line_entities = []
        for e in self.msp.query('LINE[layer=="L1"]'):
            try:
                x_min = min(e.dxf.start.x, e.dxf.end.x)
                x_max = max(e.dxf.start.x, e.dxf.end.x)
                y_min = min(e.dxf.start.y, e.dxf.end.y)
                y_max = max(e.dxf.start.y, e.dxf.end.y)
                
                line_entities.append({
                    'type': 'LINE',
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'width': x_max - x_min,
                    'height': y_max - y_min,
                    'y_center': (y_min + y_max) / 2,
                    'x_center': (x_min + x_max) / 2
                })
            except: pass
        
        # 分离水平和垂直线
        horizontal_lines = []
        vertical_lines = []
        
        for line in line_entities:
            width = line.get('width', 0)
            height = line.get('height', 0)
            
            if width > height * 3:
                horizontal_lines.append(line)
            elif height > width * 3:
                vertical_lines.append(line)
        
        print(f"  水平LINE数: {len(horizontal_lines)}")
        print(f"  垂直LINE数: {len(vertical_lines)}")
        
        # 按Y排序
        sorted_v = sorted(vertical_lines, key=lambda e: e.get('y_center', 0), reverse=True)
        sorted_h = sorted(horizontal_lines, key=lambda e: e.get('y_center', 0), reverse=True)
        
        # 最近邻匹配
        spine_data = []
        used_h_indices = set()
        
        for idx, v_line in enumerate(sorted_v):
            v_y_center = v_line.get('y_center', 0)
            v_x_center = v_line.get('x_center', 0)
            
            # 找最近水平线
            best_h_line = None
            best_y_diff = float('inf')
            best_h_idx = -1
            
            for h_idx, h_line in enumerate(sorted_h):
                if h_idx in used_h_indices:
                    continue
                h_y = h_line.get('y_center', 0)
                y_diff = abs(h_y - v_y_center)
                if y_diff < best_y_diff:
                    best_y_diff = y_diff
                    best_h_line = h_line
                    best_h_idx = h_idx
            
            # 标记已使用
            if best_h_line and best_y_diff < 50:
                used_h_indices.add(best_h_idx)
                h_x_center = best_h_line.get('x_center', 0)
                
                # ===== 基点 = 垂直线和水平线的交点 =====
                # 垂直线是航道中心线（固定X），水平线是顶边（固定Y）
                # 交点坐标: (垂直线X中心, 垂直线Y中心, 0)
                # 注意：在CAD中Y是垂直方向，但在三维中Y是前进方向
                
                spine_data.append({
                    'section_index': idx + 1,
                    # 基点坐标（CAD坐标系）
                    'base_point_cad': (v_x_center, v_y_center, 0),
                    # 垂直线高度（航道深度）- 从顶到底的高度
                    'depth': v_line.get('height', 0),
                    # 顶边宽度
                    'top_width': best_h_line.get('width', 0),
                    # 垂直线和水平线信息
                    'v_line': v_line,
                    'h_line': best_h_line,
                    'matched': True
                })
        
        print(f"  匹配脊梁线数: {len(spine_data)}")
        
        return spine_data
    
    def extract_station_texts(self):
        """提取桩号文本"""
        stations = []
        for e in self.msp.query('TEXT[layer=="L1"]'):
            try:
                txt = e.dxf.text
                match = self.STATION_PATTERN.search(txt.upper())
                if match:
                    x = e.dxf.insert.x
                    y = e.dxf.insert.y
                    sid = match.group(1)
                    stations.append({
                        'text': sid,
                        'x': x,
                        'y': y
                    })
            except: pass
        
        # 按Y排序
        return sorted(stations, key=lambda s: s['y'], reverse=True)
    
    def visualize_5_sections(self, spine_data, station_texts):
        """可视化前5个断面"""
        print("\n=== 三维可视化前5个断面 ===")
        
        # 取前5个脊梁线
        sections = spine_data[:5]
        
        if len(sections) < 5:
            print(f"  警告：只有{len(sections)}个断面")
            sections = spine_data
        
        # 创建三维图
        fig = plt.figure(figsize=(14, 10))
        ax = fig.add_subplot(111, projection='3d')
        
        # ===== 坐标系转换 =====
        # CAD坐标系: X向右，Y向下（图纸垂直方向）
        # 三维坐标系: X向右，Y向前（航道前进方向），Z向上（深度）
        # 转换: CAD_Y -> 3D_Y（航道前进方向）
        #       CAD_Y负值越大 -> 3D_Y越大（更远）
        #       深度 = 垂直线高度 -> 3D_Z负值
        
        # 收集所有基点
        base_points = []
        
        for i, section in enumerate(sections):
            # CAD坐标
            cad_x, cad_y, _ = section['base_point_cad']
            depth = section['depth']
            top_width = section['top_width']
            
            # ===== 三维坐标转换 =====
            # X保持不变
            # Y = -cad_y（取负值，使Y值从小到大表示前进）
            # Z = 0（基点在水面/顶面）
            x_3d = cad_x
            y_3d = -cad_y  # 转换：CAD Y负值 -> 3D Y正值
            z_3d = 0       # 基点在顶面
            
            base_points.append((x_3d, y_3d, z_3d))
            
            # 找对应桩号
            station_text = f"断面{i+1}"
            for st in station_texts:
                if abs(st['y'] - cad_y) < 50:
                    station_text = st['text']
                    break
            
            print(f"  [{i+1}] 桩号{station_text}: 基点({x_3d:.1f}, {y_3d:.1f}, {z_3d:.1f}), 深度={depth:.1f}, 宽度={top_width:.1f}")
            
            # ===== 绘制单个断面 =====
            # 断面是一个矩形区域：
            # - 顶边：水平线位置（Y固定），宽度=top_width
            # - 底边：垂直线底部（Y固定），宽度=top_width
            # - 垂直线：从顶到底，高度=depth
            
            # 断面四角点（在三维中）
            # 顶边中心 = 基点
            # 顶边左右端点
            half_width = top_width / 2
            top_left = (x_3d - half_width, y_3d, z_3d)
            top_right = (x_3d + half_width, y_3d, z_3d)
            
            # 底边端点（深度向下）
            bottom_z = -depth  # 深度为负Z值
            bottom_left = (x_3d - half_width, y_3d, bottom_z)
            bottom_right = (x_3d + half_width, y_3d, bottom_z)
            
            # 绘制断面边框（红色）
            # 顶边
            ax.plot([top_left[0], top_right[0]], [top_left[1], top_right[1]], [top_left[2], top_right[2]], 'r-', linewidth=2)
            # 底边
            ax.plot([bottom_left[0], bottom_right[0]], [bottom_left[1], bottom_right[1]], [bottom_left[2], bottom_right[2]], 'r-', linewidth=2)
            # 左边
            ax.plot([top_left[0], bottom_left[0]], [top_left[1], bottom_left[1]], [top_left[2], bottom_left[2]], 'r-', linewidth=2)
            # 右边
            ax.plot([top_right[0], bottom_right[0]], [top_right[1], bottom_right[1]], [top_right[2], bottom_right[2]], 'r-', linewidth=2)
            
            # 绘制航道中心线（垂直线，蓝色）
            ax.plot([x_3d, x_3d], [y_3d, y_3d], [z_3d, bottom_z], 'b-', linewidth=3)
            
            # 标注基点（绿色圆点）
            ax.scatter(x_3d, y_3d, z_3d, color='green', s=100, marker='o')
            
            # 标注桩号
            ax.text(x_3d, y_3d, z_3d + 10, station_text, fontsize=10, ha='center')
        
        # ===== 绘制航道中心线（连接所有基点）=====
        if len(base_points) >= 2:
            # 航道中心线 = 所有基点的连线
            x_line = [p[0] for p in base_points]
            y_line = [p[1] for p in base_points]
            z_line = [p[2] for p in base_points]
            
            ax.plot(x_line, y_line, z_line, 'g-', linewidth=4, label='航道中心线')
        
        # ===== 设置坐标轴 =====
        ax.set_xlabel('X (Channel Center)', fontsize=12)
        ax.set_ylabel('Y (Channel Direction)', fontsize=12)
        ax.set_zlabel('Z (Depth)', fontsize=12)
        
        ax.set_title('First 5 Sections 3D View\nBase Point = V-Line & H-Line Intersection, Centerline = All Base Points Connected', fontsize=12)
        
        # 添加图例
        ax.legend(['Section Frame', 'Channel Centerline', 'Base Point'], loc='upper left')
        
        # 设置视角
        ax.view_init(elev=30, azim=45)
        
        plt.tight_layout()
        
        # 保存图片
        output_path = r'D:\断面算量平台\测试文件\spine_3d_test.png'
        plt.savefig(output_path, dpi=150)
        print(f"\n  图片已保存: {output_path}")
        
        plt.show()
        
        return base_points


def main():
    """主函数"""
    # 使用0.6比例文件测试（因为匹配更稳定）
    dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'
    
    print("="*60)
    print("三维脊梁线测试 - 前5个断面")
    print("="*60)
    
    visualizer = Spine3DVisualizer(dxf_path)
    
    # 提取脊梁线数据
    spine_data = visualizer.extract_spine_data()
    
    # 提取桩号文本
    station_texts = visualizer.extract_station_texts()
    print(f"  桩号文本数: {len(station_texts)}")
    
    # 三维可视化
    base_points = visualizer.visualize_5_sections(spine_data, station_texts)
    
    print("\n=== 基点坐标汇总 ===")
    print("所有基点在同一直线上，串联形成航道中心线")
    print("航道中心线平行于XY平面（Z=0）")
    for i, bp in enumerate(base_points):
        print(f"  断面{i+1}: ({bp[0]:.1f}, {bp[1]:.1f}, {bp[2]:.1f})")


if __name__ == '__main__':
    main()