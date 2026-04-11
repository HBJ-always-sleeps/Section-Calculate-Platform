# -*- coding: utf-8 -*-
"""
calc_backfill.py - 回淤面积计算
计算DMX与设计断面线之间的回淤面积

算法：
1. 读取DMX图层和设计断面线图层（如20260317）
2. 计算两条线的上包络线（取最大Y值）
3. 回淤面积 = 上包络线与DMX两根线之间的面积

使用方法：
python calc_backfill.py <输入DXF文件> [设计断面线图层] [桩号图层]

示例：
python calc_backfill.py "测试文件/xxx.dxf" "20260317" "0-桩号"
"""
import ezdxf
import pandas as pd
import os
import re
import datetime
import math
from shapely.geometry import LineString, Point, Polygon, MultiPolygon, box
from shapely.ops import unary_union

STRATA_REGEX = r'^\d+级.*'  # 匹配 "x级xx" 格式的地层图层


def log(msg):
    print(f"[*] {msg}")


def hatch_to_polygon(hatch_entity):
    """将HATCH实体转换为多边形"""
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
    return unary_union(polygons)


def get_layer_lines(msp, layer_name):
    """从图层获取线段"""
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
        if not lines:
            return []
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

    # 按Y坐标聚类到多行
    def cluster_by_y(lines, y_threshold=100):
        if not lines:
            return []
        sorted_lines = sorted(lines, key=lambda x: x['mid_y'], reverse=True)
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

    for x_cluster in x_clusters:
        y_clusters = cluster_by_y(x_cluster)

        for y_cluster in y_clusters:
            if not y_cluster:
                continue
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


def generate_upper_envelope(dmx, design_lines):
    """生成上包络线（取最大Y值）- 用于回淤面积计算
    
    上包络线 = 在每个X位置，取DMX和设计线的最大Y值
    这样上包络线与DMX之间的区域就是回淤区域
    """
    # 收集所有X坐标
    all_x_coords = set()
    for pt in dmx.coords:
        all_x_coords.add(round(pt[0], 3))
    for sec in design_lines:
        for pt in sec.coords:
            all_x_coords.add(round(pt[0], 3))
    
    if not all_x_coords:
        return None
    
    sorted_x = sorted(all_x_coords)
    dmx_bounds = dmx.bounds
    x_min, x_max = dmx_bounds[0], dmx_bounds[2]
    filtered_x = [x for x in sorted_x if x_min <= x <= x_max]
    
    if not filtered_x:
        return None
    
    coords = []
    for x in filtered_x:
        all_ys = []
        
        # DMX的Y值
        dmx_y = get_y_at_x(dmx, x)
        if dmx_y is not None:
            all_ys.append(dmx_y)
        
        # 设计线的Y值
        for sec in design_lines:
            sec_y = get_y_at_x(sec, x)
            if sec_y is not None:
                all_ys.append(sec_y)
        
        if all_ys:
            # 上包络线：取最大Y值
            max_y = max(all_ys)
            coords.append((x, max_y))
    
    if len(coords) >= 2:
        return LineString(coords)
    return None


def process_backfill(input_path, timestamp, section_layer, station_layer=None):
    """
    主处理函数 - 计算回淤面积

    回淤面积 = 上包络线与DMX之间的面积
    上包络线 = DMX和设计断面线的最大Y值连线

    Args:
        input_path: 输入DXF文件路径
        timestamp: 时间戳
        section_layer: 设计断面线图层名称（如 "20260317"）
        station_layer: 桩号图层（可选，默认自动检测）
    """
    log(f"读取文件: {input_path}")
    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()

    # 获取DMX线
    dmx_lines = get_layer_lines(msp, "DMX")
    log(f"DMX线: {len(dmx_lines)}条")

    # 获取设计断面线
    design_lines = get_layer_lines(msp, section_layer)
    log(f"设计断面线（图层{section_layer}）: {len(design_lines)}条")

    # 获取超挖线（用于构建虚拟断面框）
    overexc_lines = get_layer_lines(msp, "超挖线")
    log(f"超挖线: {len(overexc_lines)}条")

    # 从超挖线构建虚拟断面框
    virtual_boxes = build_virtual_boxes_from_overexcav(overexc_lines)
    log(f"虚拟断面框: {len(virtual_boxes)}个")

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
                except:
                    pass

    log(f"桩号总数: {len(station_texts)}")

    # 结果数据
    report_data = []

    for idx, v_box in enumerate(virtual_boxes):
        minx, miny, maxx, maxy = v_box.bounds
        virtual_y_center = (miny + maxy) / 2
        virtual_x_center = (minx + maxx) / 2

        # 找该断面的桩号
        station = f"S{idx+1}"
        best_dist = float('inf')
        for st in station_texts:
            pt = Point(st['x'], st['y'])
            if v_box.distance(pt) < 200:
                dist = pt.distance(Point(virtual_x_center, miny))
                if dist < best_dist:
                    best_dist = dist
                    station = st['text']

        log(f"\n处理断面 {idx+1}: {station}")

        # 找该断面的DMX线
        dmx = None
        min_y_diff = float('inf')
        for l in dmx_lines:
            b = l.bounds
            if b[0] <= virtual_x_center <= b[2]:
                l_y_mid = (b[1] + b[3]) / 2
                y_diff = abs(l_y_mid - virtual_y_center)
                if y_diff < min_y_diff:
                    min_y_diff = y_diff
                    dmx = l

        if dmx is None:
            log(f"  警告：未找到DMX，跳过")
            continue

        # 找该断面的设计断面线
        local_design_lines = []
        boundary_box = box(minx - 20, miny - 25, maxx + 20, maxy + 25)
        for l in design_lines:
            if boundary_box.intersects(l):
                local_design_lines.append(l)

        if not local_design_lines:
            log(f"  警告：未找到设计断面线，跳过")
            continue

        # 生成上包络线
        upper_envelope = generate_upper_envelope(dmx, local_design_lines)
        
        if upper_envelope is None:
            log(f"  警告：上包络线生成失败，跳过")
            continue

        # 获取DMX和上包络线的坐标范围
        dmx_coords = list(dmx.coords)
        envelope_coords = list(upper_envelope.coords)
        
        dmx_x_min = min(c[0] for c in dmx_coords)
        dmx_x_max = max(c[0] for c in dmx_coords)
        envelope_x_min = min(c[0] for c in envelope_coords)
        envelope_x_max = max(c[0] for c in envelope_coords)
        
        # 取两者的交集范围
        common_x_min = max(dmx_x_min, envelope_x_min)
        common_x_max = min(dmx_x_max, envelope_x_max)
        
        if common_x_max <= common_x_min:
            log(f"  警告：DMX与上包络线X范围无交集，跳过")
            continue

        log(f"  DMX X范围: [{dmx_x_min:.1f}, {dmx_x_max:.1f}]")
        log(f"  上包络线X范围: [{envelope_x_min:.1f}, {envelope_x_max:.1f}]")
        log(f"  共同X范围: [{common_x_min:.1f}, {common_x_max:.1f}]")

        # 构建回淤区域多边形
        # 回淤区域 = 上包络线与DMX之间的区域
        # 从左到右：上包络线上的点 -> 从右到左：DMX上的点（闭合）
        
        # 采样共同X范围内的点
        sample_step = 1.0
        x_samples = []
        envelope_y_samples = []
        dmx_y_samples = []
        
        x_current = common_x_min
        while x_current <= common_x_max:
            envelope_y = get_y_at_x(upper_envelope, x_current)
            dmx_y = get_y_at_x(dmx, x_current)
            
            if envelope_y is not None and dmx_y is not None:
                x_samples.append(x_current)
                envelope_y_samples.append(envelope_y)
                dmx_y_samples.append(dmx_y)
            
            x_current += sample_step
        
        if len(x_samples) < 2:
            log(f"  警告：采样点不足，跳过")
            continue

        # 构建回淤区域多边形
        # 上边界：上包络线（从左到右）
        # 下边界：DMX（从右到左，形成闭合）
        polygon_coords = []
        
        # 上包络线上的点（从左到右）
        for x, y in zip(x_samples, envelope_y_samples):
            polygon_coords.append((x, y))
        
        # DMX上的点（从右到左，形成闭合）
        for i in range(len(x_samples) - 1, -1, -1):
            polygon_coords.append((x_samples[i], dmx_y_samples[i]))
        
        if len(polygon_coords) >= 3:
            backfill_polygon = Polygon(polygon_coords)
            if not backfill_polygon.is_valid:
                backfill_polygon = backfill_polygon.buffer(0)
            
            backfill_area = backfill_polygon.area
        else:
            backfill_area = 0

        log(f"  回淤面积: {backfill_area:.2f}")

        report_data.append({
            "桩号": station,
            "回淤面积": round(backfill_area, 2)
        })

    # 生成Excel报告
    if report_data:
        df = pd.DataFrame(report_data)

        # 按桩号排序
        def station_sort_key(station_str):
            nums = re.findall(r'\d+', str(station_str))
            return int("".join(nums)) if nums else 0

        df['sort_key'] = df['桩号'].apply(station_sort_key)
        df_sorted = df.sort_values(by='sort_key').drop(columns=['sort_key'])

        output_xlsx = input_path.replace(".dxf", f"_回淤面积_{timestamp}.xlsx")
        with pd.ExcelWriter(output_xlsx) as writer:
            df_sorted.to_excel(writer, sheet_name='回淤面积汇总', index=False)

            # 添加汇总行
            summary = pd.DataFrame([{
                "桩号": "合计",
                "回淤面积": df_sorted['回淤面积'].sum()
            }])
            pd.concat([df_sorted, summary], ignore_index=True).to_excel(
                writer, sheet_name='带合计', index=False)

        log(f"\n[OK] 处理完成！")
        log(f"   Excel: {output_xlsx}")
        log(f"   总回淤面积: {df_sorted['回淤面积'].sum():.2f}")

        return output_xlsx
    else:
        log("未生成任何数据")
        return None


if __name__ == "__main__":
    import sys

    t_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    if len(sys.argv) > 1:
        input_path = sys.argv[1]
        section_layer = sys.argv[2] if len(sys.argv) > 2 else "20260317"
        station_layer = sys.argv[3] if len(sys.argv) > 3 else None

        log(f"输入文件: {input_path}")
        log(f"断面线图层: {section_layer}")
        log(f"桩号图层: {station_layer or '自动检测'}")

        process_backfill(input_path, t_str, section_layer, station_layer)
    else:
        # 默认测试
        input_path = r"D:\断面算量平台\测试文件\内湾段分层图（全航道）_RESULT_20260318_152025.dxf"
        log(f"使用默认文件: {input_path}")
        process_backfill(input_path, t_str, "20260317", "0-桩号")
