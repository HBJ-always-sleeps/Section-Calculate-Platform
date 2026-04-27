# -*- coding: utf-8 -*-
"""
从DXF文件提取开挖线和超挖线的XYZ坐标
修复版v3：以L1交点为基准确定断面内容的位置

核心逻辑（参考bim_model_builder.py和engine_cad_working_v3.py）：
1. 从桩号图层定位断面
2. 使用L1交点检测器识别脊梁线交点（水平线与垂直线的交点）
3. 以L1交点为基准确定断面内容的位置
4. 避免DMX_x跳跃问题

作者: Cline
日期: 2026-04-11
"""

import ezdxf
import sys
import io
import os
import math
import json
import re
from collections import defaultdict
from typing import List, Tuple, Dict, Optional
from shapely.geometry import LineString, box

# 设置输出编码（仅在非打包环境中）
if not getattr(sys, 'frozen', False):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# ==================== L1基准点检测器（参考bim_model_builder.py第593-731行） ====================

class L1ReferencePointDetector:
    """L1基准点检测器 - 从L1图层提取脊梁线交点"""
    
    def __init__(self, msp, doc):
        self.msp = msp
        self.doc = doc
        
    def detect_reference_points(self) -> List[Dict]:
        """检测L1基准点（水平线与垂直线的交点）
        
        核心逻辑：
        - L1图层包含水平线和垂直线
        - 水平线：宽度远大于高度 (w > h * 3)
        - 垂直线：高度远大于宽度 (h > w * 3)
        - 交点：垂直线X坐标与水平线Y坐标的组合
        
        Returns:
            [{'ref_x', 'ref_y', 'v_line', 'h_line'}, ...]
        """
        print("\n  === 检测L1基准点 ===")
        
        # 收集L1图层的LINE实体
        lines = []
        for e in self.msp.query('*[layer=="L1"]'):
            try:
                if e.dxftype() == 'LINE':
                    x1, y1 = e.dxf.start.x, e.dxf.start.y
                    x2, y2 = e.dxf.end.x, e.dxf.end.y
                    w, h = abs(x2-x1), abs(y2-y1)
                    
                    # 水平线（宽度远大于高度）
                    if w > h * 3:
                        lines.append({
                            'type': 'h', 
                            'y': (y1+y2)/2, 
                            'x': (x1+x2)/2, 
                            'x_min': min(x1,x2), 
                            'x_max': max(x1,x2)
                        })
                    # 垂直线（高度远大于宽度）
                    elif h > w * 3:
                        lines.append({
                            'type': 'v', 
                            'x': (x1+x2)/2, 
                            'y': (y1+y2)/2, 
                            'y_min': min(y1,y2), 
                            'y_max': max(y1,y2)
                        })
                elif e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                    pts = [(p[0], p[1]) for p in e.get_points()]
                    for i in range(len(pts)-1):
                        x1, y1 = pts[i]
                        x2, y2 = pts[i+1]
                        w, h = abs(x2-x1), abs(y2-y1)
                        if w > h * 3:
                            lines.append({
                                'type': 'h', 
                                'y': (y1+y2)/2, 
                                'x': (x1+x2)/2, 
                                'x_min': min(x1,x2), 
                                'x_max': max(x1,x2)
                            })
                        elif h > w * 3:
                            lines.append({
                                'type': 'v', 
                                'x': (x1+x2)/2, 
                                'y': (y1+y2)/2, 
                                'y_min': min(y1,y2), 
                                'y_max': max(y1,y2)
                            })
            except: pass
        
        # 分离水平和垂直线
        h_lines = [l for l in lines if l['type'] == 'h']
        v_lines = [l for l in lines if l['type'] == 'v']
        h_lines.sort(key=lambda l: l['y'], reverse=True)
        v_lines.sort(key=lambda l: l['y'], reverse=True)
        
        print(f"    水平线: {len(h_lines)}, 垂直线: {len(v_lines)}")
        
        # 匹配交点：每条垂直线找最近的水平线
        refs = []
        used_h = set()
        
        for v in v_lines:
            best_h = None
            best_diff = float('inf')
            best_idx = -1
            
            for h_idx, h in enumerate(h_lines):
                if h_idx in used_h:
                    continue
                diff = abs(h['y'] - v['y'])
                if diff < best_diff:
                    best_diff = diff
                    best_h = h
                    best_idx = h_idx
            
            # 容差50单位
            if best_h and best_diff < 50:
                used_h.add(best_idx)
                refs.append({
                    'ref_x': v['x'],  # 垂直线X坐标作为基准点X
                    'ref_y': best_h['y'],  # 水平线Y坐标作为基准点Y
                    'v_line': v,
                    'h_line': best_h
                })
        
        print(f"    匹配基准点: {len(refs)}")
        return refs
    
    def match_to_section(self, section_bounds: Dict, refs: List[Dict], tolerance: float = 200) -> Optional[Dict]:
        """匹配L1基准点到断面
        
        Args:
            section_bounds: {'x_min', 'x_max', 'y_min', 'y_max', 'y_center'}
            refs: L1基准点列表
            tolerance: Y距离容差
            
        Returns:
            {'ref_x', 'ref_y'} 或 None
        """
        sect_x_min = section_bounds['x_min']
        sect_x_max = section_bounds['x_max']
        sect_y_min = section_bounds['y_min']
        sect_y_max = section_bounds['y_max']
        sect_y_center = section_bounds['y_center']
        
        best_ref = None
        best_diff = float('inf')
        
        for ref in refs:
            ref_x = ref['ref_x']
            ref_y = ref['ref_y']
            
            # 验证：ref X应该在断面X范围内（带容差）
            x_tolerance = (sect_x_max - sect_x_min) * 0.5
            x_in_range = (sect_x_min - x_tolerance) <= ref_x <= (sect_x_max + x_tolerance)
            
            if not x_in_range:
                continue
            
            # Y距离计算（参考bim_model_builder.py第707-715行）
            if ref_y >= sect_y_max:  # 基准点在断面上方
                y_diff = ref_y - sect_y_max
            elif ref_y >= sect_y_min:  # 基准点在断面内
                y_diff = abs(ref_y - sect_y_center)
            else:  # 基准点在断面下方
                y_diff = (sect_y_min - ref_y) + 100  # 加惩罚
            
            if y_diff < best_diff:
                best_diff = y_diff
                best_ref = ref
        
        if best_ref and best_diff < tolerance:
            return {
                'ref_x': best_ref['ref_x'],
                'ref_y': best_ref['ref_y']
            }
        
        return None


# ==================== 标尺检测器 ====================

class RulerDetector:
    """标尺检测器 - 使用线性回归拟合高程与Y坐标关系"""
    
    @staticmethod
    def detect_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max, l1_y=None):
        """检测标尺比例，返回(elev_to_y, y_to_elev)函数对"""
        ruler_layers = ['标尺', '0-标尺', 'RULER']
        ruler_candidates = []
        
        for layer_name in ruler_layers:
            for e in msp.query(f'*[layer=="{layer_name}"]'):
                try:
                    if e.dxftype() == 'INSERT':
                        insert_x, insert_y = e.dxf.insert.x, e.dxf.insert.y
                        if sect_x_min - 100 <= insert_x <= sect_x_max + 100:
                            y_min, y_max = insert_y, insert_y
                            try:
                                block_name = e.dxf.name
                                if block_name in doc.blocks:
                                    for be in doc.blocks[block_name]:
                                        if be.dxftype() in ('TEXT', 'MTEXT'):
                                            try:
                                                world_y = be.dxf.insert.y + insert_y
                                                y_min, y_max = min(y_min, world_y), max(y_max, world_y)
                                            except: pass
                            except: pass
                            ruler_candidates.append({'x': insert_x, 'y_min': y_min, 'y_max': y_max, 'entity': e})
                except: pass
        
        if not ruler_candidates:
            return None
        
        # 计算所有候选标尺的a和b值
        ruler_params = []
        for ruler in ruler_candidates:
            elevation_points = []
            if ruler.get('entity'):
                insert_y = ruler['entity'].dxf.insert.y
                try:
                    block_name = ruler['entity'].dxf.name
                    if block_name in doc.blocks:
                        for be in doc.blocks[block_name]:
                            if be.dxftype() in ('TEXT', 'MTEXT'):
                                try:
                                    world_y = be.dxf.insert.y + insert_y
                                    text = (be.dxf.text if be.dxftype() == 'TEXT' else be.text).strip()
                                    if text.startswith('-') or (text[0].isdigit() and '高程' not in text):
                                        elevation = float(text.replace('m', '').strip())
                                        elevation_points.append((world_y, elevation))
                                except: pass
                except: pass
            
            if len(elevation_points) >= 2:
                n = len(elevation_points)
                sum_y = sum(p[0] for p in elevation_points)
                sum_e = sum(p[1] for p in elevation_points)
                sum_ye = sum(p[0] * p[1] for p in elevation_points)
                sum_e2 = sum(p[1] ** 2 for p in elevation_points)
                denom = n * sum_e2 - sum_e ** 2
                
                if abs(denom) > 0.001:
                    a = (n * sum_ye - sum_y * sum_e) / denom
                    b = (sum_y - a * sum_e) / n
                    ruler_params.append({'ruler': ruler, 'a': a, 'b': b, 'elevation_points': elevation_points})
        
        if not ruler_params:
            return None
        
        # 选择最佳标尺
        best_ruler_param = None
        if l1_y is not None:
            best_ruler_param = min(ruler_params, key=lambda rp: abs(rp['b'] - l1_y))
        else:
            best_overlap = -1
            for rp in ruler_params:
                ruler = rp['ruler']
                overlap = max(0, min(sect_y_max, ruler['y_max']) - max(sect_y_min, ruler['y_min']))
                overlap_ratio = overlap / (ruler['y_max'] - ruler['y_min']) if ruler['y_max'] > ruler['y_min'] else 0
                if overlap_ratio > best_overlap:
                    best_overlap = overlap_ratio
                    best_ruler_param = rp
            if not best_ruler_param:
                best_ruler_param = ruler_params[0]
        
        a = best_ruler_param['a']
        b = best_ruler_param['b']
        
        return (lambda elev: a * elev + b, lambda y: (y - b) / a)


# ==================== 缩放比例检测器 ====================

class ScaleDetector:
    """缩放比例检测器"""
    
    @staticmethod
    def detect_scale_factor(msp, section_layer='DMX'):
        """自动检测图纸缩放比例"""
        try:
            section_lines = []
            for e in msp.query(f'LWPOLYLINE[layer=="{section_layer}"]'):
                try:
                    pts = [p[:2] for p in e.get_points()]
                    if len(pts) >= 2:
                        line = LineString(pts)
                        if line.length > 10:
                            section_lines.append(line)
                except: pass
            
            if len(section_lines) < 3:
                return 1.0
            
            avg_length = sum(l.length for l in section_lines) / len(section_lines)
            
            y_centers = []
            for line in section_lines:
                coords = list(line.coords)
                y_center = sum(c[1] for c in coords) / len(coords)
                y_centers.append(y_center)
            
            y_centers.sort()
            y_gaps = []
            for i in range(len(y_centers) - 1):
                gap = abs(y_centers[i+1] - y_centers[i])
                if gap > 5:
                    y_gaps.append(gap)
            
            if not y_gaps:
                return 1.0
            
            avg_gap = sum(y_gaps) / len(y_gaps)
            
            REFERENCE_SECTION_LENGTH = 200.0
            REFERENCE_SECTION_GAP = 35.0
            
            scale_from_length = avg_length / REFERENCE_SECTION_LENGTH
            scale_from_gap = avg_gap / REFERENCE_SECTION_GAP
            
            scale_factor = (scale_from_length + scale_from_gap) / 2
            
            scale_factor = max(0.5, min(2.0, scale_factor))
            
            return scale_factor
        except:
            return 1.0


# ==================== 断面提取 ====================

def get_section_list(msp, layer='DMX'):
    """获取断面线列表"""
    entity_list = []
    for e in msp.query(f'LWPOLYLINE[layer=="{layer}"]'):
        try:
            pts = [p[:2] for p in e.get_points()]
            if pts:
                x_min = min(p[0] for p in pts)
                x_max = max(p[0] for p in pts)
                y_min = min(p[1] for p in pts)
                y_max = max(p[1] for p in pts)
                entity_list.append({
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'pts': pts,
                    'line': LineString(pts),
                    'y_center': (y_min + y_max) / 2,
                    'x_center': (x_min + x_max) / 2
                })
        except: pass
    
    return entity_list


def get_polylines_as_lines(msp, layer):
    """将多段线转换为LineString列表"""
    lines = []
    for e in msp.query(f'LWPOLYLINE[layer=="{layer}"]'):
        try:
            pts = [p[:2] for p in e.get_points()]
            if len(pts) >= 2:
                lines.append(LineString(pts))
        except: pass
    return lines


def extend_along_direction(coords, l1_ref_y, side='left'):
    """沿着线的原方向延伸到L1的Y坐标
    
    Args:
        coords: 线段的坐标列表
        l1_ref_y: L1基准点的Y坐标
        side: 'left'从最左端延伸或'right'从最右端延伸
    
    Returns:
        延伸后的完整坐标列表
    """
    if len(coords) < 2:
        return coords
    
    # 找到coords中X最小和X最大的点及其索引
    x_values = [c[0] for c in coords]
    min_x_idx = x_values.index(min(x_values))
    max_x_idx = x_values.index(max(x_values))
    
    # 根据side选择端点和相邻点
    if side == 'left':
        end_pt = coords[min_x_idx]
        if min_x_idx > 0:
            next_pt = coords[min_x_idx - 1]
        elif min_x_idx < len(coords) - 1:
            next_pt = coords[min_x_idx + 1]
        else:
            return coords
    else:
        end_pt = coords[max_x_idx]
        if max_x_idx < len(coords) - 1:
            next_pt = coords[max_x_idx + 1]
        elif max_x_idx > 0:
            next_pt = coords[max_x_idx - 1]
        else:
            return coords
    
    # 计算方向向量（从相邻点指向端点）
    dx = end_pt[0] - next_pt[0]
    dy = end_pt[1] - next_pt[1]
    
    mag = math.sqrt(dx**2 + dy**2)
    if mag < 0.001:
        return coords
    dx /= mag
    dy /= mag
    
    y_diff = l1_ref_y - end_pt[1]
    if y_diff <= 0:
        return coords
    
    if abs(dy) < 0.001:
        new_x = end_pt[0]
        new_y = l1_ref_y
    else:
        t = y_diff / dy
        if t < 0:
            t = abs(t)
        new_x = end_pt[0] + t * dx
        new_y = end_pt[1] + t * dy
    
    if abs(new_y - l1_ref_y) > 10:
        new_y = l1_ref_y
    
    if side == 'left':
        return [(new_x, new_y)] + list(coords)
    else:
        return list(coords) + [(new_x, new_y)]


def get_all_lines_in_section(msp, layer, section_bounds, l1_ref_y):
    """获取断面范围内所有线段坐标，并延伸最左和最右两条线
    
    Returns:
        {'all_coords': 所有线段坐标列表, 'extended_left': 延伸后的最左线, 'extended_right': 延伸后的最右线}
    """
    boundary_box = box(
        section_bounds['x_min'] - 20, 
        section_bounds['y_min'] - 30, 
        section_bounds['x_max'] + 20, 
        section_bounds['y_max'] + 10
    )
    
    local_lines = []
    for e in msp.query(f'LWPOLYLINE[layer=="{layer}"]'):
        try:
            pts = [p[:2] for p in e.get_points()]
            if len(pts) >= 2:
                ls = LineString(pts)
                if boundary_box.intersects(ls):
                    x_min = min(c[0] for c in pts)
                    x_max = max(c[0] for c in pts)
                    local_lines.append({'coords': pts, 'x_min': x_min, 'x_max': x_max})
        except: pass
    
    if not local_lines:
        return {'all_coords': [], 'extended_left': None, 'extended_right': None}
    
    # 延伸最左和最右两条线
    leftmost = min(local_lines, key=lambda x: x['x_min'])
    extended_left = extend_along_direction(leftmost['coords'], l1_ref_y, 'left')
    
    rightmost = max(local_lines, key=lambda x: x['x_max'])
    extended_right = extend_along_direction(rightmost['coords'], l1_ref_y, 'right')
    
    # 收集所有线段坐标（包括中间的原始线）
    all_coords = [line['coords'] for line in local_lines]
    
    return {
        'all_coords': all_coords,
        'extended_left': extended_left,
        'extended_right': extended_right
    }


def parse_station(s):
    """解析桩号字符串为数值（米）"""
    match = re.match(r'K(\d+)\+(\d+)', s, re.IGNORECASE)
    if match:
        return int(match.group(1)) * 1000 + int(match.group(2))
    return 0


# ==================== 核心逻辑：从桩号位置定位断面 ====================

def find_section_by_station_position(station_x, station_y, dmx_list, scale_factor, tolerance_factor=500):
    """从桩号位置定位断面
    
    核心逻辑（参考engine_cad_working_v3.py第1193-1201行）：
    - 桩号上方就是断面
    - 使用自适应容差匹配
    - 距离公式：dist = sqrt((st_x - sect_x_center)^2 * 0.5 + (st_y - sect_y_center)^2)
    """
    best_dmx = None
    best_dist = float('inf')
    
    tolerance = tolerance_factor * scale_factor
    
    for dmx in dmx_list:
        sect_x_center = dmx['x_center']
        sect_y_center = dmx['y_center']
        
        # 使用engine_cad_working_v3.py的距离公式（X方向权重0.5）
        dist = math.sqrt((station_x - sect_x_center)**2 * 0.5 + (station_y - sect_y_center)**2)
        
        if dist < best_dist:
            best_dist = dist
            best_dmx = dmx
    
    if best_dist < tolerance:
        return best_dmx, best_dist
    else:
        return None, None


# ==================== 主提取函数 ====================

def load_spine_match(spine_match_path: str) -> Dict:
    """加载脊梁点匹配结果"""
    print(f"\n加载脊梁点匹配结果: {spine_match_path}")
    try:
        with open(spine_match_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [ERROR] 加载失败: {e}")
        return {}
    
    matches = data.get('matches', [])
    if not matches:
        matches = [v for k, v in data.items() if isinstance(v, dict) and 'station_value' in v]
    
    spine_data = {}
    for m in matches:
        station_value = m.get('station_value', 0)
        spine_data[station_value] = {
            'spine_x': m.get('spine_x', 0),
            'spine_y': m.get('spine_y', 0),
            'l1_x': m.get('l1_x', 0),
            'l1_y': m.get('l1_y', 0),
            'tangent_angle': m.get('tangent_angle', 0)
        }
    
    print(f"  加载 {len(spine_data)} 个脊梁点")
    return spine_data


def extract_xyz_from_dxf(dxf_path: str, spine_match_path: str = None) -> Dict:
    """从DXF文件提取开挖线和超挖线的XYZ坐标
    
    核心逻辑：
    1. 从桩号位置定位断面
    2. 使用L1交点检测器识别脊梁线交点
    3. 以L1交点为基准确定断面内容的位置
    """
    print(f"\n加载DXF文件: {dxf_path}")
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    # 加载脊梁点匹配数据
    spine_data = {}
    if spine_match_path:
        spine_data = load_spine_match(spine_match_path)
    
    # 1. 自适应缩放比例检测
    print("\n检测缩放比例...")
    scale_factor = ScaleDetector.detect_scale_factor(msp, 'DMX')
    print(f"  缩放比例: {scale_factor:.4f}")
    
    station_match_tolerance = 500 * scale_factor
    print(f"  桩号匹配容差: {station_match_tolerance:.1f}")
    
    # 2. 检测L1基准点（核心修复）
    print("\n检测L1基准点...")
    l1_detector = L1ReferencePointDetector(msp, doc)
    l1_refs = l1_detector.detect_reference_points()
    
    # 3. 获取DMX断面线列表
    print("\n提取DMX断面线...")
    dmx_sections = get_section_list(msp, 'DMX')
    print(f"  找到 {len(dmx_sections)} 个DMX断面")
    
    # 4. 获取桩号标注
    print("\n提取桩号...")
    station_texts = []
    station_pattern = re.compile(r'K(\d+)\+(\d+)', re.IGNORECASE)
    for e in msp.query('TEXT[layer=="0-桩号"]'):
        try:
            text = e.dxf.text
            m = station_pattern.search(text)
            if m:
                station_value = int(m.group(1)) * 1000 + int(m.group(2))
                station_texts.append({
                    'text': text,
                    'station_value': station_value,
                    'x': e.dxf.insert.x,
                    'y': e.dxf.insert.y
                })
        except: pass
    print(f"  桩号数量: {len(station_texts)}")
    
    # 5. 从桩号位置定位断面（使用CAD局部坐标）
    # 核心修复：不使用used_dmx限制，允许每个桩号匹配最近的DMX断面
    # 因为断面图每列有多个断面（左右两个），桩号按顺序分配到不同断面
    print("\n从桩号位置定位断面...")
    matched_pairs = []
    
    station_texts_sorted = sorted(station_texts, key=lambda s: s['station_value'])
    
    for st in station_texts_sorted:
        station_x = st['x']  # CAD局部坐标
        station_y = st['y']  # CAD局部坐标
        
        dmx, dist = find_section_by_station_position(station_x, station_y, dmx_sections, scale_factor, station_match_tolerance)
        
        if dmx:
            # 匹配L1基准点到断面
            section_bounds = {
                'x_min': dmx['x_min'],
                'x_max': dmx['x_max'],
                'y_min': dmx['y_min'],
                'y_max': dmx['y_max'],
                'y_center': dmx['y_center']
            }
            l1_ref = l1_detector.match_to_section(section_bounds, l1_refs) if l1_refs else None
            
            # 从脊梁点匹配结果获取脊梁点坐标（通过桩号值匹配）
            station_value = st['station_value']
            spine_match = spine_data.get(station_value) if spine_data else None
            
            matched_pairs.append({
                'dmx': dmx,
                'station': st,
                'dist': dist,
                'l1_ref': l1_ref,
                'spine_match': spine_match
            })
        else:
            # 未找到DMX，但仍尝试匹配脊梁点
            station_value = st['station_value']
            spine_match = spine_data.get(station_value) if spine_data else None
            matched_pairs.append({
                'dmx': None,
                'station': st,
                'dist': None,
                'l1_ref': None,
                'spine_match': spine_match
            })
    
    matched_count = len([p for p in matched_pairs if p['dmx']])
    spine_matched_count = len([p for p in matched_pairs if p['spine_match']])
    print(f"  DMX匹配成功: {matched_count}/{len(station_texts)}")
    print(f"  脊梁点匹配成功: {spine_matched_count}/{len(station_texts)}")
    
    # 6. 获取开挖线和超挖线
    print("\n提取开挖线和超挖线...")
    kaiwa_lines = get_polylines_as_lines(msp, '开挖线')
    chaowa_lines = get_polylines_as_lines(msp, '超挖线')
    print(f"  开挖线数量: {len(kaiwa_lines)}")
    print(f"  超挖线数量: {len(chaowa_lines)}")
    
    # 7. 处理每个匹配的断面
    print("\n构建XYZ数据...")
    results = []
    
    for idx, pair in enumerate(matched_pairs):
        dmx = pair['dmx']
        station = pair['station']
        l1_ref = pair['l1_ref']
        
        if not dmx:
            print(f"  警告: {station['text']} 未找到匹配断面")
            continue
        
        # DMX断面坐标
        sect_x_min = dmx['x_min']
        sect_x_max = dmx['x_max']
        sect_y_min = dmx['y_min']
        sect_y_max = dmx['y_max']
        sect_x_center = dmx['x_center']
        sect_y_center = dmx['y_center']
        
        # 桩号信息
        station_text = station['text']
        station_value = station['station_value']
        
        # L1交点坐标（核心修复：使用L1基准点）
        if l1_ref:
            l1_x = l1_ref['ref_x']
            l1_y = l1_ref['ref_y']
        else:
            # 没有L1基准点，使用DMX中心
            l1_x = sect_x_center
            l1_y = sect_y_center
        
        # 匹配脊梁点
        spine_x = 0
        spine_y = 0
        spine_match = None
        if spine_data and station_value in spine_data:
            spine_info = spine_data[station_value]
            spine_x = spine_info['spine_x']
            spine_y = spine_info['spine_y']
            spine_match = True
        
        # 检测标尺
        ruler_scale = RulerDetector.detect_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max, l1_y)
        
        if ruler_scale:
            elev_to_y, y_to_elev = ruler_scale
            y0 = elev_to_y(0)
            y1 = elev_to_y(1)
            a = y1 - y0
            b = y0
        else:
            a, b = 1.0, 0.0
            y_to_elev = lambda y: (y - b) / a
        
        # 创建边界框筛选开挖线/超挖线
        bbox_expand = 20 * scale_factor
        section_bounds = {
            'x_min': sect_x_min,
            'x_max': sect_x_max,
            'y_min': sect_y_min,
            'y_max': sect_y_max
        }
        
        # 获取所有开挖线和超挖线（包括原始线和延伸线）
        kaiwa_line_data = get_all_lines_in_section(msp, '开挖线', section_bounds, l1_y)
        chaowa_line_data = get_all_lines_in_section(msp, '超挖线', section_bounds, l1_y)
        
        # 合并所有线段用于步长插值采样
        # 原始线段 + 延伸后的左右边界线（用于扩展X范围）
        all_kaiwa_coords = kaiwa_line_data['all_coords']
        if kaiwa_line_data['extended_left']:
            all_kaiwa_coords.append(kaiwa_line_data['extended_left'])
        if kaiwa_line_data['extended_right']:
            all_kaiwa_coords.append(kaiwa_line_data['extended_right'])
        
        all_chaowa_coords = chaowa_line_data['all_coords']
        if chaowa_line_data['extended_left']:
            all_chaowa_coords.append(chaowa_line_data['extended_left'])
        if chaowa_line_data['extended_right']:
            all_chaowa_coords.append(chaowa_line_data['extended_right'])
        
        # 获取脊梁点切向角度
        if spine_match and station_value in spine_data:
            tangent_angle = spine_data[station_value]['tangent_angle']
        else:
            tangent_angle = 0
        
        # 计算断面方向角度
        cross_angle = tangent_angle + math.pi / 2
        cos_a = math.cos(cross_angle)
        sin_a = math.sin(cross_angle)
        
        # 横向比例系数（断面图横向比例不是真实比例，需要乘以系数拉宽）
        HORIZONTAL_SCALE = 3.0  # 用户确认的横向比例系数
        
        # 构建XYZ数据（以L1交点为基准）
        kaiwa_xyz = []
        chaowa_xyz = []
        
        # 步长采样参数：步长4/3 CAD坐标单位
        STEP_DX_CAD = 4.0 / 3.0  # CAD坐标步长约1.333
        
        # 按CAD坐标步长插值采样
        # 1. 计算X范围（CAD坐标）
        # 2. 按步长遍历X，对每条线插值获取Y
        # 3. 如果多条线在同一X位置有值，取离水面远的（高程绝对值大的）
        
        def interpolate_y_at_x(coords, target_x):
            """在coords中插值获取target_x位置的Y值
            
            Args:
                coords: 线段坐标列表 [(x, y), ...]
                target_x: 目标X坐标
                
            Returns:
                Y值（如果target_x在线段X范围内），否则None
            """
            if len(coords) < 2:
                return None
            
            # 找到target_x所在的线段区间
            for i in range(len(coords) - 1):
                x1, y1 = coords[i]
                x2, y2 = coords[i + 1]
                
                # 确保 x1 <= x2（或反向）
                if x1 <= target_x <= x2 or x2 <= target_x <= x1:
                    # 线性插值
                    if abs(x2 - x1) < 0.001:
                        return y1  # 几乎垂直，取第一个点的Y
                    
                    t = (target_x - x1) / (x2 - x1)
                    return y1 + t * (y2 - y1)
            
            return None  # target_x不在线段范围内
        
        # 计算所有线的X范围（CAD坐标）
        all_x_min = float('inf')
        all_x_max = float('-inf')
        
        for coords in all_kaiwa_coords:
            if coords:
                all_x_min = min(all_x_min, min(c[0] for c in coords))
                all_x_max = max(all_x_max, max(c[0] for c in coords))
        
        for coords in all_chaowa_coords:
            if coords:
                all_x_min = min(all_x_min, min(c[0] for c in coords))
                all_x_max = max(all_x_max, max(c[0] for c in coords))
        
        if all_x_min == float('inf') or all_x_max == float('-inf'):
            # 没有延伸线数据
            continue
        
        # 按步长遍历X（CAD坐标）
        # 从最左到最右，按STEP_DX_CAD步长采样
        current_x = all_x_min
        
        while current_x <= all_x_max:
            # 计算相对于L1交点的偏移（CAD坐标）
            dx_cad = l1_x - current_x  # CAD坐标偏移
            dx_scaled = dx_cad * HORIZONTAL_SCALE  # 乘以横向比例系数转换为现实坐标
            
            # 对开挖线插值获取Y值
            kaiwa_y_values = []
            for coords in all_kaiwa_coords:
                y_cad = interpolate_y_at_x(coords, current_x)
                if y_cad is not None:
                    z = y_to_elev(y_cad)
                    kaiwa_y_values.append(z)
            
            # 对超挖线插值获取Y值
            chaowa_y_values = []
            for coords in all_chaowa_coords:
                y_cad = interpolate_y_at_x(coords, current_x)
                if y_cad is not None:
                    z = y_to_elev(y_cad)
                    chaowa_y_values.append(z)
            
            # 取离水面远的点（高程绝对值大的，即z更负）
            # 开挖线：如果有多条线在同一X位置，取最深的（z最小的）
            if kaiwa_y_values:
                best_z = min(kaiwa_y_values)  # 取最深的（最负的）
                if spine_match:
                    eng_x = spine_x + dx_scaled * cos_a
                    eng_y = spine_y + dx_scaled * sin_a
                else:
                    eng_x = current_x * HORIZONTAL_SCALE
                    eng_y = 0
                
                kaiwa_xyz.append((eng_x, eng_y, best_z))
            
            # 超挖线：如果有多条线在同一X位置，取最深的
            if chaowa_y_values:
                best_z = min(chaowa_y_values)
                if spine_match:
                    eng_x = spine_x + dx_scaled * cos_a
                    eng_y = spine_y + dx_scaled * sin_a
                else:
                    eng_x = current_x * HORIZONTAL_SCALE
                    eng_y = 0
                
                chaowa_xyz.append((eng_x, eng_y, best_z))
            
            # 步进
            current_x += STEP_DX_CAD
        
        # 脊梁点高程
        spine_z = 0.0
        
        section_data = {
            'section_index': idx + 1,
            'station': station_text,
            'station_value': station_value,
            'spine_x': spine_x,
            'spine_y': spine_y,
            'spine_z': spine_z,
            'l1_x': l1_x,
            'l1_y': l1_y,
            'x_range': (sect_x_min, sect_x_max),
            'y_range': (sect_y_min, sect_y_max),
            'center_x': l1_x,
            'scale_factor': (a, b),
            'kaiwa_xyz': kaiwa_xyz,
            'chaowa_xyz': chaowa_xyz
        }
        results.append(section_data)
        
        if (idx + 1) % 20 == 0:
            print(f"  已处理 {idx+1}/{len(matched_pairs)} 个断面...")
    
    # 按桩号值排序
    print("\n按桩号排序断面...")
    results.sort(key=lambda s: s['station_value'])
    
    # 排序后重新分配section_index
    for new_idx, section in enumerate(results):
        section['section_index'] = new_idx + 1
    
    # 检查L1_x跳跃
    print("\n检查L1_x跳跃...")
    prev_l1_x = None
    jump_count = 0
    for section in results:
        if prev_l1_x is not None:
            if abs(section['l1_x'] - prev_l1_x) > 50:
                jump_count += 1
                print(f"  警告: {section['station']} l1_x从{prev_l1_x:.1f}跳到{section['l1_x']:.1f}")
        prev_l1_x = section['l1_x']
    
    if jump_count == 0:
        print("  ✓ 无跳跃，匹配正确")
    else:
        print(f"  跳跃次数: {jump_count}")
    
    print(f"  排序后桩号范围: {results[0]['station']} -> {results[-1]['station']}")
    
    return {'sections': results}


# ==================== 输出XYZ文件 ====================

def write_xyz_file(data: Dict, layer_type: str, output_path: str):
    """将XYZ数据写入文件"""
    xyz_key = f'{layer_type}_xyz'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        total_points = 0
        skipped_above_water = 0
        skipped_abnormal = 0
        for section in data['sections']:
            points = section[xyz_key]
            for x, y, z in points:
                if z >= 0:
                    skipped_above_water += 1
                    continue
                if z < -20:
                    skipped_abnormal += 1
                    continue
                f.write(f"{x:.6f} {y:.6f} {-z:.6f}\n")
                total_points += 1
    
    print(f"\nXYZ文件已保存: {output_path}")
    print(f"  总点数: {total_points}")
    print(f"  已删除水面以上点数: {skipped_above_water}")
    print(f"  已删除高程异常点数: {skipped_abnormal}")


def write_center_line_file(data: Dict, output_path: str):
    """将中心线数据写入文件"""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# 中心线位置数据\n")
        f.write("# 格式: 断面序号 桩号 spine_x spine_y z\n\n")
        
        for section in data['sections']:
            a, b = section['scale_factor']
            z = (section['l1_y'] - b) / a
            f.write(f"{section['section_index']} {section['station']} ")
            f.write(f"{section['spine_x']:.6f} {section['spine_y']:.6f} ")
            f.write(f"{z:.6f}\n")
    
    print(f"\n中心线文件已保存: {output_path}")


# ==================== 主程序 ====================

def main(dxf_path=None, spine_match_path=None, output_dir=None):
    """
    主函数 - 可被外部调用
    
    Args:
        dxf_path: DXF文件路径
        spine_match_path: 脊梁点匹配结果JSON路径
        output_dir: 输出目录
    """
    # 使用默认路径如果未提供
    if dxf_path is None:
        dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018.dxf'
    if spine_match_path is None:
        spine_match_path = r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    if output_dir is None:
        output_dir = r'D:\断面算量平台\测试文件'
    
    kaiwa_xyz_path = os.path.join(output_dir, '开挖线_xyz.txt')
    chaowa_xyz_path = os.path.join(output_dir, '超挖线_xyz.txt')
    center_line_path = os.path.join(output_dir, '中心线位置.txt')
    json_path = os.path.join(output_dir, '断面XYZ数据.json')
    
    print("=" * 60)
    print("DXF XYZ坐标提取工具（修复版v3）")
    print("核心逻辑：以L1交点为基准确定断面内容的位置")
    print("=" * 60)
    
    # 提取数据
    result = extract_xyz_from_dxf(dxf_path, spine_match_path)
    
    # 输出XYZ文件
    write_xyz_file(result, 'kaiwa', kaiwa_xyz_path)
    write_xyz_file(result, 'chaowa', chaowa_xyz_path)
    write_center_line_file(result, center_line_path)
    
    # 输出JSON文件
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nJSON文件已保存: {json_path}")
    
    # 统计
    total_kaiwa = sum(len(s['kaiwa_xyz']) for s in result['sections'])
    total_chaowa = sum(len(s['chaowa_xyz']) for s in result['sections'])
    
    print("\n" + "=" * 60)
    print("提取完成！")
    print("=" * 60)
    print(f"总断面数: {len(result['sections'])}")
    print(f"总开挖线点数: {total_kaiwa}")
    print(f"总超挖线点数: {total_chaowa}")
    
    return result


if __name__ == "__main__":
    main()