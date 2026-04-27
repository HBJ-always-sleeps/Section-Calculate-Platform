# -*- coding: utf-8 -*-
"""
外海断面图XYZ坐标提取脚本
结合外海背景.dxf获取真实世界坐标

流程：
1. 从外海断面图.dxf检测开挖线和超挖线
2. 从外海背景.dxf获取桩号的真实世界坐标
3. 将断面图的局部坐标转换为真实世界坐标
4. 输出XYZ坐标文件
"""

import ezdxf
import os
import math
import re
import json
from datetime import datetime
from collections import defaultdict


def get_bbox(pts):
    """计算边界框"""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def parse_station(text):
    """解析桩号格式：00+000.TIN"""
    match = re.search(r'(\d+)\+(\d+)\.TIN', text.upper())
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
    """从外海背景.dxf加载桩号位置"""
    print(f"\n[加载背景底图桩号]")
    print(f"  文件: {background_path}")
    
    doc = ezdxf.readfile(background_path)
    msp = doc.modelspace()
    
    # 获取桩号文本和位置
    station_positions = {}
    for e in msp.query('TEXT[layer=="MARTERS测线"]'):
        try:
            text = e.dxf.text
            station_value = parse_background_station(text)
            if station_value is not None:
                station_positions[station_value] = {
                    'text': text,
                    'x': e.dxf.insert.x,
                    'y': e.dxf.insert.y
                }
        except:
            pass
    
    print(f"  加载桩号: {len(station_positions)}个")
    
    # 显示桩号范围
    if station_positions:
        min_station = min(station_positions.keys())
        max_station = max(station_positions.keys())
        print(f"  桩号范围: {format_station(min_station)} 到 {format_station(max_station)}")
    
    return station_positions


def detect_excavation_lines(msp):
    """检测开挖线和超挖线"""
    print(f"\n[检测开挖线和超挖线]")
    
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
    
    # 区分大框和小框
    big_frames = [f for f in all_frames if f['width'] > 3.3]
    small_frames = [f for f in all_frames if f['width'] < 3.3]
    
    print(f"  大框数量: {len(big_frames)}")
    print(f"  小框数量: {len(small_frames)}")
    
    # 2. 检测斜线（2顶点多段线）
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
                    line_type = 'excav' if length < 0.85 else 'overbreak'
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
    
    # 3. 检测桩号文本
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
    
    # 4. 匹配大框与小框
    frame_pairs = []
    for big in big_frames:
        inside_small = [s for s in small_frames if is_frame_inside(big, s)]
        if inside_small:
            inside_small.sort(key=lambda s: abs(s['center_y'] - big['center_y']))
            small = inside_small[0]
            frame_pairs.append({
                'big_frame': big,
                'small_frame': small,
                'center_x': (big['center_x'] + small['center_x']) / 2
            })
    
    print(f"  大小框配对: {len(frame_pairs)}组")
    
    # 按中心X排序
    frame_pairs.sort(key=lambda p: p['center_x'])
    for i, p in enumerate(frame_pairs):
        p['index'] = i + 1
    
    # 5. 匹配小框内的斜线
    for p in frame_pairs:
        small = p['small_frame']
        
        inside_diagonals = [d for d in diagonal_lines 
                           if small['min_x'] <= d['center_x'] <= small['max_x']
                           and small['min_y'] <= d['center_y'] <= small['max_y']]
        
        p['excav_left'] = [d for d in inside_diagonals if d['line_type'] == 'excav' and d['side'] == 'left']
        p['excav_right'] = [d for d in inside_diagonals if d['line_type'] == 'excav' and d['side'] == 'right']
        p['overbreak_left'] = [d for d in inside_diagonals if d['line_type'] == 'overbreak' and d['side'] == 'left']
        p['overbreak_right'] = [d for d in inside_diagonals if d['line_type'] == 'overbreak' and d['side'] == 'right']
        
        if p['excav_left'] and p['excav_right']:
            p['excav_bottom_y'] = min(d['bottom_y'] for d in p['excav_left'] + p['excav_right'])
            left_bottom_x = p['excav_left'][0]['bottom_x']
            right_bottom_x = p['excav_right'][0]['bottom_x']
            p['excav_bottom_width'] = abs(right_bottom_x - left_bottom_x)
        else:
            p['excav_bottom_y'] = None
            p['excav_bottom_width'] = None
        
        if p['overbreak_left'] and p['overbreak_right']:
            p['overbreak_bottom_y'] = min(d['bottom_y'] for d in p['overbreak_left'] + p['overbreak_right'])
            left_bottom_x = p['overbreak_left'][0]['bottom_x']
            right_bottom_x = p['overbreak_right'][0]['bottom_x']
            p['overbreak_bottom_width'] = abs(right_bottom_x - left_bottom_x)
        else:
            p['overbreak_bottom_y'] = None
            p['overbreak_bottom_width'] = None
    
    # 6. 匹配桩号
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
        'excav_lines': excav_lines,
        'overbreak_lines': overbreak_lines
    }


def convert_to_world_coords(section_data, station_positions):
    """将断面图坐标转换为真实世界坐标"""
    print(f"\n[坐标转换]")
    
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
        
        small_frame = p['small_frame']
        frame_center_x = small_frame['center_x']
        
        # 开挖线坐标转换
        if p['excav_left'] and p['excav_right']:
            left_line = p['excav_left'][0]
            right_line = p['excav_right'][0]
            
            # 水平偏移 = 断面图X - 断面框中心X
            left_offset_top = left_line['top_x'] - frame_center_x
            left_offset_bottom = left_line['bottom_x'] - frame_center_x
            right_offset_top = right_line['top_x'] - frame_center_x
            right_offset_bottom = right_line['bottom_x'] - frame_center_x
            
            excav_xyz.append({
                'station': station,
                'station_text': format_station(station),
                'left_top': {
                    'x': station_x + left_offset_top,
                    'y': station_y,
                    'z': -left_line['top_y']  # 高程（断面图Y坐标，负值表示水下）
                },
                'left_bottom': {
                    'x': station_x + left_offset_bottom,
                    'y': station_y,
                    'z': -left_line['bottom_y']
                },
                'right_top': {
                    'x': station_x + right_offset_top,
                    'y': station_y,
                    'z': -right_line['top_y']
                },
                'right_bottom': {
                    'x': station_x + right_offset_bottom,
                    'y': station_y,
                    'z': -right_line['bottom_y']
                }
            })
        
        # 超挖线坐标转换
        if p['overbreak_left'] and p['overbreak_right']:
            left_line = p['overbreak_left'][0]
            right_line = p['overbreak_right'][0]
            
            left_offset_top = left_line['top_x'] - frame_center_x
            left_offset_bottom = left_line['bottom_x'] - frame_center_x
            right_offset_top = right_line['top_x'] - frame_center_x
            right_offset_bottom = right_line['bottom_x'] - frame_center_x
            
            overbreak_xyz.append({
                'station': station,
                'station_text': format_station(station),
                'left_top': {
                    'x': station_x + left_offset_top,
                    'y': station_y,
                    'z': -left_line['top_y']
                },
                'left_bottom': {
                    'x': station_x + left_offset_bottom,
                    'y': station_y,
                    'z': -left_line['bottom_y']
                },
                'right_top': {
                    'x': station_x + right_offset_top,
                    'y': station_y,
                    'z': -right_line['top_y']
                },
                'right_bottom': {
                    'x': station_x + right_offset_bottom,
                    'y': station_y,
                    'z': -right_line['bottom_y']
                }
            })
    
    print(f"  开挖线XYZ: {len(excav_xyz)}组")
    print(f"  超挖线XYZ: {len(overbreak_xyz)}组")
    
    return excav_xyz, overbreak_xyz


def save_xyz_files(excav_xyz, overbreak_xyz, output_dir):
    """保存XYZ坐标文件"""
    print(f"\n[保存文件]")
    
    # 保存开挖线XYZ
    excav_path = os.path.join(output_dir, '外海_开挖线_xyz.txt')
    with open(excav_path, 'w', encoding='utf-8') as f:
        f.write("# 外海开挖线XYZ坐标\n")
        f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("# 格式: 桩号, 左顶X, 左顶Y, 左顶Z, 左底X, 左底Y, 左底Z, 右顶X, 右顶Y, 右顶Z, 右底X, 右底Y, 右底Z\n")
        
        for e in excav_xyz:
            f.write(f"{e['station_text']}, ")
            f.write(f"{e['left_top']['x']:.2f}, {e['left_top']['y']:.2f}, {e['left_top']['z']:.2f}, ")
            f.write(f"{e['left_bottom']['x']:.2f}, {e['left_bottom']['y']:.2f}, {e['left_bottom']['z']:.2f}, ")
            f.write(f"{e['right_top']['x']:.2f}, {e['right_top']['y']:.2f}, {e['right_top']['z']:.2f}, ")
            f.write(f"{e['right_bottom']['x']:.2f}, {e['right_bottom']['y']:.2f}, {e['right_bottom']['z']:.2f}\n")
    
    print(f"  开挖线XYZ: {excav_path}")
    
    # 保存超挖线XYZ
    overbreak_path = os.path.join(output_dir, '外海_超挖线_xyz.txt')
    with open(overbreak_path, 'w', encoding='utf-8') as f:
        f.write("# 外海超挖线XYZ坐标\n")
        f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("# 格式: 桩号, 左顶X, 左顶Y, 左顶Z, 左底X, 左底Y, 左底Z, 右顶X, 右顶Y, 右顶Z, 右底X, 右底Y, 右底Z\n")
        
        for e in overbreak_xyz:
            f.write(f"{e['station_text']}, ")
            f.write(f"{e['left_top']['x']:.2f}, {e['left_top']['y']:.2f}, {e['left_top']['z']:.2f}, ")
            f.write(f"{e['left_bottom']['x']:.2f}, {e['left_bottom']['y']:.2f}, {e['left_bottom']['z']:.2f}, ")
            f.write(f"{e['right_top']['x']:.2f}, {e['right_top']['y']:.2f}, {e['right_top']['z']:.2f}, ")
            f.write(f"{e['right_bottom']['x']:.2f}, {e['right_bottom']['y']:.2f}, {e['right_bottom']['z']:.2f}\n")
    
    print(f"  超挖线XYZ: {overbreak_path}")
    
    # 保存JSON格式
    json_path = os.path.join(output_dir, '外海_断面XYZ数据.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'excav_xyz': excav_xyz,
            'overbreak_xyz': overbreak_xyz,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }, f, ensure_ascii=False, indent=2)
    
    print(f"  JSON数据: {json_path}")


def main():
    """主函数"""
    # 文件路径
    section_path = r'D:\断面算量平台\测试文件\外海断面图.dxf'
    background_path = r'D:\断面算量平台\测试文件\外海背景.dxf'
    output_dir = r'D:\断面算量平台\测试文件'
    
    print(f"\n{'='*60}")
    print(f"[外海断面图XYZ坐标提取]")
    print(f"{'='*60}")
    
    # 1. 加载背景底图桩号位置
    station_positions = load_background_stations(background_path)
    
    # 2. 检测断面图开挖线和超挖线
    section_doc = ezdxf.readfile(section_path)
    section_msp = section_doc.modelspace()
    section_data = detect_excavation_lines(section_msp)
    
    # 3. 坐标转换
    excav_xyz, overbreak_xyz = convert_to_world_coords(section_data, station_positions)
    
    # 4. 保存XYZ文件
    save_xyz_files(excav_xyz, overbreak_xyz, output_dir)
    
    # 5. 输出总结
    print(f"\n{'='*60}")
    print(f"[完成]")
    print(f"{'='*60}")
    print(f"  断面框: {len(section_data['frame_pairs'])}组")
    print(f"  开挖线XYZ: {len(excav_xyz)}组")
    print(f"  超挖线XYZ: {len(overbreak_xyz)}组")


if __name__ == '__main__':
    main()