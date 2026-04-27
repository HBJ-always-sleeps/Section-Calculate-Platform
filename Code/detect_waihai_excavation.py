# -*- coding: utf-8 -*-
"""
外海断面图检测脚本 - 检测完整的开挖线和超挖线
结构：
- 大框包含小框
- 小框内有4条斜线：2条开挖线（短），2条超挖线（长）
- 正向（63.4°）=右侧坡，反向（-63.4°）=左侧坡
- 开挖底边连接开挖线底点，超挖底边连接超挖线底点
"""

import ezdxf
import os
import math
import re
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


def detect_excavation_lines(msp):
    """检测开挖线和超挖线"""
    print("\n[检测开挖线和超挖线]")
    
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
    big_frames = [f for f in all_frames if f['width'] > 3.3]  # 大框宽~3.54
    small_frames = [f for f in all_frames if f['width'] < 3.3]  # 小框宽~3.21
    
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
                    # 区分开挖线（短）和超挖线（长）
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
    
    # 3. 检测水平线（底边）
    horizontal_lines = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) == 2:
                x1, y1 = pts[0]
                x2, y2 = pts[1]
                length = math.sqrt((x2-x1)**2 + (y2-y1)**2)
                angle = math.degrees(math.atan2(y2-y1, x2-x1))
                
                # 水平线判断
                if abs(angle) < 5 or abs(angle) > 175:
                    horizontal_lines.append({
                        'entity': e,
                        'pts': pts,
                        'length': length,
                        'y': (y1+y2)/2,
                        'x1': min(x1, x2),
                        'x2': max(x1, x2),
                        'center_x': (x1+x2)/2
                    })
        except:
            pass
    
    print(f"  水平线数量: {len(horizontal_lines)}")
    
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
    
    # 按桩号值分组
    station_values = defaultdict(list)
    for s in station_texts:
        station_values[s['value']].append(s)
    
    print(f"  不同桩号值: {len(station_values)}")
    
    # 5. 匹配大框与小框
    print("\n[匹配大框与小框]")
    frame_pairs = []
    for big in big_frames:
        # 找被大框包含的小框
        inside_small = [s for s in small_frames if is_frame_inside(big, s)]
        
        if inside_small:
            # 按中心Y排序，取最接近的
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
    
    # 6. 匹配小框内的斜线
    print("\n[匹配小框内的斜线]")
    
    for p in frame_pairs:
        small = p['small_frame']
        
        # 找小框内的斜线
        inside_diagonals = [d for d in diagonal_lines 
                           if small['min_x'] <= d['center_x'] <= small['max_x']
                           and small['min_y'] <= d['center_y'] <= small['max_y']]
        
        # 分类
        p['excav_left'] = [d for d in inside_diagonals if d['line_type'] == 'excav' and d['side'] == 'left']
        p['excav_right'] = [d for d in inside_diagonals if d['line_type'] == 'excav' and d['side'] == 'right']
        p['overbreak_left'] = [d for d in inside_diagonals if d['line_type'] == 'overbreak' and d['side'] == 'left']
        p['overbreak_right'] = [d for d in inside_diagonals if d['line_type'] == 'overbreak' and d['side'] == 'right']
        
        # 计算底边Y坐标
        if p['excav_left'] and p['excav_right']:
            p['excav_bottom_y'] = min(d['bottom_y'] for d in p['excav_left'] + p['excav_right'])
            # 计算底边宽度（两底点X距离）
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
    
    # 统计
    with_excav = [p for p in frame_pairs if p['excav_left'] and p['excav_right']]
    with_overbreak = [p for p in frame_pairs if p['overbreak_left'] and p['overbreak_right']]
    
    print(f"  有完整开挖线: {len(with_excav)}组")
    print(f"  有完整超挖线: {len(with_overbreak)}组")
    
    # 7. 匹配桩号
    print("\n[匹配桩号]")
    
    for p in frame_pairs:
        big = p['big_frame']
        
        # 找大框内的桩号文本
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
    
    # 8. 输出结果
    print("\n[检测结果详情]")
    
    print(f"\n  前10个断面:")
    for p in frame_pairs[:10]:
        station_str = format_station(p['station']) if p['station'] else "无桩号"
        excav_str = f"左{len(p['excav_left'])}右{len(p['excav_right'])}" if p['excav_left'] or p['excav_right'] else "无"
        overbreak_str = f"左{len(p['overbreak_left'])}右{len(p['overbreak_right'])}" if p['overbreak_left'] or p['overbreak_right'] else "无"
        
        excav_bottom_y_str = f"{p['excav_bottom_y']:.2f}" if p['excav_bottom_y'] else "N/A"
        excav_bottom_width_str = f"{p['excav_bottom_width']:.2f}" if p['excav_bottom_width'] else "N/A"
        overbreak_bottom_y_str = f"{p['overbreak_bottom_y']:.2f}" if p['overbreak_bottom_y'] else "N/A"
        overbreak_bottom_width_str = f"{p['overbreak_bottom_width']:.2f}" if p['overbreak_bottom_width'] else "N/A"
        
        print(f"    #{p['index']}: 桩号={station_str}")
        print(f"         开挖线: {excav_str}, 底边Y={excav_bottom_y_str}, 底边宽={excav_bottom_width_str}")
        print(f"         超挖线: {overbreak_str}, 底边Y={overbreak_bottom_y_str}, 底边宽={overbreak_bottom_width_str}")
        print(f"         小框中心: ({p['small_frame']['center_x']:.1f}, {p['small_frame']['center_y']:.1f})")
    
    # 9. 组合完整的开挖线和超挖线
    print("\n[组合完整的开挖线和超挖线]")
    
    complete_excav = []
    complete_overbreak = []
    
    for p in frame_pairs:
        if p['station'] is not None:
            # 开挖线组合
            if p['excav_left'] and p['excav_right']:
                excav_line = {
                    'station': p['station'],
                    'station_text': format_station(p['station']),
                    'left_line': p['excav_left'][0],
                    'right_line': p['excav_right'][0],
                    'bottom_y': p['excav_bottom_y'],
                    'bottom_width': p['excav_bottom_width'],
                    'small_frame': p['small_frame']
                }
                complete_excav.append(excav_line)
            
            # 超挖线组合
            if p['overbreak_left'] and p['overbreak_right']:
                overbreak_line = {
                    'station': p['station'],
                    'station_text': format_station(p['station']),
                    'left_line': p['overbreak_left'][0],
                    'right_line': p['overbreak_right'][0],
                    'bottom_y': p['overbreak_bottom_y'],
                    'bottom_width': p['overbreak_bottom_width'],
                    'small_frame': p['small_frame']
                }
                complete_overbreak.append(overbreak_line)
    
    print(f"  完整开挖线: {len(complete_excav)}组")
    print(f"  完整超挖线: {len(complete_overbreak)}组")
    
    # 按桩号分组
    excav_by_station = defaultdict(list)
    for e in complete_excav:
        excav_by_station[e['station']].append(e)
    
    overbreak_by_station = defaultdict(list)
    for o in complete_overbreak:
        overbreak_by_station[o['station']].append(o)
    
    print(f"\n  按桩号分组:")
    for station in sorted(excav_by_station.keys())[:10]:
        print(f"    {format_station(station)}: 开挖线{len(excav_by_station[station])}组, 超挖线{len(overbreak_by_station.get(station, []))}组")
    
    # 10. 输出总结
    print(f"\n{'='*60}")
    print(f"[总结]")
    print(f"{'='*60}")
    print(f"  大框: {len(big_frames)}")
    print(f"  小框: {len(small_frames)}")
    print(f"  大小框配对: {len(frame_pairs)}")
    print(f"  桩号值: {len(station_values)}")
    print(f"  完整开挖线: {len(complete_excav)}")
    print(f"  完整超挖线: {len(complete_overbreak)}")
    
    return {
        'big_frames': big_frames,
        'small_frames': small_frames,
        'frame_pairs': frame_pairs,
        'diagonal_lines': diagonal_lines,
        'horizontal_lines': horizontal_lines,
        'station_texts': station_texts,
        'station_values': dict(station_values),
        'complete_excav': complete_excav,
        'complete_overbreak': complete_overbreak,
        'excav_by_station': dict(excav_by_station),
        'overbreak_by_station': dict(overbreak_by_station)
    }


def main():
    """主函数"""
    test_file = r'D:\断面算量平台\测试文件\外海断面图.dxf'
    
    print(f"\n{'='*60}")
    print(f"[外海断面图开挖线和超挖线检测]")
    print(f"{'='*60}")
    print(f"文件: {test_file}")
    
    if not os.path.exists(test_file):
        print(f"文件不存在: {test_file}")
        return
    
    doc = ezdxf.readfile(test_file)
    msp = doc.modelspace()
    
    result = detect_excavation_lines(msp)
    
    # 输出桩号列表
    print(f"\n[桩号列表]")
    stations = sorted(result['station_values'].keys())
    print(f"  检测到的桩号: {len(stations)}个")
    for s in stations:
        print(f"    {format_station(s)}")


if __name__ == '__main__':
    main()