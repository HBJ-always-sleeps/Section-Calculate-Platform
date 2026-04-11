# -*- coding: utf-8 -*-
"""extract_xyz_final.py - 从分层图提取XYZ数据（完整245断面版本）"""

import ezdxf
import re
import math
from collections import defaultdict

def main():
    source_dxf_path = r"D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf"
    
    print("=" * 60)
    print("从分层图提取XYZ数据（基于桩号位置分组）")
    print("=" * 60)
    
    doc = ezdxf.readfile(source_dxf_path)
    msp = doc.modelspace()
    
    # 获取所有图层
    all_layers = [l.dxf.name for l in doc.layers]
    print(f"\n[INFO] 总图层数: {len(all_layers)}")
    
    # 找开挖线和超挖线图层
    excav_layers = [l for l in all_layers if '开挖线' in l]
    overexc_layers = [l for l in all_layers if '超挖线' in l]
    print(f"[INFO] 开挖线图层: {excav_layers}")
    print(f"[INFO] 超挖线图层: {overexc_layers}")
    
    # 找标尺图层
    ruler_layers = [l for l in all_layers if '标尺' in l or 'ruler' in l.lower()]
    print(f"[INFO] 标尺图层: {ruler_layers}")
    
    # 提取桩号文本（用于确定断面位置）
    station_texts = []
    for e in msp.query('TEXT MTEXT'):
        try:
            text = e.dxf.text if e.dxftype() == 'TEXT' else e.text
            text = text.strip()
            # 匹配 K67+400 格式
            match = re.search(r'K(\d+)\+(\d+)', text)
            if match:
                station_value = int(match.group(1)) * 1000 + int(match.group(2))
                x = e.dxf.insert.x if e.dxftype() == 'TEXT' else e.dxf.insert.x
                y = e.dxf.insert.y if e.dxftype() == 'TEXT' else e.dxf.insert.y
                station_texts.append({
                    'station': station_value,
                    'name': text,
                    'x': x,
                    'y': y
                })
        except:
            pass
    
    # 按桩号分组，每个桩号取平均Y坐标
    station_y_map = defaultdict(list)
    for s in station_texts:
        station_y_map[s['station']].append(s['y'])
    
    # 每个桩号的Y坐标中心
    station_y_center = {}
    for station, y_list in station_y_map.items():
        station_y_center[station] = sum(y_list) / len(y_list)
    
    unique_stations = sorted(station_y_center.keys())
    print(f"[INFO] 找到桩号文本: {len(station_texts)}个")
    print(f"[INFO] 唯一桩号数: {len(unique_stations)}个")
    if unique_stations:
        print(f"[INFO] 桩号范围: K{unique_stations[0]//1000}+{unique_stations[0]%1000:03d} - K{unique_stations[-1]//1000}+{unique_stations[-1]%1000:03d}")
    
    # 提取多段线实体
    def extract_polylines_from_layers(layer_names):
        entities = []
        for layer_name in layer_names:
            for e in msp.query(f'*[layer=="{layer_name}"]'):
                try:
                    if e.dxftype() == 'LWPOLYLINE':
                        pts = [(p[0], p[1]) for p in e.get_points()]
                        if len(pts) >= 2:
                            y_min = min(p[1] for p in pts)
                            y_max = max(p[1] for p in pts)
                            x_min = min(p[0] for p in pts)
                            x_max = max(p[0] for p in pts)
                            y_center = (y_min + y_max) / 2
                            entities.append({
                                'pts': pts,
                                'y_min': y_min,
                                'y_max': y_max,
                                'y_center': y_center,
                                'x_min': x_min,
                                'x_max': x_max,
                                'x_center': (x_min + x_max) / 2
                            })
                except Exception as ex:
                    pass
        return entities
    
    excav_entities = extract_polylines_from_layers(excav_layers)
    overexc_entities = extract_polylines_from_layers(overexc_layers)
    
    print(f"[INFO] 开挖线实体数: {len(excav_entities)}")
    print(f"[INFO] 超挖线实体数: {len(overexc_entities)}")
    
    # 分析Y坐标范围
    if excav_entities:
        excav_y_min = min(e['y_center'] for e in excav_entities)
        excav_y_max = max(e['y_center'] for e in excav_entities)
        print(f"[INFO] 开挖线Y范围: {excav_y_min:.1f} - {excav_y_max:.1f}")
    if overexc_entities:
        overexc_y_min = min(e['y_center'] for e in overexc_entities)
        overexc_y_max = max(e['y_center'] for e in overexc_entities)
        print(f"[INFO] 超挖线Y范围: {overexc_y_min:.1f} - {overexc_y_max:.1f}")
    
    if unique_stations:
        station_y_min = min(station_y_center.values())
        station_y_max = max(station_y_center.values())
        print(f"[INFO] 桩号Y范围: {station_y_min:.1f} - {station_y_max:.1f}")
    
    # 使用聚类方法按Y坐标分组实体（不依赖桩号文本Y坐标）
    # 这样可以覆盖开挖线实际存在的所有断面
    def cluster_by_y(entities, tolerance=5):
        """按Y坐标聚类实体"""
        if not entities:
            return []
        
        # 按Y坐标排序
        sorted_entities = sorted(entities, key=lambda e: e['y_center'])
        
        clusters = []
        current_cluster = [sorted_entities[0]]
        current_y = sorted_entities[0]['y_center']
        
        for entity in sorted_entities[1:]:
            if abs(entity['y_center'] - current_y) <= tolerance:
                current_cluster.append(entity)
                current_y = sum(e['y_center'] for e in current_cluster) / len(current_cluster)
            else:
                clusters.append({
                    'y_center': current_y,
                    'entities': current_cluster
                })
                current_cluster = [entity]
                current_y = entity['y_center']
        
        if current_cluster:
            clusters.append({
                'y_center': current_y,
                'entities': current_cluster
            })
        
        return clusters
    
    # 聚类开挖线和超挖线实体
    excav_clusters = cluster_by_y(excav_entities, tolerance=5)
    overexc_clusters = cluster_by_y(overexc_entities, tolerance=5)
    
    print(f"[INFO] 开挖线聚类数: {len(excav_clusters)}")
    print(f"[INFO] 超挖线聚类数: {len(overexc_clusters)}")
    
    # 建立开挖线Y坐标与桩号的线性映射
    # 使用开挖线实际的Y范围，而不是桩号文本的Y范围
    if excav_entities:
        excav_y_min = min(e['y_center'] for e in excav_entities)
        excav_y_max = max(e['y_center'] for e in excav_entities)
    else:
        excav_y_min = -8733.5
        excav_y_max = -135.5
    
    if overexc_entities:
        overexc_y_min = min(e['y_center'] for e in overexc_entities)
        overexc_y_max = max(e['y_center'] for e in overexc_entities)
    
    # 桩号范围
    min_station_value = min(unique_stations)  # 67400 (K67+400)
    max_station_value = max(unique_stations)  # 73500 (K73+500)
    
    # 使用开挖线的Y范围建立映射（覆盖更多断面）
    y_min_for_mapping = min(excav_y_min, overexc_y_min) if excav_entities and overexc_entities else excav_y_min
    y_max_for_mapping = max(excav_y_max, overexc_y_max) if excav_entities and overexc_entities else excav_y_max
    
    print(f"[INFO] 用于映射的Y范围: {y_min_for_mapping:.1f} - {y_max_for_mapping:.1f}")
    
    # Y到桩号的映射函数（线性）
    y_range = y_max_for_mapping - y_min_for_mapping
    station_range = max_station_value - min_station_value
    
    # 计算每25m桩号间隔对应的Y坐标间隔
    y_per_station = y_range / (station_range / 25) if station_range > 0 else 0
    print(f"[INFO] 每桩号(25m)对应Y坐标间隔: {y_per_station:.2f}")
    
    def y_to_station(y):
        """将Y坐标映射到桩号"""
        # Y坐标越小（越负）对应桩号越小
        # Y=-8717.5 对应 K67+400 (67400)
        # Y=-63.1 对应 K73+500附近
        ratio = (y - y_min_for_mapping) / y_range if y_range > 0 else 0
        # 桩号从小到大
        station = min_station_value + int(ratio * station_range / 25) * 25
        # 限制范围
        station = max(min_station_value, min(max_station_value, station))
        # 找最近的桩号
        valid_stations = set(unique_stations)
        if station not in valid_stations:
            closest = min(valid_stations, key=lambda s: abs(s - station))
            return closest
        return station
    
    # 将聚类分配到桩号
    excav_by_station = defaultdict(list)
    for cluster in excav_clusters:
        y = cluster['y_center']
        station = y_to_station(y)
        excav_by_station[station].extend(cluster['entities'])
    
    overexc_by_station = defaultdict(list)
    for cluster in overexc_clusters:
        y = cluster['y_center']
        station = y_to_station(y)
        overexc_by_station[station].extend(cluster['entities'])
    
    # 统计每个桩号的数据
    excav_stations = set(excav_by_station.keys())
    overexc_stations = set(overexc_by_station.keys())
    all_data_stations = excav_stations | overexc_stations
    missing_stations = set(unique_stations) - all_data_stations
    
    print(f"[INFO] 有开挖线数据的桩号: {len(excav_stations)}")
    print(f"[INFO] 有超挖线数据的桩号: {len(overexc_stations)}")
    print(f"[INFO] 有任意数据的桩号: {len(all_data_stations)}")
    print(f"[INFO] 缺失数据的桩号: {len(missing_stations)}")
    
    if missing_stations and len(missing_stations) <= 20:
        missing_list = sorted(missing_stations)
        print(f"[INFO] 缺失桩号列表: {[f'K{s//1000}+{s%1000:03d}' for s in missing_list]}")
    
    # 分析桩号文本的X坐标分布（判断是否在图框边缘）
    station_x_values = [s['x'] for s in station_texts]
    if station_x_values:
        print(f"[INFO] 桩号文本X范围: {min(station_x_values):.1f} - {max(station_x_values):.1f}")
    
    # 分析开挖线的X坐标分布
    if excav_entities:
        excav_x_min = min(e['x_center'] for e in excav_entities)
        excav_x_max = max(e['x_center'] for e in excav_entities)
        print(f"[INFO] 开挖线X范围: {excav_x_min:.1f} - {excav_x_max:.1f}")
    
    # 提取标尺高程信息
    def extract_ruler_elevations(msp, doc):
        """从标尺块引用中提取高程映射"""
        elevation_map = []  # [(cad_y, elevation), ...]
        
        # 查找标尺块引用
        for e in msp.query('INSERT'):
            try:
                block_name = e.dxf.name
                if '标尺' in block_name or 'ruler' in block_name.lower():
                    insert_x = e.dxf.insert.x
                    insert_y = e.dxf.insert.y
                    
                    # 获取块定义中的文本
                    if block_name in doc.blocks:
                        block = doc.blocks[block_name]
                        for be in block:
                            if be.dxftype() == 'TEXT':
                                try:
                                    local_y = be.dxf.insert.y
                                    world_y = local_y + insert_y
                                    text = be.dxf.text.strip()
                                    elev = float(text)
                                    elevation_map.append((world_y, elev))
                                except:
                                    pass
            except:
                pass
        
        # 也检查TEXT实体（可能标尺直接是文本）
        for layer in ruler_layers:
            for e in msp.query(f'TEXT[layer=="{layer}"]'):
                try:
                    text = e.dxf.text.strip()
                    elev = float(text)
                    elevation_map.append((e.dxf.insert.y, elev))
                except:
                    pass
        
        return elevation_map
    
    ruler_elevs = extract_ruler_elevations(msp, doc)
    print(f"[INFO] 标尺高程点数: {len(ruler_elevs)}")
    
    # 建立Y坐标到高程的映射（线性回归）
    def build_elevation_func(elevation_map):
        if len(elevation_map) < 2:
            return None
        
        # 线性回归: cad_y = a * elevation + b
        n = len(elevation_map)
        sum_y = sum(p[0] for p in elevation_map)
        sum_e = sum(p[1] for p in elevation_map)
        sum_ye = sum(p[0] * p[1] for p in elevation_map)
        sum_e2 = sum(p[1] ** 2 for p in elevation_map)
        
        denom = n * sum_e2 - sum_e ** 2
        if abs(denom) < 0.001:
            return None
        
        a = (n * sum_ye - sum_y * sum_e) / denom
        b = (sum_y - a * sum_e) / n
        
        # 返回从cad_y计算elevation的函数
        return lambda cad_y: (cad_y - b) / a
    
    elev_func = build_elevation_func(ruler_elevs)
    if elev_func:
        print(f"[INFO] 成功建立高程映射函数")
    
    # 生成XYZ数据
    excav_xyz = []
    overexc_xyz = []
    
    # 处理开挖线
    for station, entities in excav_by_station.items():
        station_str = f"K{station//1000}+{station%1000:03d}"
        
        for entity in entities:
            for pt in entity['pts']:
                x, y = pt
                z = elev_func(y) if elev_func else 0
                excav_xyz.append({
                    'x': x,
                    'y': y,
                    'z': z,
                    'station': station,
                    'station_str': station_str
                })
    
    # 处理超挖线
    for station, entities in overexc_by_station.items():
        station_str = f"K{station//1000}+{station%1000:03d}"
        
        for entity in entities:
            for pt in entity['pts']:
                x, y = pt
                z = elev_func(y) if elev_func else 0
                overexc_xyz.append({
                    'x': x,
                    'y': y,
                    'z': z,
                    'station': station,
                    'station_str': station_str
                })
    
    print(f"\n[RESULT] 开挖线数据点: {len(excav_xyz)}")
    print(f"[RESULT] 超挖线数据点: {len(overexc_xyz)}")
    
    # 保存文件
    excav_path = r"D:\断面算量平台\测试文件\开挖线_xyz.txt"
    with open(excav_path, 'w', encoding='utf-8') as f:
        f.write("# 开挖线XYZ数据\n")
        f.write("# X=横向偏移, Y=纵向位置(与桩号相关), Z=高程\n")
        f.write("# Station=桩号值, StationStr=桩号字符串\n")
        f.write("# X Y Z Station StationStr\n")
        for d in sorted(excav_xyz, key=lambda x: (x['station'], x['x'])):
            f.write(f"{d['x']:.3f} {d['y']:.3f} {d['z']:.3f} {d['station']} {d['station_str']}\n")
    
    overexc_path = r"D:\断面算量平台\测试文件\超挖线_xyz.txt"
    with open(overexc_path, 'w', encoding='utf-8') as f:
        f.write("# 超挖线XYZ数据\n")
        f.write("# X=横向偏移, Y=纵向位置(与桩号相关), Z=高程\n")
        f.write("# Station=桩号值, StationStr=桩号字符串\n")
        f.write("# X Y Z Station StationStr\n")
        for d in sorted(overexc_xyz, key=lambda x: (x['station'], x['x'])):
            f.write(f"{d['x']:.3f} {d['y']:.3f} {d['z']:.3f} {d['station']} {d['station_str']}\n")
    
    # 生成中心线文件（每个桩号的中心点）
    centerline_path = r"D:\断面算量平台\测试文件\中心线坐标.txt"
    with open(centerline_path, 'w', encoding='utf-8') as f:
        f.write("# 航道中心线坐标\n")
        f.write("# Y_center=桩号Y位置, X_center=0(中心线)\n")
        f.write("# Y_center X_center Station StationStr\n")
        
        for station in sorted(unique_stations):
            station_str = f"K{station//1000}+{station%1000:03d}"
            y_center = station_y_center[station]
            f.write(f"{y_center:.3f} 0.000 {station} {station_str}\n")
    
    print(f"\n[SAVED] {excav_path}")
    print(f"[SAVED] {overexc_path}")
    print(f"[SAVED] {centerline_path}")

if __name__ == '__main__':
    main()