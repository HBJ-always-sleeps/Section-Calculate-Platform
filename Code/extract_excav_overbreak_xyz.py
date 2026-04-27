# -*- coding: utf-8 -*-
"""
extract_excav_overbreak_xyz.py - 提取开挖线和超挖线XYZ数据

基于geology_model_v17.py的L1对齐逻辑：
1. 从断面图读取开挖线、超挖线、L1图层
2. 从标尺图层获取高程映射
3. 从断面图内部的桩号图层获取桩号信息
4. 按L1对齐逻辑输出XYZ数据

作者: Cline
日期: 2026-04-11
"""

import ezdxf
import math
import json
import sys
import io
import os
import re
from collections import defaultdict
from shapely.geometry import LineString, Point, box

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 文件路径
SECTION_DXF = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf'
OUTPUT_DIR = r'D:\断面算量平台\测试文件'


def get_layer_entities(msp, layer_name):
    """获取图层所有实体"""
    return list(msp.query(f'*[layer=="{layer_name}"]'))


def get_layer_lines(msp, layer_name):
    """从图层获取所有线段（返回LineString列表）"""
    res = []
    for e in msp.query(f'*[layer=="{layer_name}"]'):
        try:
            if e.dxftype() == 'LWPOLYLINE':
                pts = [p[:2] for p in e.get_points()]
                if len(pts) >= 2:
                    res.append(LineString(pts))
            elif e.dxftype() == 'POLYLINE':
                pts = [v.dxf.location.vec2 for v in e.vertices]
                if len(pts) >= 2:
                    res.append(LineString(pts))
            elif e.dxftype() == 'LINE':
                res.append(LineString([e.dxf.start.vec2, e.dxf.end.vec2]))
        except:
            pass
    return res


def detect_ruler_scale(msp, doc, sect_bounds):
    """检测标尺比例 - 从autosection.py移植"""
    ruler_layers = ['标尺', '0-标尺', 'RULER']
    sect_x_min, sect_x_max, sect_y_min, sect_y_max = sect_bounds
    
    ruler_candidates = []
    
    for layer_name in ruler_layers:
        for e in msp.query(f'*[layer=="{layer_name}"]'):
            try:
                if e.dxftype() == 'INSERT':
                    insert_x = e.dxf.insert.x
                    insert_y = e.dxf.insert.y
                    
                    if sect_x_min - 100 <= insert_x <= sect_x_max + 100:
                        y_min = insert_y
                        y_max = insert_y
                        
                        try:
                            block_name = e.dxf.name
                            if block_name in doc.blocks:
                                block = doc.blocks[block_name]
                                for be in block:
                                    if be.dxftype() in ('TEXT', 'MTEXT'):
                                        try:
                                            local_y = be.dxf.insert.y
                                            world_y = local_y + insert_y
                                            y_min = min(y_min, world_y)
                                            y_max = max(y_max, world_y)
                                        except:
                                            pass
                        except:
                            pass
                        
                        ruler_candidates.append({
                            'x': insert_x,
                            'y_min': y_min,
                            'y_max': y_max,
                            'entity': e
                        })
            except:
                pass
    
    if not ruler_candidates:
        return None
    
    sect_y_center = (sect_y_min + sect_y_max) / 2
    best_ruler = None
    best_overlap = -1
    
    for ruler in ruler_candidates:
        overlap_start = max(sect_y_min, ruler['y_min'])
        overlap_end = min(sect_y_max, ruler['y_max'])
        overlap = max(0, overlap_end - overlap_start)
        ruler_height = ruler['y_max'] - ruler['y_min']
        overlap_ratio = overlap / ruler_height if ruler_height > 0 else 0
        
        if overlap_ratio > best_overlap:
            best_overlap = overlap_ratio
            best_ruler = ruler
    
    if not best_ruler:
        best_ruler = min(ruler_candidates, key=lambda r: abs(r['x'] - (sect_x_min + sect_x_max)/2))
    
    elevation_points = []
    
    if best_ruler.get('entity'):
        insert_e = best_ruler['entity']
        insert_y = insert_e.dxf.insert.y
        
        try:
            block_name = insert_e.dxf.name
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
    
    # 线性回归计算Y坐标与高程的关系
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
    
    # elev_to_y: 高程 -> Y坐标
    # y_to_elev: Y坐标 -> 高程
    return (lambda elev: a * elev + b, lambda y: (y - b) / a)


def parse_station(s):
    """解析桩号字符串为数值（米）"""
    # K69+400 -> 69400
    match = re.match(r'K(\d+)\+(\d+)', s)
    if match:
        return int(match.group(1)) * 1000 + int(match.group(2))
    return 0


def get_section_stations(msp):
    """从断面图内部的桩号图层获取桩号信息"""
    stations = []
    for txt in msp.query('TEXT[layer=="0-桩号"]'):
        try:
            text = txt.dxf.text.strip()
            if 'K' in text and '+' in text:
                x, y = txt.dxf.insert.x, txt.dxf.insert.y
                station_value = parse_station(text)
                stations.append({
                    'text': text,
                    'x': x,
                    'y': y,
                    'value': station_value
                })
        except:
            pass
    
    # 按桩号数值排序
    stations.sort(key=lambda s: s['value'])
    return stations


def extract_section_bounds(msp, doc):
    """提取所有断面区域范围"""
    bounds_list = []
    
    # 从开挖线推断断面区域
    excav_lines = get_layer_lines(msp, '开挖线')
    if excav_lines:
        # 按Y坐标分组，识别不同断面
        y_groups = defaultdict(list)
        for line in excav_lines:
            coords = list(line.coords)
            y_center = sum(c[1] for c in coords) / len(coords)
            # 使用更细的分组间隔
            y_key = round(y_center / 30) * 30
            y_groups[y_key].append(line)
        
        for y_key in sorted(y_groups.keys(), reverse=True):
            lines = y_groups[y_key]
            all_pts = []
            for line in lines:
                all_pts.extend(list(line.coords))
            
            if all_pts:
                x_min = min(p[0] for p in all_pts)
                x_max = max(p[0] for p in all_pts)
                y_min = min(p[1] for p in all_pts)
                y_max = max(p[1] for p in all_pts)
                bounds_list.append({
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'y_center': (y_min + y_max) / 2
                })
    
    # 按Y坐标从大到小排序（从上到下）
    bounds_list.sort(key=lambda b: b['y_center'], reverse=True)
    
    return bounds_list


def match_section_to_station(bounds, stations, used_stations):
    """匹配断面到桩号（按Y坐标）"""
    sect_y_center = bounds['y_center']
    sect_y_min = bounds['y_min']
    sect_y_max = bounds['y_max']
    
    best_station = None
    best_dist = float('inf')
    
    for st in stations:
        if st['text'] in used_stations:
            continue
        
        # 检查桩号Y是否在断面范围内
        if sect_y_min - 30 <= st['y'] <= sect_y_max + 30:
            dist = abs(st['y'] - sect_y_center)
            if dist < best_dist:
                best_dist = dist
                best_station = st
    
    return best_station, best_dist


def get_l1_reference(msp, bounds):
    """获取L1参考点"""
    l1_entities = get_layer_entities(msp, 'L1')
    
    l1_points = []
    for e in l1_entities:
        try:
            if e.dxftype() == 'LINE':
                # L1可能是短线段，取中点
                mx = (e.dxf.start.x + e.dxf.end.x) / 2
                my = (e.dxf.start.y + e.dxf.end.y) / 2
                l1_points.append((mx, my))
            elif e.dxftype() == 'LWPOLYLINE':
                pts = list(e.vertices())
                if pts:
                    mx = pts[0][0]
                    my = pts[0][1]
                    l1_points.append((mx, my))
            elif e.dxftype() == 'POINT':
                l1_points.append((e.dxf.location.x, e.dxf.location.y))
        except:
            pass
    
    # 选择在断面范围内的L1点
    sect_x_center = (bounds['x_min'] + bounds['x_max']) / 2
    
    best_l1 = None
    best_dist = float('inf')
    
    for lx, ly in l1_points:
        # L1应该在断面范围内
        if bounds['x_min'] - 10 <= lx <= bounds['x_max'] + 10:
            if bounds['y_min'] - 10 <= ly <= bounds['y_max'] + 10:
                dist = abs(lx - sect_x_center)
                if dist < best_dist:
                    best_dist = dist
                    best_l1 = (lx, ly)
    
    return best_l1


def main():
    print("="*60)
    print("提取开挖线和超挖线XYZ数据")
    print("="*60)
    
    # 读取断面图
    print("\n[1] 读取断面图...")
    section_doc = ezdxf.readfile(SECTION_DXF)
    section_msp = section_doc.modelspace()
    
    # 获取断面图内部的桩号
    stations = get_section_stations(section_msp)
    print(f"  桩号数量: {len(stations)}")
    if stations:
        print(f"  桩号范围: {stations[0]['text']} 到 {stations[-1]['text']}")
    
    # 提取断面区域
    bounds_list = extract_section_bounds(section_msp, section_doc)
    print(f"  识别断面数: {len(bounds_list)}")
    
    # 提取开挖线和超挖线
    excav_lines_all = get_layer_lines(section_msp, '开挖线')
    overbreak_lines_all = get_layer_lines(section_msp, '超挖线')
    print(f"  开挖线数量: {len(excav_lines_all)}")
    print(f"  超挖线数量: {len(overbreak_lines_all)}")
    
    # 处理每个断面
    print("\n[2] 处理各断面...")
    all_excav_xyz = []
    all_overbreak_xyz = []
    used_stations = set()
    section_info = []  # 断面信息汇总
    
    for idx, bounds in enumerate(bounds_list):
        # 匹配桩号
        station_info, dist = match_section_to_station(bounds, stations, used_stations)
        
        if station_info and dist < 100:
            used_stations.add(station_info['text'])
            station_text = station_info['text']
            station_value = station_info['value']
        else:
            # 未匹配到桩号
            station_text = f"S{idx+1}"
            station_value = idx * 25  # 默认间隔
        
        # 获取L1参考点
        l1_ref = get_l1_reference(section_msp, bounds)
        if not l1_ref:
            # 使用断面中心作为默认参考
            l1_ref = ((bounds['x_min'] + bounds['x_max']) / 2, bounds['y_center'])
        
        # 检测标尺
        ruler_scale = detect_ruler_scale(section_msp, section_doc, 
            (bounds['x_min'], bounds['x_max'], bounds['y_min'], bounds['y_max']))
        
        # 提取断面范围内的开挖线和超挖线
        boundary_box = box(bounds['x_min']-20, bounds['y_min']-50, 
                           bounds['x_max']+20, bounds['y_max']+50)
        
        excav_in_section = [l for l in excav_lines_all if boundary_box.intersects(l)]
        overbreak_in_section = [l for l in overbreak_lines_all if boundary_box.intersects(l)]
        
        # 提取XYZ点
        section_excav_xyz = []
        section_overbreak_xyz = []
        
        for line in excav_in_section:
            coords = list(line.coords)
            for x, y in coords:
                # 获取高程
                if ruler_scale:
                    z = ruler_scale[1](y)
                else:
                    z = y - l1_ref[1]  # 相对高程
                
                # 断面水平偏移（相对于L1点）
                offset_x = x - l1_ref[0]
                
                pt = {
                    'station': station_text,
                    'station_value': station_value,
                    'cad_x': x,
                    'cad_y': y,
                    'offset_x': offset_x,  # 断面水平偏移
                    'z': z,  # 高程
                    'l1_x': l1_ref[0],
                    'l1_y': l1_ref[1]
                }
                section_excav_xyz.append(pt)
                all_excav_xyz.append(pt)
        
        for line in overbreak_in_section:
            coords = list(line.coords)
            for x, y in coords:
                if ruler_scale:
                    z = ruler_scale[1](y)
                else:
                    z = y - l1_ref[1]
                
                offset_x = x - l1_ref[0]
                
                pt = {
                    'station': station_text,
                    'station_value': station_value,
                    'cad_x': x,
                    'cad_y': y,
                    'offset_x': offset_x,
                    'z': z,
                    'l1_x': l1_ref[0],
                    'l1_y': l1_ref[1]
                }
                section_overbreak_xyz.append(pt)
                all_overbreak_xyz.append(pt)
        
        # 记录断面信息
        section_info.append({
            'station': station_text,
            'station_value': station_value,
            'y_center': bounds['y_center'],
            'l1_x': l1_ref[0],
            'l1_y': l1_ref[1],
            'excav_points': len(section_excav_xyz),
            'overbreak_points': len(section_overbreak_xyz),
            'has_ruler': ruler_scale is not None
        })
        
        # 每10个断面输出进度
        if (idx + 1) % 10 == 0:
            print(f"  已处理 {idx+1}/{len(bounds_list)} 个断面...")
    
    # 输出结果
    print("\n[3] 输出结果...")
    
    # 保存开挖线XYZ (JSON)
    excav_xyz_file = os.path.join(OUTPUT_DIR, '开挖线_XYZ.json')
    with open(excav_xyz_file, 'w', encoding='utf-8') as f:
        json.dump(all_excav_xyz, f, ensure_ascii=False, indent=2)
    print(f"  开挖线XYZ: {excav_xyz_file} ({len(all_excav_xyz)}点)")
    
    # 保存超挖线XYZ (JSON)
    overbreak_xyz_file = os.path.join(OUTPUT_DIR, '超挖线_XYZ.json')
    with open(overbreak_xyz_file, 'w', encoding='utf-8') as f:
        json.dump(all_overbreak_xyz, f, ensure_ascii=False, indent=2)
    print(f"  超挖线XYZ: {overbreak_xyz_file} ({len(all_overbreak_xyz)}点)")
    
    # 保存断面信息汇总
    section_info_file = os.path.join(OUTPUT_DIR, '断面匹配信息.json')
    with open(section_info_file, 'w', encoding='utf-8') as f:
        json.dump(section_info, f, ensure_ascii=False, indent=2)
    print(f"  断面信息: {section_info_file} ({len(section_info)}断面)")
    
    # 输出简单XYZ文本文件（用于3D可视化）
    excav_xyz_txt = os.path.join(OUTPUT_DIR, '开挖线_XYZ.txt')
    with open(excav_xyz_txt, 'w', encoding='utf-8') as f:
        f.write("# 开挖线XYZ数据\n")
        f.write("# 格式: station_value, offset_x, z, station_text\n")
        for pt in all_excav_xyz:
            f.write(f"{pt['station_value']},{pt['offset_x']:.2f},{pt['z']:.2f},{pt['station']}\n")
    print(f"  开挖线TXT: {excav_xyz_txt}")
    
    overbreak_xyz_txt = os.path.join(OUTPUT_DIR, '超挖线_XYZ.txt')
    with open(overbreak_xyz_txt, 'w', encoding='utf-8') as f:
        f.write("# 超挖线XYZ数据\n")
        f.write("# 格式: station_value, offset_x, z, station_text\n")
        for pt in all_overbreak_xyz:
            f.write(f"{pt['station_value']},{pt['offset_x']:.2f},{pt['z']:.2f},{pt['station']}\n")
    print(f"  超挖线TXT: {overbreak_xyz_txt}")
    
    # 输出中心线数据（桩号序列）
    centerline_file = os.path.join(OUTPUT_DIR, '中心线桩号.json')
    centerline_data = []
    for st in stations:
        centerline_data.append({
            'station': st['text'],
            'station_value': st['value'],
            'y_in_section': st['y']
        })
    with open(centerline_file, 'w', encoding='utf-8') as f:
        json.dump(centerline_data, f, ensure_ascii=False, indent=2)
    print(f"  中心线桩号: {centerline_file} ({len(centerline_data)}桩号)")
    
    # 统计匹配情况
    matched_count = len([s for s in section_info if s['station'].startswith('K')])
    print(f"\n[统计] 匹配桩号: {matched_count}/{len(section_info)} 断面")
    print(f"[统计] 开挖线总点数: {len(all_excav_xyz)}")
    print(f"[统计] 超挖线总点数: {len(all_overbreak_xyz)}")
    
    print("\n"+"="*60)
    print("完成！")
    print("="*60)


if __name__ == "__main__":
    main()