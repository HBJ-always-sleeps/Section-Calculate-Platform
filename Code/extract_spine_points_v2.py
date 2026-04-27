# -*- coding: utf-8 -*-
"""
从内湾背景原始底图提取脊梁点（新版本）

新底图特点：
1. 桩号图层: "Marters测线"
2. 每个桩号对应一条LWPOLYLINE（长直线）和一个TEXT
3. TEXT位置在LWPOLYLINE终点，内容如"67+400"
4. 不需要连线过程，直接用LWPOLYLINE与中心线求交点

作者: @黄秉俊
日期: 2026-04-15
"""

import ezdxf
import numpy as np
from collections import defaultdict
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
import json
import math
import sys
import io

# 设置输出编码（仅在非打包环境中）
if not getattr(sys, 'frozen', False):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def parse_station_value(text_content):
    """解析桩号文本，返回桩号值（米）"""
    try:
        content = text_content.strip().replace('K', '').replace('k', '')
        if '+' in content:
            parts = content.split('+')
            if len(parts) == 2:
                km = int(parts[0])
                m = int(parts[1])
                return km * 1000 + m
    except:
        pass
    return None


def get_centerline_points(dxf_path):
    """提取航道中心线坐标（使用flattening处理带圆弧的多段线）
    
    改进：找到最长的LWPOLYLINE作为完整中心线
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    center_layer = '01-1-1 航道中心线'
    
    # 收集所有LWPOLYLINE，找到最长的（完整中心线）
    all_lwpolylines = []
    for e in msp:
        if e.dxf.layer == center_layer and e.dxftype() == 'LWPOLYLINE':
            pts = [(pt[0], pt[1]) for pt in e]
            # 计算长度
            length = 0
            for i in range(len(pts) - 1):
                length += math.sqrt((pts[i+1][0]-pts[i][0])**2 + (pts[i+1][1]-pts[i][1])**2)
            all_lwpolylines.append({
                'entity': e,
                'points': pts,
                'length': length,
                'has_arc': e.has_arc
            })
    
    if not all_lwpolylines:
        return []
    
    # 选择最长的LWPOLYLINE作为完整中心线
    longest = max(all_lwpolylines, key=lambda x: x['length'])
    e = longest['entity']
    
    print(f"  选择最长中心线: {longest['length']:.2f}m, {len(longest['points'])}顶点, 圆弧={longest['has_arc']}")
    
    if longest['has_arc']:
        exploded_entities = e.explode()
        all_points = []
        prev_end = None
        
        for ent in exploded_entities:
            if ent.dxftype() == 'LINE':
                start = (ent.dxf.start.x, ent.dxf.start.y)
                end = (ent.dxf.end.x, ent.dxf.end.y)
                
                if prev_end is not None:
                    dist_start = math.sqrt((start[0]-prev_end[0])**2 + (start[1]-prev_end[1])**2)
                    dist_end = math.sqrt((end[0]-prev_end[0])**2 + (end[1]-prev_end[1])**2)
                    if dist_end < dist_start:
                        start, end = end, start
                
                if not all_points or start != all_points[-1]:
                    all_points.append(start)
                all_points.append(end)
                prev_end = end
                
            elif ent.dxftype() == 'ARC':
                arc_points = list(ent.flattening(sagitta=0.1))
                arc_pts = [(pt.x, pt.y) for pt in arc_points]
                
                arc_start = arc_pts[0]
                arc_end = arc_pts[-1]
                
                if prev_end is not None:
                    dist_start = math.sqrt((arc_start[0]-prev_end[0])**2 + (arc_start[1]-prev_end[1])**2)
                    dist_end = math.sqrt((arc_end[0]-prev_end[0])**2 + (arc_end[1]-prev_end[1])**2)
                    
                    if dist_end < dist_start:
                        arc_pts = arc_pts[::-1]
                
                for pt_tuple in arc_pts:
                    if not all_points or pt_tuple != all_points[-1]:
                        all_points.append(pt_tuple)
                prev_end = arc_pts[-1]
        
        return all_points
    else:
        # 无圆弧，直接提取顶点
        return longest['points']


def get_station_lines_and_texts(dxf_path, station_layer='Marters测线'):
    """
    从新底图提取桩号线和文本
    
    新格式：每个桩号对应一条LWPOLYLINE和一个TEXT
    TEXT位置在LWPOLYLINE终点
    
    Returns:
        dict: {station_value: {'line': (start, end), 'text': content, 'text_pos': (x, y)}}
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    # 先收集所有TEXT，建立位置到桩号的映射
    text_map = {}  # {(x, y): station_value}
    for e in msp:
        if e.dxf.layer == station_layer and e.dxftype() == 'TEXT':
            station_val = parse_station_value(e.dxf.text)
            if station_val:
                pos = (round(e.dxf.insert.x, 2), round(e.dxf.insert.y, 2))
                text_map[pos] = station_val
    
    # 收集LWPOLYLINE，匹配TEXT
    station_data = {}
    for e in msp:
        if e.dxf.layer == station_layer and e.dxftype() == 'LWPOLYLINE':
            if len(e) >= 2:
                # 获取起点和终点
                pts = [(pt[0], pt[1]) for pt in e]
                start = pts[0]
                end = pts[-1]
                
                # 检查终点是否匹配TEXT位置
                end_rounded = (round(end[0], 2), round(end[1], 2))
                if end_rounded in text_map:
                    station_val = text_map[end_rounded]
                    station_data[station_val] = {
                        'line': (start, end),
                        'text': str(station_val),
                        'text_pos': end
                    }
    
    print(f"  提取到 {len(station_data)} 个桩号线")
    
    return station_data


def calculate_tangent_direction(centerline_coords, point):
    """计算中心线在某点处的切线方向"""
    min_dist = float('inf')
    nearest_segment = None
    
    for i in range(len(centerline_coords) - 1):
        p1 = centerline_coords[i]
        p2 = centerline_coords[i + 1]
        
        line = LineString([p1, p2])
        pt = Point(point)
        dist = line.distance(pt)
        
        if dist < min_dist:
            min_dist = dist
            nearest_segment = (p1, p2)
    
    if nearest_segment:
        p1, p2 = nearest_segment
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        return math.atan2(dy, dx)
    
    return 0


def find_spine_intersections(centerline_coords, station_data):
    """
    找到桩号线与中心线的交点（脊梁点）
    
    Args:
        centerline_coords: 中心线坐标列表
        station_data: 桩号数据字典
    
    Returns:
        脊梁点列表 [{station_name, station_value, x, y, tangent_angle}, ...]
    """
    centerline = LineString(centerline_coords)
    spine_points = []
    
    for station_val, data in sorted(station_data.items()):
        line_start, line_end = data['line']
        
        # 创建桩号线
        station_line = LineString([line_start, line_end])
        
        # 求交点
        intersection = centerline.intersection(station_line)
        
        if intersection.is_empty:
            continue
        
        # 处理交点
        if intersection.geom_type == 'Point':
            spine_x = intersection.x
            spine_y = intersection.y
        elif intersection.geom_type == 'MultiPoint':
            # 取第一个点
            spine_x = intersection.geoms[0].x
            spine_y = intersection.geoms[0].y
        else:
            continue
        
        # 计算切线方向
        tangent_angle = calculate_tangent_direction(centerline_coords, (spine_x, spine_y))
        
        spine_points.append({
            'station_name': data['text'],
            'station_value': station_val,
            'x': spine_x,
            'y': spine_y,
            'tangent_angle': tangent_angle
        })
    
    return spine_points


def main(dxf_path=None, output_path=None):
    """
    主函数 - 从新底图提取脊梁点
    
    Args:
        dxf_path: 内湾背景原始底图DXF路径
        output_path: 输出脊梁点JSON路径
    """
    # 使用默认路径如果未提供
    if dxf_path is None:
        dxf_path = r'D:\断面算量平台\测试文件\内湾背景原始.dxf'
    if output_path is None:
        output_path = r'D:\断面算量平台\测试文件\内湾背景原始_脊梁点.json'
    
    print("=" * 60)
    print("脊梁点提取工具（新版本 - Marters测线图层）")
    print("=" * 60)
    
    # 1. 提取中心线
    print("\n[1] 提取航道中心线...")
    centerline = get_centerline_points(dxf_path)
    if centerline:
        print(f"  中心线顶点数: {len(centerline)}")
        print(f"  起点: ({centerline[0][0]:.2f}, {centerline[0][1]:.2f})")
        print(f"  终点: ({centerline[-1][0]:.2f}, {centerline[-1][1]:.2f})")
    else:
        print("  错误: 未找到航道中心线!")
        return
    
    # 2. 提取桩号线和文本
    print("\n[2] 提取桩号线（Marters测线图层）...")
    station_data = get_station_lines_and_texts(dxf_path, 'Marters测线')
    
    if station_data:
        stations = sorted(station_data.keys())
        print(f"  桩号范围: K{stations[0]//1000}+{stations[0]%1000:03d} ~ K{stations[-1]//1000}+{stations[-1]%1000:03d}")
    
    # 3. 求交点
    print("\n[3] 计算脊梁点（桩号线与中心线交点）...")
    spine_points = find_spine_intersections(centerline, station_data)
    print(f"  成功提取脊梁点: {len(spine_points)}个")
    
    # 4. 验证脊梁点落在中心线上
    print("\n[4] 验证脊梁点...")
    centerline_geom = LineString(centerline)
    max_dist = 0
    for sp in spine_points:
        pt = Point(sp['x'], sp['y'])
        dist = centerline_geom.distance(pt)
        max_dist = max(max_dist, dist)
    print(f"  最大偏离距离: {max_dist:.4f}m")
    
    # 5. 保存结果
    print(f"\n[5] 保存到: {output_path}")
    output_data = {
        'source': dxf_path,
        'station_layer': 'Marters测线',
        'centerline_layer': '01-1-1 航道中心线',
        'total_spine_points': len(spine_points),
        'station_range': {
            'start': spine_points[0]['station_name'] if spine_points else None,
            'end': spine_points[-1]['station_name'] if spine_points else None
        },
        'spine_points': spine_points
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print("提取完成！")
    print("=" * 60)
    
    return spine_points


if __name__ == "__main__":
    main()