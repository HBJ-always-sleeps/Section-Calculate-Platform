# -*- coding: utf-8 -*-
"""
autosection.py - 独立断面分层算量模块
计算指定高程以下的面积，支持区分/不区分设计和超挖

功能：
1. 使用AA_最终断面线图层中已计算好的断面线
2. 支持区分设计和超挖（5个sheet）或不区分（3个sheet）
3. 输出包含分层线和分类填充的DXF文件
"""

import ezdxf
import os
import re
import datetime
import math
import pandas as pd
from shapely.geometry import LineString, Point, Polygon, box, MultiPolygon
from shapely.ops import unary_union


# ==================== 通用辅助函数 ====================

def hatch_to_polygon(hatch_entity):
    """填充转多边形"""
    polygons = []
    try:
        for path in hatch_entity.paths:
            pts = []
            if hasattr(path, 'vertices') and len(path.vertices) > 0:
                pts = [(v[0], v[1]) for v in path.vertices]
            elif hasattr(path, 'edges'):
                for edge in path.edges:
                    edge_type = type(edge).__name__
                    if edge_type == 'LineEdge':
                        pts.extend([(edge.start[0], edge.start[1]), (edge.end[0], edge.end[1])])
                    elif edge_type in ('ArcEdge', 'EllipseEdge'):
                        try:
                            pts.extend([(p.x, p.y) for p in edge.flattening(distance=0.01)])
                        except:
                            pass
            if len(pts) >= 3:
                poly = Polygon(pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if not poly.is_empty:
                    polygons.append(Polygon(poly.exterior))
    except:
        pass
    return unary_union(polygons) if polygons else None


def get_layer_lines(msp, layer_name):
    """从图层获取所有线段"""
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


def detect_ruler_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max):
    """检测标尺比例"""
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
    
    return (lambda elev: a * elev + b, lambda y: (y - b) / a)


def station_sort_key(station_str):
    """桩号排序键"""
    nums = re.findall(r'\d+', str(station_str))
    return int("".join(nums)) if nums else 0


def strata_sort_key(name):
    """地层排序键"""
    nums = re.findall(r'^(\d+)', name)
    return int(nums[0]) if nums else 999


def polygon_to_boundary_points(polygon):
    """将多边形转换为边界点列表"""
    if polygon.is_empty:
        return []
    
    boundaries = []
    
    if hasattr(polygon, 'exterior'):
        ext_coords = list(polygon.exterior.coords)
        if len(ext_coords) >= 3:
            boundaries.append(ext_coords)
        for interior in polygon.interiors:
            int_coords = list(interior.coords)
            if len(int_coords) >= 3:
                boundaries.append(int_coords)
    elif isinstance(polygon, MultiPolygon):
        for p in polygon.geoms:
            ext_coords = list(p.exterior.coords)
            if len(ext_coords) >= 3:
                boundaries.append(ext_coords)
            for interior in p.interiors:
                int_coords = list(interior.coords)
                if len(int_coords) >= 3:
                    boundaries.append(int_coords)
    
    return boundaries


def get_y_at_x(line, x):
    """获取指定X处的Y值"""
    coords = list(line.coords)
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        if (x1 <= x <= x2) or (x2 <= x <= x1):
            if abs(x2 - x1) < 0.001:
                return y1
            t = (x - x1) / (x2 - x1)
            return y1 + t * (y2 - y1)
    return None


def connect_nearby_endpoints(lines, tolerance=2.0):
    """连接临近端点"""
    if not lines:
        return []
    if len(lines) == 1:
        return lines
    
    endpoints = []
    for i, line in enumerate(lines):
        coords = list(line.coords)
        if len(coords) >= 2:
            endpoints.append((coords[0][0], coords[0][1], i, True))
            endpoints.append((coords[-1][0], coords[-1][1], i, False))
    
    connections = []
    used = set()
    
    for i in range(len(endpoints)):
        if i in used:
            continue
        x1, y1, line_idx1, is_start1 = endpoints[i]
        best_j = -1
        best_dist = tolerance + 1
        
        for j in range(len(endpoints)):
            if i == j or j in used:
                continue
            x2, y2, line_idx2, is_start2 = endpoints[j]
            if line_idx1 == line_idx2:
                continue
            dist = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_j = j
        
        if best_j >= 0 and best_dist <= tolerance:
            x2, y2, line_idx2, is_start2 = endpoints[best_j]
            connections.append((line_idx1, is_start1, line_idx2, is_start2, x1, y1, x2, y2))
            used.add(i)
            used.add(best_j)
    
    all_lines = list(lines)
    for line_idx1, is_start1, line_idx2, is_start2, x1, y1, x2, y2 in connections:
        conn_line = LineString([(x1, y1), (x2, y2)])
        all_lines.append(conn_line)
    
    from shapely.ops import linemerge
    merged = linemerge(unary_union(all_lines))
    
    if isinstance(merged, MultiPolygon):
        return list(merged.geoms)
    elif isinstance(merged, LineString):
        return [merged]
    else:
        return all_lines


def build_design_polygon(excav_lines, sect_x_min, sect_x_max, sect_y_max):
    """构建设计区多边形（开挖线最低点以内）"""
    if not excav_lines:
        return None
    
    all_points = []
    for l in excav_lines:
        for pt in l.coords:
            all_points.append(pt)
    
    if not all_points:
        return None
    
    excav_x_min = min(p[0] for p in all_points)
    excav_x_max = max(p[0] for p in all_points)
    
    design_x_min = max(excav_x_min, sect_x_min)
    design_x_max = min(excav_x_max, sect_x_max)
    
    if design_x_max <= design_x_min:
        return None
    
    # 采样开挖线上的最低点
    x_samples = []
    y_samples = []
    x_current = design_x_min
    
    while x_current <= design_x_max:
        min_y_at_x = None
        for line in excav_lines:
            y_on_line = get_y_at_x(line, x_current)
            if y_on_line is not None:
                if min_y_at_x is None or y_on_line < min_y_at_x:
                    min_y_at_x = y_on_line
        
        if min_y_at_x is not None:
            x_samples.append(x_current)
            y_samples.append(min_y_at_x)
        
        x_current += 1.0
    
    if len(x_samples) < 2:
        return None
    
    # 构建多边形：开挖线最低点 + 上边界闭合
    design_coords = []
    for x, y in zip(x_samples, y_samples):
        design_coords.append((x, y))
    
    # 右边界向上
    design_coords.append((x_samples[-1], sect_y_max + 10))
    # 左边界
    design_coords.append((x_samples[0], sect_y_max + 10))
    design_coords.append(design_coords[0])  # 闭合
    
    poly = Polygon(design_coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    
    return poly


# 地层颜色映射
STRATA_COLORS = {
    '1级淤泥': 11,
    '1级淤泥质土': 12,
    '2级淤泥': 31,
    '3级淤泥': 32,
    '3级粘土': 33,
    '4级粘土': 41,
    '4级淤泥': 42,
    '5级粘土': 51,
    '6级砂': 61,
    '6级碎石': 62,
    '7级砂': 71,
    '8级砂': 81,
    '9级碎石': 91,
}

# 高对比度颜色（用于区分设计/超挖填充）
HIGH_CONTRAST_COLORS = [
    (255, 0, 0), (0, 200, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255),
    (255, 128, 0), (128, 0, 255), (0, 128, 255), (255, 0, 128), (128, 255, 0), (0, 255, 128),
]


def add_hatch_to_dxf(msp, poly, layer_name, color_index=7, rgb_color=None):
    """添加填充到DXF"""
    if poly is None or poly.is_empty:
        return
    
    boundaries = polygon_to_boundary_points(poly)
    if not boundaries:
        return
    
    dxfattribs = {'layer': layer_name, 'hatch_style': 0, 'color': color_index}
    
    hatch = msp.add_hatch(dxfattribs=dxfattribs)
    hatch.set_pattern_fill('SOLID', scale=1.0)
    
    if rgb_color:
        hatch.rgb = rgb_color
    
    for boundary_pts in boundaries:
        if len(boundary_pts) >= 3:
            hatch.paths.add_polyline_path(boundary_pts, is_closed=True)


def calc_area_below_elevation(
    input_path, 
    target_elevation=-13.5,
    distinguish_design_excavate=False,
    output_hatch=True,
    log_func=None
):
    """
    计算指定高程以下的面积
    
    Args:
        input_path: 输入DXF文件路径
        target_elevation: 目标高程（如-10.0表示-10m以下）
        distinguish_design_excavate: 是否区分设计和超挖
            - False: 不区分，输出3个sheet（明细表、地层汇总、汇总）
            - True: 区分，输出5个sheet（设计量、超挖量、总量、地层汇总、汇总）
        output_hatch: 是否输出填充到DXF
        log_func: 日志函数
    
    Returns:
        (results, output_dxf_path) 或 ([], None)
    """
    def log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)
    
    log(f"[INFO] 正在读取文件: {os.path.basename(input_path)}")
    log(f"[INFO] 目标高程: {target_elevation}m")
    log(f"[INFO] 区分设计/超挖: {'是' if distinguish_design_excavate else '否'}")
    
    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()
    
    all_layers = [l.dxf.name for l in doc.layers]
    log(f"[INFO] 图层总数: {len(all_layers)}")
    
    if 'AA_最终断面线' not in all_layers:
        log("[ERROR] 未找到AA_最终断面线图层！")
        return [], None
    
    # 获取地层图层列表
    strata_layers = sorted(
        [l for l in all_layers if re.match(r'^\d+级', l)],
        key=strata_sort_key
    )
    log(f"[INFO] 地层图层: {strata_layers}")
    
    # 获取AA_最终断面线列表
    final_section_list = []
    for e in msp.query('*[layer=="AA_最终断面线"]'):
        if e.dxftype() == 'LWPOLYLINE':
            pts = [p[:2] for p in e.get_points()]
            if pts:
                x_min = min(p[0] for p in pts)
                x_max = max(p[0] for p in pts)
                y_min = min(p[1] for p in pts)
                y_max = max(p[1] for p in pts)
                final_section_list.append({
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'pts': pts, 'line': LineString(pts),
                    'y_center': (y_min + y_max) / 2
                })
    
    final_section_list = sorted(final_section_list, key=lambda d: d['y_center'], reverse=True)
    log(f"[INFO] AA_最终断面线数量: {len(final_section_list)}")
    
    # 获取桩号文本
    station_texts = []
    for layer in ["0-桩号", "桩号", "AA_桩号"]:
        for e in msp.query(f'*[layer=="{layer}"]'):
            if e.dxftype() in ('TEXT', 'MTEXT'):
                try:
                    x, y = e.dxf.insert.x, e.dxf.insert.y
                    text = e.dxf.text if e.dxftype() == 'TEXT' else e.text
                    text = text.split(";")[-1].replace("}", "").strip()
                    if re.match(r'^[Kk]?\d*\+?\d+$', text) or re.match(r'^[Kk]\d+\+\d+', text):
                        station_texts.append({'text': text, 'x': x, 'y': y})
                except:
                    pass
    log(f"[INFO] 桩号数量: {len(station_texts)}")
    
    station_texts_sorted = sorted(station_texts, key=lambda s: s['y'], reverse=True)
    
    def find_nearest_station(sect_x_center, sect_y_center, used_stations):
        best_station = None
        best_dist = float('inf')
        
        for st in station_texts_sorted:
            if st['text'] in used_stations:
                continue
            dist = ((st['x'] - sect_x_center)**2 * 0.5 + (st['y'] - sect_y_center)**2)**0.5
            if dist < best_dist:
                best_dist = dist
                best_station = st
        
        return best_station, best_dist
    
    # 获取开挖线和超挖线
    excav_lines_all = get_layer_lines(msp, "开挖线")
    overexc_lines_all = get_layer_lines(msp, "超挖线")
    log(f"[INFO] 开挖线数量: {len(excav_lines_all)}")
    log(f"[INFO] 超挖线数量: {len(overexc_lines_all)}")
    
    # 读取地层填充
    strata_hatches = {}
    for layer in strata_layers:
        strata_hatches[layer] = []
        for h in msp.query(f'HATCH[layer=="{layer}"]'):
            poly = hatch_to_polygon(h)
            if poly and not poly.is_empty:
                strata_hatches[layer].append(poly)
        if strata_hatches[layer]:
            log(f"  {layer}: {len(strata_hatches[layer])}个填充")
    
    # 创建输出文档
    output_doc = ezdxf.readfile(input_path)
    output_msp = output_doc.modelspace()
    
    # 创建图层
    layer_name_elev = f"分层线_{target_elevation}m"
    if layer_name_elev not in [l.dxf.name for l in output_doc.layers]:
        output_doc.layers.new(name=layer_name_elev, dxfattribs={'color': 1})
    
    # 为每个地层创建输出图层（区分设计/超挖时创建两组）
    strata_output_layers = {}
    for layer in strata_layers:
        if distinguish_design_excavate:
            # 设计图层
            design_layer = f"{target_elevation}m_{layer}_设计"
            if design_layer not in [l.dxf.name for l in output_doc.layers]:
                output_doc.layers.new(name=design_layer, dxfattribs={'color': STRATA_COLORS.get(layer, 7)})
            # 超挖图层
            over_layer = f"{target_elevation}m_{layer}_超挖"
            if over_layer not in [l.dxf.name for l in output_doc.layers]:
                output_doc.layers.new(name=over_layer, dxfattribs={'color': STRATA_COLORS.get(layer, 7)})
            strata_output_layers[layer] = {'design': design_layer, 'over': over_layer}
        else:
            output_layer = f"{target_elevation}m_{layer}"
            if output_layer not in [l.dxf.name for l in output_doc.layers]:
                output_doc.layers.new(name=output_layer, dxfattribs={'color': STRATA_COLORS.get(layer, 7)})
            strata_output_layers[layer] = output_layer
    
    results = []
    used_stations = set()
    
    for idx, sect in enumerate(final_section_list):
        sect_x_min = sect['x_min']
        sect_x_max = sect['x_max']
        sect_y_min = sect['y_min']
        sect_y_max = sect['y_max']
        sect_y_center = sect['y_center']
        sect_x_center = (sect_x_min + sect_x_max) / 2
        
        # 桩号匹配
        nearest_st, dist = find_nearest_station(sect_x_center, sect_y_center, used_stations)
        
        if nearest_st and dist < 500:
            station = nearest_st['text']
            used_stations.add(station)
        else:
            station = f"S{idx+1}"
        
        # 检测标尺比例
        ruler_scale = detect_ruler_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max)
        
        if ruler_scale:
            elev_to_y, y_to_elev = ruler_scale
            target_line_y = elev_to_y(target_elevation)
        else:
            target_line_y = 5.0 * target_elevation - 27.0
        
        # 构建开挖区域多边形
        sect_coords = sect['pts']
        bottom_y = sect_y_min - 50
        total_open_poly = Polygon(sect_coords + [(sect_x_max, bottom_y), (sect_x_min, bottom_y)]).buffer(0)
        
        if total_open_poly.is_empty:
            # 记录空结果
            result = {'断面名称': station, '分层线高程': target_elevation, '总面积': 0.0}
            for layer in strata_layers:
                if distinguish_design_excavate:
                    result[f'{layer}_设计'] = 0.0
                    result[f'{layer}_超挖'] = 0.0
                else:
                    result[layer] = 0.0
            results.append(result)
            continue
        
        # 判断分层线位置
        if target_line_y < sect_y_min:
            # 高程线在断面底部以下，面积为0
            result = {'断面名称': station, '分层线高程': target_elevation, '总面积': 0.0}
            for layer in strata_layers:
                if distinguish_design_excavate:
                    result[f'{layer}_设计'] = 0.0
                    result[f'{layer}_超挖'] = 0.0
                else:
                    result[layer] = 0.0
            results.append(result)
            continue
        
        if target_line_y >= sect_y_max:
            # 高程线在断面顶部以上，使用整个断面
            below_layer_open = total_open_poly
        else:
            # 高程线穿过断面，计算交线以下部分
            below_layer_poly = box(sect_x_min - 10, sect_y_min - 100, sect_x_max + 10, target_line_y)
            below_layer_open = total_open_poly.intersection(below_layer_poly)
        
        if below_layer_open.is_empty:
            result = {'断面名称': station, '分层线高程': target_elevation, '总面积': 0.0}
            for layer in strata_layers:
                if distinguish_design_excavate:
                    result[f'{layer}_设计'] = 0.0
                    result[f'{layer}_超挖'] = 0.0
                else:
                    result[layer] = 0.0
            results.append(result)
            continue
        
        # 绘制高程线
        if output_hatch:
            if target_line_y >= sect_y_max:
                line_pts = [(sect_x_min - 5, sect_y_max), (sect_x_max + 5, sect_y_max)]
                output_msp.add_lwpolyline(line_pts, dxfattribs={'layer': layer_name_elev, 'color': 1, 'linetype': 'DASHED'})
            elif target_line_y > sect_y_min:
                line_pts = [(sect_x_min - 5, target_line_y), (sect_x_max + 5, target_line_y)]
                output_msp.add_lwpolyline(line_pts, dxfattribs={'layer': layer_name_elev, 'color': 1})
        
        # 构建设计区多边形（如果需要区分设计/超挖）
        design_polygon = None
        if distinguish_design_excavate:
            boundary_box = box(sect_x_min - 20, sect_y_min - 50, sect_x_max + 20, sect_y_max + 50)
            excav_in_section = [l for l in excav_lines_all if boundary_box.intersects(l)]
            
            if excav_in_section:
                excav_connected = connect_nearby_endpoints(excav_in_section, tolerance=2.0)
                design_polygon = build_design_polygon(excav_connected, sect_x_min, sect_x_max, sect_y_max)
        
        # 统计各地层面积
        boundary_box = box(sect_x_min - 20, sect_y_min - 50, sect_x_max + 20, sect_y_max + 50)
        strata_areas = {}
        total_area = 0.0
        
        for layer in strata_layers:
            design_area = 0.0
            over_area = 0.0
            total_layer_area = 0.0
            
            design_polys = []
            over_polys = []
            
            for h_poly in strata_hatches[layer]:
                try:
                    if not boundary_box.intersects(h_poly):
                        continue
                    
                    inter = h_poly.intersection(below_layer_open)
                    if inter.is_empty:
                        continue
                    
                    if distinguish_design_excavate and design_polygon:
                        # 区分设计区和超挖区
                        design_part = inter.intersection(design_polygon)
                        over_part = inter.difference(design_polygon)
                        
                        if not design_part.is_empty:
                            if isinstance(design_part, Polygon):
                                design_area += design_part.area
                                design_polys.append(design_part)
                            elif hasattr(design_part, 'geoms'):
                                for g in design_part.geoms:
                                    if isinstance(g, Polygon):
                                        design_area += g.area
                                        design_polys.append(g)
                        
                        if not over_part.is_empty:
                            if isinstance(over_part, Polygon):
                                over_area += over_part.area
                                over_polys.append(over_part)
                            elif hasattr(over_part, 'geoms'):
                                for g in over_part.geoms:
                                    if isinstance(g, Polygon):
                                        over_area += g.area
                                        over_polys.append(g)
                    else:
                        # 不区分，计算总面积
                        if isinstance(inter, Polygon):
                            total_layer_area += inter.area
                            design_polys.append(inter)
                        elif hasattr(inter, 'geoms'):
                            for g in inter.geoms:
                                if isinstance(g, Polygon):
                                    total_layer_area += g.area
                                    design_polys.append(g)
                except:
                    pass
            
            if distinguish_design_excavate:
                strata_areas[f'{layer}_设计'] = round(design_area, 3)
                strata_areas[f'{layer}_超挖'] = round(over_area, 3)
                total_area += design_area + over_area
                
                # 输出填充
                if output_hatch:
                    color_idx = STRATA_COLORS.get(layer, 7)
                    rgb_color = HIGH_CONTRAST_COLORS[strata_layers.index(layer) % len(HIGH_CONTRAST_COLORS)]
                    
                    for poly in design_polys:
                        add_hatch_to_dxf(output_msp, poly, strata_output_layers[layer]['design'], color_idx, rgb_color)
                    
                    for poly in over_polys:
                        add_hatch_to_dxf(output_msp, poly, strata_output_layers[layer]['over'], color_idx, rgb_color)
            else:
                strata_areas[layer] = round(total_layer_area, 3)
                total_area += total_layer_area
                
                if output_hatch and total_layer_area > 0.01:
                    color_idx = STRATA_COLORS.get(layer, 7)
                    for poly in design_polys:
                        add_hatch_to_dxf(output_msp, poly, strata_output_layers[layer], color_idx)
        
        result = {
            '断面名称': station,
            '分层线高程': target_elevation,
            **strata_areas,
            '总面积': round(total_area, 3)
        }
        results.append(result)
        
        if (idx + 1) % 50 == 0:
            log(f"  已处理 {idx+1}/{len(final_section_list)} 个断面...")
    
    # 排序结果
    results.sort(key=lambda x: station_sort_key(x['断面名称']))
    
    # 保存DXF
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.basename(input_path).replace('.dxf', '')
    output_dir = os.path.dirname(input_path)
    output_dxf = os.path.join(output_dir, f"{base_name}_{target_elevation}m分层_{timestamp}.dxf")
    
    output_doc.saveas(output_dxf)
    log(f"[INFO] DXF文件已保存: {output_dxf}")
    
    return results, output_dxf


def generate_excel_report(results, strata_layers, input_path, target_elevation, distinguish_design_excavate):
    """生成Excel报告
    
    不区分设计/超挖: 明细表、地层汇总、汇总
    区分设计/超挖: 设计量、超挖量、总量、地层汇总、汇总
    """
    if not results:
        return None
    
    df = pd.DataFrame(results)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.basename(input_path).replace('.dxf', '')
    output_dir = os.path.dirname(input_path)
    output_xlsx = os.path.join(output_dir, f"{base_name}_{target_elevation}m以下面积_{timestamp}.xlsx")
    
    with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
        if distinguish_design_excavate:
            # 设计量sheet
            design_cols = ['断面名称'] + [c for c in df.columns if c.endswith('_设计')]
            df_design = df[design_cols].copy()
            df_design.columns = ['断面名称'] + [c.replace('_设计', '') for c in df.columns if c.endswith('_设计')]
            df_design.to_excel(writer, sheet_name='设计量', index=False)
            
            # 超挖量sheet
            over_cols = ['断面名称'] + [c for c in df.columns if c.endswith('_超挖')]
            df_over = df[over_cols].copy()
            df_over.columns = ['断面名称'] + [c.replace('_超挖', '') for c in df.columns if c.endswith('_超挖')]
            df_over.to_excel(writer, sheet_name='超挖量', index=False)
            
            # 总量sheet（设计+超挖）
            df_total = df[['断面名称']].copy()
            for layer in strata_layers:
                design_col = f'{layer}_设计'
                over_col = f'{layer}_超挖'
                total_val = 0.0
                if design_col in df.columns:
                    total_val = total_val + df[design_col].fillna(0)
                if over_col in df.columns:
                    total_val = total_val + df[over_col].fillna(0)
                df_total[layer] = total_val
            df_total.to_excel(writer, sheet_name='总量', index=False)
        else:
            # 明细表（不区分设计/超挖）
            df.to_excel(writer, sheet_name='明细表', index=False)
        
        # 地层汇总sheet
        if distinguish_design_excavate:
            # 设计量汇总
            design_summary = {'地层': [], '设计面积(㎡)': []}
            for layer in strata_layers:
                col = f'{layer}_设计'
                design_summary['地层'].append(layer)
                design_summary['设计面积(㎡)'].append(df[col].sum() if col in df.columns else 0.0)
            df_design_summary = pd.DataFrame(design_summary)
            
            # 超挖量汇总
            over_summary = {'地层': [], '超挖面积(㎡)': []}
            for layer in strata_layers:
                col = f'{layer}_超挖'
                over_summary['地层'].append(layer)
                over_summary['超挖面积(㎡)'].append(df[col].sum() if col in df.columns else 0.0)
            df_over_summary = pd.DataFrame(over_summary)
            
            # 合并
            df_strata_summary = pd.merge(df_design_summary, df_over_summary, on='地层', how='outer')
            df_strata_summary['总面积(㎡)'] = df_strata_summary['设计面积(㎡)'] + df_strata_summary['超挖面积(㎡)']
        else:
            strata_cols = [c for c in df.columns if '级' in c]
            summary_data = {
                '地层': strata_cols,
                '面积(㎡)': [df[c].sum() for c in strata_cols]
            }
            df_strata_summary = pd.DataFrame(summary_data)
        
        df_strata_summary.to_excel(writer, sheet_name='地层汇总', index=False)
        
        # 汇总sheet
        total_data = {
            '统计项': ['总断面数', f'{target_elevation}m以下总面积'],
            '数值': [len(results), df['总面积'].sum()]
        }
        total_df = pd.DataFrame(total_data)
        total_df.to_excel(writer, sheet_name='汇总', index=False)
    
    return output_xlsx


def main():
    """主函数"""
    input_path = r"D:\断面算量平台\测试文件\内湾段分层图（全航道）_RESULT_20260318_152025.dxf"
    
    # 测试区分设计/超挖
    target_elevation = -10.0
    distinguish_design_excavate = True
    
    print(f"\n{'='*60}")
    print(f"[INFO] 开始处理高程: {target_elevation}m")
    print(f"[INFO] 区分设计/超挖: {distinguish_design_excavate}")
    print(f"{'='*60}\n")
    
    results, output_dxf = calc_area_below_elevation(
        input_path, 
        target_elevation=target_elevation,
        distinguish_design_excavate=distinguish_design_excavate
    )
    
    if results:
        # 获取地层列表
        all_layers = [l for l in results[0].keys() if '级' in l and '_' in l]
        strata_layers = sorted(set([l.replace('_设计', '').replace('_超挖', '') for l in all_layers]), key=strata_sort_key)
        
        output_xlsx = generate_excel_report(
            results, strata_layers, input_path, target_elevation, distinguish_design_excavate
        )
        
        print(f"\n[OK] 处理完成！")
        print(f"  结果Excel: {output_xlsx}")
        print(f"  结果DXF: {output_dxf}")
        print(f"  总断面数: {len(results)}")
        
        df = pd.DataFrame(results)
        print(f"  {target_elevation}m以下总面积: {df['总面积'].sum():.3f} ㎡")
    else:
        print("[WARN] 未生成任何数据")


if __name__ == "__main__":
    main()