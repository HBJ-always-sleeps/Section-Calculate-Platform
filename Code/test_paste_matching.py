# -*- coding: utf-8 -*-
"""
测试批量粘贴匹配算法
分析蓝线源文件和蓝线目标文件的基点检测情况
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import ezdxf
import re
import os
from collections import defaultdict

def analyze_source_file(src_path):
    """分析源文件"""
    print("=" * 60)
    print(f"分析源文件: {os.path.basename(src_path)}")
    print("=" * 60)
    
    doc = ezdxf.readfile(src_path)
    msp = doc.modelspace()
    
    # 获取所有图层
    layers = [l.dxf.name for l in doc.layers]
    print(f"\n图层列表: {layers}")
    
    # 1. 检测小矩形（XSECTION图层）
    print("\n--- 检测小矩形（XSECTION图层）---")
    small_rects = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) >= 4:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                width = max(xs) - min(xs)
                height = max(ys) - min(ys)
                center_x = (min(xs) + max(xs)) / 2
                top_y = max(ys)
                
                # 打印所有矩形尺寸信息
                print(f"  矩形: 宽={width:.1f}, 高={height:.1f}, 中心X={center_x:.1f}, 顶Y={top_y:.1f}")
                
                # 新检测逻辑：检测大矩形（宽≈168，高≈150），基点在顶部中心
                # 这些大矩形框住整个断面曲线，顶部中心即为基点
                if 160 < width < 180 and 140 < height < 160:
                    small_rects.append({
                        'bbox': (min(xs), min(ys), max(xs), max(ys)),
                        'basepoint': (center_x, top_y),
                        'center_y': (min(ys) + max(ys)) / 2
                    })
                    print(f"    [OK] 符合大矩形条件(基点框)")
        except: pass
    
    print(f"\n检测到小矩形数量: {len(small_rects)}")
    
    # 2. 检测断面曲线（>50顶点）
    print("\n--- 检测断面曲线（XSECTION图层，>50顶点）---")
    curves = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) > 50:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
                curves.append({
                    'entity': e,
                    'bbox': (min(xs), min(ys), max(xs), max(ys)),
                    'center': center,
                    'num_pts': len(pts)
                })
                print(f"  曲线: 顶点数={len(pts)}, 中心={center}")
        except: pass
    
    print(f"\n检测到断面曲线数量: {len(curves)}")
    
    # 3. 检测桩号标注
    print("\n--- 检测桩号标注 ---")
    station_pattern_src = re.compile(r'(\d+)\+(\d+)\.TIN', re.IGNORECASE)
    station_texts = []
    
    # 搜索所有TEXT实体
    for e in msp.query('TEXT'):
        try:
            text = e.dxf.text
            m = station_pattern_src.search(text)
            if m:
                station_value = int(m.group(1)) * 1000 + int(m.group(2))
                station_texts.append({
                    'text': text,
                    'value': station_value,
                    'x': e.dxf.insert.x,
                    'y': e.dxf.insert.y
                })
                print(f"  桩号: {text} -> 值={station_value}, 位置=({e.dxf.insert.x:.1f}, {e.dxf.insert.y:.1f})")
        except: pass
    
    # 也搜索其他格式的桩号
    print("\n--- 搜索其他桩号格式 ---")
    other_patterns = [
        re.compile(r'K(\d+)\+(\d+)', re.IGNORECASE),
        re.compile(r'(\d+)\+(\d+)', re.IGNORECASE),
    ]
    
    for e in msp.query('TEXT MTEXT'):
        try:
            if e.dxftype() == 'TEXT':
                text = e.dxf.text
                x, y = e.dxf.insert.x, e.dxf.insert.y
            else:
                text = e.text
                x, y = e.dxf.insert.x, e.dxf.insert.y
            
            for pattern in other_patterns:
                m = pattern.search(text)
                if m:
                    station_value = int(m.group(1)) * 1000 + int(m.group(2))
                    print(f"  其他桩号: {text} -> 值={station_value}, 位置=({x:.1f}, {y:.1f})")
                    break
        except: pass
    
    print(f"\n检测到桩号标注数量: {len(station_texts)}")
    
    return {
        'small_rects': small_rects,
        'curves': curves,
        'station_texts': station_texts,
        'layers': layers
    }


def analyze_target_file(dst_path):
    """分析目标文件"""
    print("\n" + "=" * 60)
    print(f"分析目标文件: {os.path.basename(dst_path)}")
    print("=" * 60)
    
    doc = ezdxf.readfile(dst_path)
    msp = doc.modelspace()
    
    # 获取所有图层
    layers = [l.dxf.name for l in doc.layers]
    print(f"\n图层列表: {layers}")
    
    # 1. 检测L1脊梁线
    print("\n--- 检测L1脊梁线 ---")
    
    # 检查是否有L1图层
    if 'L1' in layers:
        print("  ✓ L1图层存在")
    else:
        print("  ✗ L1图层不存在")
        # 搜索类似的图层
        for l in layers:
            if 'L1' in l.upper() or '脊' in l or '梁' in l:
                print(f"  可能的替代图层: {l}")
    
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
                    print(f"  水平线: Y={horizontal_lines[-1]['y']:.1f}, X范围=[{min(x1, x2):.1f}, {max(x1, x2):.1f}]")
                elif height > width * 3:  # 垂直线
                    vertical_lines.append({
                        'entity': e,
                        'x': (x1 + x2) / 2,
                        'y_center': (y1 + y2) / 2
                    })
                    print(f"  垂直线: X={vertical_lines[-1]['x']:.1f}, Y中心={(y1 + y2) / 2:.1f}")
            elif e.dxftype() == 'LWPOLYLINE':
                pts = [(p[0], p[1]) for p in e.get_points()]
                print(f"  多段线(L1): 顶点数={len(pts)}")
        except: pass
    
    print(f"\nL1水平线数量: {len(horizontal_lines)}")
    print(f"L1垂直线数量: {len(vertical_lines)}")
    
    # 2. 计算交点（基点）
    print("\n--- 计算L1交点（基点）---")
    basepoints = []
    
    # 排序
    horizontal_lines.sort(key=lambda l: l['y'], reverse=True)
    vertical_lines.sort(key=lambda l: l['x'])
    
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
            basepoints.append({'x': v_x, 'y': h_line['y']})
            print(f"  基点: ({v_x:.1f}, {h_line['y']:.1f})")
    
    print(f"\n检测到L1基点数量: {len(basepoints)}")
    
    # 3. 检测目标桩号标注
    print("\n--- 检测目标桩号标注 ---")
    station_pattern_dst = re.compile(r'K(\d+)\+(\d+)', re.IGNORECASE)
    station_texts = []
    
    for e in msp.query('TEXT'):
        try:
            text = e.dxf.text
            m = station_pattern_dst.search(text)
            if m:
                station_value = int(m.group(1)) * 1000 + int(m.group(2))
                station_texts.append({
                    'text': text,
                    'value': station_value,
                    'x': e.dxf.insert.x,
                    'y': e.dxf.insert.y
                })
                print(f"  桩号: {text} -> 值={station_value}")
        except: pass
    
    # 搜索其他格式
    print("\n--- 搜索其他桩号格式 ---")
    other_patterns = [
        re.compile(r'(\d+)\+(\d+)\.TIN', re.IGNORECASE),
        re.compile(r'(\d+)\+(\d+)', re.IGNORECASE),
    ]
    
    for e in msp.query('TEXT MTEXT'):
        try:
            if e.dxftype() == 'TEXT':
                text = e.dxf.text
                x, y = e.dxf.insert.x, e.dxf.insert.y
            else:
                text = e.text
                x, y = e.dxf.insert.x, e.dxf.insert.y
            
            for pattern in other_patterns:
                m = pattern.search(text)
                if m:
                    station_value = int(m.group(1)) * 1000 + int(m.group(2))
                    print(f"  其他桩号: {text} -> 值={station_value}, 位置=({x:.1f}, {y:.1f})")
                    break
        except: pass
    
    print(f"\n检测到桩号标注数量: {len(station_texts)}")
    
    return {
        'horizontal_lines': horizontal_lines,
        'vertical_lines': vertical_lines,
        'basepoints': basepoints,
        'station_texts': station_texts,
        'layers': layers
    }


def test_matching(src_info, dst_info):
    """测试匹配"""
    print("\n" + "=" * 60)
    print("测试匹配结果")
    print("=" * 60)
    
    src_stations = sorted([s['value'] for s in src_info['station_texts']])
    dst_stations = sorted([s['value'] for s in dst_info['station_texts']])
    
    print(f"\n源桩号列表: {src_stations}")
    print(f"目标桩号列表: {dst_stations}")
    
    # 检查匹配
    common_stations = set(src_stations) & set(dst_stations)
    print(f"\n共同桩号: {sorted(common_stations)}")
    
    print(f"\n源小矩形数量: {len(src_info['small_rects'])}")
    print(f"目标基点数量: {len(dst_info['basepoints'])}")
    
    # 检查数量是否匹配
    if len(src_info['small_rects']) == len(dst_info['basepoints']):
        print("  ✓ 数量匹配")
    else:
        print(f"  ✗ 数量不匹配: 源{len(src_info['small_rects'])} vs 目标{len(dst_info['basepoints'])}")
    
    if len(common_stations) > 0:
        print(f"  ✓ 有{len(common_stations)}个共同桩号可匹配")
    else:
        print("  ✗ 无共同桩号，无法匹配")


if __name__ == "__main__":
    src_path = r"D:\断面算量平台\测试文件\蓝线源文件.dxf"
    dst_path = r"D:\断面算量平台\测试文件\蓝线目标文件.dxf"
    
    if not os.path.exists(src_path):
        print(f"源文件不存在: {src_path}")
    elif not os.path.exists(dst_path):
        print(f"目标文件不存在: {dst_path}")
    else:
        src_info = analyze_source_file(src_path)
        dst_info = analyze_target_file(dst_path)
        test_matching(src_info, dst_info)