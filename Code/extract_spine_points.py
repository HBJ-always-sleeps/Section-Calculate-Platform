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
    """提取航道中心线坐标（使用flattening处理带圆弧的多段线）
    
    关键改进：
    1. LWPOLYLINE 没有 flattening 方法，需要先 explode 分解
    2. 对 ARC 使用 flattening，对 LINE 直接取端点
    3. ARC的起点/终点可能与中心线方向相反，需要根据连续性判断是否反转
    """
    # 尝试多种编码打开 DXF 文件
    for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
        try:
            doc = ezdxf.readfile(dxf_path, encoding=encoding)
            msp = doc.modelspace()
            break
        except UnicodeDecodeError:
            continue
    else:
        # 如果都失败，使用默认方式
        import warnings
        warnings.warn(f"无法使用已知编码打开 {dxf_path}，尝试使用默认编码")
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
    
    center_layer = '01-1-1 航道中心线'
    
    # 收集所有中心线LWPOLYLINE，按顶点数排序（优先使用顶点数多的）
    centerline_entities = []
    for e in msp:
        if e.dxf.layer == center_layer and e.dxftype() == 'LWPOLYLINE':
            pts = list(e.get_points())
            centerline_entities.append((e, len(pts)))
    
    if not centerline_entities:
        print(f"  错误: 未找到图层 '{center_layer}' 的 LWPOLYLINE")
        return None
    
    # 按顶点数排序，选择顶点数最多的
    centerline_entities.sort(key=lambda x: x[1], reverse=True)
    e, vertex_count = centerline_entities[0]
    print(f"  找到 {len(centerline_entities)} 条中心线，选择顶点数最多的 ({vertex_count} 个顶点)")
    
    # 检查是否包含圆弧
    if e.has_arc:
        # 使用 explode 方法将带圆弧的多段线分解为 ARC 和 LINE
        exploded_entities = e.explode()
        
        # 按原始顺序处理分解后的实体，确保连续性
        all_points = []
        prev_end = None  # 上一个实体的终点
        
        for ent in exploded_entities:
            if ent.dxftype() == 'LINE':
                start = (ent.dxf.start.x, ent.dxf.start.y)
                end = (ent.dxf.end.x, ent.dxf.end.y)
                
                # 检查是否需要反转LINE方向
                if prev_end is not None:
                    dist_start = math.sqrt((start[0]-prev_end[0])**2 + (start[1]-prev_end[1])**2)
                    dist_end = math.sqrt((end[0]-prev_end[0])**2 + (end[1]-prev_end[1])**2)
                    if dist_end < dist_start:
                        # 反转LINE方向
                        start, end = end, start
                
                if not all_points or start != all_points[-1]:
                    all_points.append(start)
                all_points.append(end)
                prev_end = end
                
            elif ent.dxftype() == 'ARC':
                # 使用 flattening 将圆弧转换为高精度点集
                arc_points = list(ent.flattening(sagitta=0.1))
                arc_pts = [(pt.x, pt.y) for pt in arc_points]
                
                # 检查ARC方向是否与中心线连续
                arc_start = arc_pts[0]
                arc_end = arc_pts[-1]
                
                if prev_end is not None:
                    dist_start = math.sqrt((arc_start[0]-prev_end[0])**2 + (arc_start[1]-prev_end[1])**2)
                    dist_end = math.sqrt((arc_end[0]-prev_end[0])**2 + (arc_end[1]-prev_end[1])**2)
                    
                    if dist_end < dist_start:
                        # ARC方向相反，需要反转
                        arc_pts = arc_pts[::-1]
                
                for pt_tuple in arc_pts:
                    if not all_points or pt_tuple != all_points[-1]:
                        all_points.append(pt_tuple)
                prev_end = arc_pts[-1]
        
        print(f"  中心线离散点数: {len(all_points)} (ARC使用flattening, sagitta=0.1m, 自动修正方向)")
        return all_points
    else:
        # 没有圆弧，直接获取点
        pts = [(p[0], p[1]) for p in e.get_points()]
        print(f"  中心线顶点数: {len(pts)} (无圆弧)")
        return pts

def get_station_texts(dxf_path):
    """从桩号图层LINE出发，合并连线并确保经过脊梁点
    
    关键理解：
    1. 每个桩号有2个TEXT（左侧和右侧）
    2. 每个TEXT附近有1条LINE（LINE起点靠近TEXT，LINE终点远离TEXT）
    3. 正确连线方式：从左侧LINE的终点到右侧LINE的终点
    4. 连线与中心线的交点即为脊梁点
    """
    # 尝试多种编码打开 DXF 文件
    for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
        try:
            doc = ezdxf.readfile(dxf_path, encoding=encoding)
            msp = doc.modelspace()
            break
        except UnicodeDecodeError:
            continue
    else:
        # 如果都失败，使用默认方式
        import warnings
        warnings.warn(f"无法使用已知编码打开 {dxf_path}，尝试使用默认编码")
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
    
    station_layer = '02-1-10桩号'
    
    # 步骤1: 收集所有TEXT，按桩号分组
    text_groups = {}
    for e in msp:
        if e.dxf.layer == station_layer and e.dxftype() == 'TEXT':
            station_val = parse_station_value(e.dxf.text)
            if station_val:
                if station_val not in text_groups:
                    text_groups[station_val] = []
                text_groups[station_val].append({
                    'text': e.dxf.text.strip(),
                    'x': e.dxf.insert.x,
                    'y': e.dxf.insert.y
                })
    
    # 步骤2: 收集所有LINE
    all_lines = []
    for e in msp:
        if e.dxf.layer == station_layer and e.dxftype() == 'LINE':
            all_lines.append({
                'start': (e.dxf.start.x, e.dxf.start.y),
                'end': (e.dxf.end.x, e.dxf.end.y)
            })
    
    # 步骤3: 为每个桩号找到正确的连线
    station_groups = {}
    
    for station_val, texts in text_groups.items():
        if len(texts) < 2:
            continue
        
        # 按X坐标排序，区分左右TEXT
        sorted_texts = sorted(texts, key=lambda t: t['x'])
        left_text = sorted_texts[0]
        right_text = sorted_texts[-1]
        
        # 找左侧TEXT最近的LINE（按起点距离）
        min_dist_left = float('inf')
        left_line = None
        for l in all_lines:
            dist_start = ((l['start'][0]-left_text['x'])**2 + (l['start'][1]-left_text['y'])**2)**0.5
            if dist_start < min_dist_left:
                min_dist_left = dist_start
                left_line = l
        
        # 找右侧TEXT最近的LINE（按起点距离）
        min_dist_right = float('inf')
        right_line = None
        for l in all_lines:
            dist_start = ((l['start'][0]-right_text['x'])**2 + (l['start'][1]-right_text['y'])**2)**0.5
            if dist_start < min_dist_right:
                min_dist_right = dist_start
                right_line = l
        
        if left_line and right_line:
            # 正确连线：从左侧LINE的终点到右侧LINE的终点
            connection_start = left_line['end']
            connection_end = right_line['end']
            
            station_groups[station_val] = {
                'texts': texts,
                'lines': [{
                    'start': connection_start,
                    'end': connection_end,
                    'layer': 'merged'
                }],
                'left_text': left_text,
                'right_text': right_text
            }
    
    print(f"  合并后桩号数量: {len(station_groups)}")
    
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
    
    for station_val, data in sorted(station_groups.items()):
        # data是字典，包含'texts'和'lines'
        texts = data.get('texts', [])
        lines = data.get('lines', [])
        
        # 优先使用LINE位置来创建连线
        if lines and len(lines) >= 1:
            # 使用桩号图层的LINE来创建连线
            line = lines[0]
            connection_line = LineString([line['start'], line['end']])
            
            # 从TEXT中获取left_text和right_text
            if len(texts) >= 2:
                sorted_texts = sorted(texts, key=lambda t: t['x'])
                left_text = sorted_texts[0]
                right_text = sorted_texts[-1]
            else:
                # 如果没有足够的TEXT，使用LINE的端点
                left_text = {'x': line['start'][0], 'y': line['start'][1]}
                right_text = {'x': line['end'][0], 'y': line['end'][1]}
        elif len(texts) >= 2:
            # 旧格式：使用TEXT位置创建连线
            sorted_texts = sorted(texts, key=lambda t: t['x'])
            left_text = sorted_texts[0]
            right_text = sorted_texts[-1]
            
            connection_line = LineString([
                (left_text['x'], left_text['y']),
                (right_text['x'], right_text['y'])
            ])
        else:
            # 跳过没有足够数据的桩号
            continue
        
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
                'lines': lines,  # 保存LINE位置用于可视化
                'left_text': left_text,
                'right_text': right_text
            })
        else:
            print(f"  警告: 桩号K{station_val//1000}+{station_val%1000}连线与中心线无交点")
    
    return spine_points

def main(dxf_path=None, section_json_path=None, output_path=None):
    """
    主函数 - 可被外部调用
    
    Args:
        dxf_path: 内湾底图DXF路径
        section_json_path: 断面元数据JSON路径（可选，用于过滤桩号范围）
        output_path: 输出脊梁点JSON路径
    """
    # 使用默认路径如果未提供
    if dxf_path is None:
        dxf_path = r'D:\断面算量平台\测试文件\内湾底图.dxf'
    if output_path is None:
        output_path = r'D:\断面算量平台\测试文件\内湾底图_脊梁点.json'
    
    print("=" * 60)
    print("脊梁点提取工具")
    print("=" * 60)
    
    # 0. 加载断面桩号范围（可选）
    section_stations = None
    if section_json_path:
        print("\n[0] 加载断面桩号范围...")
        try:
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
        except Exception as e:
            print(f"  警告: 无法加载断面元数据: {e}")
            print(f"  将提取所有桩号的脊梁点")
            section_stations = None
    else:
        print("\n[0] 未提供断面元数据，将提取所有桩号的脊梁点")
    
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
    
    # 过滤：只保留断面桩号范围内的（如果有断面元数据）
    if section_stations:
        filtered_groups = {k: v for k, v in station_groups.items() if k in section_stations}
        print(f"  过滤后桩号数量: {len(filtered_groups)}")
    else:
        filtered_groups = station_groups
        print(f"  使用全部桩号: {len(filtered_groups)}")
    
    # 统计每桩号TEXT数量
    counts = defaultdict(int)
    for station_val, data in filtered_groups.items():
        texts = data.get('texts', [])
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
    import argparse
    parser = argparse.ArgumentParser(description='脊梁点提取脚本')
    parser.add_argument('--dxf', type=str,
                       default=r'D:\断面算量平台\测试文件\内湾底图.dxf',
                       help='背景底图DXF文件路径')
    parser.add_argument('--output', '-o', type=str,
                       default=r'D:\断面算量平台\测试文件\内湾底图_脊梁点.json',
                       help='输出脊梁点JSON文件路径')
    parser.add_argument('--section-json', type=str,
                       default=None,
                       help='断面元数据JSON文件路径（用于过滤桩号范围）')
    args = parser.parse_args()
    main(dxf_path=args.dxf, section_json_path=args.section_json, output_path=args.output)