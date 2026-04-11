# -*- coding: utf-8 -*-
"""
成套对应粘贴脚本 v2 - 基于位置顺序匹配
发现：源文件桩号标注集中在文件顶部，不与小矩形位置对应
解决：按小矩形Y顺序和桩号标注值顺序一对一匹配

核心逻辑：
1. 源文件：小矩形按Y排序（163个），桩号标注按值排序（163个不同值）
2. 目标文件：基点按Y排序（163个），桩号标注按值排序（163个）
3. 通过桩号值匹配：源套组 <-> 目标套组
"""

import ezdxf
import os
import re
from datetime import datetime
from collections import defaultdict


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


def get_bbox(entity):
    pts = [(p[0], p[1]) for p in entity.get_points()]
    xs = [pt[0] for pt in pts]
    ys = [pt[1] for pt in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def detect_source_sets_v2(msp):
    """检测源文件成套数据 v2 - 基于位置顺序匹配
    
    发现：桩号标注集中在文件顶部，不与小矩形位置对应
    解决：按小矩形Y顺序和桩号值顺序一对一匹配
    """
    print("\n[检测源文件成套数据 v2]")
    
    # 1. 检测小矩形
    small_rects = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) >= 4:
                bbox = get_bbox(e)
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
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
    
    # 按Y从上到下排序（Y越大越靠上）
    small_rects.sort(key=lambda r: r['center_y'], reverse=True)
    for i, rect in enumerate(small_rects):
        rect['index'] = i + 1
    
    # 2. 检测断面曲线（>50顶点）
    curves = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) > 50:
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
    
    # 3. 检测桩号标注并按值排序
    station_values = set()
    for e in msp.query('TEXT'):
        try:
            text = e.dxf.text
            station_value = parse_source_station(text)
            if station_value is not None:
                station_values.add(station_value)
        except: pass
    
    # 按桩号值排序（从小到大）
    sorted_station_values = sorted(station_values)
    print(f"  不同桩号值数量: {len(sorted_station_values)}")
    
    # 4. 匹配：小矩形按Y顺序 ↔ 桩号值按值顺序（一对一）
    # 假设：小矩形从上到下对应桩号值从小到大
    source_sets = []
    
    for i, rect in enumerate(small_rects):
        # 匹配断面曲线
        rect_bbox = rect['bbox']
        rect_center_x = (rect_bbox[0] + rect_bbox[2]) / 2
        rect_center_y = (rect_bbox[1] + rect_bbox[3]) / 2
        
        best_curve = None
        for curve in curves:
            if (rect_bbox[0] < curve['center'][0] < rect_bbox[2] and
                rect_bbox[1] < curve['center'][1] < rect_bbox[3]):
                best_curve = curve
                break
        
        # 匹配桩号（按顺序一对一）
        if i < len(sorted_station_values):
            station_value = sorted_station_values[i]
        else:
            station_value = None
        
        source_set = {
            'index': rect['index'],
            'rect_bbox': rect_bbox,
            'basepoint': rect['basepoint'],
            'center_y': rect['center_y'],
            'curve': best_curve,
            'curve_entity': best_curve['entity'] if best_curve else None,
            'station': station_value,
            'station_text': format_station(station_value) if station_value else None
        }
        source_sets.append(source_set)
    
    # 统计
    with_curve = [s for s in source_sets if s['curve'] is not None]
    with_station = [s for s in source_sets if s['station'] is not None]
    
    print(f"  成套数量: {len(source_sets)}")
    print(f"  有断面线: {len(with_curve)}")
    print(f"  有桩号: {len(with_station)}")
    
    # 显示前10个匹配
    print(f"\n  前10个匹配（小矩形Y顺序 <-> 桩号值顺序）:")
    for s in source_sets[:10]:
        print(f"    #{s['index']}: Y={s['center_y']:.1f}, 桩号={s['station_text']}, 基点=({s['basepoint'][0]:.1f}, {s['basepoint'][1]:.1f})")
    
    return source_sets, sorted_station_values


def detect_target_sets_v2(msp):
    """检测目标文件成套数据 v2"""
    print("\n[检测目标文件成套数据 v2]")
    
    # 1. 检测L1脊梁线
    horizontal_lines = []
    vertical_lines = []
    
    for e in msp.query('*[layer=="L1"]'):
        try:
            if e.dxftype() == 'LINE':
                x1, y1 = e.dxf.start.x, e.dxf.start.y
                x2, y2 = e.dxf.end.x, e.dxf.end.y
                
                width = abs(x2 - x1)
                height = abs(y2 - y1)
                
                if width > height * 3:
                    horizontal_lines.append({
                        'entity': e,
                        'y': (y1 + y2) / 2,
                        'x_min': min(x1, x2),
                        'x_max': max(x1, x2)
                    })
                elif height > width * 3:
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
    
    # 排序
    horizontal_lines.sort(key=lambda l: l['y'], reverse=True)
    vertical_lines.sort(key=lambda l: l['x'])
    
    # 2. 计算交点（一对一匹配）
    basepoints = []
    used_h_indices = set()
    
    for v_line in vertical_lines:
        v_x = v_line['x']
        v_y_center = v_line['y_center']
        
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
    
    # 3. 检测桩号标注
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
    
    # 4. 匹配基点与桩号 - 按X坐标分组匹配
    # 发现：桩号X与基点X有约5.8偏移，需按X分组后Y排序一对一匹配
    target_sets = []
    
    # 按X坐标分组基点（容差50）
    bp_groups = {}
    for bp in basepoints:
        bp_x = bp['x']
        # 找到合适的分组
        assigned = False
        for group_x in bp_groups:
            if abs(bp_x - group_x) < 50:
                bp_groups[group_x].append(bp)
                assigned = True
                break
        if not assigned:
            bp_groups[bp_x] = [bp]
    
    # 按X坐标分组桩号（容差50）
    station_groups = {}
    for station in station_texts:
        st_x = station['x']
        assigned = False
        for group_x in station_groups:
            if abs(st_x - group_x) < 50:
                station_groups[group_x].append(station)
                assigned = True
                break
        if not assigned:
            station_groups[st_x] = [station]
    
    # 按分组匹配：基点X组 <-> 桩号X组
    matched_bp_stations = {}  # (bp_x, bp_y) -> station
    
    for bp_group_x, bp_list in bp_groups.items():
        # 找到对应的桩号组
        best_station_group_x = None
        best_x_diff = float('inf')
        
        for station_group_x in station_groups:
            x_diff = abs(bp_group_x - station_group_x)
            if x_diff < best_x_diff:
                best_x_diff = x_diff
                best_station_group_x = station_group_x
        
        if best_station_group_x is not None and best_x_diff < 50:
            station_list = station_groups[best_station_group_x]
            
            # 按Y排序（从大到小）
            bp_list.sort(key=lambda b: b['y'], reverse=True)
            station_list.sort(key=lambda s: s['y'], reverse=True)
            
            # 一对一匹配
            for i, bp in enumerate(bp_list):
                if i < len(station_list):
                    matched_bp_stations[(bp['x'], bp['y'])] = station_list[i]
    
    # 构建target_sets
    for bp in basepoints:
        station = matched_bp_stations.get((bp['x'], bp['y']))
        target_set = {
            'basepoint': (bp['x'], bp['y']),
            'station': station['value'] if station else None,
            'station_text': station['text'] if station else None
        }
        target_sets.append(target_set)
    
    with_station = [t for t in target_sets if t['station'] is not None]
    print(f"  有桩号: {len(with_station)}")
    
    return target_sets


def match_sets_v2(source_sets, target_sets):
    """桩号匹配 v2 - 通过桩号值匹配"""
    print("\n[桩号匹配 v2]")
    
    # 构建桩号索引
    source_by_station = {}
    for s in source_sets:
        if s['station'] is not None:
            source_by_station[s['station']] = s
    
    target_by_station = {}
    for t in target_sets:
        if t['station'] is not None:
            target_by_station[t['station']] = t
    
    print(f"  源桩号索引: {len(source_by_station)}")
    print(f"  目标桩号索引: {len(target_by_station)}")
    
    # 匹配
    matched_pairs = []
    matched_stations = set()
    
    for station_value in sorted(source_by_station.keys()):
        if station_value in target_by_station:
            source_set = source_by_station[station_value]
            target_set = target_by_station[station_value]
            
            if source_set['curve_entity'] is not None:
                matched_pairs.append({
                    'source': source_set,
                    'target': target_set,
                    'station': station_value
                })
                matched_stations.add(station_value)
    
    unmatched_source = [s for s in source_sets if s['station'] not in matched_stations]
    unmatched_target = [t for t in target_sets if t['station'] not in matched_stations]
    
    print(f"  匹配成功: {len(matched_pairs)}对")
    print(f"  源未匹配: {len(unmatched_source)}")
    print(f"  目标未匹配: {len(unmatched_target)}")
    
    return matched_pairs, unmatched_source, unmatched_target


def copy_curve_to_target(source_msp, target_msp, curve_entity, source_bp, target_bp):
    """复制断面曲线到目标基点位置"""
    try:
        offset_x = target_bp[0] - source_bp[0]
        offset_y = target_bp[1] - source_bp[1]
        
        pts = [(p[0], p[1]) for p in curve_entity.get_points()]
        new_pts = [(p[0] + offset_x, p[1] + offset_y) for p in pts]
        
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


def run_autopaste_v2(source_path, target_path, output_path=None):
    """执行成套对应粘贴 v2"""
    print(f"\n{'='*60}")
    print(f"[成套对应粘贴 v2] 开始")
    print(f"{'='*60}")
    print(f"源文件: {source_path}")
    print(f"目标文件: {target_path}")
    
    source_doc = ezdxf.readfile(source_path)
    target_doc = ezdxf.readfile(target_path)
    
    source_msp = source_doc.modelspace()
    target_msp = target_doc.modelspace()
    
    source_sets, source_station_values = detect_source_sets_v2(source_msp)
    target_sets = detect_target_sets_v2(target_msp)
    
    matched_pairs, unmatched_source, unmatched_target = match_sets_v2(source_sets, target_sets)
    
    if matched_pairs:
        print(f"\n[匹配详情] 前10对:")
        for pair in matched_pairs[:10]:
            src = pair['source']
            tgt = pair['target']
            print(f"  {format_station(pair['station'])}: 源基点({src['basepoint'][0]:.1f}, {src['basepoint'][1]:.1f}) -> 目标基点({tgt['basepoint'][0]:.1f}, {tgt['basepoint'][1]:.1f})")
    
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
    
    if output_path is None:
        base, ext = os.path.splitext(target_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{base}_成套粘贴v2_{timestamp}{ext}"
    
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
    test_dir = r'D:\断面算量平台\测试文件'
    source_file = os.path.join(test_dir, '批量粘贴测试源.dxf')
    target_file = os.path.join(test_dir, '批量粘贴测试目标.dxf')
    
    result = run_autopaste_v2(source_file, target_file)
    
    print(f"\n{'='*60}")
    print(f"[完成]")
    print(f"{'='*60}")
    print(f"输出: {result['output_path']}")
    print(f"源套组: {result['source_sets_count']}")
    print(f"目标套组: {result['target_sets_count']}")
    print(f"匹配: {result['matched_count']}")
    print(f"粘贴: {result['pasted_count']}")