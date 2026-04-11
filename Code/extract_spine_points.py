# -*- coding: utf-8 -*-
"""
从内湾底图提取脊梁点
逻辑：
1. 按桩号值分组TEXT（每个桩号左右两侧各一个TEXT）
2. 同一桩号的两个TEXT连线
3. 连线与航道中心线求交点 → 脊梁点
4. 在交点处计算中心线切线方向

作者: @黄秉俊
日期: 2026-04-02
"""

import ezdxf
import numpy as np
from collections import defaultdict
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
import json
import math

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
    """提取航道中心线坐标"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    center_layer = '01-1-1 航道中心线'
    for e in msp:
        if e.dxf.layer == center_layer and e.dxftype() == 'LWPOLYLINE':
            pts = [(p[0], p[1]) for p in e.get_points()]
            return pts
    return None

def get_station_texts(dxf_path):
    """提取桩号TEXT，按桩号值分组"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    station_layer = '02-1-10桩号'
    station_groups = defaultdict(list)
    
    for e in msp:
        if e.dxf.layer == station_layer and e.dxftype() == 'TEXT':
            station_val = parse_station_value(e.dxf.text)
            if station_val:
                pos = (e.dxf.insert.x, e.dxf.insert.y)
                station_groups[station_val].append({
                    'text': e.dxf.text.strip(),
                    'x': pos[0],
                    'y': pos[1]
                })
    
    return station_groups

def calculate_tangent_direction(centerline_coords, point):
    """
    计算中心线在某点处的切线方向
    
    Args:
        centerline_coords: 中心线坐标列表
        point: 目标点 (x, y)
    
    Returns:
        切线方向角（弧度），从X轴正向逆时针旋转
    """
    # 找到最近的中心线线段
    min_dist = float('inf')
    nearest_segment = None
    
    for i in range(len(centerline_coords) - 1):
        p1 = centerline_coords[i]
        p2 = centerline_coords[i + 1]
        
        # 计算点到线段的距离
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

def find_spine_intersections(centerline_coords, station_groups):
    """
    找到桩号连线与中心线的交点（脊梁点）
    
    Args:
        centerline_coords: 中心线坐标列表
        station_groups: 桩号分组字典
    
    Returns:
        脊梁点列表 [{station_name, station_value, x, y, tangent_angle}, ...]
    """
    centerline = LineString(centerline_coords)
    spine_points = []
    
    for station_val, texts in sorted(station_groups.items()):
        if len(texts) >= 2:
            # 找到左右两个TEXT
            # 按X坐标排序，确定左右
            sorted_texts = sorted(texts, key=lambda t: t['x'])
            left_text = sorted_texts[0]
            right_text = sorted_texts[-1]
            
            # 创建连线
            connection_line = LineString([
                (left_text['x'], left_text['y']),
                (right_text['x'], right_text['y'])
            ])
            
            # 求与中心线的交点
            intersection = centerline.intersection(connection_line)
            
            if not intersection.is_empty:
                if intersection.geom_type == 'Point':
                    ix, iy = intersection.x, intersection.y
                elif intersection.geom_type == 'MultiPoint':
                    # 取第一个交点
                    ix, iy = intersection.geoms[0].x, intersection.geoms[0].y
                else:
                    print(f"  警告: 桩号K{station_val//1000}+{station_val%1000}交点类型异常: {intersection.geom_type}")
                    continue
                
                # 计算切线方向
                tangent_angle = calculate_tangent_direction(centerline_coords, (ix, iy))
                
                spine_points.append({
                    'station_name': f"K{station_val//1000}+{station_val%1000:03d}",
                    'station_value': station_val,
                    'x': ix,
                    'y': iy,
                    'tangent_angle': tangent_angle,
                    'left_text': left_text,
                    'right_text': right_text
                })
            else:
                print(f"  警告: 桩号K{station_val//1000}+{station_val%1000}连线与中心线无交点")
        else:
            print(f"  警告: 桩号K{station_val//1000}+{station_val%1000}只有{len(texts)}个TEXT")
    
    return spine_points

def main():
    dxf_path = r'D:\断面算量平台\测试文件\内湾底图.dxf'
    section_json_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    output_path = r'D:\断面算量平台\测试文件\内湾底图_脊梁点.json'
    
    print("=" * 60)
    print("脊梁点提取工具")
    print("=" * 60)
    
    # 0. 加载断面桩号范围
    print("\n[0] 加载断面桩号范围...")
    with open(section_json_path, 'r', encoding='utf-8') as f:
        section_data = json.load(f)
    section_stations = set()
    for sec in section_data['sections']:
        station_val = sec.get('station_value')
        if station_val:
            section_stations.add(station_val)
    print(f"  断面桩号数量: {len(section_stations)}")
    if section_stations:
        print(f"  桩号范围: {min(section_stations)} - {max(section_stations)}")
    
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
    
    # 2. 提取桩号TEXT
    print("\n[2] 提取桩号TEXT...")
    station_groups = get_station_texts(dxf_path)
    print(f"  不同桩号值数量: {len(station_groups)}")
    
    # 过滤：只保留断面桩号范围内的
    filtered_groups = {k: v for k, v in station_groups.items() if k in section_stations}
    print(f"  过滤后桩号数量: {len(filtered_groups)}")
    
    # 统计每桩号TEXT数量
    counts = defaultdict(int)
    for station_val, texts in filtered_groups.items():
        counts[len(texts)] += 1
    for count, num in sorted(counts.items()):
        print(f"  {count}个TEXT的桩号: {num}个")
    
    # 3. 计算脊梁点
    print("\n[3] 计算脊梁点...")
    spine_points = find_spine_intersections(centerline, filtered_groups)
    print(f"  成功提取脊梁点: {len(spine_points)}个")
    
    # 4. 输出结果
    print("\n[4] 脊梁点示例（前5个）:")
    for i, sp in enumerate(spine_points[:5]):
        angle_deg = math.degrees(sp['tangent_angle'])
        print(f"  [{i+1}] {sp['station_name']} @ ({sp['x']:.2f}, {sp['y']:.2f}) 切线角={angle_deg:.1f}°")
    
    # 5. 保存JSON
    print(f"\n[5] 保存到: {output_path}")
    output_data = {
        'source_file': dxf_path,
        'total_spine_points': len(spine_points),
        'centerline_vertices': len(centerline),
        'spine_points': spine_points
    }
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)

if __name__ == '__main__':
    main()