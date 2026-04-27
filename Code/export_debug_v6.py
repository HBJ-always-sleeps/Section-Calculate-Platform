# -*- coding: utf-8 -*-
"""使用正确的脊柱点重新生成DXF调试文件"""
import shutil
import math
import ezdxf
import re

# 比例尺定义
SCALE_X = 200.0  # 水平比例尺: 1单位 = 200米
SCALE_Y = 10.0   # 垂直比例尺: 1单位 = 10米
ELEVATION_REF = -12.0  # 小框上长边对应的高程基准（米）
TARGET_ELEVATION = 0.0  # 目标高程
INTERVAL_X = 4.0  # 水平插值间隔（米）

def parse_station(text):
    match = re.search(r'(\d+)\+(\d+)', text)
    if match:
        return int(match.group(1)) * 1000 + int(match.group(2))
    return None

def find_spine_positions_correct(background_path):
    """正确的脊柱点计算 - 使用正确的图层"""
    doc = ezdxf.readfile(background_path)
    msp = doc.modelspace()
    
    # 找到航道中心线图层（脊梁点所在位置）
    hangdao_layer = None
    for layer in doc.layers:
        name = layer.dxf.name
        if '航道' in name and '中心线' in name and '超深' not in name:
            hangdao_layer = name
            break
    
    # 获取航道中心线线段（包括LWPOLYLINE）
    center_lines = []
    for e in msp.query('LINE[layer=="{}"]'.format(hangdao_layer)):
        center_lines.append({'start': (e.dxf.start.x, e.dxf.start.y), 'end': (e.dxf.end.x, e.dxf.end.y)})
    for e in msp.query('LWPOLYLINE[layer=="{}"]'.format(hangdao_layer)):
        pts = [(p[0], p[1]) for p in e.get_points()]
        for i in range(len(pts) - 1):
            center_lines.append({'start': pts[i], 'end': pts[i+1]})
    
    # 获取测线线段
    survey_lines = []
    for e in msp.query('LWPOLYLINE[layer=="MARTERS测线"]'):
        pts = [(p[0], p[1]) for p in e.get_points()]
        for i in range(len(pts) - 1):
            survey_lines.append({'start': pts[i], 'end': pts[i+1]})
    
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
    
    survey_to_intersection = {}
    for si, survey in enumerate(survey_lines):
        for ci, center in enumerate(center_lines):
            pt = lines_intersect_pt(center, survey)
            if pt:
                if si not in survey_to_intersection:
                    survey_to_intersection[si] = pt
    
    station_positions = {}
    for e in msp.query('TEXT[layer=="MARTERS测线"]'):
        try:
            text = e.dxf.text
            station_value = parse_station(text)
            if station_value is not None:
                sx, sy = e.dxf.insert.x, e.dxf.insert.y
                
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
                
                if best_survey_idx is not None and best_survey_idx in survey_to_intersection:
                    spine_pt = survey_to_intersection[best_survey_idx]
                    station_positions[station_value] = {
                        'text': text,
                        'x': spine_pt[0],
                        'y': spine_pt[1]
                    }
        except:
            pass
    
    return station_positions

def calculate_spine_direction(station_positions, station):
    stations = sorted(station_positions.keys())
    idx = stations.index(station) if station in stations else -1
    if idx < 0:
        return (1.0, 0.0)
    
    if idx == 0:
        next_station = stations[idx+1] if idx+1 < len(stations) else station
        dx = station_positions[next_station][0] - station_positions[station][0]
        dy = station_positions[next_station][1] - station_positions[station][1]
    elif idx == len(stations)-1:
        prev_station = stations[idx-1]
        dx = station_positions[station][0] - station_positions[prev_station][0]
        dy = station_positions[station][1] - station_positions[prev_station][1]
    else:
        prev_station, next_station = stations[idx-1], stations[idx+1]
        dx = station_positions[next_station][0] - station_positions[prev_station][0]
        dy = station_positions[next_station][1] - station_positions[prev_station][1]
    
    length = math.sqrt(dx**2 + dy**2)
    if length > 0:
        dx /= length
        dy /= length
    return (dx, dy)

def convert_to_world(local_x, local_y, small, center_line_x, spine_pos, perp_dx, perp_dy):
    """断面局部坐标转世界坐标"""
    dx_local = local_x - center_line_x
    world_x = spine_pos[0] + dx_local * SCALE_X * perp_dx
    world_y = spine_pos[1] + dx_local * SCALE_X * perp_dy
    world_z = ELEVATION_REF - (small['max_y'] - local_y) * SCALE_Y
    return world_x, world_y, world_z

def extend_line_to_elevation(top_x, top_y, bottom_x, bottom_y, target_y):
    """将线延长到目标Y坐标"""
    dx = bottom_x - top_x
    dy = bottom_y - top_y
    if abs(dy) < 0.001:
        return None, None
    t = (target_y - top_y) / dy
    ext_x = top_x + t * dx
    return ext_x, target_y

def interpolate_points_along_line(x1, y1, x2, y2, interval):
    """沿线按间隔插值生成点（返回CAD单位坐标）"""
    points = []
    dx = x2 - x1
    dy = y2 - y1
    length = math.sqrt(dx**2 + dy**2)
    if length < 0.001:
        return [(x1, y1, 0)]
    
    ux = dx / length
    uy = dy / length
    num_points = int(length / interval) + 1
    
    for i in range(num_points):
        t = i * interval / length
        if t > 1.0:
            t = 1.0
        x = x1 + t * dx
        y = y1 + t * dy
        points.append((x, y, i * interval))
    
    return points

def main():
    background_dxf = r'D:\断面算量平台\测试文件\外海背景.dxf'
    section_dxf = r'D:\断面算量平台\测试文件\外海断面图.dxf'
    output_path = r'D:\断面算量平台\测试文件\外海_调试_转到世界坐标_v6.dxf'
    
    print("=" * 60)
    print("外海断面调试 - 使用正确脊柱点生成")
    print("=" * 60)
    
    # 1. 获取脊梁点
    print("\n[1] 加载脊梁点...")
    spine_positions = find_spine_positions_correct(background_dxf)
    print(f"    找到 {len(spine_positions)} 个脊梁点")
    
    # 验证18+300的脊柱点
    if 18300 in spine_positions:
        sp = spine_positions[18300]
        print(f"    18+300 脊柱点: ({sp['x']:.2f}, {sp['y']:.2f})")
    
    # 2. 复制背景图并创建图层
    print("\n[2] 准备输出...")
    shutil.copy(background_dxf, output_path)
    doc = ezdxf.readfile(output_path)
    msp = doc.modelspace()
    
    for layer_name, color in [('SPINE_PTS', 1), ('EXCAV_INTERP', 3), ('OVERBREAK_INTERP', 5), ('LABELS', 2)]:
        try:
            if layer_name not in doc.layers:
                doc.layers.add(layer_name, dxfattribs={'color': color})
        except:
            pass
    
    print(f"    输出文件: {output_path}")
    
    print("\n完成！请在CAD中打开 {} 检查脊柱点位置".format(output_path))

if __name__ == '__main__':
    main()