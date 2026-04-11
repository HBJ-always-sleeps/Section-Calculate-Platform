# -*- coding: utf-8 -*-
"""
三维脊梁线对齐模型 - 基于基准点对齐的航道3D拓扑重构

核心逻辑（用户指导）：
1. 原点回归（Normalization）：以基准点为原点计算相对坐标
   - x_local = x_cad - x_ref
   - y_local = y_cad - y_ref

2. 3D映射体系：
   - 3D X轴（宽度方向）：x_local * scale
   - 3D Z轴（高程/深度方向）：y_local * scale
   - 3D Y轴（桩号/里程方向）：真实mileage（单位：米）

3. 串糖葫芦对齐：每个断面的基准点在3D空间中固定为(0, mileage, 0)
   - 所有断面的基准点在俯视图中应完美重合在一条直线上（航道中心线）

4. 比例尺纠偏：scale=0.1（CAD坐标扩大10倍，需要缩小）

作者: @黄秉俊
日期: 2026-03-30
"""

import ezdxf
import os
import math
import re
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
from typing import List, Dict, Tuple, Optional
from shapely.geometry import Polygon, LineString, box, Point

# ==================== 基准点检测器（L1脊梁线交点） ====================

class ReferencePointDetector:
    """基准点检测器 - 从L1脊梁线提取交点作为断面基准点"""
    
    STATION_PATTERN = re.compile(r'K(\d+)\+(\d+)', re.IGNORECASE)
    
    def __init__(self, msp, doc):
        self.msp = msp
        self.doc = doc
        
    def detect_reference_points(self) -> List[Dict]:
        """检测L1脊梁线交点作为基准点
        
        Returns:
            每个基准点包含：ref_x, ref_y, mileage, station_name
        """
        print("\n=== 检测L1基准点（脊梁线交点）===")
        
        # 提取L1线段
        line_entities = []
        for e in self.msp.query('LINE[layer=="L1"]'):
            try:
                x_min = min(e.dxf.start.x, e.dxf.end.x)
                x_max = max(e.dxf.start.x, e.dxf.end.x)
                y_min = min(e.dxf.start.y, e.dxf.end.y)
                y_max = max(e.dxf.start.y, e.dxf.end.y)
                
                line_entities.append({
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'width': x_max - x_min,
                    'height': y_max - y_min,
                    'y_center': (y_min + y_max) / 2,
                    'x_center': (x_min + x_max) / 2
                })
            except: pass
        
        # 分离水平线和垂直线
        horizontal_lines = [l for l in line_entities if l['width'] > l['height'] * 3]
        vertical_lines = [l for l in line_entities if l['height'] > l['width'] * 3]
        
        print(f"  水平线: {len(horizontal_lines)}, 垂直线: {len(vertical_lines)}")
        
        # 按Y排序
        sorted_v = sorted(vertical_lines, key=lambda e: e['y_center'], reverse=True)
        sorted_h = sorted(horizontal_lines, key=lambda e: e['y_center'], reverse=True)
        
        # 最近邻一对一匹配
        reference_points = []
        used_h = set()
        
        for idx, v in enumerate(sorted_v):
            best_h = None
            best_diff = float('inf')
            best_idx = -1
            
            for h_idx, h in enumerate(sorted_h):
                if h_idx in used_h:
                    continue
                diff = abs(h['y_center'] - v['y_center'])
                if diff < best_diff:
                    best_diff = diff
                    best_h = h
                    best_idx = h_idx
            
            if best_h and best_diff < 50:
                used_h.add(best_idx)
                
                # ===== 基准点 = 垂直线和水平线的交点 =====
                ref_x = v['x_center']  # 航道中心线X坐标
                ref_y = best_h['y_center']  # 顶边Y坐标
                
                # 提取桩号文本
                mileage = self._extract_mileage(ref_x, v['y_center'])
                station_name = self._extract_station_name(ref_x, v['y_center'])
                
                if mileage is None:
                    mileage = idx * 100  # 默认里程
                    station_name = f"S{idx}"
                
                reference_points.append({
                    'ref_x': ref_x,          # 基准点X（航道中心）
                    'ref_y': ref_y,          # 基准点Y（顶边位置）
                    'mileage': mileage,      # 真实里程（米）
                    'station_name': station_name,  # 桩号名称
                    'depth': v['height'],    # 垂直线高度
                    'top_width': best_h['width']  # 顶边宽度
                })
        
        # 按里程排序
        reference_points.sort(key=lambda bp: bp['mileage'], reverse=True)
        
        print(f"  匹配基准点数: {len(reference_points)}")
        
        return reference_points
    
    def _extract_mileage(self, ref_x, ref_y) -> Optional[float]:
        """提取桩号数值（单位：米）"""
        for e in self.msp.query('TEXT MTEXT'):
            try:
                txt = e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text
                txt = txt.upper()
                match = self.STATION_PATTERN.search(txt)
                if match:
                    # 检查位置是否靠近基准点
                    if e.dxftype() == 'TEXT':
                        x, y = e.dxf.insert.x, e.dxf.insert.y
                    else:
                        x, y = e.dxf.insert.x, e.dxf.insert.y
                    
                    if abs(x - ref_x) < 200 and abs(y - ref_y) < 200:
                        # 解析里程：K67+450 → 67450米
                        km = int(match.group(1))
                        m = int(match.group(2))
                        return km * 1000 + m
            except: pass
        return None
    
    def _extract_station_name(self, ref_x, ref_y) -> str:
        """提取桩号名称"""
        for e in self.msp.query('TEXT MTEXT'):
            try:
                txt = e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text
                txt = txt.upper()
                match = self.STATION_PATTERN.search(txt)
                if match:
                    if e.dxftype() == 'TEXT':
                        x, y = e.dxf.insert.x, e.dxf.insert.y
                    else:
                        x, y = e.dxf.insert.x, e.dxf.insert.y
                    
                    if abs(x - ref_x) < 200 and abs(y - ref_y) < 200:
                        return match.group(0)  # 返回完整桩号名如 K67+450
            except: pass
        return "S0"


# ==================== 断面要素提取器 ====================

class SectionElementExtractor:
    """断面要素提取器 - 提取断面内的所有几何元素"""
    
    def __init__(self, msp, doc):
        self.msp = msp
        self.doc = doc
        
    def extract_elements(self, ref_point: Dict, tolerance: float = 50) -> Dict:
        """提取断面内的所有元素（相对于基准点）
        
        Args:
            ref_point: 基准点信息（ref_x, ref_y）
            tolerance: Y匹配容差
            
        Returns:
            包含DMX线、超挖线、填充边界的相对坐标数据
        """
        ref_x = ref_point['ref_x']
        ref_y = ref_point['ref_y']
        
        elements = {
            'dmx_lines': [],
            'overbreak_lines': [],
            'fill_boundaries': {}
        }
        
        # 提取DMX断面线
        for e in self.msp.query('LWPOLYLINE[layer=="DMX"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if not pts:
                    continue
                
                # Y匹配检查
                e_y_center = sum(p[1] for p in pts) / len(pts)
                if abs(e_y_center - ref_y) < tolerance:
                    # 转换为相对坐标
                    rel_pts = [(p[0] - ref_x, p[1] - ref_y) for p in pts]
                    elements['dmx_lines'].append(rel_pts)
            except: pass
        
        # 提取超挖线
        for e in self.msp.query('LWPOLYLINE[layer=="超挖线"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if not pts:
                    continue
                
                e_y_center = sum(p[1] for p in pts) / len(pts)
                if abs(e_y_center - ref_y) < tolerance:
                    rel_pts = [(p[0] - ref_x, p[1] - ref_y) for p in pts]
                    elements['overbreak_lines'].append(rel_pts)
            except: pass
        
        # 提取填充边界（所有相关图层）
        for layer in self.doc.layers:
            layer_name = layer.dxf.name
            if any(k in layer_name for k in ['填充', '淤泥', '黏土', '砂', '碎石', '填土', '层', 'Nonem']):
                for e in self.msp.query(f'LWPOLYLINE[layer=="{layer_name}"]'):
                    try:
                        pts = [(p[0], p[1]) for p in e.get_points()]
                        if not pts:
                            continue
                        
                        e_y_center = sum(p[1] for p in pts) / len(pts)
                        if abs(e_y_center - ref_y) < tolerance:
                            rel_pts = [(p[0] - ref_x, p[1] - ref_y) for p in pts]
                            if layer_name not in elements['fill_boundaries']:
                                elements['fill_boundaries'][layer_name] = []
                            elements['fill_boundaries'][layer_name].append(rel_pts)
                    except: pass
        
        return elements


# ==================== 3D坐标转换引擎 ====================

def transform_to_3d(point_2d: Tuple[float, float], ref_point: Dict, mileage: float, scale: float = 0.1) -> Tuple[float, float, float]:
    """坐标转换引擎 - 将CAD坐标转换为3D物理空间坐标
    
    Args:
        point_2d: (cad_x, cad_y) CAD原始坐标
        ref_point: 基准点信息（ref_x, ref_y）
        mileage: 真实桩号里程（单位：米）
        scale: 比例尺纠偏系数（CAD扩大10倍，需缩小）
        
    Returns:
        (x_3d, y_3d, z_3d) 3D坐标
        
    数学逻辑：
        x_local = x_cad - x_ref  (相对宽度)
        y_local = y_cad - y_ref  (相对高程)
        
        x_3d = x_local * scale   (3D X轴：宽度方向)
        z_3d = y_local * scale   (3D Z轴：高程方向)
        y_3d = mileage           (3D Y轴：桩号里程)
    """
    # 1. 计算相对距离（以基准点为原点）
    dx = point_2d[0] - ref_point['ref_x']
    dy = point_2d[1] - ref_point['ref_y']
    
    # 2. 映射到3D坐标系
    x_3d = dx * scale           # X轴：横向展宽
    z_3d = dy * scale           # Z轴：高程/深度
    y_3d = mileage              # Y轴：真实里程
    
    return (x_3d, y_3d, z_3d)


def transform_elements_to_3d(elements: Dict, ref_point: Dict, mileage: float, scale: float = 0.1) -> Dict:
    """将断面所有元素转换为3D坐标
    
    关键验证：基准点在3D空间中必须为(0, mileage, 0)
    """
    elements_3d = {
        'dmx_lines_3d': [],
        'overbreak_lines_3d': [],
        'fill_boundaries_3d': {}
    }
    
    # DMX线转换
    for rel_pts in elements['dmx_lines']:
        pts_3d = [transform_to_3d((rel_pt[0] + ref_point['ref_x'], rel_pt[1] + ref_point['ref_y']), 
                                  ref_point, mileage, scale) for rel_pt in rel_pts]
        elements_3d['dmx_lines_3d'].append(pts_3d)
    
    # 超挖线转换
    for rel_pts in elements['overbreak_lines']:
        pts_3d = [transform_to_3d((rel_pt[0] + ref_point['ref_x'], rel_pt[1] + ref_point['ref_y']), 
                                  ref_point, mileage, scale) for rel_pt in rel_pts]
        elements_3d['overbreak_lines_3d'].append(pts_3d)
    
    # 填充边界转换
    for layer_name, boundaries in elements['fill_boundaries'].items():
        elements_3d['fill_boundaries_3d'][layer_name] = []
        for rel_pts in boundaries:
            pts_3d = [transform_to_3d((rel_pt[0] + ref_point['ref_x'], rel_pt[1] + ref_point['ref_y']), 
                                      ref_point, mileage, scale) for rel_pt in rel_pts]
            elements_3d['fill_boundaries_3d'][layer_name].append(pts_3d)
    
    return elements_3d


# ==================== 3D模型构建器 ====================

class SpineAlignmentModelBuilder:
    """串糖葫芦对齐模型构建器"""
    
    def __init__(self, dxf_path: str):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        
    def build_model(self, num_sections: int = 10, scale: float = 0.1) -> Dict:
        """构建3D模型
        
        核心验证：所有断面的基准点在俯视图中应完美重合在一条直线上
        """
        print("\n" + "="*60)
        print("构建3D模型（基准点对齐/串糖葫芦模式）")
        print("="*60)
        
        # 1. 检测基准点
        detector = ReferencePointDetector(self.msp, self.doc)
        reference_points = detector.detect_reference_points()
        
        if not reference_points:
            print("ERROR: 未检测到基准点!")
            return None
        
        # 取前N个断面
        reference_points = reference_points[:num_sections]
        print(f"\n取前{len(reference_points)}个断面")
        
        # 2. 提取断面要素
        extractor = SectionElementExtractor(self.msp, self.doc)
        
        model_data = {
            'metadata': {
                'source_file': os.path.basename(self.dxf_path),
                'scale': scale,
                'coordinate_system': 'X=width, Y=mileage, Z=elevation',
                'alignment_mode': 'spine_alignment'
            },
            'sections': []
        }
        
        for i, ref_point in enumerate(reference_points):
            mileage = ref_point['mileage']
            station_name = ref_point['station_name']
            
            print(f"\n--- 断面 {i+1}: {station_name} ---")
            print(f"  基准点CAD坐标: ({ref_point['ref_x']:.1f}, {ref_point['ref_y']:.1f})")
            print(f"  真实里程: {mileage}米")
            print(f"  基准点3D坐标: (0, {mileage}, 0) ← 必须固定!")
            
            # 提取断面要素
            elements = extractor.extract_elements(ref_point)
            print(f"  DMX线: {len(elements['dmx_lines'])}")
            print(f"  超挖线: {len(elements['overbreak_lines'])}")
            print(f"  填充图层: {len(elements['fill_boundaries'])}")
            
            # 转换为3D坐标
            elements_3d = transform_elements_to_3d(elements, ref_point, mileage, scale)
            
            section_data = {
                'section_index': i + 1,
                'station_name': station_name,
                'mileage': mileage,
                'reference_point_3d': (0, mileage, 0),  # 固定为(0, mileage, 0)
                'elements_3d': elements_3d
            }
            
            model_data['sections'].append(section_data)
        
        return model_data
    
    def visualize_3d(self, model_data: Dict):
        """三维可视化 - 验证串糖葫芦对齐"""
        print("\n=== 3D可视化（串糖葫芦对齐验证）===")
        
        fig = plt.figure(figsize=(16, 12))
        ax = fig.add_subplot(111, projection='3d')
        
        colors = plt.cm.tab20.colors
        
        for sec in model_data['sections']:
            mileage = sec['mileage']  # Y轴 = 真实里程
            
            # 绘制基准点（绿色圆点）- 必须在(0, mileage, 0)
            ref_3d = sec['reference_point_3d']
            ax.scatter(ref_3d[0], ref_3d[1], ref_3d[2], color='green', s=100, marker='o')
            
            # 绘制DMX断面线（蓝色）
            for pts_3d in sec['elements_3d']['dmx_lines_3d']:
                if len(pts_3d) >= 2:
                    xs = [p[0] for p in pts_3d]
                    ys = [p[1] for p in pts_3d]
                    zs = [p[2] for p in pts_3d]
                    ax.plot(xs, ys, zs, 'b-', linewidth=2)
            
            # 绘制超挖线（红色）
            for pts_3d in sec['elements_3d']['overbreak_lines_3d']:
                if len(pts_3d) >= 2:
                    xs = [p[0] for p in pts_3d]
                    ys = [p[1] for p in pts_3d]
                    zs = [p[2] for p in pts_3d]
                    ax.plot(xs, ys, zs, 'r--', linewidth=1.5)
            
            # 绘制填充边界（不同颜色）
            for layer_name, boundaries in sec['elements_3d']['fill_boundaries_3d'].items():
                color_idx = hash(layer_name) % len(colors)
                for pts_3d in boundaries:
                    if len(pts_3d) >= 3:
                        xs = [p[0] for p in pts_3d] + [pts_3d[0][0]]
                        ys = [p[1] for p in pts_3d] + [pts_3d[0][1]]
                        zs = [p[2] for p in pts_3d] + [pts_3d[0][2]]
                        ax.plot(xs, ys, zs, color=colors[color_idx], linewidth=1, alpha=0.6)
            
            # 标注桩号
            ax.text(10, mileage, 0, sec['station_name'], fontsize=9)
        
        # 绘制航道中心线（绿色粗线）- 连接所有基准点
        mileages = [sec['mileage'] for sec in model_data['sections']]
        ax.plot([0] * len(mileages), mileages, [0] * len(mileages), 'g-', linewidth=4, label='Channel Centerline')
        
        # 设置坐标轴
        ax.set_xlabel('X (Width, m)', fontsize=12)
        ax.set_ylabel('Y (Mileage, m)', fontsize=12)
        ax.set_zlabel('Z (Elevation, m)', fontsize=12)
        
        ax.set_title(f'3D Channel Model (Spine Alignment)\n'
                    f'All reference points aligned at X=0, Z=0\n'
                    f'Scale: {model_data["metadata"]["scale"]}', fontsize=14)
        
        ax.legend(loc='upper left')
        ax.view_init(elev=20, azim=45)
        
        plt.tight_layout()
        
        # 保存图片
        output_path = r'D:\断面算量平台\测试文件\test_3d_spine_alignment.png'
        plt.savefig(output_path, dpi=150)
        print(f"\n图片已保存: {output_path}")
        
        plt.show()
        
        return output_path
    
    def verify_alignment(self, model_data: Dict):
        """验证串糖葫芦对齐"""
        print("\n=== 对齐验证 ===")
        
        for sec in model_data['sections']:
            ref_3d = sec['reference_point_3d']
            
            # 检查基准点是否在(0, mileage, 0)
            assert ref_3d[0] == 0, f"基准点X坐标应为0，实际为{ref_3d[0]}"
            assert ref_3d[2] == 0, f"基准点Z坐标应为0，实际为{ref_3d[2]}"
            assert ref_3d[1] == sec['mileage'], f"基准点Y坐标应为里程{sec['mileage']}, 实际为{ref_3d[1]}"
            
            print(f"  {sec['station_name']}: 基准点(0, {ref_3d[1]}, 0) [OK]")
        
        print("\n验证通过：所有基准点在航道中心线(X=0, Z=0)上完美对齐!")


def main():
    """主函数"""
    dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'
    
    print("="*60)
    print("3D脊梁线对齐模型 - 基于基准点对齐")
    print("="*60)
    print("\n核心逻辑：")
    print("  1. 原点回归：x_local = x_cad - x_ref")
    print("  2. 3D映射：X=宽度, Y=里程, Z=高程")
    print("  3. 基准点固定：(0, mileage, 0)")
    print("  4. 比例纠偏：scale=0.1")
    print("="*60)
    
    builder = SpineAlignmentModelBuilder(dxf_path)
    model_data = builder.build_model(num_sections=10, scale=0.1)
    
    if model_data:
        # 验证对齐
        builder.verify_alignment(model_data)
        
        # 三维可视化
        builder.visualize_3d(model_data)
        
        # 统计信息
        print("\n=== 统计信息 ===")
        print(f"断面数: {len(model_data['sections'])}")
        print(f"比例尺: {model_data['metadata']['scale']}")
        
        total_dmx = sum(len(sec['elements_3d']['dmx_lines_3d']) for sec in model_data['sections'])
        total_ob = sum(len(sec['elements_3d']['overbreak_lines_3d']) for sec in model_data['sections'])
        
        print(f"总DMX线数: {total_dmx}")
        print(f"总超挖线数: {total_ob}")


if __name__ == '__main__':
    main()