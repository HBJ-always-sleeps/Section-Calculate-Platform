# -*- coding: utf-8 -*-
"""
autoclassify.py - 断面分类算量
修复记录：
- 20260309: 用超挖线构建虚拟断面框，替代超挖框
- 20260309: 用开挖线最低Y判定设计区/超挖区
"""
import ezdxf
import pandas as pd
import os
import re
import datetime
import math
from shapely.geometry import LineString, Point, Polygon, MultiPolygon, MultiLineString, box
from shapely.ops import unary_union, linemerge, polygonize

STRATA_REGEX = r'^\d+级.*'
EXTEND_DIST = 100.0
LY_FINAL_SECTION = "AA_最终断面线"
LY_OUTPUT_HATCH = "AA_分类填充"
LY_OUTPUT_LABEL = "AA_分类标注"
TEXT_HEIGHT = 2.5

def log(msg):
    print(f"[*] {msg}")

def extend_line_to_pierce(line, dist):
    coords = list(line.coords)
    if len(coords) < 2: return line
    p1, p2 = Point(coords[0]), Point(coords[1])
    dx, dy = p1.x - p2.x, p1.y - p2.y
    length = math.sqrt(dx**2 + dy**2) or 1
    coords.insert(0, (p1.x + dx/length * dist, p1.y + dy/length * dist))
    p_last, p_prev = Point(coords[-1]), Point(coords[-2])
    dx, dy = p_last.x - p_prev.x, p_last.y - p_prev.y
    length = math.sqrt(dx**2 + dy**2) or 1
    coords.append((p_last.x + dx/length * dist, p_last.y + dy/length * dist))
    return LineString(coords)

def hatch_to_polygon(hatch_entity):
    polygons = []
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
                    try: pts.extend([(p.x, p.y) for p in edge.flattening(distance=0.01)])
                    except: pass
        if len(pts) >= 3:
            poly = Polygon(pts)
            if not poly.is_valid: poly = poly.buffer(0)
            if not poly.is_empty:
                polygons.append(Polygon(poly.exterior))
    return unary_union(polygons)

def get_y_at_x(line, x):
    """获取线段在指定X坐标处的Y值"""
    b = line.bounds
    if x < b[0] or x > b[2]:
        return None
    v_line = LineString([(x, b[1] - 100), (x, b[3] + 100)])
    try:
        inter = line.intersection(v_line)
        if inter.is_empty: return None
        if inter.geom_type == 'Point': return inter.y
        if inter.geom_type in ('MultiPoint', 'LineString'):
            coords = inter.coords if inter.geom_type == 'LineString' else [p.coords[0] for p in inter.geoms]
            return min(c[1] for c in coords)
    except: return None
    return None

def find_intersections(line1, line2):
    """找出两条线的所有交点"""
    try:
        inter = line1.intersection(line2)
        if inter.is_empty:
            return []
        if inter.geom_type == 'Point':
            return [(inter.x, inter.y)]
        if inter.geom_type == 'MultiPoint':
            return [(p.x, p.y) for p in inter.geoms]
        if inter.geom_type == 'LineString':
            return list(inter.coords)
        if inter.geom_type == 'GeometryCollection':
            pts = []
            for g in inter.geoms:
                if g.geom_type == 'Point':
                    pts.append((g.x, g.y))
            return pts
    except:
        pass
    return []

def generate_complete_final_section(dmx, section_lines):
    """生成完整的最终断面线 - 交点附近密集采样确保贴合
    
    算法：
    1. 收集所有源线的顶点X坐标
    2. 找出所有交点，在交点±1单位内增加密集采样点
    3. 对每个X坐标，计算所有线在该位置的Y值，取最低
    """
    # 收集所有线的X坐标
    all_x_coords = set()
    
    # DMX的所有顶点X
    for pt in dmx.coords:
        all_x_coords.add(round(pt[0], 3))
    
    # 其他断面线的所有顶点X
    for sec in section_lines:
        for pt in sec.coords:
            all_x_coords.add(round(pt[0], 3))
    
    # 找出所有交点，在交点附近增加密集采样
    intersection_x = set()
    all_lines = [dmx] + list(section_lines)
    
    for i in range(len(all_lines)):
        for j in range(i + 1, len(all_lines)):
            intersections = find_intersections(all_lines[i], all_lines[j])
            for ix, iy in intersections:
                # 交点本身
                intersection_x.add(round(ix, 3))
                # 交点±1单位内密集采样（步长0.1）
                for delta in [-1.0, -0.9, -0.8, -0.7, -0.6, -0.5, -0.4, -0.3, -0.2, -0.1,
                              0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
                    intersection_x.add(round(ix + delta, 3))
    
    # 合并所有X坐标
    all_x_coords.update(intersection_x)
    
    if not all_x_coords:
        return None
    
    # 排序X坐标
    sorted_x = sorted(all_x_coords)
    
    # 获取DMX的X范围作为边界
    dmx_bounds = dmx.bounds
    x_min = dmx_bounds[0]
    x_max = dmx_bounds[2]
    
    # 过滤在DMX范围内的X坐标
    filtered_x = [x for x in sorted_x if x_min <= x <= x_max]
    
    if not filtered_x:
        return None
    
    # 对每个X坐标计算最低Y值
    coords = []
    for x in filtered_x:
        all_ys = []
        
        # DMX在该X的Y值
        dmx_y = get_y_at_x(dmx, x)
        if dmx_y is not None:
            all_ys.append(dmx_y)
        
        # 其他断面线在该X的Y值
        for sec in section_lines:
            sec_y = get_y_at_x(sec, x)
            if sec_y is not None:
                all_ys.append(sec_y)
        
        if all_ys:
            min_y = min(all_ys)
            coords.append((x, min_y))
    
    if len(coords) >= 2:
        return LineString(coords)
    return None

# 高区分度颜色列表 - 根据HSL色轮均匀选取，确保相邻颜色差异大
# 格式: (R, G, B) - 颜色名称
HIGH_CONTRAST_COLORS = [
    (255, 0, 0),      # 红色
    (0, 200, 0),      # 绿色
    (0, 0, 255),      # 蓝色
    (255, 255, 0),    # 黄色
    (255, 0, 255),    # 品红
    (0, 255, 255),    # 青色
    (255, 128, 0),    # 橙色
    (128, 0, 255),    # 紫色
    (0, 128, 255),    # 天蓝
    (255, 0, 128),    # 玫红
    (128, 255, 0),    # 黄绿
    (0, 255, 128),    # 青绿
    (128, 128, 0),    # 橄榄
    (0, 128, 128),    # 深青
    (128, 0, 128),    # 紫红
    (200, 100, 50),   # 棕色
    (50, 200, 100),   # 薄荷绿
    (100, 50, 200),   # 靛蓝
    (200, 50, 150),   # 梅红
    (50, 150, 200),   # 浅蓝
]

def get_strata_color(strata_name, strata_list):
    """根据地层名称获取高区分度颜色
    
    Args:
        strata_name: 地层名称
        strata_list: 所有地层名称列表（已按数字排序）
    
    Returns:
        RGB颜色元组
    """
    if strata_name in strata_list:
        idx = strata_list.index(strata_name) % len(HIGH_CONTRAST_COLORS)
        return HIGH_CONTRAST_COLORS[idx]
    return HIGH_CONTRAST_COLORS[0]

def add_hatch_with_label(msp, poly, layer_hatch, layer_label, rgb_color, pattern, scale, text_height, strata_name, is_design):
    if not poly or poly.is_empty: return 0.0
    if isinstance(poly, (LineString, Point)):
        return 0.0
    geoms = [poly] if isinstance(poly, Polygon) else list(poly.geoms) if hasattr(poly, 'geoms') else [poly]
    total_area = 0.0
    label_type = "设计" if is_design else "超挖"
    full_label = f"{strata_name}{label_type}"
    for p in geoms:
        if isinstance(p, (LineString, Point)): continue
        if p.area < 0.01: continue
        total_area += p.area
        hatch = msp.add_hatch(dxfattribs={'layer': layer_hatch})
        hatch.rgb = rgb_color
        hatch.set_pattern_fill(pattern, scale=scale)
        hatch.paths.add_polyline_path(list(p.exterior.coords), is_closed=True)
        for interior in p.interiors:
            hatch.paths.add_polyline_path(list(interior.coords), is_closed=True)
        area_val = round(p.area, 3)
        if area_val > 0.1:
            try:
                in_point = p.representative_point()
                label_content = f"{{\\fArial|b1;{full_label}\\P{area_val}}}"
                mtext = msp.add_mtext(label_content, dxfattribs={
                    'layer': layer_label, 'insert': (in_point.x, in_point.y),
                    'char_height': text_height, 'attachment_point': 5,
                })
                mtext.rgb = rgb_color
                try:
                    mtext.dxf.bg_fill_setting = 1
                    mtext.dxf.bg_fill_scale_factor = 1.3
                except: pass
            except: pass
    return total_area

def get_layer_lines(msp, layer_name):
    res = []
    for e in msp.query(f'*[layer=="{layer_name}"]'):
        try:
            if e.dxftype() == 'LWPOLYLINE':
                pts = [p[:2] for p in e.get_points()]
                if len(pts) >= 2: res.append(LineString(pts))
            elif e.dxftype() == 'POLYLINE':
                pts = [v.dxf.location.vec2 for v in e.vertices]
                if len(pts) >= 2: res.append(LineString(pts))
            elif e.dxftype() == 'LINE':
                res.append(LineString([e.dxf.start.vec2, e.dxf.end.vec2]))
        except: pass
    return res

def connect_nearby_endpoints(lines, tolerance=2.0):
    """连接相近的端点，构建连续的开挖线
    
    算法：
    1. 收集所有线段的端点
    2. 找出距离 < tolerance 的端点对
    3. 添加连接线段
    4. 用 linemerge 合并所有线段
    
    Returns:
        合并后的线段列表（保留所有折角）
    """
    if not lines:
        return []
    
    if len(lines) == 1:
        return lines
    
    # 收集所有端点及其所属线段索引
    endpoints = []  # [(x, y, line_idx, is_start)]
    for i, line in enumerate(lines):
        coords = list(line.coords)
        if len(coords) >= 2:
            endpoints.append((coords[0][0], coords[0][1], i, True))   # 起点
            endpoints.append((coords[-1][0], coords[-1][1], i, False))  # 终点
    
    # 找出需要连接的端点对
    connections = []  # [(line_idx1, is_start1, line_idx2, is_start2)]
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
            # 不要连接同一条线的两个端点
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
    
    # 创建连接线段
    all_lines = list(lines)
    for line_idx1, is_start1, line_idx2, is_start2, x1, y1, x2, y2 in connections:
        # 添加连接线
        conn_line = LineString([(x1, y1), (x2, y2)])
        all_lines.append(conn_line)
    
    # 合并所有线段
    merged = linemerge(unary_union(all_lines))
    
    if isinstance(merged, MultiLineString):
        return list(merged.geoms)
    elif isinstance(merged, LineString):
        return [merged]
    else:
        return all_lines

def get_y_on_line_at_x(line, x):
    """计算线段在指定X坐标处的Y值（线性插值）"""
    coords = list(line.coords)
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        # 检查x是否在这两个点之间
        if (x1 <= x <= x2) or (x2 <= x <= x1):
            if abs(x2 - x1) < 0.001:
                return y1
            t = (x - x1) / (x2 - x1)
            return y1 + t * (y2 - y1)
    return None

def build_design_polygon(excav_lines, section_line, sect_x_min, sect_x_max, min_excav_y):
    """构建设计区多边形
    
    开挖线是断裂的多段线（底部水平段 + 左右侧斜边）
    设计区 = 开挖线上方的区域（只在开挖线X范围内）
    
    重要：开挖线X范围 < 断面线X范围时，两侧没有开挖线的区域是超挖区！
    
    算法（修复版 - 20260310）：
    1. 收集开挖线所有顶点，确定开挖线的实际X范围
    2. 设计区只在开挖线的X范围内构建
    3. 设计区底部边界必须精确贴合开挖线（使用开挖线实际顶点 + 密集采样）
    4. 对开挖线断裂区域进行线性插值
    """
    if not excav_lines:
        return None, sect_x_min, sect_x_max  # 返回空设计区和超挖区X范围
    
    # 收集开挖线所有顶点
    all_points = []
    for l in excav_lines:
        for pt in l.coords:
            all_points.append(pt)
    
    if not all_points:
        return None, sect_x_min, sect_x_max
    
    # 计算开挖线的实际X范围
    excav_x_min = min(p[0] for p in all_points)
    excav_x_max = max(p[0] for p in all_points)
    
    log(f"    开挖线X范围: [{excav_x_min:.1f}, {excav_x_max:.1f}]")
    log(f"    断面线X范围: [{sect_x_min:.1f}, {sect_x_max:.1f}]")
    
    # 设计区只在开挖线X范围内
    design_x_min = max(excav_x_min, sect_x_min)
    design_x_max = min(excav_x_max, sect_x_max)
    
    log(f"    设计区X范围: [{design_x_min:.1f}, {design_x_max:.1f}]")
    
    # 关键修复：使用开挖线实际顶点构建底部边界，确保精确贴合
    # 1. 收集所有开挖线顶点（在X范围内）
    vertex_points = []
    for l in excav_lines:
        for pt in l.coords:
            x, y = pt
            # 使用更宽松的容差，确保边界顶点被包含
            if excav_x_min - 1 <= x <= excav_x_max + 1:
                vertex_points.append((x, y))
    
    # 2. 按X坐标分组，取每个X对应的最低Y
    x_to_min_y = {}
    for x, y in vertex_points:
        x_key = round(x, 2)
        if x_key not in x_to_min_y or y < x_to_min_y[x_key]:
            x_to_min_y[x_key] = y
    
    # 3. 对开挖线进行密集采样，获取每个X位置的精确Y值
    sample_step = 1.0  # 采样步长1单位
    x_samples = []
    y_samples = []
    
    x_current = design_x_min
    while x_current <= design_x_max:
        min_y_at_x = None
        
        # 方法1：从开挖线顶点中查找
        x_key = round(x_current, 2)
        if x_key in x_to_min_y:
            min_y_at_x = x_to_min_y[x_key]
        
        # 方法2：通过线性插值计算每条开挖线在该X处的Y值
        for line in excav_lines:
            y_on_line = get_y_on_line_at_x(line, x_current)
            if y_on_line is not None:
                if min_y_at_x is None or y_on_line < min_y_at_x:
                    min_y_at_x = y_on_line
        
        if min_y_at_x is not None:
            x_samples.append(x_current)
            y_samples.append(min_y_at_x)
        
        x_current += sample_step
    
    # 4. 检测并处理断裂区域（相邻X间距过大）
    gap_threshold = 20.0
    final_x = []
    final_y = []
    
    for i in range(len(x_samples)):
        final_x.append(x_samples[i])
        final_y.append(y_samples[i])
        
        if i < len(x_samples) - 1:
            gap = x_samples[i + 1] - x_samples[i]
            if gap > gap_threshold:
                log(f"    检测到断裂: X=[{x_samples[i]:.1f}, {x_samples[i+1]:.1f}], 间距={gap:.1f}, 进行插值")
                # 插值填充
                num_insert = int(gap / 2.0)
                for j in range(1, num_insert + 1):
                    t = j / (num_insert + 1)
                    interp_x = x_samples[i] + t * gap
                    interp_y = y_samples[i] + t * (y_samples[i + 1] - y_samples[i])
                    final_x.append(interp_x)
                    final_y.append(interp_y)
    
    # 重新排序
    if final_x:
        sorted_pairs = sorted(zip(final_x, final_y), key=lambda p: p[0])
        x_samples = [p[0] for p in sorted_pairs]
        y_samples = [p[1] for p in sorted_pairs]
    
    if len(x_samples) < 2:
        return None, sect_x_min, sect_x_max
    
    # 构建设计区多边形
    # 设计区边界：开挖线上边界 + 左右垂直边界 + 顶部边界（断面线Y值）
    
    # 获取断面线的Y范围
    sect_y_max = max(p[1] for p in section_line.coords) if section_line else min_excav_y + 50
    
    # 构建多边形顶点
    polygon_coords = []
    
    # 底部边界（开挖线，从左到右）
    for x, y in zip(x_samples, y_samples):
        polygon_coords.append((x, y))
    
    # 右边界（向上延伸）
    right_x = x_samples[-1]
    right_y = y_samples[-1]
    polygon_coords.append((right_x, sect_y_max + 10))
    
    # 顶部边界（从右到左）
    left_x = x_samples[0]
    polygon_coords.append((left_x, sect_y_max + 10))
    
    # 闭合多边形
    polygon_coords.append(polygon_coords[0])
    
    if len(polygon_coords) >= 4:
        poly = Polygon(polygon_coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        # 返回设计区多边形 + 左右两侧超挖区的X范围
        left_over_x = (sect_x_min, design_x_min) if design_x_min > sect_x_min else None
        right_over_x = (design_x_max, sect_x_max) if design_x_max < sect_x_max else None
        return poly, left_over_x, right_over_x
    
    return None, sect_x_min, sect_x_max

def build_virtual_boxes_from_overexcav(overexc_lines):
    """从超挖线构建虚拟断面框 - 支持多行布局"""
    if not overexc_lines:
        return []
    
    # 收集所有超挖线信息
    line_info = []
    for line in overexc_lines:
        bounds = line.bounds
        mid_x = (bounds[0] + bounds[2]) / 2
        mid_y = (bounds[1] + bounds[3]) / 2
        line_info.append({'line': line, 'mid_x': mid_x, 'mid_y': mid_y, 'bounds': bounds})
    
    # 按X坐标聚类到各断面列
    def cluster_by_x(lines, x_threshold=200):
        if not lines: return []
        sorted_lines = sorted(lines, key=lambda x: x['mid_x'])
        clusters = []
        current_cluster = [sorted_lines[0]]
        for i in range(1, len(sorted_lines)):
            if abs(sorted_lines[i]['mid_x'] - current_cluster[0]['mid_x']) < x_threshold:
                current_cluster.append(sorted_lines[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [sorted_lines[i]]
        clusters.append(current_cluster)
        return clusters
    
    # 按Y坐标聚类到多行（自适应行数）
    def cluster_by_y(lines, y_threshold=100):
        if not lines: return []
        sorted_lines = sorted(lines, key=lambda x: x['mid_y'], reverse=True)  # Y从大到小
        clusters = []
        current_cluster = [sorted_lines[0]]
        for i in range(1, len(sorted_lines)):
            if abs(sorted_lines[i]['mid_y'] - current_cluster[0]['mid_y']) < y_threshold:
                current_cluster.append(sorted_lines[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [sorted_lines[i]]
        clusters.append(current_cluster)
        return clusters
    
    x_clusters = cluster_by_x(line_info)
    virtual_boxes = []
    
    # 在每个断面列内按Y分多行
    for x_cluster in x_clusters:
        y_clusters = cluster_by_y(x_cluster)
        
        for y_cluster in y_clusters:
            if not y_cluster: continue
            all_coords = []
            for info in y_cluster:
                all_coords.extend(list(info['line'].coords))
            
            if all_coords:
                min_x = min(c[0] for c in all_coords)
                max_x = max(c[0] for c in all_coords)
                min_y = min(c[1] for c in all_coords)
                max_y = max(c[1] for c in all_coords)
                virtual_boxes.append(box(min_x, min_y, max_x, max_y))
    
    return virtual_boxes

def process_autoclassify(input_path, timestamp, section_layers=None, station_layer=None, merge_section=True):
    """主处理函数
    
    Args:
        input_path: 输入DXF文件路径
        timestamp: 时间戳
        section_layers: 断面线图层列表，默认["DMX"]
        station_layer: 桩号图层，默认自动检测
        merge_section: 是否合并断面线图层，True=合并多图层取最低Y，False=只用第一个图层
    """
    if section_layers is None:
        section_layers = ["DMX"]
    
    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()

    if LY_FINAL_SECTION not in doc.layers:
        doc.layers.add(LY_FINAL_SECTION, color=4)
    if LY_OUTPUT_HATCH not in doc.layers:
        doc.layers.add(LY_OUTPUT_HATCH, color=7)
    if LY_OUTPUT_LABEL not in doc.layers:
        doc.layers.add(LY_OUTPUT_LABEL, color=7)

    strata_layers = [l.dxf.name for l in doc.layers if re.match(STRATA_REGEX, l.dxf.name)]
    
    # 按数字顺序排列地层（1级淤泥在2级淤泥前面）
    def strata_sort_key(name):
        nums = re.findall(r'^(\d+)', name)
        return int(nums[0]) if nums else 999
    strata_layers = sorted(strata_layers, key=strata_sort_key)
    
    log(f"地层图层（按数字排序）: {strata_layers}")
    
    for layer_name in strata_layers:
        try: doc.layers.get(layer_name).off()
        except: pass

    excav_lines_all = get_layer_lines(msp, "开挖线")
    overexc_lines_all = get_layer_lines(msp, "超挖线")
    
    # 合并多个断面线图层
    dmx_lines_all = []
    for layer in section_layers:
        dmx_lines_all.extend(get_layer_lines(msp, layer))
    
    log(f"开挖线总数: {len(excav_lines_all)}")
    log(f"超挖线总数: {len(overexc_lines_all)}")
    log(f"断面线总数(DMX): {len(dmx_lines_all)}")

    # 从超挖线构建虚拟断面框
    virtual_boxes = build_virtual_boxes_from_overexcav(overexc_lines_all)
    log(f"虚拟断面框: {len(virtual_boxes)} 个")

    # 获取桩号列表
    station_layer_names = [station_layer] if station_layer else ["桩号", "0-桩号"]
    station_texts = []
    for layer in station_layer_names:
        for e in msp.query(f'*[layer=="{layer}"]'):
            if e.dxftype() in ('TEXT', 'MTEXT'):
                try:
                    x, y = e.dxf.insert.x, e.dxf.insert.y
                    text = e.dxf.text if e.dxftype() == 'TEXT' else e.text
                    text = text.split(";")[-1].replace("}", "").strip()
                    station_texts.append({'text': text, 'x': x, 'y': y})
                except: pass
    
    log(f"桩号总数: {len(station_texts)}")
    
    report_data = []

    for idx, v_box in enumerate(virtual_boxes):
        minx, miny, maxx, maxy = v_box.bounds
        virtual_y_center = (miny + maxy) / 2
        
        # 找该断面的桩号
        station = f"S{idx+1}"
        best_dist = float('inf')
        for st in station_texts:
            pt = Point(st['x'], st['y'])
            if v_box.distance(pt) < 200:
                dist = pt.distance(Point((minx + maxx) / 2, miny))
                if dist < best_dist:
                    best_dist = dist
                    station = st['text']
        
        log(f"\n处理断面 {idx+1}: {station}")
        log(f"  虚拟框: X=[{minx:.1f}, {maxx:.1f}], Y=[{miny:.1f}, {maxy:.1f}]")

        # 找该断面DMX（用虚拟框Y中心匹配）
        # 优先匹配DMX图层，只有DMX图层没有匹配时才用其他图层
        dmx = None
        min_y_diff = float('inf')
        virtual_x_center = (minx + maxx) / 2
        
        # 先在DMX图层中查找
        dmx_layer_lines = get_layer_lines(msp, "DMX")
        for l in dmx_layer_lines:
            b = l.bounds
            if b[0] <= virtual_x_center <= b[2]:
                dmx_y_mid = (b[1] + b[3]) / 2
                y_diff = abs(dmx_y_mid - virtual_y_center)
                if y_diff < min_y_diff:
                    min_y_diff = y_diff
                    dmx = l
        
        # DMX图层没找到，再在其他断面线图层中查找
        if dmx is None:
            for l in dmx_lines_all:
                b = l.bounds
                if b[0] <= virtual_x_center <= b[2]:
                    dmx_y_mid = (b[1] + b[3]) / 2
                    y_diff = abs(dmx_y_mid - virtual_y_center)
                    if y_diff < min_y_diff:
                        min_y_diff = y_diff
                        dmx = l
        
        if not dmx:
            log(f"  警告：未找到DMX，跳过")
            continue
        
        dmx_bounds = dmx.bounds
        dmx_x_min, dmx_x_max = dmx_bounds[0], dmx_bounds[2]
        
        # 找该断面的断面线（包括断面线图层 + section_layers中的其他图层）
        boundary_box = box(minx - 20, miny - 25, maxx + 20, maxy + 25)
        
        if merge_section:
            # 合并模式：收集所有断面线图层，合并取最低Y
            local_section = [l for l in get_layer_lines(msp, "断面线") if boundary_box.intersects(l)]
            
            # 添加section_layers中其他图层的断面线（排除DMX，因为已经作为主dmx）
            for layer in section_layers:
                if layer != "DMX":
                    layer_lines = get_layer_lines(msp, layer)
                    for l in layer_lines:
                        if boundary_box.intersects(l):
                            local_section.append(l)
            
            log(f"  断面线数量: DMX + {len(local_section)}条")
            
            # 生成最终断面线（合并DMX和其他断面线，取最低Y）
            final_sect = generate_complete_final_section(dmx, local_section)
        else:
            # 不合并模式：直接使用DMX作为最终断面线
            log(f"  断面线数量: 仅使用DMX")
            final_sect = dmx
        
        if not final_sect:
            log(f"  警告：最终断面线生成失败，跳过")
            continue
        
        sect_coords = list(final_sect.coords)
        sect_x_min = min(c[0] for c in sect_coords)
        sect_x_max = max(c[0] for c in sect_coords)
        
        log(f"  最终断面线 X范围: [{sect_x_min:.1f}, {sect_x_max:.1f}]")

        msp.add_lwpolyline(sect_coords, dxfattribs={'layer': LY_FINAL_SECTION})

        # 找该断面的开挖线
        excav_list = [l for l in excav_lines_all if boundary_box.intersects(l)]
        
        if not excav_list:
            log(f"  警告：未找到开挖线，跳过")
            continue

        # 收集断面线X范围内的开挖线段
        excav_in_section = []
        for l in excav_list:
            l_bounds = l.bounds
            # 检查线段是否在断面线X范围内（允许一定容差）
            if l_bounds[2] >= sect_x_min - 5 and l_bounds[0] <= sect_x_max + 5:
                excav_in_section.append(l)
        
        if not excav_in_section:
            log(f"  警告：断面线X范围内没有开挖线，跳过")
            continue
        
        log(f"  开挖线段数（断面范围内）: {len(excav_in_section)}")
        
        # 连接相近端点，构建连续的开挖线
        excav_connected = connect_nearby_endpoints(excav_in_section, tolerance=2.0)
        log(f"  连接后开挖线数: {len(excav_connected)}")
        
        # 收集开挖线所有点，计算最低Y
        all_excav_pts = [p for l in excav_connected for p in l.coords]
        min_excav_y = min(p[1] for p in all_excav_pts) if all_excav_pts else miny
        log(f"  开挖线最低Y: {min_excav_y:.1f}")
        
        # 构建设计区多边形
        # 算法：开挖线定义了设计区的底部边界
        # 设计区 = 断面线下方、开挖线上方的区域（只在开挖线X范围内）
        # 返回值：设计区多边形, 左侧超挖区X范围, 右侧超挖区X范围
        design_result = build_design_polygon(excav_in_section, final_sect, sect_x_min, sect_x_max, min_excav_y)
        
        if design_result[0] is None:
            log(f"  警告：设计区多边形构建失败，跳过")
            continue
        
        design_polygon, left_over_x, right_over_x = design_result
        
        if design_polygon is None or design_polygon.is_empty:
            log(f"  警告：设计区多边形为空，跳过")
            continue
        
        log(f"  设计区多边形面积: {design_polygon.area:.1f}")
        if left_over_x:
            log(f"  左侧超挖区X范围: [{left_over_x[0]:.1f}, {left_over_x[1]:.1f}]")
        if right_over_x:
            log(f"  右侧超挖区X范围: [{right_over_x[0]:.1f}, {right_over_x[1]:.1f}]")

        # 延长开挖线和断面线用于切割
        # 使用连接后的开挖线来切割，确保分区线贴合开挖线的折角
        excav_extended = [extend_line_to_pierce(l, EXTEND_DIST) for l in excav_connected]
        section_extended = extend_line_to_pierce(final_sect, EXTEND_DIST)

        # 构建切割区域
        boundary_line = LineString(boundary_box.exterior.coords)
        cutters = [boundary_line, section_extended] + excav_extended
        zones = list(polygonize(unary_union(cutters)))

        if not zones:
            log(f"  警告：切割区域为空，跳过")
            continue
        
        log(f"  切割区域数量: {len(zones)}")
        
        # 用设计区多边形判定设计区/超挖区
        design_zones = []
        over_zones = []
        
        for z in zones:
            # 判断区域中心是否在设计区多边形内
            z_center = z.representative_point()
            
            # 方法1：检查区域是否在设计区多边形内
            if design_polygon.contains(z_center):
                design_zones.append(z)
            else:
                # 方法2：检查区域是否与设计区多边形相交
                inter = z.intersection(design_polygon)
                if inter.is_empty or inter.area < 0.1:
                    over_zones.append(z)
                else:
                    # 区域跨边界，需要分割
                    # 简单处理：根据相交面积占比判断
                    if inter.area > z.area * 0.5:
                        design_zones.append(z)
                    else:
                        over_zones.append(z)

        design_zone_poly = unary_union(design_zones) if design_zones else None
        log(f"  设计区面积: {design_zone_poly.area:.1f}" if design_zone_poly else "  设计区为空")

        # 总开挖区域
        over_y_bottom = miny
        total_open_poly = Polygon(sect_coords + [(sect_x_max, over_y_bottom), (sect_x_min, over_y_bottom)]).buffer(0)
        
        if total_open_poly.is_empty:
            log(f"  警告：总开挖区域无效，跳过")
            continue

        # 处理各地层填充
        for layer in strata_layers:
            layer_hatches = []
            for h in msp.query(f'HATCH[layer=="{layer}"]'):
                h_poly = hatch_to_polygon(h)
                if h_poly.intersects(boundary_box):
                    layer_hatches.append(h_poly)
            if not layer_hatches: continue

            combined_hatch = unary_union(layer_hatches).intersection(total_open_poly)
            if combined_hatch.is_empty: continue

            poly_design = combined_hatch.intersection(design_zone_poly) if design_zone_poly else None
            poly_over = combined_hatch.difference(design_zone_poly) if design_zone_poly else combined_hatch

            layer_color = get_strata_color(layer, strata_layers)
            design_area = add_hatch_with_label(msp, poly_design, LY_OUTPUT_HATCH, LY_OUTPUT_LABEL, layer_color, 'ANGLE', 0.1, TEXT_HEIGHT, layer, is_design=True)
            over_area = add_hatch_with_label(msp, poly_over, LY_OUTPUT_HATCH, LY_OUTPUT_LABEL, layer_color, 'ANSI31', 0.1, TEXT_HEIGHT, layer, is_design=False)

            if design_area > 0.01 or over_area > 0.01:
                report_data.append({"断面": f"S{idx+1}", "桩号": station, "地层": layer, "设计面积": round(design_area, 3), "超挖面积": round(over_area, 3)})

    if report_data:
        df = pd.DataFrame(report_data)
        def station_sort_key(station_str):
            nums = re.findall(r'\d+', str(station_str))
            return int("".join(nums)) if nums else 0
        df['sort_key'] = df['桩号'].apply(station_sort_key)
        df_sorted = df.sort_values(by='sort_key')

        output_xlsx = input_path.replace(".dxf", f"_分类汇总_{timestamp}.xlsx")
        with pd.ExcelWriter(output_xlsx) as writer:
            df_design = df_sorted.pivot_table(index='桩号', columns='地层', values='设计面积', aggfunc='sum', sort=False).fillna(0)
            df_design.to_excel(writer, sheet_name='设计量汇总')
            df_over = df_sorted.pivot_table(index='桩号', columns='地层', values='超挖面积', aggfunc='sum', sort=False).fillna(0)
            df_over.to_excel(writer, sheet_name='超挖汇总')
            df_sorted[['断面', '桩号', '地层', '设计面积', '超挖面积']].to_excel(writer, sheet_name='明细表', index=False)

        output_dxf = input_path.replace(".dxf", f"_RESULT_{timestamp}.dxf")
        doc.saveas(output_dxf)
        log(f"\n[OK] 处理完成！")
        log(f"   DXF: {output_dxf}")
        log(f"   Excel: {output_xlsx}")
        
        return output_dxf, output_xlsx
    else:
        log("未生成任何数据")
        return None, None

if __name__ == "__main__":
    import sys
    
    t_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = r"d:\tunnel_build"
    
    # 支持命令行参数传入文件路径
    if len(sys.argv) > 1:
        input_path = sys.argv[1]
        log(f"使用命令行参数文件: {input_path}")
        # 自动检测断面线图层和桩号图层
        process_autoclassify(input_path, t_str, section_layers=["DMX", "20260305"], station_layer="0-桩号")
    else:
        # 默认测试文件（仅用于无参数时）
        input_path = os.path.join(base_dir, "测试文件", "内湾段部分.dxf")
        if os.path.exists(input_path):
            log(f"使用默认测试文件: {input_path}")
            process_autoclassify(input_path, t_str, section_layers=["DMX", "20260305"], station_layer="0-桩号")
        else:
            log(f"找不到测试文件: {input_path}")
