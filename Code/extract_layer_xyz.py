# -*- coding: utf-8 -*-
"""
extract_layer_xyz.py - 基于L1对齐逻辑提取开挖线和超挖线的XYZ数据

核心原理（参考geology_model_v17.py）：
1. 中心线 = 航道脊梁线（spine_x, spine_y世界坐标）
2. 开挖线和超挖线共享同一条中心线
3. 桩号来自脊梁点匹配结果（脊梁点_L1匹配结果.json）
4. L1参考点用于断面图坐标到世界坐标的变换
"""

import ezdxf
import re
import math
import json
from typing import Dict, List, Tuple, Optional


def load_spine_matches(match_path: str) -> Dict:
    """加载脊梁点匹配结果"""
    with open(match_path, 'r', encoding='utf-8') as f:
        match_data = json.load(f)
    
    matches = match_data.get('matches', [])
    if not matches:
        matches = [v for k, v in match_data.items() if isinstance(v, dict) and 'station_value' in v]
    
    spine_data = {}
    for m in matches:
        spine_data[m['station_value']] = {
            'station_name': m['station_name'],
            'spine_x': m['spine_x'],
            'spine_y': m['spine_y'],
            'l1_x': m['l1_x'],
            'l1_y': m['l1_y'],
            'tangent_angle': m['tangent_angle']
        }
    
    return spine_data


def transform_to_spine_aligned(cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle):
    """
    将断面图坐标转换为世界坐标（参考geology_model_v17.py）
    
    Args:
        cad_x, cad_y: 断面图坐标
        ref_x, ref_y: L1参考点坐标
        spine_x, spine_y: 脊梁线中心点世界坐标
        rotation_angle: 旋转角度（弧度）
    
    Returns:
        eng_x, eng_y, z: 世界坐标
    """
    z = cad_y - ref_y  # Z = 断面图Y - L1参考点Y
    dx = cad_x - ref_x  # 横向偏移 = 断面图X - L1参考点X
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    eng_x = spine_x + dx * cos_a
    eng_y = spine_y + dx * sin_a
    return eng_x, eng_y, z


def get_layer_entities(msp, layer_names):
    """从图层获取所有实体"""
    entities = []
    for layer_name in layer_names:
        for e in msp.query(f'*[layer=="{layer_name}"]'):
            entities.append(e)
    return entities


def extract_entity_points(entity):
    """从实体提取点坐标"""
    pts = []
    try:
        if entity.dxftype() == 'LWPOLYLINE':
            pts = [p[:2] for p in entity.get_points()]
        elif entity.dxftype() == 'POLYLINE':
            pts = [v.dxf.location.vec2 for v in entity.vertices]
        elif entity.dxftype() == 'LINE':
            pts = [entity.dxf.start.vec2, entity.dxf.end.vec2]
        elif entity.dxftype() == 'SPLINE':
            pts = [p[:2] for p in entity.control_points]
    except:
        pass
    return pts


def detect_ruler_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max):
    """检测标尺比例 - 使用autosection.py的完整逻辑"""
    ruler_layers = ['标尺', '0-标尺', 'RULER']
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
    
    sect_x_center = (sect_x_min + sect_x_max) / 2
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
        best_ruler = min(ruler_candidates, key=lambda r: abs(r['x'] - sect_x_center))
    
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
    
    # 线性回归计算高程映射
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
    
    # 返回: Y坐标转高程的函数
    return lambda y: (y - b) / a


def main():
    dxf_path = r"D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf"
    match_path = r"D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json"
    
    print("=" * 60)
    print("基于L1对齐逻辑提取开挖线和超挖线XYZ数据")
    print("中心线 = 航道脊梁线")
    print("=" * 60)
    
    # 加载脊梁点匹配结果
    print(f"\n[INFO] 加载脊梁点匹配结果: {match_path}")
    spine_matches = load_spine_matches(match_path)
    print(f"[INFO] 脊梁点匹配数量: {len(spine_matches)}")
    
    if not spine_matches:
        print("[ERROR] 没有找到脊梁点匹配数据")
        return
    
    # 显示桩号范围
    station_values = sorted(spine_matches.keys())
    print(f"[INFO] 桩号范围: {spine_matches[station_values[0]]['station_name']} - {spine_matches[station_values[-1]]['station_name']}")
    
    # 加载DXF文件
    print(f"\n[INFO] 正在读取DXF文件: {dxf_path}")
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    all_layers = [l.dxf.name for l in doc.layers]
    print(f"[INFO] 图层总数: {len(all_layers)}")
    
    # 获取开挖线和超挖线图层
    excav_layer_names = [l for l in all_layers if '开挖线' in l]
    overexc_layer_names = [l for l in all_layers if '超挖线' in l]
    print(f"[INFO] 开挖线图层: {excav_layer_names}")
    print(f"[INFO] 超挖线图层: {overexc_layer_names}")
    
    # 获取开挖线和超挖线实体
    excav_entities = get_layer_entities(msp, excav_layer_names)
    overexc_entities = get_layer_entities(msp, overexc_layer_names)
    print(f"[INFO] 开挖线实体数量: {len(excav_entities)}")
    print(f"[INFO] 超挖线实体数量: {len(overexc_entities)}")
    
    # 为每个实体计算边界框
    excav_with_bounds = []
    for e in excav_entities:
        pts = extract_entity_points(e)
        if pts:
            x_min = min(p[0] for p in pts)
            x_max = max(p[0] for p in pts)
            y_min = min(p[1] for p in pts)
            y_max = max(p[1] for p in pts)
            y_center = (y_min + y_max) / 2
            excav_with_bounds.append({
                'entity': e,
                'pts': pts,
                'x_min': x_min, 'x_max': x_max,
                'y_min': y_min, 'y_max': y_max,
                'y_center': y_center
            })
    
    overexc_with_bounds = []
    for e in overexc_entities:
        pts = extract_entity_points(e)
        if pts:
            x_min = min(p[0] for p in pts)
            x_max = max(p[0] for p in pts)
            y_min = min(p[1] for p in pts)
            y_max = max(p[1] for p in pts)
            y_center = (y_min + y_max) / 2
            overexc_with_bounds.append({
                'entity': e,
                'pts': pts,
                'x_min': x_min, 'x_max': x_max,
                'y_min': y_min, 'y_max': y_max,
                'y_center': y_center
            })
    
    print(f"[INFO] 开挖线有效断面: {len(excav_with_bounds)}")
    print(f"[INFO] 超挖线有效断面: {len(overexc_with_bounds)}")
    
    # 根据L1参考点匹配断面
    print("\n[INFO] 匹配断面到桩号...")
    
    def match_section_to_spine(sect_data, spine_matches):
        """将断面匹配到最近的桩号"""
        sect_y = sect_data['y_center']
        sect_x_center = (sect_data['x_min'] + sect_data['x_max']) / 2
        
        best_station = None
        best_dist = float('inf')
        
        for station_value, spine_info in spine_matches.items():
            l1_y = spine_info['l1_y']
            l1_x = spine_info['l1_x']
            
            # 计算断面Y中心到L1参考点Y的距离
            y_dist = abs(sect_y - l1_y)
            x_dist = abs(sect_x_center - l1_x)
            
            # 综合距离（Y方向权重更大）
            dist = y_dist * 2 + x_dist
            
            if dist < best_dist:
                best_dist = dist
                best_station = station_value
        
        return best_station, best_dist
    
    # 匹配开挖线断面
    excav_matched = {}
    for sect in excav_with_bounds:
        station, dist = match_section_to_spine(sect, spine_matches)
        if dist < 200:  # 距离阈值
            if station not in excav_matched:
                excav_matched[station] = []
            excav_matched[station].append(sect)
    
    # 匹配超挖线断面
    overexc_matched = {}
    for sect in overexc_with_bounds:
        station, dist = match_section_to_spine(sect, spine_matches)
        if dist < 200:
            if station not in overexc_matched:
                overexc_matched[station] = []
            overexc_matched[station].append(sect)
    
    print(f"[INFO] 开挖线匹配桩号数: {len(excav_matched)}")
    print(f"[INFO] 超挖线匹配桩号数: {len(overexc_matched)}")
    
    # 处理开挖线数据
    print("\n[INFO] 处理开挖线XYZ数据...")
    excav_xyz_data = []
    excav_centerline = []
    
    for station_value, sections in sorted(excav_matched.items()):
        spine_info = spine_matches[station_value]
        ref_x = spine_info['l1_x']
        ref_y = spine_info['l1_y']
        spine_x = spine_info['spine_x']
        spine_y = spine_info['spine_y']
        rotation_angle = spine_info['tangent_angle'] + math.pi / 2
        
        all_pts = []
        for sect in sections:
            all_pts.extend(sect['pts'])
        
        if not all_pts:
            continue
        
        # 获取标尺
        sect_x_min = min(p[0] for p in all_pts)
        sect_x_max = max(p[0] for p in all_pts)
        sect_y_min = min(p[1] for p in all_pts)
        sect_y_max = max(p[1] for p in all_pts)
        sect_y_center = (sect_y_min + sect_y_max) / 2
        
        ruler_func = detect_ruler_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max)
        
        # 处理每个点
        for sect in sections:
            for pt in sect['pts']:
                cad_x, cad_y = pt
                
                # 转换到世界坐标
                eng_x, eng_y, z = transform_to_spine_aligned(
                    cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                )
                
                # 如果有标尺，使用标尺高程
                if ruler_func:
                    z = ruler_func(cad_y)
                
                excav_xyz_data.append((eng_x, eng_y, z, station_value, spine_info['station_name']))
        
        # 计算中心线点（脊梁线位置）
        center_x = spine_x
        center_y = spine_y
        center_z = 0
        if ruler_func:
            # 中心点高程 = L1参考点对应的高程
            center_z = ruler_func(ref_y)
        
        excav_centerline.append((center_x, center_y, center_z, station_value, spine_info['station_name']))
    
    print(f"[INFO] 开挖线XYZ数据量: {len(excav_xyz_data)}")
    print(f"[INFO] 开挖线中心线点数: {len(excav_centerline)}")
    
    # 处理超挖线数据
    print("\n[INFO] 处理超挖线XYZ数据...")
    overexc_xyz_data = []
    overexc_centerline = []
    
    for station_value, sections in sorted(overexc_matched.items()):
        spine_info = spine_matches[station_value]
        ref_x = spine_info['l1_x']
        ref_y = spine_info['l1_y']
        spine_x = spine_info['spine_x']
        spine_y = spine_info['spine_y']
        rotation_angle = spine_info['tangent_angle'] + math.pi / 2
        
        all_pts = []
        for sect in sections:
            all_pts.extend(sect['pts'])
        
        if not all_pts:
            continue
        
        # 获取标尺
        sect_x_min = min(p[0] for p in all_pts)
        sect_x_max = max(p[0] for p in all_pts)
        sect_y_min = min(p[1] for p in all_pts)
        sect_y_max = max(p[1] for p in all_pts)
        sect_y_center = (sect_y_min + sect_y_max) / 2
        
        ruler_func = detect_ruler_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max)
        
        # 处理每个点
        for sect in sections:
            for pt in sect['pts']:
                cad_x, cad_y = pt
                
                # 转换到世界坐标
                eng_x, eng_y, z = transform_to_spine_aligned(
                    cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                )
                
                # 如果有标尺，使用标尺高程
                if ruler_func:
                    z = ruler_func(cad_y)
                
                overexc_xyz_data.append((eng_x, eng_y, z, station_value, spine_info['station_name']))
        
        # 计算中心线点（脊梁线位置）- 与开挖线共享同一条中心线
        center_x = spine_x
        center_y = spine_y
        center_z = 0
        if ruler_func:
            center_z = ruler_func(ref_y)
        
        overexc_centerline.append((center_x, center_y, center_z, station_value, spine_info['station_name']))
    
    print(f"[INFO] 超挖线XYZ数据量: {len(overexc_xyz_data)}")
    print(f"[INFO] 超挖线中心线点数: {len(overexc_centerline)}")
    
    # 保存XYZ文件
    print("\n[INFO] 保存XYZ文件...")
    
    # 开挖线XYZ文件
    excav_xyz_path = r"D:\断面算量平台\测试文件\开挖线_xyz.txt"
    with open(excav_xyz_path, 'w', encoding='utf-8') as f:
        f.write("# 开挖线XYZ数据 (世界坐标系 - 基于L1对齐)\n")
        f.write("# X,Y = 世界坐标（脊梁线坐标系）\n")
        f.write("# Z = 标尺高程\n")
        f.write("# Station = 桩号数值, StationStr = 桩号文本\n")
        f.write("# 格式: X Y Z Station StationStr\n")
        for d in sorted(excav_xyz_data, key=lambda x: (x[3], x[0])):
            f.write(f"{d[0]:.3f} {d[1]:.3f} {d[2]:.3f} {d[3]} {d[4]}\n")
    print(f"[INFO] 保存开挖线XYZ文件: {excav_xyz_path}")
    
    # 超挖线XYZ文件
    overexc_xyz_path = r"D:\断面算量平台\测试文件\超挖线_xyz.txt"
    with open(overexc_xyz_path, 'w', encoding='utf-8') as f:
        f.write("# 超挖线XYZ数据 (世界坐标系 - 基于L1对齐)\n")
        f.write("# X,Y = 世界坐标（脊梁线坐标系）\n")
        f.write("# Z = 标尺高程\n")
        f.write("# Station = 桩号数值, StationStr = 桩号文本\n")
        f.write("# 格式: X Y Z Station StationStr\n")
        for d in sorted(overexc_xyz_data, key=lambda x: (x[3], x[0])):
            f.write(f"{d[0]:.3f} {d[1]:.3f} {d[2]:.3f} {d[3]} {d[4]}\n")
    print(f"[INFO] 保存超挖线XYZ文件: {overexc_xyz_path}")
    
    # 保存中心线（脊梁线）- 开挖线和超挖线共享
    centerline_path = r"D:\断面算量平台\测试文件\航道中心线.txt"
    with open(centerline_path, 'w', encoding='utf-8') as f:
        f.write("# 航道中心线（脊梁线）\n")
        f.write("# 开挖线和超挖线共享同一条中心线\n")
        f.write("# X,Y = 世界坐标, Z = 高程\n")
        f.write("# 格式: X Y Z Station StationStr\n")
        # 合并开挖线和超挖线的中心线点（去重）
        all_center_points = {}
        for d in excav_centerline + overexc_centerline:
            key = d[3]  # 桩号
            if key not in all_center_points:
                all_center_points[key] = d
        for d in sorted(all_center_points.values(), key=lambda x: x[3]):
            f.write(f"{d[0]:.3f} {d[1]:.3f} {d[2]:.3f} {d[3]} {d[4]}\n")
    print(f"[INFO] 保存中心线文件: {centerline_path}")
    
    # 摘要
    print("\n" + "=" * 60)
    print("输出文件摘要")
    print("=" * 60)
    print(f"1. 开挖线XYZ文件: {excav_xyz_path}")
    print(f"   - 数据点量: {len(excav_xyz_data)}")
    excav_stations = set(d[3] for d in excav_xyz_data)
    print(f"   - 桩号数: {len(excav_stations)}")
    if excav_stations:
        print(f"   - 桩号范围: {min(excav_stations)} - {max(excav_stations)}")
    print(f"2. 超挖线XYZ文件: {overexc_xyz_path}")
    print(f"   - 数据点量: {len(overexc_xyz_data)}")
    overexc_stations = set(d[3] for d in overexc_xyz_data)
    print(f"   - 桩号数: {len(overexc_stations)}")
    if overexc_stations:
        print(f"   - 桩号范围: {min(overexc_stations)} - {max(overexc_stations)}")
    print(f"3. 航道中心线文件: {centerline_path}")
    print(f"   - 中心线点数: {len(all_center_points)}")


if __name__ == '__main__':
    main()