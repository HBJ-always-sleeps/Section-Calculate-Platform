# -*- coding: utf-8 -*-
"""
外海断面图XYZ坐标提取脚本 v2 - 使用正确比例尺
关键信息：
1. 水平比例尺：竖线间距0.25单位 = 50米
2. 垂直比例尺：1单位 = 10米
3. 小框上长边代表高程-12米的Y位置
4. 开挖线和超挖线延长至0米高程位置
5. 脊梁点：中心线X + 小框中心Y

流程：
1. 从外海断面图.dxf检测开挖线和超挖线
2. 从外海背景.dxf获取桩号的真实世界坐标
3. 将断面图的局部坐标转换为真实世界坐标
4. 延长开挖线和超挖线至0米高程
5. 输出XYZ坐标文件
"""

import ezdxf
import os
import math
import re
import json
from datetime import datetime
from collections import defaultdict


# 比例尺定义（完整版断面图）
# 竖线间隔16.67代表50米 → 水平比例尺 = 50/16.67 = 3米/单位
# 小框短边120代表24米 → 垂直比例尺 = 24/120 = 0.2米/单位
SCALE_X = 3.0    # 水平比例尺: 1单位 = 3米
SCALE_Y = 0.2    # 垂直比例尺: 1单位 = 0.2米
ELEVATION_REF = 0.0  # 小框上长边对应的高程基准（米）- 用户确认上长边=0米
TARGET_ELEVATION = -24.0  # 延长目标高程（米）- 下长边=-24米
INTERVAL_X = 4.0  # 水平插值间隔（米）


def get_bbox(pts):
    """计算边界框"""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def parse_station(text):
    """解析桩号格式：00+000 或 00+000.TIN"""
    # 先尝试匹配带.TIN的格式
    match = re.search(r'(\d+)\+(\d+)\.TIN', text.upper())
    if match:
        return int(match.group(1)) * 1000 + int(match.group(2))
    # 再尝试匹配不带.TIN的格式
    match = re.search(r'(\d+)\+(\d+)', text)
    if match:
        return int(match.group(1)) * 1000 + int(match.group(2))
    return None


def parse_background_station(text):
    """解析背景底图桩号格式：00+000"""
    match = re.search(r'(\d+)\+(\d+)', text)
    if match:
        return int(match.group(1)) * 1000 + int(match.group(2))
    return None


def format_station(value):
    """格式化桩号数值为文本"""
    km = int(value // 1000)
    m = int(value % 1000)
    return f"{km}+{m:03d}"


def is_frame_inside(big_frame, small_frame):
    """检查小框是否在大框内"""
    return (big_frame['min_x'] <= small_frame['min_x'] and 
            big_frame['max_x'] >= small_frame['max_x'] and
            big_frame['min_y'] <= small_frame['min_y'] and
            big_frame['max_y'] >= small_frame['max_y'])


def load_background_stations(background_path):
    """从外海背景.dxf加载桩号脊梁点位置（测线与中心线交点）"""
    print(f"\n[加载背景底图桩号脊梁点]")
    print(f"  文件: {background_path}")
    
    doc = ezdxf.readfile(background_path)
    msp = doc.modelspace()
    
    # 找到航道中心线图层（脊梁点所在位置）
    hangdao_layer = None
    for layer in doc.layers:
        name = layer.dxf.name
        if '航道' in name and '中心线' in name and '超深' not in name:
            hangdao_layer = name
            break
    
    # 如果没找到，尝试更宽泛的匹配
    if hangdao_layer is None:
        for layer in doc.layers:
            if '航道' in layer.dxf.name and '中心线' in layer.dxf.name:
                hangdao_layer = layer.dxf.name
                break
    
    # 获取航道中心线线段
    center_lines = []
    for e in msp.query(f'LINE[layer=="{hangdao_layer}"]'):
        center_lines.append({'start': (e.dxf.start.x, e.dxf.start.y), 'end': (e.dxf.end.x, e.dxf.end.y)})
    for e in msp.query(f'LWPOLYLINE[layer=="{hangdao_layer}"]'):
        pts = [(p[0], p[1]) for p in e.get_points()]
        for i in range(len(pts) - 1):
            center_lines.append({'start': pts[i], 'end': pts[i+1]})
    
    # 获取测线线段
    survey_lines = []
    for e in msp.query('LWPOLYLINE[layer=="MARTERS测线"]'):
        pts = [(p[0], p[1]) for p in e.get_points()]
        for i in range(len(pts) - 1):
            survey_lines.append({'start': pts[i], 'end': pts[i+1]})
    
    # 计算测线与中心线的交点
    def lines_intersect_pt(line1, line2):
        x1, y1 = line1['start']
        x2, y2 = line1['end']
        x3, y3 = line2['start']
        x4, y4 = line2['end']
        denom = (x1-x2)*(y3-y4) - (y1-y2)*(x3-x4)
        if abs(denom) < 0.001:
            return None
        t = ((x1-x3)*(y3-y4) - (y1-y3)*(x3-x4)) / denom
        u = -((x1-x2)*(y1-y3) - (y1-y2)*(x1-x3)) / denom
        if 0 <= t <= 1 and 0 <= u <= 1:
            return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        return None
    
    # 为每条测线建立到交点的映射
    survey_to_intersection = {}
    for si, survey in enumerate(survey_lines):
        for ci, center in enumerate(center_lines):
            pt = lines_intersect_pt(center, survey)
            if pt:
                if si not in survey_to_intersection:
                    survey_to_intersection[si] = pt
    
    # 获取桩号标签并匹配脊梁点
    station_positions = {}
    for e in msp.query('TEXT[layer=="MARTERS测线"]'):
        try:
            text = e.dxf.text
            station_value = parse_background_station(text)
            if station_value is not None:
                sx, sy = e.dxf.insert.x, e.dxf.insert.y
                
                # 找到最近的测线
                best_dist = float('inf')
                best_survey_idx = None
                for si, survey in enumerate(survey_lines):
                    x1, y1 = survey['start']
                    x2, y2 = survey['end']
                    dx, dy = x2-x1, y2-y1
                    t = max(0, min(1, ((sx-x1)*dx + (sy-y1)*dy) / (dx*dx + dy*dy + 0.001)))
                    proj_x, proj_y = x1+t*dx, y1+t*dy
                    dist = math.sqrt((sx-proj_x)**2 + (sy-proj_y)**2)
                    if dist < best_dist:
                        best_dist = dist
                        best_survey_idx = si
                
                # 使用测线与中心线的交点作为脊梁点
                if best_survey_idx is not None and best_survey_idx in survey_to_intersection:
                    spine_pt = survey_to_intersection[best_survey_idx]
                    station_positions[station_value] = {
                        'text': text,
                        'x': spine_pt[0],
                        'y': spine_pt[1]
                    }
        except:
            pass
    
    print(f"  加载脊梁点: {len(station_positions)}个")
    
    if station_positions:
        min_station = min(station_positions.keys())
        max_station = max(station_positions.keys())
        print(f"  桩号范围: {format_station(min_station)} 到 {format_station(max_station)}")
    
    return station_positions


def detect_section_data(msp):
    """检测断面数据"""
    print(f"\n[检测断面数据]")
    
    # 1. 检测断面框（5顶点多段线）
    all_frames = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) == 5:
                bbox = get_bbox(pts)
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
                all_frames.append({
                    'entity': e,
                    'pts': pts,
                    'width': width,
                    'height': height,
                    'min_x': bbox[0],
                    'max_x': bbox[2],
                    'min_y': bbox[1],
                    'max_y': bbox[3],
                    'center_x': (bbox[0] + bbox[2]) / 2,
                    'center_y': (bbox[1] + bbox[3]) / 2
                })
        except:
            pass
    
    # 区分大框和小框（完整版用高度区分）
    # 小框高度约120，大框高度约185
    small_frames = [f for f in all_frames if abs(f['height'] - 120) < 10]
    big_frames = [f for f in all_frames if f['height'] > 150]
    
    print(f"  大框数量: {len(big_frames)}")
    print(f"  小框数量: {len(small_frames)}")
    
    # 2. 检测竖线（用于找中心线）
    vertical_lines = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) == 2:
                x1, y1 = pts[0]
                x2, y2 = pts[1]
                length = math.sqrt((x2-x1)**2 + (y2-y1)**2)
                angle = math.degrees(math.atan2(y2-y1, x2-x1))
                
                # 垂直线判断
                if 85 < abs(angle) < 95:
                    vertical_lines.append({
                        'entity': e,
                        'pts': pts,
                        'length': length,
                        'center_x': (x1+x2)/2,
                        'center_y': (y1+y2)/2,
                        'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2
                    })
        except:
            pass
    
    print(f"  竖线数量: {len(vertical_lines)}")
    
    # 3. 检测斜线（开挖线和超挖线）
    diagonal_lines = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) == 2:
                x1, y1 = pts[0]
                x2, y2 = pts[1]
                length = math.sqrt((x2-x1)**2 + (y2-y1)**2)
                angle = math.degrees(math.atan2(y2-y1, x2-x1))
                
                # 斜线判断
                angle_normalized = abs(angle) % 180
                is_diagonal = not (angle_normalized < 5 or 85 < angle_normalized < 95)
                
                if is_diagonal:
                    # 完整版：斜线长度约117-120，角度约56°
                    # 用角度区分开挖线和超挖线（开挖线角度约56°，超挖线角度约-56°）
                    # 或者用长度区分：长度约117是开挖线，长度约120是超挖线
                    line_type = 'excav' if length < 118 else 'overbreak'
                    # 斜线角度判断：
                    # angle > 0 表示从底部到顶部X增加（在CAD坐标系中X大的一侧， 即右侧）
                    # angle < 0 表示从底部到顶部X减少（在CAD坐标系中X小的一侧， 即左侧）
                    # 注意：这里"左/右"是相对于中心线的位置
                    side = 'right' if angle > 0 else 'left'
                    
                    diagonal_lines.append({
                        'entity': e,
                        'pts': pts,
                        'length': length,
                        'angle': angle,
                        'line_type': line_type,
                        'side': side,
                        'center_x': (x1+x2)/2,
                        'center_y': (y1+y2)/2,
                        'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                        'top_y': max(y1, y2),
                        'bottom_y': min(y1, y2),
                        'top_x': x1 if y1 > y2 else x2,
                        'bottom_x': x1 if y1 < y2 else x2
                    })
        except:
            pass
    
    print(f"  斜线数量: {len(diagonal_lines)}")
    
    excav_lines = [d for d in diagonal_lines if d['line_type'] == 'excav']
    overbreak_lines = [d for d in diagonal_lines if d['line_type'] == 'overbreak']
    
    print(f"    开挖线(短): {len(excav_lines)}条")
    print(f"    超挖线(长): {len(overbreak_lines)}条")
    
    # 4. 检测桩号文本
    station_texts = []
    for e in msp.query('TEXT[layer=="LABELS"]'):
        try:
            text = e.dxf.text
            station_value = parse_station(text)
            if station_value is not None:
                station_texts.append({
                    'entity': e,
                    'text': text,
                    'value': station_value,
                    'x': e.dxf.insert.x,
                    'y': e.dxf.insert.y
                })
        except:
            pass
    
    print(f"  桩号文本数量: {len(station_texts)}")
    
    # 5. 匹配大框与小框
    frame_pairs = []
    for big in big_frames:
        inside_small = [s for s in small_frames if is_frame_inside(big, s)]
        if inside_small:
            inside_small.sort(key=lambda s: abs(s['center_y'] - big['center_y']))
            small = inside_small[0]
            
            # 找大框内的竖线
            inside_vertical = [v for v in vertical_lines 
                              if big['min_x'] <= v['center_x'] <= big['max_x']
                              and big['min_y'] <= v['center_y'] <= big['max_y']]
            
            # 按X坐标排序
            inside_vertical.sort(key=lambda v: v['center_x'])
            
            # 找中心线（小框中心附近的竖线，或多条重叠的竖线）
            center_line_x = None
            
            # 方法1：找小框中心附近的竖线（优先）
            small_center_x = small['center_x']
            for v in inside_vertical:
                if abs(v['center_x'] - small_center_x) < 5:  # 在小框中心5单位内
                    center_line_x = v['center_x']
                    break
            
            # 方法2：如果方法1没找到，找重叠最多的竖线位置
            if center_line_x is None:
                # 统计每个X位置的重叠数量
                x_counts = {}
                for v in inside_vertical:
                    x_key = round(v['center_x'], 1)
                    x_counts[x_key] = x_counts.get(x_key, 0) + 1
                
                # 找重叠最多的位置（且在小框中间区域）
                max_count = 0
                best_x = None
                for x_key, count in x_counts.items():
                    # 检查是否在小框中间区域（30%-70%）
                    x_ratio = (x_key - small['min_x']) / (small['max_x'] - small['min_x'])
                    if 0.3 <= x_ratio <= 0.7 and count > max_count:
                        max_count = count
                        best_x = x_key
                
                if best_x is not None:
                    center_line_x = best_x
            
            frame_pairs.append({
                'big_frame': big,
                'small_frame': small,
                'center_line_x': center_line_x,
                'vertical_lines': inside_vertical
            })
    
    print(f"  大小框配对: {len(frame_pairs)}组")
    
    # 6. 匹配小框内的斜线
    for p in frame_pairs:
        small = p['small_frame']
        
        inside_diagonal = [d for d in diagonal_lines 
                          if small['min_x'] <= d['center_x'] <= small['max_x']
                          and small['min_y'] <= d['center_y'] <= small['max_y']]
        
        p['excav_left'] = [d for d in inside_diagonal if d['line_type'] == 'excav' and d['side'] == 'left']
        p['excav_right'] = [d for d in inside_diagonal if d['line_type'] == 'excav' and d['side'] == 'right']
        p['overbreak_left'] = [d for d in inside_diagonal if d['line_type'] == 'overbreak' and d['side'] == 'left']
        p['overbreak_right'] = [d for d in inside_diagonal if d['line_type'] == 'overbreak' and d['side'] == 'right']
    
    # 7. 匹配桩号
    for p in frame_pairs:
        big = p['big_frame']
        
        inside_stations = [s for s in station_texts 
                          if big['min_x'] <= s['x'] <= big['max_x']
                          and big['min_y'] <= s['y'] <= big['max_y']]
        
        if inside_stations:
            p['station'] = inside_stations[0]['value']
            p['station_text'] = inside_stations[0]['text']
        else:
            p['station'] = None
            p['station_text'] = None
    
    with_station = [p for p in frame_pairs if p['station'] is not None]
    print(f"  有桩号: {len(with_station)}组")
    
    return {
        'frame_pairs': frame_pairs,
        'vertical_lines': vertical_lines,
        'diagonal_lines': diagonal_lines
    }


def extend_line_to_elevation(top_x, top_z, bottom_x, bottom_z, target_z):
    """将线延长到目标高程
    
    参数:
        top_x, top_z: 线的顶点坐标
        bottom_x, bottom_z: 线的底点坐标
        target_z: 目标高程
    
    返回:
        延长后的顶点坐标 (extended_x, extended_z)
    """
    # 计算线的方向向量
    dx = bottom_x - top_x
    dz = bottom_z - top_z
    
    if abs(dz) < 0.001:  # 水平线，无法延长
        return None, None
    
    # 计算延长比例
    t = (target_z - top_z) / dz
    
    # 计算延长后的X坐标
    extended_x = top_x + t * dx
    extended_z = target_z
    
    return extended_x, extended_z


def calculate_spine_direction(station_positions, station):
    """计算脊梁线在当前桩号处的方向向量
    
    通过相邻桩号的位置计算脊梁线方向
    
    Returns:
        (dx, dy): 脊梁线方向向量（单位向量）
    """
    # 获取所有桩号并排序
    stations = sorted(station_positions.keys())
    
    # 找到当前桩号的位置
    idx = stations.index(station) if station in stations else -1
    
    if idx < 0:
        return (1.0, 0.0)  # 默认水平方向
    
    # 计算方向向量
    if idx == 0:
        # 第一个桩号，使用下一个桩号计算方向
        next_station = stations[idx + 1] if idx + 1 < len(stations) else station
        curr_pos = station_positions[station]
        next_pos = station_positions[next_station]
        dx = next_pos['x'] - curr_pos['x']
        dy = next_pos['y'] - curr_pos['y']
    elif idx == len(stations) - 1:
        # 最后一个桩号，使用上一个桩号计算方向
        prev_station = stations[idx - 1]
        curr_pos = station_positions[station]
        prev_pos = station_positions[prev_station]
        dx = curr_pos['x'] - prev_pos['x']
        dy = curr_pos['y'] - prev_pos['y']
    else:
        # 中间桩号，使用前后两个桩号计算方向
        prev_station = stations[idx - 1]
        next_station = stations[idx + 1]
        prev_pos = station_positions[prev_station]
        next_pos = station_positions[next_station]
        dx = next_pos['x'] - prev_pos['x']
        dy = next_pos['y'] - prev_pos['y']
    
    # 归一化为单位向量
    length = math.sqrt(dx**2 + dy**2)
    if length > 0:
        dx /= length
        dy /= length
    
    return (dx, dy)


def convert_to_world_coords(section_data, station_positions):
    """将断面图坐标转换为真实世界坐标
    
    关键说明:
    - 小框上长边代表高程-12米的Y位置 (small['max_y'] 对应 ELEVATION_REF = -12米)
    - 垂直比例尺: 1单位 = 10米
    - 开挖线和超挖线延长至0米高程
    - 断面图中的水平偏移转换为垂直于脊梁线方向的偏移
    """
    print(f"\n[坐标转换]")
    print(f"  水平比例尺: 1单位 = {SCALE_X}米")
    print(f"  垂直比例尺: 1单位 = {SCALE_Y}米")
    print(f"  小框上长边高程基准: {ELEVATION_REF}米")
    print(f"  延长目标高程: {TARGET_ELEVATION}米")
    
    excav_xyz = []
    overbreak_xyz = []
    
    for p in section_data['frame_pairs']:
        if p['station'] is None:
            continue
        
        station = p['station']
        
        # 获取桩号的真实世界位置
        if station not in station_positions:
            print(f"  警告: 桩号{format_station(station)}在背景底图中未找到")
            continue
        
        station_pos = station_positions[station]
        station_x = station_pos['x']
        station_y = station_pos['y']
        
        # 获取脊梁线方向向量
        spine_dx, spine_dy = calculate_spine_direction(station_positions, station)
        
        # 计算垂直于脊梁线的方向向量（断面偏移方向）
        # 垂直方向：旋转90度，有两种选择（左侧和右侧）
        # 选择使得断面图中的"左"对应世界坐标中的"左"（相对于脊梁线前进方向）
        perp_dx = -spine_dy  # 垂直方向X分量
        perp_dy = spine_dx    # 垂直方向Y分量
        
        # 获取小框信息
        small = p['small_frame']
        center_line_x = p['center_line_x']
        
        # 小框上长边对应高程-12米
        def y_to_elevation(y_local):
            """将局部Y坐标转换为高程
            
            小框上边(max_y)对应高程-12米
            往下（Y坐标减小）深度增加，高程更负
            """
            return ELEVATION_REF - (small['max_y'] - y_local) * SCALE_Y
        
        def elevation_to_y(elevation):
            """将高程转换为局部Y坐标"""
            return small['max_y'] - (ELEVATION_REF - elevation) / SCALE_Y
        
        # 脊梁点真实世界坐标（桩号位置即为脊梁点）
        # 用户确认：脊梁点在重叠竖线和小矩形上长边的交点，上长边对应0米高程
        spine_world_x = station_x
        spine_world_y = station_y
        spine_world_z = y_to_elevation(small['max_y'])  # 上长边对应ELEVATION_REF=0米
        
        # 计算切向角度和断面方向角度（参考内湾逻辑）
        tangent_angle = math.atan2(spine_dy, spine_dx)
        cross_angle = tangent_angle + math.pi / 2  # 断面方向垂直于脊梁线
        cos_a = math.cos(cross_angle)
        sin_a = math.sin(cross_angle)
        
        print(f"  桩号{format_station(station)}: 脊梁点({spine_world_x:.2f}, {spine_world_y:.2f}, {spine_world_z:.2f}), 切向角度={math.degrees(tangent_angle):.2f}°")
        
        # 开挖线坐标转换
        if p['excav_left'] and p['excav_right']:
            left_line = p['excav_left'][0]
            right_line = p['excav_right'][0]
            
            # 计算相对于中心线的X偏移（修复：与内湾extract_xyz_from_dxf.py一致）
            # 内湾公式：dx_cad = l1_x - current_x（第847行）
            # 即：中心线坐标 - 当前点坐标，这样左侧点dx>0，右侧点dx<0
            left_top_dx_cad = center_line_x - left_line['top_x'] if center_line_x else 0
            left_bottom_dx_cad = center_line_x - left_line['bottom_x'] if center_line_x else 0
            right_top_dx_cad = center_line_x - right_line['top_x'] if center_line_x else 0
            right_bottom_dx_cad = center_line_x - right_line['bottom_x'] if center_line_x else 0
            
            # 转换为真实世界坐标偏移（乘以比例尺）
            left_top_dx_scaled = left_top_dx_cad * SCALE_X
            left_bottom_dx_scaled = left_bottom_dx_cad * SCALE_X
            right_top_dx_scaled = right_top_dx_cad * SCALE_X
            right_bottom_dx_scaled = right_bottom_dx_cad * SCALE_X
            
            # 转换高程
            left_top_z = y_to_elevation(left_line['top_y'])
            left_bottom_z = y_to_elevation(left_line['bottom_y'])
            right_top_z = y_to_elevation(right_line['top_y'])
            right_bottom_z = y_to_elevation(right_line['bottom_y'])
            
            # 计算世界坐标（参考内湾逻辑：eng_x = spine_x + dx_scaled * cos_a）
            left_top_x = spine_world_x + left_top_dx_scaled * cos_a
            left_top_y = spine_world_y + left_top_dx_scaled * sin_a
            left_bottom_x = spine_world_x + left_bottom_dx_scaled * cos_a
            left_bottom_y = spine_world_y + left_bottom_dx_scaled * sin_a
            
            right_top_x = spine_world_x + right_top_dx_scaled * cos_a
            right_top_y = spine_world_y + right_top_dx_scaled * sin_a
            right_bottom_x = spine_world_x + right_bottom_dx_scaled * cos_a
            right_bottom_y = spine_world_y + right_bottom_dx_scaled * sin_a
            
            # 延长至目标高程（-24m）
            # 延长后的点应该作为新的底部点
            left_ext_x, left_ext_z = extend_line_to_elevation(
                left_top_x, left_top_z,
                left_bottom_x, left_bottom_z,
                TARGET_ELEVATION
            )
            
            right_ext_x, right_ext_z = extend_line_to_elevation(
                right_top_x, right_top_z,
                right_bottom_x, right_bottom_z,
                TARGET_ELEVATION
            )
            
            excav_xyz.append({
                'station': station,
                'station_text': format_station(station),
                'spine_world': {
                    'x': spine_world_x,
                    'y': spine_world_y,
                    'z': spine_world_z
                },
                'direction': {
                    'cos_a': cos_a,
                    'sin_a': sin_a
                },
                'left_top': {
                    'x': left_top_x,
                    'y': left_top_y,
                    'z': left_top_z
                },
                'left_bottom': {
                    'x': left_ext_x if left_ext_x is not None else left_bottom_x,
                    'y': left_bottom_y,
                    'z': left_ext_z if left_ext_z is not None else left_bottom_z
                },
                'right_top': {
                    'x': right_top_x,
                    'y': right_top_y,
                    'z': right_top_z
                },
                'right_bottom': {
                    'x': right_ext_x if right_ext_x is not None else right_bottom_x,
                    'y': right_bottom_y,
                    'z': right_ext_z if right_ext_z is not None else right_bottom_z
                },
                'original_left_top': {
                    'x': left_top_x,
                    'y': left_top_y,
                    'z': left_top_z
                },
                'original_right_top': {
                    'x': right_top_x,
                    'y': right_top_y,
                    'z': right_top_z
                }
            })
        
        # 超挖线坐标转换
        if p['overbreak_left'] and p['overbreak_right']:
            left_line = p['overbreak_left'][0]
            right_line = p['overbreak_right'][0]
            
            # 计算相对于中心线的X偏移（修复：与内湾extract_xyz_from_dxf.py一致）
            # 内湾公式：dx_cad = l1_x - current_x（第847行）
            left_top_dx_cad = center_line_x - left_line['top_x'] if center_line_x else 0
            left_bottom_dx_cad = center_line_x - left_line['bottom_x'] if center_line_x else 0
            right_top_dx_cad = center_line_x - right_line['top_x'] if center_line_x else 0
            right_bottom_dx_cad = center_line_x - right_line['bottom_x'] if center_line_x else 0
            
            # 转换为真实世界坐标偏移
            left_top_dx_scaled = left_top_dx_cad * SCALE_X
            left_bottom_dx_scaled = left_bottom_dx_cad * SCALE_X
            right_top_dx_scaled = right_top_dx_cad * SCALE_X
            right_bottom_dx_scaled = right_bottom_dx_cad * SCALE_X
            
            left_top_z = y_to_elevation(left_line['top_y'])
            left_bottom_z = y_to_elevation(left_line['bottom_y'])
            right_top_z = y_to_elevation(right_line['top_y'])
            right_bottom_z = y_to_elevation(right_line['bottom_y'])
            
            # 计算世界坐标（参考内湾逻辑）
            left_top_x = spine_world_x + left_top_dx_scaled * cos_a
            left_top_y = spine_world_y + left_top_dx_scaled * sin_a
            left_bottom_x = spine_world_x + left_bottom_dx_scaled * cos_a
            left_bottom_y = spine_world_y + left_bottom_dx_scaled * sin_a
            
            right_top_x = spine_world_x + right_top_dx_scaled * cos_a
            right_top_y = spine_world_y + right_top_dx_scaled * sin_a
            right_bottom_x = spine_world_x + right_bottom_dx_scaled * cos_a
            right_bottom_y = spine_world_y + right_bottom_dx_scaled * sin_a
            
            # 延长至目标高程（-24m）
            # 延长后的点应该作为新的底部点
            left_ext_x, left_ext_z = extend_line_to_elevation(
                left_top_x, left_top_z,
                left_bottom_x, left_bottom_z,
                TARGET_ELEVATION
            )
            
            right_ext_x, right_ext_z = extend_line_to_elevation(
                right_top_x, right_top_z,
                right_bottom_x, right_bottom_z,
                TARGET_ELEVATION
            )
            
            overbreak_xyz.append({
                'station': station,
                'station_text': format_station(station),
                'spine_world': {
                    'x': spine_world_x,
                    'y': spine_world_y,
                    'z': spine_world_z
                },
                'direction': {
                    'cos_a': cos_a,
                    'sin_a': sin_a
                },
                'left_top': {
                    'x': left_top_x,
                    'y': left_top_y,
                    'z': left_top_z
                },
                'left_bottom': {
                    'x': left_ext_x if left_ext_x is not None else left_bottom_x,
                    'y': left_bottom_y,
                    'z': left_ext_z if left_ext_z is not None else left_bottom_z
                },
                'right_top': {
                    'x': right_top_x,
                    'y': right_top_y,
                    'z': right_top_z
                },
                'right_bottom': {
                    'x': right_ext_x if right_ext_x is not None else right_bottom_x,
                    'y': right_bottom_y,
                    'z': right_ext_z if right_ext_z is not None else right_bottom_z
                },
                'original_left_top': {
                    'x': left_top_x,
                    'y': left_top_y,
                    'z': left_top_z
                },
                'original_right_top': {
                    'x': right_top_x,
                    'y': right_top_y,
                    'z': right_top_z
                }
            })
    
    print(f"  开挖线XYZ: {len(excav_xyz)}组")
    print(f"  超挖线XYZ: {len(overbreak_xyz)}组")
    
    return excav_xyz, overbreak_xyz


def interpolate_line_points_3d(x1, y1, z1, x2, y2, z2, interval):
    """在两点之间按指定间隔插值生成点（三维坐标）
    
    参数:
        x1, y1, z1: 第一个点的坐标
        x2, y2, z2: 第二个点的坐标
        interval: 插值间隔（米）
    
    返回:
        插值点列表 [(x, y, z), ...]
    """
    points = []
    
    # 计算两点之间的距离（三维）
    dx = x2 - x1
    dy = y2 - y1
    dz = z2 - z1
    length = math.sqrt(dx**2 + dy**2 + dz**2)
    
    if length < 0.001:
        return [(x1, y1, z1)]
    
    # 计算需要插值的点数
    num_points = int(length / interval) + 1
    
    for i in range(num_points):
        t = i / (num_points - 1) if num_points > 1 else 0
        x = x1 + t * dx
        y = y1 + t * dy
        z = z1 + t * dz
        points.append((x, y, z))
    
    return points


def generate_interpolated_xyz(excav_xyz, overbreak_xyz, interval=INTERVAL_X):
    """按水平间隔生成插值后的XYZ点
    
    参数:
        excav_xyz: 开挖线XYZ数据
        overbreak_xyz: 超挖线XYZ数据
        interval: 水平插值间隔（米）
    
    返回:
        excav_points: 开挖线插值点列表 [{'x', 'y', 'z', 'side', 'station'}, ...]
        overbreak_points: 超挖线插值点列表
    """
    excav_points = []
    overbreak_points = []
    
    for e in excav_xyz:
        station = e['station']
        station_text = e['station_text']
        
        # 左侧线：从顶到底插值（使用三维坐标）
        left_points = interpolate_line_points_3d(
            e['left_top']['x'], e['left_top']['y'], e['left_top']['z'],
            e['left_bottom']['x'], e['left_bottom']['y'], e['left_bottom']['z'],
            interval
        )
        
        for x, y, z in left_points:
            excav_points.append({
                'x': x,
                'y': y,
                'z': z,
                'side': 'left',
                'station': station,
                'station_text': station_text
            })
        
        # 右侧线：从顶到底插值（使用三维坐标）
        right_points = interpolate_line_points_3d(
            e['right_top']['x'], e['right_top']['y'], e['right_top']['z'],
            e['right_bottom']['x'], e['right_bottom']['y'], e['right_bottom']['z'],
            interval
        )
        
        for x, y, z in right_points:
            excav_points.append({
                'x': x,
                'y': y,
                'z': z,
                'side': 'right',
                'station': station,
                'station_text': station_text
            })
        
        # 底边插值：连接左右底端点（使用三维坐标）
        bottom_points = interpolate_line_points_3d(
            e['left_bottom']['x'], e['left_bottom']['y'], e['left_bottom']['z'],
            e['right_bottom']['x'], e['right_bottom']['y'], e['right_bottom']['z'],
            interval
        )
        
        for x, y, z in bottom_points:
            excav_points.append({
                'x': x,
                'y': y,
                'z': z,
                'side': 'bottom',
                'station': station,
                'station_text': station_text
            })
    
    for e in overbreak_xyz:
        station = e['station']
        station_text = e['station_text']
        
        # 左侧线插值（使用三维坐标）
        left_points = interpolate_line_points_3d(
            e['left_top']['x'], e['left_top']['y'], e['left_top']['z'],
            e['left_bottom']['x'], e['left_bottom']['y'], e['left_bottom']['z'],
            interval
        )
        
        for x, y, z in left_points:
            overbreak_points.append({
                'x': x,
                'y': y,
                'z': z,
                'side': 'left',
                'station': station,
                'station_text': station_text
            })
        
        # 右侧线插值（使用三维坐标）
        right_points = interpolate_line_points_3d(
            e['right_top']['x'], e['right_top']['y'], e['right_top']['z'],
            e['right_bottom']['x'], e['right_bottom']['y'], e['right_bottom']['z'],
            interval
        )
        
        for x, y, z in right_points:
            overbreak_points.append({
                'x': x,
                'y': y,
                'z': z,
                'side': 'right',
                'station': station,
                'station_text': station_text
            })
        
        # 底边插值（使用三维坐标）
        bottom_points = interpolate_line_points_3d(
            e['left_bottom']['x'], e['left_bottom']['y'], e['left_bottom']['z'],
            e['right_bottom']['x'], e['right_bottom']['y'], e['right_bottom']['z'],
            interval
        )
        
        for x, y, z in bottom_points:
            overbreak_points.append({
                'x': x,
                'y': y,
                'z': z,
                'side': 'bottom',
                'station': station,
                'station_text': station_text
            })
    
    return excav_points, overbreak_points
def write_xyz_file(points, output_path, layer_type):
    """将XYZ数据写入文件（与内湾格式一致）
    
    格式: X Y Z（空格分隔，Z取负值表示深度）
    过滤: 水面以上点(z >= 0)和高程异常点(z < -30)
    
    Args:
        points: 点列表 [{'x', 'y', 'z', 'station_text', 'side'}, ...]
        output_path: 输出文件路径
        layer_type: 线类型 ('开挖线' 或 '超挖线')
    """
    total_points = 0
    skipped_above_water = 0
    skipped_abnormal = 0
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for p in points:
            z = p['z']
            
            # 过滤水面以上点（z >= 0）
            if z >= 0:
                skipped_above_water += 1
                continue
            
            # 过滤高程异常点（z < -30）
            if z < -30:
                skipped_abnormal += 1
                continue
            
            # Z取负值表示深度（与内湾格式一致）
            f.write(f"{p['x']:.6f} {p['y']:.6f} {-z:.6f}\n")
            total_points += 1
    
    print(f"\n{layer_type}XYZ文件已保存: {output_path}")
    print(f"  总点数: {total_points}")
    print(f"  已删除水面以上点数: {skipped_above_water}")
    print(f"  已删除高程异常点数: {skipped_abnormal}")
    
    return total_points, skipped_above_water, skipped_abnormal


def save_xyz_files(excav_xyz, overbreak_xyz, output_dir, interval=INTERVAL_X):
    """保存XYZ坐标文件（与内湾格式一致）
    
    说明:
    - 垂直比例尺: 1单位 = 10米
    - 小框上长边对应高程-12米
    - 开挖线和超挖线已延长至0米高程
    - 水平插值间隔: 4米
    - 输出格式: X Y Z（空格分隔，Z取负值表示深度）
    """
    print(f"\n[保存文件]")
    print(f"  水平插值间隔: {interval}米")
    
    # 生成插值点
    excav_points, overbreak_points = generate_interpolated_xyz(excav_xyz, overbreak_xyz, interval)
    
    print(f"  开挖线插值点: {len(excav_points)}个")
    print(f"  超挖线插值点: {len(overbreak_points)}个")
    
    # 保存开挖线XYZ（与内湾格式一致）
    excav_path = os.path.join(output_dir, '外海_开挖线_xyz.txt')
    excav_total, excav_water, excav_abnormal = write_xyz_file(excav_points, excav_path, '开挖线')
    
    # 保存超挖线XYZ（与内湾格式一致）
    overbreak_path = os.path.join(output_dir, '外海_超挖线_xyz.txt')
    overbreak_total, overbreak_water, overbreak_abnormal = write_xyz_file(overbreak_points, overbreak_path, '超挖线')
    
    # 保存中心线位置文件（与内湾格式一致）
    centerline_path = os.path.join(output_dir, '外海_中心线位置.txt')
    with open(centerline_path, 'w', encoding='utf-8') as f:
        f.write("# 外海中心线位置数据\n")
        f.write("# 格式: 断面序号 桩号 spine_x spine_y z\n\n")
        
        for idx, e in enumerate(excav_xyz, 1):
            # 使用脊梁点世界坐标（修复：之前错误地使用了left_top坐标）
            spine_x = e['spine_world']['x']
            spine_y = e['spine_world']['y']
            z = e['spine_world']['z']
            f.write(f"{idx} {e['station_text']} {spine_x:.6f} {spine_y:.6f} {-z:.6f}\n")
    
    print(f"\n中心线文件已保存: {centerline_path}")
    
    # 保存JSON格式（包含完整数据）
    json_path = os.path.join(output_dir, '外海_断面XYZ数据.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'scale_x': SCALE_X,
            'scale_y': SCALE_Y,
            'elevation_ref': ELEVATION_REF,
            'target_elevation': TARGET_ELEVATION,
            'interval_x': interval,
            'sections': [
                {
                    'section_index': idx,
                    'station': e['station_text'],
                    'kaiwa_xyz': [
                        [p['x'], p['y'], -p['z']]
                        for p in excav_points
                        if p['station'] == e['station'] and p['z'] < 0 and p['z'] >= -20
                    ],
                    'chaowa_xyz': [
                        [p['x'], p['y'], -p['z']]
                        for p in overbreak_points
                        if p['station'] == e['station'] and p['z'] < 0 and p['z'] >= -20
                    ],
                    'spine_x': e['left_top']['x'],
                    'spine_y': e['left_top']['y'],
                    'l1_y': e['left_top']['z']
                }
                for idx, e in enumerate(excav_xyz, 1)
            ],
            'excav_xyz': excav_xyz,
            'overbreak_xyz': overbreak_xyz,
            'excav_points': excav_points,
            'overbreak_points': overbreak_points,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\nJSON文件已保存: {json_path}")
    
    # 统计
    total_kaiwa = excav_total
    total_chaowa = overbreak_total
    
    print(f"\n总开挖线点数: {total_kaiwa}")
    print(f"总超挖线点数: {total_chaowa}")
    
    return excav_points, overbreak_points


def main():
    """主函数"""
    section_path = r'D:\断面算量平台\测试文件\外海断面图完整.dxf'
    background_path = r'D:\断面算量平台\测试文件\外海背景.dxf'
    output_dir = r'D:\断面算量平台\测试文件'
    
    print(f"\n{'='*60}")
    print(f"[外海断面图XYZ坐标提取 v2]")
    print(f"{'='*60}")
    print(f"  水平比例尺: 1单位 = {SCALE_X}米")
    print(f"  垂直比例尺: 1单位 = {SCALE_Y}米")
    print(f"  小框上长边高程基准: {ELEVATION_REF}米")
    print(f"  延长目标高程: {TARGET_ELEVATION}米")
    print(f"  水平插值间隔: {INTERVAL_X}米")
    
    # 1. 加载背景底图桩号位置
    station_positions = load_background_stations(background_path)
    
    # 2. 检测断面图开挖线和超挖线
    section_doc = ezdxf.readfile(section_path)
    section_msp = section_doc.modelspace()
    section_data = detect_section_data(section_msp)
    
    # 3. 坐标转换
    excav_xyz, overbreak_xyz = convert_to_world_coords(section_data, station_positions)
    
    # 4. 保存XYZ文件（含插值）
    excav_points, overbreak_points = save_xyz_files(excav_xyz, overbreak_xyz, output_dir)
    
    # 5. 输出总结
    print(f"\n{'='*60}")
    print(f"[完成]")
    print(f"{'='*60}")
    print(f"  断面框: {len(section_data['frame_pairs'])}组")
    print(f"  开挖线端点: {len(excav_xyz)}组")
    print(f"  开挖线插值点: {len(excav_points)}个")
    print(f"  超挖线端点: {len(overbreak_xyz)}组")
    print(f"  超挖线插值点: {len(overbreak_points)}个")


if __name__ == '__main__':
    main()