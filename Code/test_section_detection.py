# -*- coding: utf-8 -*-
"""
断面检测测试脚本
对比原始文件和面积比例0.6版本的断面检测结果
"""

import ezdxf
import os
import re
import math
from collections import defaultdict

def get_best_point(e):
    """获取文本实体的最佳点"""
    try:
        if e.dxftype() == 'TEXT':
            return (e.dxf.align_point.x, e.dxf.align_point.y) if (e.dxf.halign or e.dxf.valign) else (e.dxf.insert.x, e.dxf.insert.y)
        return (e.dxf.insert.x, e.dxf.insert.y)
    except:
        return (0, 0)

def get_text(e):
    """获取文本内容"""
    return e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text

def analyze_dxf(file_path):
    """分析DXF文件的基本信息"""
    print(f"\n{'='*60}")
    print(f"分析文件: {os.path.basename(file_path)}")
    print('='*60)
    
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return None
    
    doc = ezdxf.readfile(file_path)
    msp = doc.modelspace()
    
    # 1. 统计图层
    layers = [l.dxf.name for l in doc.layers]
    print(f"\n[图层统计] 总数: {len(layers)}")
    
    # 2. 统计实体类型
    entity_types = defaultdict(int)
    for e in msp:
        entity_types[e.dxftype()] += 1
    print(f"\n[实体类型统计]")
    for etype, count in sorted(entity_types.items(), key=lambda x: -x[1]):
        print(f"  {etype}: {count}")
    
    # 3. 获取所有文本
    all_texts = list(msp.query('TEXT MTEXT'))
    print(f"\n[文本统计] 总数: {len(all_texts)}")
    
    # 4. 分析文本内容 - 找桩号
    station_pattern = re.compile(r'(\d+\+\d+)')
    stations = []
    for t in all_texts:
        try:
            txt = get_text(t).strip()
            pt = get_best_point(t)
            match = station_pattern.search(txt.upper())
            if match:
                stations.append({
                    'text': txt,
                    'station_id': match.group(1),
                    'x': pt[0],
                    'y': pt[1]
                })
        except: pass
    
    print(f"\n[桩号统计] 找到: {len(stations)}个")
    if stations:
        stations.sort(key=lambda s: s['y'], reverse=True)
        print(f"  Y范围: {stations[-1]['y']:.1f} ~ {stations[0]['y']:.1f}")
        print(f"  前5个桩号: {[s['station_id'] for s in stations[:5]]}")
        print(f"  后5个桩号: {[s['station_id'] for s in stations[-5:]]}")
    
    # 5. 找DMX图层断面线
    dmx_entities = list(msp.query('LWPOLYLINE[layer=="DMX"]'))
    print(f"\n[DMX断面线] 数量: {len(dmx_entities)}")
    
    if dmx_entities:
        dmx_info = []
        for e in dmx_entities:
            pts = list(e.get_points())
            if pts:
                x_min = min(p[0] for p in pts)
                x_max = max(p[0] for p in pts)
                y_min = min(p[1] for p in pts)
                y_max = max(p[1] for p in pts)
                y_center = (y_min + y_max) / 2
                dmx_info.append({
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'y_center': y_center,
                    'pts': pts
                })
        
        dmx_info.sort(key=lambda d: d['y_center'], reverse=True)
        print(f"  Y范围: {dmx_info[-1]['y_center']:.1f} ~ {dmx_info[0]['y_center']:.1f}")
        
        # 计算断面间距
        if len(dmx_info) >= 2:
            gaps = []
            for i in range(1, len(dmx_info)):
                gap = dmx_info[i-1]['y_center'] - dmx_info[i]['y_center']
                gaps.append(gap)
            avg_gap = sum(gaps) / len(gaps)
            print(f"  平均间距: {avg_gap:.1f}")
            print(f"  间距范围: {min(gaps):.1f} ~ {max(gaps):.1f}")
    
    # 6. 找"0.00"文本（用于导航定位）
    nav_00_texts = []
    for t in all_texts:
        try:
            txt = get_text(t).strip()
            if txt == "0.00":
                pt = get_best_point(t)
                nav_00_texts.append({'x': pt[0], 'y': pt[1]})
        except: pass
    
    print(f"\n[0.00导航点] 数量: {len(nav_00_texts)}")
    if nav_00_texts:
        nav_00_texts.sort(key=lambda n: n['y'], reverse=True)
        print(f"  Y范围: {nav_00_texts[-1]['y']:.1f} ~ {nav_00_texts[0]['y']:.1f}")
        if len(nav_00_texts) >= 2:
            gaps = []
            for i in range(1, len(nav_00_texts)):
                gap = nav_00_texts[i-1]['y'] - nav_00_texts[i]['y']
                gaps.append(gap)
            avg_gap = sum(gaps) / len(gaps)
            print(f"  平均间距: {avg_gap:.1f}")
    
    # 7. 找.TIN文本（桩号标注）
    tin_texts = []
    for t in all_texts:
        try:
            txt = get_text(t).strip()
            if ".TIN" in txt.upper():
                pt = get_best_point(t)
                match = station_pattern.search(txt)
                station_id = match.group(1) if match else None
                tin_texts.append({'text': txt, 'x': pt[0], 'y': pt[1], 'station_id': station_id})
        except: pass
    
    print(f"\n[.TIN桩号标注] 数量: {len(tin_texts)}")
    if tin_texts:
        tin_texts.sort(key=lambda t: t['y'], reverse=True)
        print(f"  X范围: {min(t['x'] for t in tin_texts):.1f} ~ {max(t['x'] for t in tin_texts):.1f}")
        print(f"  Y范围: {tin_texts[-1]['y']:.1f} ~ {tin_texts[0]['y']:.1f}")
    
    # 8. 找红线（color=1的LWPOLYLINE）
    red_lines = [e for e in msp.query('LWPOLYLINE') if e.dxf.color == 1]
    print(f"\n[红线实体] 数量: {len(red_lines)}")
    
    if red_lines:
        red_info = []
        for e in red_lines:
            pts = list(e.get_points())
            if pts:
                avg_y = sum(p[1] for p in pts) / len(pts)
                red_info.append({'avg_y': avg_y, 'pts': pts})
        red_info.sort(key=lambda r: r['avg_y'], reverse=True)
        print(f"  Y范围: {red_info[-1]['avg_y']:.1f} ~ {red_info[0]['avg_y']:.1f}")
    
    # 9. 计算坐标范围
    all_coords = []
    for e in msp.query('LWPOLYLINE LINE'):
        try:
            if e.dxftype() == 'LWPOLYLINE':
                pts = list(e.get_points())
                all_coords.extend([(p[0], p[1]) for p in pts])
            elif e.dxftype() == 'LINE':
                all_coords.append((e.dxf.start.x, e.dxf.start.y))
                all_coords.append((e.dxf.end.x, e.dxf.end.y))
        except: pass
    
    if all_coords:
        x_min = min(c[0] for c in all_coords)
        x_max = max(c[0] for c in all_coords)
        y_min = min(c[1] for c in all_coords)
        y_max = max(c[1] for c in all_coords)
        print(f"\n[坐标范围]")
        print(f"  X: {x_min:.1f} ~ {x_max:.1f} (宽度: {x_max-x_min:.1f})")
        print(f"  Y: {y_min:.1f} ~ {y_max:.1f} (高度: {y_max-y_min:.1f})")
    
    return {
        'stations': stations,
        'dmx_info': dmx_info if dmx_entities else [],
        'nav_00_texts': nav_00_texts,
        'tin_texts': tin_texts,
        'red_lines': red_lines,
        'doc': doc,
        'msp': msp
    }


def compare_detection(file1, file2):
    """对比两个文件的检测结果"""
    print("\n" + "="*60)
    print("对比检测结果")
    print("="*60)
    
    data1 = analyze_dxf(file1)
    data2 = analyze_dxf(file2)
    
    if data1 and data2:
        print("\n" + "-"*60)
        print("关键对比:")
        print("-"*60)
        
        # 计算比例
        if data1['dmx_info'] and data2['dmx_info']:
            dmx_ratio = len(data2['dmx_info']) / len(data1['dmx_info']) if len(data1['dmx_info']) > 0 else 0
            print(f"DMX断面数: {len(data1['dmx_info'])} vs {len(data2['dmx_info'])} (比例: {dmx_ratio:.2f})")
        
        if data1['stations'] and data2['stations']:
            station_ratio = len(data2['stations']) / len(data1['stations']) if len(data1['stations']) > 0 else 0
            print(f"桩号数: {len(data1['stations'])} vs {len(data2['stations'])} (比例: {station_ratio:.2f})")
        
        if data1['nav_00_texts'] and data2['nav_00_texts']:
            nav_ratio = len(data2['nav_00_texts']) / len(data1['nav_00_texts']) if len(data1['nav_00_texts']) > 0 else 0
            print(f"0.00导航点: {len(data1['nav_00_texts'])} vs {len(data2['nav_00_texts'])} (比例: {nav_ratio:.2f})")
        
        if data1['red_lines'] and data2['red_lines']:
            red_ratio = len(data2['red_lines']) / len(data1['red_lines']) if len(data1['red_lines']) > 0 else 0
            print(f"红线数: {len(data1['red_lines'])} vs {len(data2['red_lines'])} (比例: {red_ratio:.2f})")
        
        # 计算坐标比例
        if data1['dmx_info'] and data2['dmx_info']:
            # Y坐标比例
            y1_range = data1['dmx_info'][0]['y_center'] - data1['dmx_info'][-1]['y_center']
            y2_range = data2['dmx_info'][0]['y_center'] - data2['dmx_info'][-1]['y_center']
            y_scale = y2_range / y1_range if y1_range > 0 else 0
            print(f"\nY坐标范围比例: {y_scale:.4f} (sqrt(0.6) = {math.sqrt(0.6):.4f})")
            
            # X坐标比例
            x1_range = data1['dmx_info'][0]['x_max'] - data1['dmx_info'][0]['x_min']
            x2_range = data2['dmx_info'][0]['x_max'] - data2['dmx_info'][0]['x_min']
            x_scale = x2_range / x1_range if x1_range > 0 else 0
            print(f"X坐标范围比例: {x_scale:.4f}")
        
        # 分析断面间距变化
        if len(data1['dmx_info']) >= 2 and len(data2['dmx_info']) >= 2:
            gaps1 = []
            gaps2 = []
            for i in range(1, min(len(data1['dmx_info']), len(data2['dmx_info']))):
                gap1 = data1['dmx_info'][i-1]['y_center'] - data1['dmx_info'][i]['y_center']
                gap2 = data2['dmx_info'][i-1]['y_center'] - data2['dmx_info'][i]['y_center']
                gaps1.append(gap1)
                gaps2.append(gap2)
            
            avg_gap1 = sum(gaps1) / len(gaps1)
            avg_gap2 = sum(gaps2) / len(gaps2)
            gap_ratio = avg_gap2 / avg_gap1 if avg_gap1 > 0 else 0
            
            print(f"\n断面间距对比:")
            print(f"  文件1平均间距: {avg_gap1:.1f}")
            print(f"  文件2平均间距: {avg_gap2:.1f}")
            print(f"  间距比例: {gap_ratio:.4f}")


if __name__ == "__main__":
    file1 = r"D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf"
    file2 = r"D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf"
    
    compare_detection(file1, file2)