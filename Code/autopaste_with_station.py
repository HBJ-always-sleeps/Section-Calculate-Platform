# -*- coding: utf-8 -*-
"""
成套对应粘贴脚本
实现：断面线 - 桩号 - 源基点 - 目标基点 的成套对应匹配

核心逻辑：
1. 源文件检测：断面线 + 桩号标注 + 小矩形基点 → 成套对应
2. 目标文件检测：L1脊梁线交点基点 + 桩号标注 → 成套对应
3. 通过桩号值匹配：源套组 ↔ 目标套组
4. 执行复制粘贴：断面线复制到目标基点位置

代码位置: D:\断面算量平台\Code\autopaste_with_station.py
"""

import ezdxf
import os
import re
from datetime import datetime
from collections import defaultdict


# ============== 桩号解析工具 ==============

def parse_source_station(text):
    """解析源文件桩号格式：00+000.TIN"""
    match = re.search(r'(\d+)\+(\d+)\.TIN', text.upper())
    if match:
        return int(match.group(1)) * 1000 + int(match.group(2))
    return None


def parse_target_station(text):
    """解析目标文件桩号格式：K00+000"""
    match = re.search(r'K(\d+)\+(\d+)', text.upper())
    if match:
        return int(match.group(1)) * 1000 + int(match.group(2))
    return None


def format_station(value):
    """格式化桩号数值为文本"""
    km = int(value // 1000)
    m = int(value % 1000)
    return f"K{km:02d}+{m:03d}"


# ============== 源文件检测 ==============

def get_bbox(entity):
    """获取实体边界框"""
    pts = [(p[0], p[1]) for p in entity.get_points()]
    xs = [pt[0] for pt in pts]
    ys = [pt[1] for pt in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def detect_source_sets(msp):
    """检测源文件的成套数据：断面线 + 桩号 + 基点
    
    源文件结构：
    - XSECTION图层：外框（大矩形）包含多个小矩形
    - 每个小矩形内有一条断面曲线（>50顶点）
    - 每个小矩形顶部有桩号标注（00+000.TIN格式）
    - 基点：小矩形中心X + 顶边Y
    
    Returns:
        list: 成套数据列表，每套包含 {station, station_text, basepoint, curve, rect_bbox}
    """
    print("\n[检测源文件成套数据]")
    
    # 1. 检测所有XSECTION图层的小矩形
    small_rects = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) >= 4:
                bbox = get_bbox(e)
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
                # 内框条件
                if 130 < width < 200 and 95 <= height < 140:
                    center_x = (bbox[0] + bbox[2]) / 2
                    top_y = bbox[3]
                    small_rects.append({
                        'entity': e,
                        'bbox': bbox,
                        'basepoint': (center_x, top_y),
                        'center_y': (bbox[1] + bbox[3]) / 2
                    })
        except: pass
    
    print(f"  小矩形数量: {len(small_rects)}")
    
    # 按Y从上到下排序
    small_rects.sort(key=lambda r: r['center_y'], reverse=True)
    for i, rect in enumerate(small_rects):
        rect['index'] = i + 1
    
    # 2. 检测所有断面曲线（>50顶点的复杂曲线）
    curves = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) > 50:  # 断面曲线特征：顶点数>50
                bbox = get_bbox(e)
                center_x = (bbox[0] + bbox[2]) / 2
                center_y = (bbox[1] + bbox[3]) / 2
                curves.append({
                    'entity': e,
                    'bbox': bbox,
                    'center': (center_x, center_y),
                    'vertex_count': len(pts)
                })
        except: pass
    
    print(f"  断面曲线数量: {len(curves)}")
    
    # 3. 检测所有桩号标注文本
    station_texts = []
    for e in msp.query('TEXT'):
        try:
            text = e.dxf.text
            station_value = parse_source_station(text)
            if station_value is not None:
                station_texts.append({
                    'entity': e,
                    'text': text,
                    'value': station_value,
                    'x': e.dxf.insert.x,
                    'y': e.dxf.insert.y
                })
        except: pass
    
    print(f"  桩号标注数量: {len(station_texts)}")
    
    # 4. 成套匹配：小矩形 + 断面曲线 + 桩号标注
    source_sets = []
    
    for rect in small_rects:
        rect_bbox = rect['bbox']
        rect_center_x = (rect_bbox[0] + rect_bbox[2]) / 2
        rect_center_y = (rect_bbox[1] + rect_bbox[3]) / 2
        
        # 找最近的断面曲线（在小矩形内部）
        best_curve = None
        best_curve_dist = float('inf')
        
        for curve in curves:
            # 检查曲线中心是否在小矩形内
            if (rect_bbox[0] < curve['center'][0] < rect_bbox[2] and
                rect_bbox[1] < curve['center'][1] < rect_bbox[3]):
                # 计算距离
                dist = ((curve['center'][0] - rect_center_x)**2 + 
                        (curve['center'][1] - rect_center_y)**2)**0.5
                if dist < best_curve_dist:
                    best_curve_dist = dist
                    best_curve = curve
        
        # 找最近的桩号标注（在小矩形上方或附近）
        # 源文件桩号格式：00+000.TIN，可能在小矩形顶部附近
        best_station = None
        best_station_dist = float('inf')
        
        for station in station_texts:
            # 桩号应该在小矩形顶部附近（上方或同一行）
            y_diff = rect_bbox[3] - station['y']  # 桩号Y与矩形顶边的关系
            x_diff = abs(station['x'] - rect_center_x)
            
            # 放宽条件：桩号可以在矩形上方0-50范围内，或者同一水平线附近
            # X范围放宽到矩形宽度内
            if -10 < y_diff < 50 and x_diff < (rect_bbox[2] - rect_bbox[0]):
                dist = (x_diff**2 + y_diff**2)**0.5
                if dist < best_station_dist:
                    best_station_dist = dist
                    best_station = station
        
        # 组装成套数据
        source_set = {
            'index': rect['index'],
            'rect_bbox': rect_bbox,
            'basepoint': rect['basepoint'],
            'curve': best_curve,
            'curve_entity': best_curve['entity'] if best_curve else None,
            'station': best_station['value'] if best_station else None,
            'station_text': best_station['text'] if best_station else None
        }
        source_sets.append(source_set)
    
    # 统计
    with_station = [s for s in source_sets if s['station'] is not None]
    with_curve = [s for s in source_sets if s['curve'] is not None]
    
    print(f"  成套数量: {len(source_sets)}")
    print(f"  有桩号: {len(with_station)}")
    print(f"  有断面线: {len(with_curve)}")
    
    return source_sets


# ============== 目标文件检测 ==============

def detect_target_sets(msp):
    """检测目标文件的成套数据：基点 + 桩号
    
    目标文件结构：
    - L1图层：水平线和垂直线（脊梁线）
    - 交点即为基点
    - 基点附近有桩号标注（K00+000格式）
    
    Returns:
        list: 成套数据列表，每套包含 {station, station_text, basepoint}
    """
    print("\n[检测目标文件成套数据]")
    
    # 1. 检测L1图层脊梁线
    horizontal_lines = []
    vertical_lines = []
    
    for e in msp.query('*[layer=="L1"]'):
        try:
            if e.dxftype() == 'LINE':
                x1, y1 = e.dxf.start.x, e.dxf.start.y
                x2, y2 = e.dxf.end.x, e.dxf.end.y
                
                width = abs(x2 - x1)
                height = abs(y2 - y1)
                
                if width > height * 3:  # 水平线
                    horizontal_lines.append({
                        'entity': e,
                        'y': (y1 + y2) / 2,
                        'x_min': min(x1, x2),
                        'x_max': max(x1, x2)
                    })
                elif height > width * 3:  # 垂直线
                    vertical_lines.append({
                        'entity': e,
                        'x': (x1 + x2) / 2,
                        'y_min': min(y1, y2),
                        'y_max': max(y1, y2),
                        'y_center': (y1 + y2) / 2
                    })
        except: pass
    
    print(f"  水平线数量: {len(horizontal_lines)}")
    print(f"  垂直线数量: {len(vertical_lines)}")
    
    # 按坐标排序
    horizontal_lines.sort(key=lambda l: l['y'], reverse=True)
    vertical_lines.sort(key=lambda l: l['x'])
    
    # 2. 计算交点（一对一匹配）
    basepoints = []
    used_h_indices = set()
    
    for v_line in vertical_lines:
        v_x = v_line['x']
        v_y_center = v_line['y_center']
        
        # 找Y最接近的水平线
        best_h_idx = -1
        best_y_diff = float('inf')
        
        for h_idx, h_line in enumerate(horizontal_lines):
            if h_idx in used_h_indices:
                continue
            
            y_diff = abs(h_line['y'] - v_y_center)
            if y_diff < best_y_diff:
                best_y_diff = y_diff
                best_h_idx = h_idx
        
        if best_h_idx >= 0 and best_y_diff < 50:
            used_h_indices.add(best_h_idx)
            h_line = horizontal_lines[best_h_idx]
            
            basepoints.append({
                'x': v_x,
                'y': h_line['y'],
                'v_line': v_line,
                'h_line': h_line
            })
    
    print(f"  基点数量: {len(basepoints)}")
    
    # 3. 检测所有桩号标注文本
    station_texts = []
    for e in msp.query('TEXT'):
        try:
            text = e.dxf.text
            station_value = parse_target_station(text)
            if station_value is not None:
                station_texts.append({
                    'entity': e,
                    'text': text,
                    'value': station_value,
                    'x': e.dxf.insert.x,
                    'y': e.dxf.insert.y
                })
        except: pass
    
    print(f"  桩号标注数量: {len(station_texts)}")
    
    # 4. 成套匹配：基点 + 桩号
    target_sets = []
    
    for bp in basepoints:
        # 找最近的桩号标注
        best_station = None
        best_station_dist = float('inf')
        
        for station in station_texts:
            dist = ((station['x'] - bp['x'])**2 + (station['y'] - bp['y'])**2)**0.5
            if dist < best_station_dist:
                best_station_dist = dist
                best_station = station
        
        target_set = {
            'basepoint': (bp['x'], bp['y']),
            'station': best_station['value'] if best_station else None,
            'station_text': best_station['text'] if best_station else None,
            'station_dist': best_station_dist if best_station else None
        }
        target_sets.append(target_set)
    
    # 统计
    with_station = [t for t in target_sets if t['station'] is not None]
    print(f"  有桩号: {len(with_station)}")
    
    return target_sets


# ============== 桩号匹配 ==============

def match_sets(source_sets, target_sets):
    """通过桩号匹配源套组和目标套组
    
    Returns:
        list: 匹配对列表，每对包含 {source, target, station}
    """
    print("\n[桩号匹配]")
    
    # 构建桩号索引
    source_by_station = {}
    for s in source_sets:
        if s['station'] is not None:
            source_by_station[s['station']] = s
    
    target_by_station = {}
    for t in target_sets:
        if t['station'] is not None:
            target_by_station[t['station']] = t
    
    # 匹配
    matched_pairs = []
    matched_stations = set()
    
    for station_value in sorted(source_by_station.keys()):
        if station_value in target_by_station:
            source_set = source_by_station[station_value]
            target_set = target_by_station[station_value]
            
            # 检查源套组是否有断面曲线
            if source_set['curve_entity'] is not None:
                matched_pairs.append({
                    'source': source_set,
                    'target': target_set,
                    'station': station_value
                })
                matched_stations.add(station_value)
    
    # 统计未匹配
    unmatched_source = [s for s in source_sets if s['station'] not in matched_stations]
    unmatched_target = [t for t in target_sets if t['station'] not in matched_stations]
    
    print(f"  匹配成功: {len(matched_pairs)}对")
    print(f"  源未匹配: {len(unmatched_source)}")
    print(f"  目标未匹配: {len(unmatched_target)}")
    
    return matched_pairs, unmatched_source, unmatched_target


# ============== 复制粘贴 ==============

def copy_curve_to_target(source_msp, target_msp, curve_entity, source_bp, target_bp):
    """复制断面曲线到目标基点位置
    
    Args:
        source_msp: 源文件模型空间
        target_msp: 目标文件模型空间
        curve_entity: 断面曲线实体
        source_bp: 源基点 (x, y)
        target_bp: 目标基点 (x, y)
    
    Returns:
        bool: 是否成功
    """
    try:
        # 计算偏移量
        offset_x = target_bp[0] - source_bp[0]
        offset_y = target_bp[1] - source_bp[1]
        
        # 获取曲线顶点
        pts = [(p[0], p[1]) for p in curve_entity.get_points()]
        
        # 偏移顶点
        new_pts = [(p[0] + offset_x, p[1] + offset_y) for p in pts]
        
        # 创建新曲线
        target_msp.add_lwpolyline(
            new_pts,
            dxfattribs={
                'layer': curve_entity.dxf.layer,
                'color': curve_entity.dxf.color
            }
        )
        
        return True
    except Exception as e:
        print(f"    [错误] 复制失败: {e}")
        return False


def run_autopaste_with_station(source_path, target_path, output_path=None):
    """执行成套对应粘贴
    
    Args:
        source_path: 源DXF文件路径
        target_path: 目标DXF文件路径
        output_path: 输出DXF文件路径（可选）
    
    Returns:
        dict: 处理结果
    """
    print(f"\n{'='*60}")
    print(f"[成套对应粘贴] 开始")
    print(f"{'='*60}")
    print(f"源文件: {source_path}")
    print(f"目标文件: {target_path}")
    
    # 加载文件
    source_doc = ezdxf.readfile(source_path)
    target_doc = ezdxf.readfile(target_path)
    
    source_msp = source_doc.modelspace()
    target_msp = target_doc.modelspace()
    
    # 检测源文件成套数据
    source_sets = detect_source_sets(source_msp)
    
    # 检测目标文件成套数据
    target_sets = detect_target_sets(target_msp)
    
    # 桩号匹配
    matched_pairs, unmatched_source, unmatched_target = match_sets(source_sets, target_sets)
    
    # 显示匹配结果
    if matched_pairs:
        print(f"\n[匹配详情] 前10对:")
        for pair in matched_pairs[:10]:
            src = pair['source']
            tgt = pair['target']
            print(f"  {format_station(pair['station'])}: 源基点({src['basepoint'][0]:.1f}, {src['basepoint'][1]:.1f}) -> 目标基点({tgt['basepoint'][0]:.1f}, {tgt['basepoint'][1]:.1f})")
    
    # 执行复制粘贴
    print(f"\n[复制粘贴]")
    pasted_count = 0
    failed_count = 0
    
    for pair in matched_pairs:
        source_set = pair['source']
        target_set = pair['target']
        
        curve_entity = source_set['curve_entity']
        source_bp = source_set['basepoint']
        target_bp = target_set['basepoint']
        
        success = copy_curve_to_target(source_msp, target_msp, curve_entity, source_bp, target_bp)
        
        if success:
            pasted_count += 1
        else:
            failed_count += 1
    
    print(f"  成功粘贴: {pasted_count}")
    print(f"  失败: {failed_count}")
    
    # 保存输出
    if output_path is None:
        base, ext = os.path.splitext(target_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{base}_成套粘贴_{timestamp}{ext}"
    
    target_doc.saveas(output_path)
    
    print(f"\n[输出文件]: {output_path}")
    
    return {
        'source_path': source_path,
        'target_path': target_path,
        'output_path': output_path,
        'source_sets_count': len(source_sets),
        'target_sets_count': len(target_sets),
        'matched_count': len(matched_pairs),
        'pasted_count': pasted_count,
        'failed_count': failed_count,
        'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S")
    }


if __name__ == '__main__':
    # 测试文件路径
    test_dir = r'D:\断面算量平台\测试文件'
    source_file = os.path.join(test_dir, '批量粘贴测试源.dxf')
    target_file = os.path.join(test_dir, '批量粘贴测试目标.dxf')
    
    result = run_autopaste_with_station(source_file, target_file)
    
    print(f"\n{'='*60}")
    print(f"[完成]")
    print(f"{'='*60}")
    print(f"输出: {result['output_path']}")
    print(f"源套组: {result['source_sets_count']}")
    print(f"目标套组: {result['target_sets_count']}")
    print(f"匹配: {result['matched_count']}")
    print(f"粘贴: {result['pasted_count']}")