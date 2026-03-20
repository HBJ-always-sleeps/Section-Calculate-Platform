# -*- coding: utf-8 -*-
"""分析DXF文件中断面间距分布，用于自适应参数调整"""
import ezdxf
import os
import math
from collections import defaultdict
from shapely.geometry import LineString, box

def analyze_file(file_path):
    """分析文件的断面分布"""
    print(f"\n{'='*70}")
    print(f"分析文件: {os.path.basename(file_path)}")
    print('='*70)
    
    doc = ezdxf.readfile(file_path)
    msp = doc.modelspace()
    
    # 获取超挖线
    overexc_lines = []
    for e in msp.query('*[layer=="超挖线"]'):
        if e.dxftype() in ('LWPOLYLINE', 'POLYLINE', 'LINE'):
            pts = [(p[0], p[1]) for p in e.get_points()] if e.dxftype() != 'LINE' else [
                (e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)
            ]
            if len(pts) >= 2:
                overexc_lines.append(LineString(pts))
    
    print(f"超挖线数量: {len(overexc_lines)}")
    
    if not overexc_lines:
        return None
    
    # 计算每条线的中心点和边界框
    line_info = []
    for line in overexc_lines:
        bounds = line.bounds
        mid_x = (bounds[0] + bounds[2]) / 2
        mid_y = (bounds[1] + bounds[3]) / 2
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        line_info.append({
            'mid_x': mid_x,
            'mid_y': mid_y,
            'width': width,
            'height': height,
            'bounds': bounds
        })
    
    # 分析断面框尺寸
    widths = [info['width'] for info in line_info]
    heights = [info['height'] for info in line_info]
    
    avg_width = sum(widths) / len(widths)
    avg_height = sum(heights) / len(heights)
    min_width, max_width = min(widths), max(widths)
    min_height, max_height = min(heights), max(heights)
    
    print(f"\n断面框尺寸统计:")
    print(f"  宽度: 平均={avg_width:.2f}, 范围=[{min_width:.2f}, {max_width:.2f}]")
    print(f"  高度: 平均={avg_height:.2f}, 范围=[{min_height:.2f}, {max_height:.2f}]")
    
    # 按X坐标排序
    sorted_by_x = sorted(line_info, key=lambda x: x['mid_x'])
    
    # 计算相邻断面的X间距
    x_gaps = []
    for i in range(1, len(sorted_by_x)):
        gap = sorted_by_x[i]['mid_x'] - sorted_by_x[i-1]['mid_x']
        x_gaps.append(gap)
    
    if x_gaps:
        # 分析间距分布
        x_gaps_sorted = sorted(x_gaps)
        
        # 找出小间距（同一断面内的线）和大间距（不同断面间）
        # 使用K-means思想：假设间距有两种模式
        
        # 简单方法：使用百分位数
        p10 = x_gaps_sorted[int(len(x_gaps_sorted) * 0.1)]
        p50 = x_gaps_sorted[int(len(x_gaps_sorted) * 0.5)]
        p90 = x_gaps_sorted[int(len(x_gaps_sorted) * 0.9)]
        
        print(f"\nX间距分布:")
        print(f"  10%分位: {p10:.2f}")
        print(f"  50%分位(中位数): {p50:.2f}")
        print(f"  90%分位: {p90:.2f}")
        
        # 使用密度聚类找断面间距
        # 假设小于中位数的一半是同一断面内的间距
        small_gap_threshold = p50 * 0.3
        large_gaps = [g for g in x_gaps if g > small_gap_threshold]
        
        if large_gaps:
            large_gaps_sorted = sorted(large_gaps)
            print(f"\n断面间间距(过滤小间距后):")
            print(f"  数量: {len(large_gaps)}")
            print(f"  最小: {min(large_gaps):.2f}")
            print(f"  最大: {max(large_gaps):.2f}")
            print(f"  平均: {sum(large_gaps)/len(large_gaps):.2f}")
        
        # 推断断面数量：统计大间距的数量+1
        # 但更准确的方法是统计有多少组线
        
        # 简单聚类：使用小阈值分组
        groups = []
        current_group = [sorted_by_x[0]]
        
        for i in range(1, len(sorted_by_x)):
            gap = sorted_by_x[i]['mid_x'] - sorted_by_x[i-1]['mid_x']
            if gap < p50 * 0.5:  # 同一组
                current_group.append(sorted_by_x[i])
            else:  # 新组
                groups.append(current_group)
                current_group = [sorted_by_x[i]]
        groups.append(current_group)
        
        print(f"\n使用阈值 {p50 * 0.5:.2f} 聚类后的断面组数: {len(groups)}")
        
        # 分析每组的线数量
        lines_per_group = [len(g) for g in groups]
        print(f"  每组线数: 平均={sum(lines_per_group)/len(lines_per_group):.1f}, 范围=[{min(lines_per_group)}, {max(lines_per_group)}]")
    
    # 获取桩号数量
    station_count = 0
    for e in msp.query('TEXT MTEXT'):
        try:
            text = e.dxf.text if e.dxftype() == 'TEXT' else e.text
            if 'K' in text.upper() and '+' in text:
                station_count += 1
        except:
            pass
    
    print(f"\n桩号文本数量: {station_count}")
    
    # 返回关键参数
    return {
        'avg_width': avg_width,
        'avg_height': avg_height,
        'line_count': len(overexc_lines),
        'station_count': station_count,
        'x_gaps': x_gaps if x_gaps else []
    }

# 分析两个文件
original_file = r"\\Beihai01\广西北海-测量资料\3、内湾段\内湾段分层图（全航道底图20260318）面积比例0.6.dxf"

if os.path.exists(original_file):
    result = analyze_file(original_file)
    
    if result and result['x_gaps']:
        print(f"\n{'='*70}")
        print("建议的自适应参数:")
        print('='*70)
        
        # 使用X间距的统计特征来设置聚类距离
        x_gaps = sorted(result['x_gaps'])
        p25 = x_gaps[int(len(x_gaps) * 0.25)]
        p50 = x_gaps[int(len(x_gaps) * 0.5)]
        
        # 聚类距离应该大于同一断面内的线间距，小于相邻断面间距
        # 建议使用 p50 * 0.5 作为阈值
        suggested_cluster_dist = p50 * 0.5
        
        print(f"  建议聚类距离: {suggested_cluster_dist:.2f}")
        print(f"  (基于X间距中位数 {p50:.2f} 的50%)")
        
        # 断面框尺寸用于其他距离参数
        avg_size = (result['avg_width'] + result['avg_height']) / 2
        print(f"  平均断面框尺寸: {avg_size:.2f}")
        print(f"  建议DMX匹配距离: {avg_size * 0.5:.2f}")
        print(f"  建议桩号匹配距离: {avg_size * 2:.2f}")
else:
    print(f"文件不存在: {original_file}")