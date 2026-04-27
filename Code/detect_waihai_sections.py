# -*- coding: utf-8 -*-
"""
外海断面图检测脚本
检测断面框、桩号、斜线、断面曲线

发现：
- 86个断面框（5顶点多段线）
- 86条断面曲线（高顶点多段线>=200顶点）
- 172条斜线（每个断面2条，角度±63.4°）
- 43个桩号值（每个断面框对应一个桩号，重复4次）
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


def detect_sections(msp):
    """检测外海断面图的各个断面"""
    print("\n[检测断面]")
    
    # 1. 检测断面框（5顶点多段线）
    section_frames = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) == 5:
                bbox = get_bbox(pts)
                section_frames.append({
                    'entity': e,
                    'pts': pts,
                    'bbox': bbox,
                    'min_x': bbox[0],
                    'min_y': bbox[1],
                    'max_x': bbox[2],
                    'max_y': bbox[3],
                    'center_x': (bbox[0] + bbox[2]) / 2,
                    'center_y': (bbox[1] + bbox[3]) / 2
                })
        except:
            pass
    
    print(f"  断面框数量: {len(section_frames)}")
    
    # 按X坐标排序
    section_frames.sort(key=lambda f: f['center_x'])
    for i, f in enumerate(section_frames):
        f['index'] = i + 1
    
    # 2. 检测斜线（2顶点多段线，角度±63.4°）
    diagonal_lines = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) == 2:
                x1, y1 = pts[0]
                x2, y2 = pts[1]
                length = math.sqrt((x2-x1)**2 + (y2-y1)**2)
                angle = math.degrees(math.atan2(y2-y1, x2-x1))
                
                # 斜线判断：角度不在0°, 90°附近
                angle_normalized = abs(angle) % 180
                is_diagonal = not (angle_normalized < 5 or 85 < angle_normalized < 95)
                
                if is_diagonal:
                    diagonal_lines.append({
                        'entity': e,
                        'pts': pts,
                        'length': length,
                        'angle': angle,
                        'center_x': (x1+x2)/2,
                        'center_y': (y1+y2)/2,
                        'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2
                    })
        except:
            pass
    
    print(f"  斜线数量: {len(diagonal_lines)}")
    
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
    
    # 按桩号值分组
    station_values = defaultdict(list)
    for s in station_texts:
        station_values[s['value']].append(s)
    
    print(f"  不同桩号值: {len(station_values)}")
    
    # 4. 检测断面曲线（高顶点多段线>=200顶点）
    section_curves = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) >= 200:
                bbox = get_bbox(pts)
                section_curves.append({
                    'entity': e,
                    'pts': pts,
                    'bbox': bbox,
                    'min_x': bbox[0],
                    'min_y': bbox[1],
                    'max_x': bbox[2],
                    'max_y': bbox[3],
                    'center_x': (bbox[0] + bbox[2]) / 2,
                    'center_y': (bbox[1] + bbox[3]) / 2,
                    'vertex_count': len(pts)
                })
        except:
            pass
    
    print(f"  断面曲线数量: {len(section_curves)}")
    
    # 5. 匹配断面框与桩号
    print("\n[匹配断面框与桩号]")
    
    for f in section_frames:
        # 找断面框内的桩号文本
        inside_stations = []
        for s in station_texts:
            if (f['min_x'] <= s['x'] <= f['max_x'] and
                f['min_y'] <= s['y'] <= f['max_y']):
                inside_stations.append(s)
        
        if inside_stations:
            # 取第一个桩号
            f['station'] = inside_stations[0]['value']
            f['station_text'] = inside_stations[0]['text']
            f['station_count'] = len(inside_stations)
        else:
            f['station'] = None
            f['station_text'] = None
            f['station_count'] = 0
    
    with_station = [f for f in section_frames if f['station'] is not None]
    print(f"  有桩号的断面框: {len(with_station)}")
    
    # 6. 匹配断面框与斜线
    print("\n[匹配断面框与斜线]")
    
    for f in section_frames:
        # 找断面框内的斜线
        inside_diagonals = []
        for d in diagonal_lines:
            if (f['min_x'] <= d['center_x'] <= f['max_x'] and
                f['min_y'] <= d['center_y'] <= f['max_y']):
                inside_diagonals.append(d)
        
        f['diagonals'] = inside_diagonals
        f['diagonal_count'] = len(inside_diagonals)
    
    with_diagonal = [f for f in section_frames if f['diagonal_count'] > 0]
    print(f"  有斜线的断面框: {len(with_diagonal)}")
    
    # 统计斜线数量分布
    diagonal_counts = defaultdict(int)
    for f in section_frames:
        diagonal_counts[f['diagonal_count']] += 1
    
    print(f"  斜线数量分布:")
    for count, num in sorted(diagonal_counts.items()):
        print(f"    {count}条斜线: {num}个断面框")
    
    # 7. 匹配断面框与断面曲线
    print("\n[匹配断面框与断面曲线]")
    
    for f in section_frames:
        # 找断面框内的断面曲线
        inside_curves = []
        for c in section_curves:
            # 断面曲线中心在断面框内
            if (f['min_x'] <= c['center_x'] <= f['max_x'] and
                f['min_y'] <= c['center_y'] <= f['max_y']):
                inside_curves.append(c)
        
        f['curves'] = inside_curves
        f['curve_count'] = len(inside_curves)
    
    with_curve = [f for f in section_frames if f['curve_count'] > 0]
    print(f"  有断面曲线的断面框: {len(with_curve)}")
    
    # 8. 输出匹配结果
    print("\n[匹配结果详情]")
    
    print(f"\n  前10个断面:")
    for f in section_frames[:10]:
        station_str = f"{format_station(f['station'])}" if f['station'] else "无桩号"
        diagonal_str = f"{f['diagonal_count']}条" if f['diagonal_count'] > 0 else "无斜线"
        curve_str = f"{f['curve_count']}条({f['curves'][0]['vertex_count']}顶点)" if f['curve_count'] > 0 else "无曲线"
        
        print(f"    #{f['index']}: 桩号={station_str}, 斜线={diagonal_str}, 曲线={curve_str}")
        print(f"         中心=({f['center_x']:.1f}, {f['center_y']:.1f})")
        
        # 显示斜线详情
        if f['diagonals']:
            for d in f['diagonals']:
                print(f"         斜线: 角度={d['angle']:.1f}°, 长度={d['length']:.2f}")
    
    # 9. 统计完整匹配
    complete_matches = [f for f in section_frames if 
                        f['station'] is not None and 
                        f['diagonal_count'] > 0 and 
                        f['curve_count'] > 0]
    
    print(f"\n[完整匹配统计]")
    print(f"  完整匹配(桩号+斜线+曲线): {len(complete_matches)}个")
    print(f"  有桩号: {len(with_station)}个")
    print(f"  有斜线: {len(with_diagonal)}个")
    print(f"  有曲线: {len(with_curve)}个")
    
    return {
        'section_frames': section_frames,
        'diagonal_lines': diagonal_lines,
        'station_texts': station_texts,
        'station_values': dict(station_values),
        'section_curves': section_curves,
        'complete_matches': complete_matches
    }


def main():
    """主函数"""
    test_file = r'D:\断面算量平台\测试文件\外海断面图.dxf'
    
    print(f"\n{'='*60}")
    print(f"[外海断面图检测]")
    print(f"{'='*60}")
    print(f"文件: {test_file}")
    
    if not os.path.exists(test_file):
        print(f"文件不存在: {test_file}")
        return
    
    doc = ezdxf.readfile(test_file)
    msp = doc.modelspace()
    
    result = detect_sections(msp)
    
    # 输出桩号列表
    print(f"\n[桩号列表]")
    stations = sorted(set(f['station'] for f in result['section_frames'] if f['station']))
    print(f"  检测到的桩号: {len(stations)}个")
    for s in stations:
        print(f"    {format_station(s)}")
    
    print(f"\n{'='*60}")
    print(f"[完成]")
    print(f"{'='*60}")
    print(f"断面框: {len(result['section_frames'])}")
    print(f"斜线: {len(result['diagonal_lines'])}")
    print(f"桩号值: {len(result['station_values'])}")
    print(f"断面曲线: {len(result['section_curves'])}")
    print(f"完整匹配: {len(result['complete_matches'])}")


if __name__ == '__main__':
    main()