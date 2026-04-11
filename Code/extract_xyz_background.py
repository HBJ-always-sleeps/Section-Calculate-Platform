# -*- coding: utf-8 -*-
"""extract_xyz_background.py - 使用内湾背景.dxf作为坐标基准提取XYZ"""

import ezdxf
import re
import math
from typing import Dict, List, Tuple, Optional

def extract_centerline_and_stations(background_dxf_path: str) -> Dict:
    """从内湾背景.dxf提取中心线和桩号"""
    doc = ezdxf.readfile(background_dxf_path)
    msp = doc.modelspace()
    
    # 提取中心线（脊梁线）坐标
    centerline_points = []
    for e in msp.query('LWPOLYLINE LINE'):
        layer = e.dxf.layer
        if '中心线' in layer or '脊梁' in layer or 'spine' in layer.lower():
            pts = extract_entity_points(e)
            centerline_points.extend(pts)
    
    # 提取桩号文本
    station_data = {}
    for e in msp.query('TEXT MTEXT'):
        try:
            text = e.dxf.text if e.dxftype() == 'TEXT' else e.text
            text = text.strip()
            x = e.dxf.insert.x if e.dxftype() == 'TEXT' else e.dxf.insert.x
            y = e.dxf.insert.y if e.dxftype() == 'TEXT' else e.dxf.insert.y
            
            # 解析桩号 K67+400 格式
            match = re.search(r'K(\d+)\+(\d+)', text)
            if match:
                station_value = int(match.group(1)) * 1000 + int(match.group(2))
                station_data[station_value] = {
                    'station_name': text,
                    'x': x,
                    'y': y
                }
        except:
            pass
    
    print(f"[INFO] 中心线点数: {len(centerline_points)}")
    print(f"[INFO] 桩号数量: {len(station_data)}")
    
    if station_data:
        sorted_stations = sorted(station_data.keys())
        print(f"[INFO] 桩号范围: {station_data[sorted_stations[0]]['station_name']} - {station_data[sorted_stations[-1]]['station_name']}")
    
    return station_data, centerline_points

def extract_entity_points(entity):
    """从实体提取点坐标"""
    pts = []
    try:
        if entity.dxftype() == 'LWPOLYLINE':
            pts = [p[:2] for p in entity.get_points()]
        elif entity.dxftype() == 'LINE':
            pts = [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
    except:
        pass
    return pts

def match_section_to_station(sect_y_center, sect_x_center, station_data):
    """将断面匹配到桩号"""
    best_station = None
    best_dist = float('inf')
    
    for station_value, info in station_data.items():
        dist = math.sqrt((sect_y_center - info['y'])**2 + (sect_x_center - info['x'])**2)
        if dist < best_dist:
            best_dist = dist
            best_station = station_value
    
    return best_station, best_dist

def detect_ruler_scale(msp, doc, sect_bounds):
    """检测标尺比例"""
    ruler_layers = ['标尺', '0-标尺', 'RULER']
    sect_x_min, sect_x_max, sect_y_min, sect_y_max = sect_bounds
    
    elevation_points = []
    
    for layer_name in ruler_layers:
        for e in msp.query(f'*[layer=="{layer_name}"]'):
            try:
                if e.dxftype() == 'INSERT':
                    insert_x = e.dxf.insert.x
                    insert_y = e.dxf.insert.y
                    
                    if sect_x_min - 100 <= insert_x <= sect_x_max + 100:
                        block_name = e.dxf.name
                        if block_name in doc.blocks:
                            block = doc.blocks[block_name]
                            for be in block:
                                if be.dxftype() in ('TEXT', 'MTEXT'):
                                    try:
                                        local_y = be.dxf.insert.y
                                        world_y = local_y + insert_y
                                        text = be.dxf.text if be.dxftype() == 'TEXT' else be.text
                                        text = text.strip()
                                        elev = float(text)
                                        elevation_points.append((world_y, elev))
                                    except:
                                        pass
            except:
                pass
    
    if len(elevation_points) < 2:
        return None
    
    n = len(elevation_points)
    sum_y = sum(p[0] for p in elevation_points)
    sum_e = sum(p[1] for p in elevation_points)
    sum_ye = sum(p[0] * p[1] for p in elevation_points)
    sum_e2 = sum(p[1] ** 2 for p in elevation_points)
    
    denom = n * sum_e2 - sum_e ** 2
    if abs(denom) < 0.001:
        return None
    
    a = (n * sum_ye - sum_y * sum_e) / denom
    b = (sum_y - a * sum_e) / n
    
    return lambda y: (y - b) / a

def main():
    background_dxf_path = r"D:\断面算量平台\测试文件\内湾背景.dxf"
    source_dxf_path = r"D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf"
    
    print("=" * 60)
    print("使用内湾背景.dxf作为坐标基准提取XYZ数据")
    print("=" * 60)
    
    # 从内湾背景.dxf提取中心线和桩号
    print(f"\n[INFO] 读取内湾背景.dxf...")
    station_data, centerline_points = extract_centerline_and_stations(background_dxf_path)
    
    if not station_data:
        print("[ERROR] 没有找到桩号数据")
        return
    
    # 读取源DXF文件（开挖线/超挖线）
    print(f"\n[INFO] 读取源DXF文件...")
    doc = ezdxf.readfile(source_dxf_path)
    msp = doc.modelspace()
    
    all_layers = [l.dxf.name for l in doc.layers]
    excav_layer_names = [l for l in all_layers if '开挖线' in l]
    overexc_layer_names = [l for l in all_layers if '超挖线' in l]
    
    print(f"[INFO] 开挖线图层: {excav_layer_names}")
    print(f"[INFO] 超挖线图层: {overexc_layer_names}")
    
    # 收集开挖线和超挖线实体
    excav_entities = []
    for layer_name in excav_layer_names:
        for e in msp.query(f'*[layer=="{layer_name}"]'):
            pts = extract_entity_points(e)
            if pts:
                x_min = min(p[0] for p in pts)
                x_max = max(p[0] for p in pts)
                y_min = min(p[1] for p in pts)
                y_max = max(p[1] for p in pts)
                y_center = (y_min + y_max) / 2
                x_center = (x_min + x_max) / 2
                excav_entities.append({
                    'pts': pts,
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'y_center': y_center,
                    'x_center': x_center
                })
    
    overexc_entities = []
    for layer_name in overexc_layer_names:
        for e in msp.query(f'*[layer=="{layer_name}"]'):
            pts = extract_entity_points(e)
            if pts:
                x_min = min(p[0] for p in pts)
                x_max = max(p[0] for p in pts)
                y_min = min(p[1] for p in pts)
                y_max = max(p[1] for p in pts)
                y_center = (y_min + y_max) / 2
                x_center = (x_min + x_max) / 2
                overexc_entities.append({
                    'pts': pts,
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'y_center': y_center,
                    'x_center': x_center
                })
    
    print(f"[INFO] 开挖线实体数: {len(excav_entities)}")
    print(f"[INFO] 超挖线实体数: {len(overexc_entities)}")
    
    # 匹配断面到桩号
    print("\n[INFO] 匹配断面到桩号...")
    
    excav_matched = {}
    for sect in excav_entities:
        station, dist = match_section_to_station(sect['y_center'], sect['x_center'], station_data)
        if dist < 500:  # 距离阈值
            if station not in excav_matched:
                excav_matched[station] = []
            excav_matched[station].append(sect)
    
    overexc_matched = {}
    for sect in overexc_entities:
        station, dist = match_section_to_station(sect['y_center'], sect['x_center'], station_data)
        if dist < 500:
            if station not in overexc_matched:
                overexc_matched[station] = []
            overexc_matched[station].append(sect)
    
    print(f"[INFO] 开挖线匹配桩号数: {len(excav_matched)}")
    print(f"[INFO] 超挖线匹配桩号数: {len(overexc_matched)}")
    
    # 处理XYZ数据
    excav_xyz_data = []
    overexc_xyz_data = []
    centerline_xyz = []
    
    # 开挖线XYZ
    print("\n[INFO] 处理开挖线XYZ...")
    for station_value, sections in sorted(excav_matched.items()):
        station_info = station_data[station_value]
        center_x = station_info['x']
        center_y = station_info['y']
        
        all_pts = []
        for sect in sections:
            all_pts.extend(sect['pts'])
        
        if not all_pts:
            continue
        
        sect_bounds = (
            min(p[0] for p in all_pts),
            max(p[0] for p in all_pts),
            min(p[1] for p in all_pts),
            max(p[1] for p in all_pts)
        )
        
        ruler_func = detect_ruler_scale(msp, doc, sect_bounds)
        
        for sect in sections:
            for pt in sect['pts']:
                cad_x, cad_y = pt
                # 使用桩号位置作为基准
                eng_x = center_x + (cad_x - sections[0]['x_center'])
                eng_y = center_y + (cad_y - sections[0]['y_center'])
                
                z = 0
                if ruler_func:
                    z = ruler_func(cad_y)
                
                excav_xyz_data.append((eng_x, eng_y, z, station_value, station_info['station_name']))
        
        center_z = 0
        centerline_xyz.append((center_x, center_y, center_z, station_value, station_info['station_name']))
    
    # 超挖线XYZ
    print("\n[INFO] 处理超挖线XYZ...")
    for station_value, sections in sorted(overexc_matched.items()):
        station_info = station_data[station_value]
        center_x = station_info['x']
        center_y = station_info['y']
        
        all_pts = []
        for sect in sections:
            all_pts.extend(sect['pts'])
        
        if not all_pts:
            continue
        
        sect_bounds = (
            min(p[0] for p in all_pts),
            max(p[0] for p in all_pts),
            min(p[1] for p in all_pts),
            max(p[1] for p in all_pts)
        )
        
        ruler_func = detect_ruler_scale(msp, doc, sect_bounds)
        
        for sect in sections:
            for pt in sect['pts']:
                cad_x, cad_y = pt
                eng_x = center_x + (cad_x - sections[0]['x_center'])
                eng_y = center_y + (cad_y - sections[0]['y_center'])
                
                z = 0
                if ruler_func:
                    z = ruler_func(cad_y)
                
                overexc_xyz_data.append((eng_x, eng_y, z, station_value, station_info['station_name']))
    
    # 保存文件
    print("\n[INFO] 保存XYZ文件...")
    
    excav_path = r"D:\断面算量平台\测试文件\开挖线_xyz.txt"
    with open(excav_path, 'w', encoding='utf-8') as f:
        f.write("# 开挖线XYZ数据 (世界坐标系)\n")
        f.write("# 基于内湾背景.dxf中心线坐标\n")
        f.write("# X Y Z Station StationStr\n")
        for d in sorted(excav_xyz_data, key=lambda x: (x[3], x[0])):
            f.write(f"{d[0]:.3f} {d[1]:.3f} {d[2]:.3f} {d[3]} {d[4]}\n")
    
    overexc_path = r"D:\断面算量平台\测试文件\超挖线_xyz.txt"
    with open(overexc_path, 'w', encoding='utf-8') as f:
        f.write("# 超挖线XYZ数据 (世界坐标系)\n")
        f.write("# 基于内湾背景.dxf中心线坐标\n")
        f.write("# X Y Z Station StationStr\n")
        for d in sorted(overexc_xyz_data, key=lambda x: (x[3], x[0])):
            f.write(f"{d[0]:.3f} {d[1]:.3f} {d[2]:.3f} {d[3]} {d[4]}\n")
    
    center_path = r"D:\断面算量平台\测试文件\中心线坐标.txt"
    with open(center_path, 'w', encoding='utf-8') as f:
        f.write("# 航道中心线坐标\n")
        f.write("# X Y Z Station StationStr\n")
        for d in sorted(centerline_xyz, key=lambda x: x[3]):
            f.write(f"{d[0]:.3f} {d[1]:.3f} {d[2]:.3f} {d[3]} {d[4]}\n")
    
    print(f"\n[RESULT] 开挖线数据点: {len(excav_xyz_data)}")
    print(f"[RESULT] 超挖线数据点: {len(overexc_xyz_data)}")
    print(f"[RESULT] 中心线点数: {len(centerline_xyz)}")
    print(f"[RESULT] 匹配桩号数: {len(centerline_xyz)}")

if __name__ == '__main__':
    main()