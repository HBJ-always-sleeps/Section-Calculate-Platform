# -*- coding: utf-8 -*-
"""
XYZ提取核心模块 - 可被GUI直接导入调用
所有功能整合在一个文件内，支持独立打包

作者: @黄秉俊
日期: 2026-04-13
"""

import os
import sys
import json
import math
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# 导入ezdxf相关库
try:
    import ezdxf
    from ezdxf import bbox
    from ezdxf.math import Vec2, Vec3
    from ezdxf.entities import Arc, Line, LWPOLYLINE
except ImportError:
    pass

try:
    import numpy as np
    from scipy import stats
except ImportError:
    pass

try:
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    from matplotlib.lines import Line2D
except ImportError:
    pass


# ==================== 配置 ====================
DEFAULT_CONFIG = {
    'neiwan_ditu_dxf': r'D:\断面算量平台\测试文件\内湾底图.dxf',
    'section_dxf': r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018.dxf',
    'output_dir': r'D:\断面算量平台\测试文件',
    'spine_points_json': '内湾底图_脊梁点.json',
    'bim_metadata_json': '内湾段分层图（全航道底图20260331）2018_bim_metadata.json',
    'spine_match_json': '脊梁点_L1匹配结果.json',
    'kaiwa_xyz': '开挖线_xyz.txt',
    'chaowa_xyz': '超挖线_xyz.txt',
    'centerline_txt': '中心线位置.txt',
    'section_xyz_json': '断面XYZ数据.json',
    'visualization_png': 'xyz_scatter_plot.png',
}


# ==================== 工具函数 ====================
def parse_station_value(text_content: str) -> Optional[float]:
    """解析桩号文本，返回桩号值（米）"""
    text = str(text_content).strip().upper().replace(' ', '').replace('K', 'k')
    
    patterns = [
        r'([0-9]+)\+([0-9]+(?:\.\d+)?)',
        r'([0-9]+)([0-9]{3})(?:\.\d+)?',
        r'([0-9]+)\.([0-9]+)',
        r'([0-9]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                if '+' in text or (len(groups[1]) == 3 and groups[1].isdigit() and int(groups[1]) < 1000):
                    try:
                        km = float(groups[0])
                        meter = float(groups[1])
                        return km * 1000 + meter
                    except:
                        pass
            try:
                return float(''.join(groups))
            except:
                pass
    
    digits = re.findall(r'\d+', text)
    if len(digits) >= 2:
        try:
            km = float(digits[0])
            meter = float(digits[1])
            return km * 1000 + meter
        except:
            pass
    
    if digits:
        try:
            return float(digits[0])
        except:
            pass
    
    return None


def format_station_number(station_value: float) -> str:
    """格式化桩号值为标准格式"""
    km = int(station_value // 1000)
    m = station_value % 1000
    return f"K{km}+{m:03.0f}"


def line_intersection(p1: Tuple[float, float], p2: Tuple[float, float],
                      p3: Tuple[float, float], p4: Tuple[float, float]) -> Optional[Tuple[float, float]]:
    """计算两条线段的交点"""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-10:
        return None
    
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    
    if t < 0 or t > 1:
        return None
    
    x = x1 + t * (x2 - x1)
    y = y1 + t * (y2 - y1)
    return (x, y)


def point_line_distance(point: Tuple[float, float], line_start: Tuple[float, float], 
                        line_end: Tuple[float, float]) -> float:
    """计算点到线段的距离"""
    px, py = point
    x1, y1 = line_start
    x2, y2 = line_end
    
    line_len_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
    if line_len_sq < 1e-10:
        return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
    
    t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_len_sq))
    proj_x = x1 + t * (x2 - x1)
    proj_y = y1 + t * (y2 - y1)
    
    return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


# ==================== 步骤1: 脊梁点提取 ====================
def step1_extract_spine_points(neiwan_dxf_path: str, output_dir: str, 
                                progress_callback=None) -> Dict:
    """
    步骤1: 从DXF提取脊梁点
    
    Args:
        neiwan_dxf_path: 内湾底图DXF路径
        output_dir: 输出目录
        progress_callback: 进度回调函数
        
    Returns:
        包含脊梁点数据的字典
    """
    if progress_callback:
        progress_callback("步骤1/5: 提取脊梁点...")
    
    # 加载DXF
    doc = ezdxf.readfile(neiwan_dxf_path)
    msp = doc.modelspace()
    
    # 提取中心线点
    centerline_coords = []
    for entity in msp:
        if entity.dxftype() == 'LWPOLYLINE':
            try:
                points = list(entity.vertices_in_wcs())
                centerline_coords.extend([(p.x, p.y) for p in points])
            except:
                pass
        elif entity.dxftype() == 'LINE':
            start = entity.dxf.start
            end = entity.dxf.end
            centerline_coords.append((start.x, start.y))
            centerline_coords.append((end.x, end.y))
    
    if progress_callback:
        progress_callback(f"  找到 {len(centerline_coords)} 个中心线点")
    
    # 提取桩号文本和连线
    station_texts = []
    station_lines = []
    
    for entity in msp:
        if entity.dxftype() == 'TEXT' or entity.dxftype() == 'MTEXT':
            text = entity.dxf.text if hasattr(entity.dxf, 'text') else entity.text
            station_value = parse_station_value(text)
            if station_value:
                insert = entity.dxf.insert
                station_texts.append({
                    'station': station_value,
                    'text': text,
                    'x': insert.x,
                    'y': insert.y
                })
        elif entity.dxftype() == 'LINE':
            start = entity.dxf.start
            end = entity.dxf.end
            # 检查是否是垂直于中心线的桩号线
            dx = abs(end.x - start.x)
            dy = abs(end.y - start.y)
            if dx < dy:  # 近似垂直线
                station_lines.append({
                    'start': (start.x, start.y),
                    'end': (end.x, end.y),
                    'mid_x': (start.x + end.x) / 2,
                    'mid_y': (start.y + end.y) / 2
                })
    
    if progress_callback:
        progress_callback(f"  找到 {len(station_texts)} 个桩号文本")
        progress_callback(f"  找到 {len(station_lines)} 条桩号线")
    
    # 匹配桩号文本和连线
    spine_points = []
    tolerance = 50.0
    
    for text in station_texts:
        best_line = None
        best_dist = float('inf')
        
        for line in station_lines:
            dist = math.sqrt((text['x'] - line['mid_x']) ** 2 + 
                           (text['y'] - line['mid_y']) ** 2)
            if dist < tolerance and dist < best_dist:
                best_dist = dist
                best_line = line
        
        if best_line:
            # 计算与中心线的交点
            best_intersection = None
            best_intersection_dist = float('inf')
            
            for i in range(len(centerline_coords) - 1):
                intersection = line_intersection(
                    best_line['start'], best_line['end'],
                    centerline_coords[i], centerline_coords[i + 1]
                )
                if intersection:
                    dist = math.sqrt((intersection[0] - text['x']) ** 2 + 
                                   (intersection[1] - text['y']) ** 2)
                    if dist < best_intersection_dist:
                        best_intersection_dist = dist
                        best_intersection = intersection
            
            if best_intersection:
                # 计算切线方向
                tangent_angle = 0
                for i in range(len(centerline_coords) - 1):
                    if point_line_distance(best_intersection, centerline_coords[i], 
                                         centerline_coords[i + 1]) < 1.0:
                        dx = centerline_coords[i + 1][0] - centerline_coords[i][0]
                        dy = centerline_coords[i + 1][1] - centerline_coords[i][1]
                        tangent_angle = math.degrees(math.atan2(dy, dx))
                        break
                
                spine_points.append({
                    'station': text['station'],
                    'station_text': text['text'],
                    'intersection': {
                        'x': best_intersection[0],
                        'y': best_intersection[1],
                        'z': 0
                    },
                    'tangent_angle': tangent_angle,
                    'left_text': {'x': text['x'], 'y': text['y']},
                    'right_text': {'x': text['x'], 'y': text['y']},
                    'line': {
                        'start': best_line['start'],
                        'end': best_line['end']
                    }
                })
    
    # 排序
    spine_points.sort(key=lambda x: x['station'])
    
    if progress_callback:
        progress_callback(f"  成功提取 {len(spine_points)} 个脊梁点")
    
    # 保存JSON
    result = {'spine_points': spine_points}
    output_path = os.path.join(output_dir, '内湾底图_脊梁点.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    if progress_callback:
        progress_callback(f"  已保存: {output_path}")
    
    return result


# ==================== 步骤2: BIM元数据生成 ====================
def step2_build_bim_metadata(section_dxf_path: str, output_dir: str,
                              progress_callback=None) -> Dict:
    """
    步骤2: 从断面图生成BIM元数据
    """
    if progress_callback:
        progress_callback("步骤2/5: 生成BIM元数据...")
    
    doc = ezdxf.readfile(section_dxf_path)
    msp = doc.modelspace()
    
    sections = []
    
    # 提取DMX图层信息
    for entity in msp:
        if entity.dxftype() in ['TEXT', 'MTEXT']:
            text = entity.dxf.text if hasattr(entity.dxf, 'text') else entity.text
            station_value = parse_station_value(text)
            if station_value:
                insert = entity.dxf.insert
                sections.append({
                    'station': station_value,
                    'station_text': text,
                    'x': insert.x,
                    'y': insert.y,
                    'layer': entity.dxf.layer
                })
    
    # 去重并排序
    seen = set()
    unique_sections = []
    for s in sections:
        if s['station'] not in seen:
            seen.add(s['station'])
            unique_sections.append(s)
    
    unique_sections.sort(key=lambda x: x['station'])
    
    if progress_callback:
        progress_callback(f"  找到 {len(unique_sections)} 个断面")
    
    # 计算边界框
    all_x = [s['x'] for s in unique_sections]
    all_y = [s['y'] for s in unique_sections]
    
    metadata = {
        'sections': unique_sections,
        'count': len(unique_sections),
        'bounds': {
            'x_min': min(all_x) if all_x else 0,
            'x_max': max(all_x) if all_x else 0,
            'y_min': min(all_y) if all_y else 0,
            'y_max': max(all_y) if all_y else 0
        }
    }
    
    output_path = os.path.join(output_dir, '内湾段分层图（全航道底图20260331）2018_bim_metadata.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    if progress_callback:
        progress_callback(f"  已保存: {output_path}")
    
    return metadata


# ==================== 步骤3: 脊梁点匹配 ====================
def step3_match_spine_to_sections(spine_data: Dict, metadata: Dict, output_dir: str,
                                   progress_callback=None) -> Dict:
    """
    步骤3: 将脊梁点与断面进行匹配
    """
    if progress_callback:
        progress_callback("步骤3/5: 匹配脊梁点与断面...")
    
    spine_points = spine_data.get('spine_points', [])
    sections = metadata.get('sections', [])
    
    matches = []
    tolerance = 500.0
    
    for section in sections:
        section_station = section['station']
        section_x = section['x']
        section_y = section['y']
        
        best_match = None
        best_dist = float('inf')
        
        for spine in spine_points:
            spine_station = spine['station']
            if abs(spine_station - section_station) < tolerance:
                dist = abs(spine_station - section_station)
                if dist < best_dist:
                    best_dist = dist
                    best_match = spine
        
        if best_match:
            matches.append({
                'section_station': section_station,
                'section_x': section_x,
                'section_y': section_y,
                'spine_station': best_match['station'],
                'spine_x': best_match['intersection']['x'],
                'spine_y': best_match['intersection']['y'],
                'tangent_angle': best_match['tangent_angle'],
                'rotation_angle': best_match['tangent_angle'] - 90
            })
    
    if progress_callback:
        progress_callback(f"  成功匹配 {len(matches)} 对")
    
    result = {'matches': matches}
    output_path = os.path.join(output_dir, '脊梁点_L1匹配结果.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    if progress_callback:
        progress_callback(f"  已保存: {output_path}")
    
    return result


# ==================== 步骤4: XYZ坐标提取 ====================
def step4_extract_xyz(section_dxf_path: str, match_data: Dict, output_dir: str,
                       progress_callback=None) -> Dict:
    """
    步骤4: 从断面图提取XYZ坐标
    """
    if progress_callback:
        progress_callback("步骤4/5: 提取XYZ坐标...")
    
    doc = ezdxf.readfile(section_dxf_path)
    msp = doc.modelspace()
    
    matches = match_data.get('matches', [])
    
    kaiwa_points = []
    chaowa_points = []
    centerline_points = []
    section_data = []
    
    for match in matches:
        station = match['section_station']
        section_x = match['section_x']
        section_y = match['section_y']
        spine_x = match['spine_x']
        spine_y = match['spine_y']
        rotation = math.radians(match['rotation_angle'])
        
        # 查找该断面的多段线
        section_polylines = []
        for entity in msp:
            if entity.dxftype() == 'LWPOLYLINE':
                try:
                    bbox_result = bbox.extents(entity)
                    center = bbox_result.center
                    dist = math.sqrt((center.x - section_x) ** 2 + (center.y - section_y) ** 2)
                    if dist < 1000:  # 在断面附近
                        section_polylines.append(entity)
                except:
                    pass
        
        # 提取点
        for poly in section_polylines:
            layer = poly.dxf.layer
            
            # 获取L1点（中心线）
            l1_x, l1_y = section_x, section_y
            
            for point in poly.vertices_in_wcs():
                x_cad, y_cad = point.x, point.y
                
                # 计算相对于L1的偏移
                dx = l1_x - x_cad  # 取负值修正左右反转
                dy = y_cad - l1_y
                
                # 旋转到全局坐标系
                dx_global = dx * math.cos(rotation) - dy * math.sin(rotation)
                dy_global = dx * math.sin(rotation) + dy * math.cos(rotation)
                
                x_global = spine_x + dx_global
                y_global = spine_y + dy_global
                z = y_cad  # 高程
                
                point_data = {
                    'station': station,
                    'x': x_global,
                    'y': y_global,
                    'z': z,
                    'dx': dx,
                    'dy': dy
                }
                
                if '开挖' in layer or 'DMX' in layer:
                    kaiwa_points.append(point_data)
                elif '超挖' in layer or 'CW' in layer:
                    chaowa_points.append(point_data)
        
        centerline_points.append({
            'station': station,
            'x': spine_x,
            'y': spine_y,
            'z': 0
        })
        
        section_data.append({
            'station': station,
            'kaiwa_count': len([p for p in kaiwa_points if p['station'] == station]),
            'chaowa_count': len([p for p in chaowa_points if p['station'] == station])
        })
    
    if progress_callback:
        progress_callback(f"  开挖线点: {len(kaiwa_points)}")
        progress_callback(f"  超挖线点: {len(chaowa_points)}")
        progress_callback(f"  中心线点: {len(centerline_points)}")
    
    # 保存文件
    # 开挖线
    kaiwa_path = os.path.join(output_dir, '开挖线_xyz.txt')
    with open(kaiwa_path, 'w', encoding='utf-8') as f:
        f.write("# 开挖线XYZ坐标\n")
        f.write("# 格式: 桩号 X Y Z dx dy\n")
        for p in kaiwa_points:
            f.write(f"{p['station']:.2f} {p['x']:.4f} {p['y']:.4f} {p['z']:.4f} {p['dx']:.4f} {p['dy']:.4f}\n")
    
    # 超挖线
    chaowa_path = os.path.join(output_dir, '超挖线_xyz.txt')
    with open(chaowa_path, 'w', encoding='utf-8') as f:
        f.write("# 超挖线XYZ坐标\n")
        f.write("# 格式: 桩号 X Y Z dx dy\n")
        for p in chaowa_points:
            f.write(f"{p['station']:.2f} {p['x']:.4f} {p['y']:.4f} {p['z']:.4f} {p['dx']:.4f} {p['dy']:.4f}\n")
    
    # 中心线
    centerline_path = os.path.join(output_dir, '中心线位置.txt')
    with open(centerline_path, 'w', encoding='utf-8') as f:
        f.write("# 中心线位置\n")
        f.write("# 格式: 桩号 X Y Z\n")
        for p in centerline_points:
            f.write(f"{p['station']:.2f} {p['x']:.4f} {p['y']:.4f} {p['z']:.4f}\n")
    
    # JSON数据
    json_path = os.path.join(output_dir, '断面XYZ数据.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'kaiwa': kaiwa_points,
            'chaowa': chaowa_points,
            'centerline': centerline_points,
            'sections': section_data
        }, f, ensure_ascii=False, indent=2)
    
    if progress_callback:
        progress_callback(f"  已保存所有文件到: {output_dir}")
    
    return {
        'kaiwa': kaiwa_points,
        'chaowa': chaowa_points,
        'centerline': centerline_points
    }


# ==================== 步骤5: 可视化 ====================
def step5_visualize(kaiwa_data: List, chaowa_data: List, centerline_data: List,
                    output_dir: str, progress_callback=None) -> str:
    """
    步骤5: 生成可视化图表
    """
    if progress_callback:
        progress_callback("步骤5/5: 生成可视化图表...")
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('航道断面XYZ数据可视化', fontsize=16, fontweight='bold')
    
    # 3D散点图
    ax3d = fig.add_subplot(2, 2, 1, projection='3d')
    if kaiwa_data:
        kaiwa_x = [p['x'] for p in kaiwa_data]
        kaiwa_y = [p['y'] for p in kaiwa_data]
        kaiwa_z = [p['z'] for p in kaiwa_data]
        ax3d.scatter(kaiwa_x, kaiwa_y, kaiwa_z, c='blue', s=1, alpha=0.5, label='开挖线')
    if chaowa_data:
        chaowa_x = [p['x'] for p in chaowa_data]
        chaowa_y = [p['y'] for p in chaowa_data]
        chaowa_z = [p['z'] for p in chaowa_data]
        ax3d.scatter(chaowa_x, chaowa_y, chaowa_z, c='red', s=1, alpha=0.5, label='超挖线')
    ax3d.set_xlabel('X')
    ax3d.set_ylabel('Y')
    ax3d.set_zlabel('Z (高程)')
    ax3d.set_title('3D视图')
    ax3d.legend()
    
    # 平面视图
    ax1 = axes[0, 1]
    if kaiwa_data:
        ax1.scatter([p['x'] for p in kaiwa_data], [p['y'] for p in kaiwa_data], 
                   c='blue', s=1, alpha=0.5, label='开挖线')
    if chaowa_data:
        ax1.scatter([p['x'] for p in chaowa_data], [p['y'] for p in chaowa_data], 
                   c='red', s=1, alpha=0.5, label='超挖线')
    if centerline_data:
        ax1.plot([p['x'] for p in centerline_data], [p['y'] for p in centerline_data], 
                'g-', linewidth=2, label='中心线')
    ax1.set_xlabel('X')
    ax1.set_ylabel('Y')
    ax1.set_title('平面视图 (X-Y)')
    ax1.legend()
    ax1.grid(True)
    
    # 断面视图
    ax2 = axes[1, 0]
    if kaiwa_data:
        ax2.scatter([p['station'] for p in kaiwa_data], [p['z'] for p in kaiwa_data], 
                   c='blue', s=1, alpha=0.5, label='开挖线')
    if chaowa_data:
        ax2.scatter([p['station'] for p in chaowa_data], [p['z'] for p in chaowa_data], 
                   c='red', s=1, alpha=0.5, label='超挖线')
    ax2.set_xlabel('桩号')
    ax2.set_ylabel('Z (高程)')
    ax2.set_title('断面视图 (桩号-高程)')
    ax2.legend()
    ax2.grid(True)
    
    # 统计信息
    ax3 = axes[1, 1]
    ax3.axis('off')
    stats_text = f"""
    数据统计:
    
    开挖线点数: {len(kaiwa_data)}
    超挖线点数: {len(chaowa_data)}
    中心线点数: {len(centerline_data)}
    
    开挖线高程范围:
      最小: {min(p['z'] for p in kaiwa_data):.2f}m
      最大: {max(p['z'] for p in kaiwa_data):.2f}m
      
    超挖线高程范围:
      最小: {min(p['z'] for p in chaowa_data):.2f}m
      最大: {max(p['z'] for p in chaowa_data):.2f}m
    """
    ax3.text(0.1, 0.5, stats_text, fontsize=12, verticalalignment='center',
             family='monospace')
    
    plt.tight_layout()
    output_path = os.path.join(output_dir, 'xyz_scatter_plot.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    if progress_callback:
        progress_callback(f"  已保存: {output_path}")
    
    return output_path


# ==================== 主运行函数 ====================
def run_extraction(neiwan_dxf: str, section_dxf: str, output_dir: str,
                   steps: List[int] = None, progress_callback=None) -> Dict:
    """
    运行完整的XYZ提取流程
    
    Args:
        neiwan_dxf: 内湾底图DXF路径
        section_dxf: 断面图DXF路径
        output_dir: 输出目录
        steps: 要执行的步骤列表 [1,2,3,4,5]，None表示全部
        progress_callback: 进度回调函数(message: str)
        
    Returns:
        执行结果字典
    """
    if steps is None:
        steps = [1, 2, 3, 4, 5]
    
    results = {
        'success': True,
        'steps_completed': [],
        'steps_failed': [],
        'data': {}
    }
    
    try:
        # 步骤1: 脊梁点提取
        if 1 in steps:
            try:
                spine_data = step1_extract_spine_points(neiwan_dxf, output_dir, progress_callback)
                results['steps_completed'].append(1)
                results['data']['spine'] = spine_data
            except Exception as e:
                results['steps_failed'].append((1, str(e)))
                if progress_callback:
                    progress_callback(f"  错误: {e}")
        
        # 步骤2: BIM元数据
        if 2 in steps:
            try:
                metadata = step2_build_bim_metadata(section_dxf, output_dir, progress_callback)
                results['steps_completed'].append(2)
                results['data']['metadata'] = metadata
            except Exception as e:
                results['steps_failed'].append((2, str(e)))
                if progress_callback:
                    progress_callback(f"  错误: {e}")
        
        # 步骤3: 匹配
        if 3 in steps:
            try:
                # 如果前面步骤没执行，从文件加载
                if 'spine' not in results['data']:
                    spine_path = os.path.join(output_dir, '内湾底图_脊梁点.json')
                    with open(spine_path, 'r', encoding='utf-8') as f:
                        results['data']['spine'] = json.load(f)
                if 'metadata' not in results['data']:
                    meta_path = os.path.join(output_dir, '内湾段分层图（全航道底图20260331）2018_bim_metadata.json')
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        results['data']['metadata'] = json.load(f)
                
                match_data = step3_match_spine_to_sections(
                    results['data']['spine'], 
                    results['data']['metadata'], 
                    output_dir, 
                    progress_callback
                )
                results['steps_completed'].append(3)
                results['data']['matches'] = match_data
            except Exception as e:
                results['steps_failed'].append((3, str(e)))
                if progress_callback:
                    progress_callback(f"  错误: {e}")
        
        # 步骤4: XYZ提取
        if 4 in steps:
            try:
                if 'matches' not in results['data']:
                    match_path = os.path.join(output_dir, '脊梁点_L1匹配结果.json')
                    with open(match_path, 'r', encoding='utf-8') as f:
                        results['data']['matches'] = json.load(f)
                
                xyz_data = step4_extract_xyz(section_dxf, results['data']['matches'], 
                                            output_dir, progress_callback)
                results['steps_completed'].append(4)
                results['data']['xyz'] = xyz_data
            except Exception as e:
                results['steps_failed'].append((4, str(e)))
                if progress_callback:
                    progress_callback(f"  错误: {e}")
        
        # 步骤5: 可视化
        if 5 in steps:
            try:
                if 'xyz' not in results['data']:
                    # 从文件加载
                    kaiwa_path = os.path.join(output_dir, '开挖线_xyz.txt')
                    chaowa_path = os.path.join(output_dir, '超挖线_xyz.txt')
                    centerline_path = os.path.join(output_dir, '中心线位置.txt')
                    
                    kaiwa_data = []
                    chaowa_data = []
                    centerline_data = []
                    
                    if os.path.exists(kaiwa_path):
                        with open(kaiwa_path, 'r', encoding='utf-8') as f:
                            for line in f:
                                if line.startswith('#'):
                                    continue
                                parts = line.strip().split()
                                if len(parts) >= 6:
                                    kaiwa_data.append({
                                        'station': float(parts[0]),
                                        'x': float(parts[1]),
                                        'y': float(parts[2]),
                                        'z': float(parts[3]),
                                        'dx': float(parts[4]),
                                        'dy': float(parts[5])
                                    })
                    
                    if os.path.exists(chaowa_path):
                        with open(chaowa_path, 'r', encoding='utf-8') as f:
                            for line in f:
                                if line.startswith('#'):
                                    continue
                                parts = line.strip().split()
                                if len(parts) >= 6:
                                    chaowa_data.append({
                                        'station': float(parts[0]),
                                        'x': float(parts[1]),
                                        'y': float(parts[2]),
                                        'z': float(parts[3]),
                                        'dx': float(parts[4]),
                                        'dy': float(parts[5])
                                    })
                    
                    if os.path.exists(centerline_path):
                        with open(centerline_path, 'r', encoding='utf-8') as f:
                            for line in f:
                                if line.startswith('#'):
                                    continue
                                parts = line.strip().split()
                                if len(parts) >= 4:
                                    centerline_data.append({
                                        'station': float(parts[0]),
                                        'x': float(parts[1]),
                                        'y': float(parts[2]),
                                        'z': float(parts[3])
                                    })
                else:
                    xyz_data = results['data']['xyz']
                    kaiwa_data = xyz_data.get('kaiwa', [])
                    chaowa_data = xyz_data.get('chaowa', [])
                    centerline_data = xyz_data.get('centerline', [])
                
                viz_path = step5_visualize(kaiwa_data, chaowa_data, centerline_data,
                                          output_dir, progress_callback)
                results['steps_completed'].append(5)
                results['data']['visualization'] = viz_path
            except Exception as e:
                results['steps_failed'].append((5, str(e)))
                if progress_callback:
                    progress_callback(f"  错误: {e}")
        
        if results['steps_failed']:
            results['success'] = False
            
    except Exception as e:
        results['success'] = False
        results['error'] = str(e)
    
    return results


# 命令行入口
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='XYZ提取核心模块')
    parser.add_argument('--neiwan', required=True, help='内湾底图DXF路径')
    parser.add_argument('--section', required=True, help='断面图DXF路径')
    parser.add_argument('--output', required=True, help='输出目录')
    parser.add_argument('--steps', default='1,2,3,4,5', help='执行步骤，如: 1,2,3,4,5')
    
    args = parser.parse_args()
    
    steps = [int(s) for s in args.steps.split(',')]
    
    def print_progress(msg):
        print(msg)
    
    results = run_extraction(args.neiwan, args.section, args.output, steps, print_progress)
    
    print("\n" + "="*50)
    print("执行结果:")
    print(f"成功步骤: {results['steps_completed']}")
    if results['steps_failed']:
        print(f"失败步骤: {results['steps_failed']}")
    print(f"总体状态: {'成功' if results['success'] else '失败'}")
