# -*- coding: utf-8 -*-
"""
计算指定高程以下的面积
使用AA_最终断面线图层中已计算好的断面线
输出包含分层线和分类填充的DXF文件
"""

import ezdxf
import os
import re
import datetime
import pandas as pd
from shapely.geometry import LineString, Point, Polygon, box, MultiPolygon
from shapely.ops import unary_union


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


def calc_area_below_elevation(input_path, target_elevation=-13.5):
    """计算指定高程以下的面积 - 使用AA_最终断面线"""
    print(f"[INFO] 正在读取文件: {os.path.basename(input_path)}")
    print(f"[INFO] 目标高程: {target_elevation}m")
    
    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()
    
    all_layers = [l.dxf.name for l in doc.layers]
    print(f"[INFO] 图层总数: {len(all_layers)}")
    
    if 'AA_最终断面线' not in all_layers:
        print("[ERROR] 未找到AA_最终断面线图层！")
        return [], None
    
    strata_layers = sorted(
        [l for l in all_layers if re.match(r'^\d+级', l)],
        key=lambda x: int(re.findall(r'^(\d+)', x)[0]) if re.findall(r'^(\d+)', x) else 999
    )
    print(f"[INFO] 地层图层: {strata_layers}")
    
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
    
    # 按Y坐标从大到小排序（图纸上方在先）
    final_section_list = sorted(final_section_list, key=lambda d: d['y_center'], reverse=True)
    print(f"[INFO] AA_最终断面线数量: {len(final_section_list)}")
    
    # 获取桩号文本 - 收集所有可能的桩号
    station_texts = []
    for layer in ["0-桩号", "桩号", "AA_桩号"]:
        for e in msp.query(f'*[layer=="{layer}"]'):
            if e.dxftype() in ('TEXT', 'MTEXT'):
                try:
                    x, y = e.dxf.insert.x, e.dxf.insert.y
                    text = e.dxf.text if e.dxftype() == 'TEXT' else e.text
                    # 清理文本
                    text = text.split(";")[-1].replace("}", "").strip()
                    # 验证是否是有效的桩号格式
                    if re.match(r'^[Kk]?\d*\+?\d+$', text) or re.match(r'^[Kk]\d+\+\d+', text):
                        station_texts.append({'text': text, 'x': x, 'y': y})
                except:
                    pass
    print(f"[INFO] 桩号数量: {len(station_texts)}")
    
    # 按Y坐标排序桩号（从上到下）
    station_texts_sorted = sorted(station_texts, key=lambda s: s['y'], reverse=True)
    
    # 改进的桩号匹配：使用最近邻匹配
    def find_nearest_station(sect_x_center, sect_y_center, used_stations):
        """找到最近的未使用的桩号"""
        best_station = None
        best_dist = float('inf')
        
        for st in station_texts_sorted:
            if st['text'] in used_stations:
                continue
            # 计算距离（Y方向权重更大，因为断面是垂直排列的）
            dist = ((st['x'] - sect_x_center)**2 * 0.5 + (st['y'] - sect_y_center)**2)**0.5
            if dist < best_dist:
                best_dist = dist
                best_station = st
        
        return best_station, best_dist
    
    overexc_lines = get_layer_lines(msp, "超挖线")
    print(f"[INFO] 超挖线数量: {len(overexc_lines)}")
    
    strata_hatches = {}
    for layer in strata_layers:
        strata_hatches[layer] = []
        for h in msp.query(f'HATCH[layer=="{layer}"]'):
            poly = hatch_to_polygon(h)
            if poly and not poly.is_empty:
                strata_hatches[layer].append(poly)
        if strata_hatches[layer]:
            print(f"  {layer}: {len(strata_hatches[layer])}个填充")
    
    output_doc = ezdxf.readfile(input_path)
    output_msp = output_doc.modelspace()
    
    layer_name_elev = f"分层线_{target_elevation}m"
    layer_name_below = f"{target_elevation}m以下分类"
    
    if layer_name_elev not in [l.dxf.name for l in output_doc.layers]:
        output_doc.layers.new(name=layer_name_elev, dxfattribs={'color': 1})
    if layer_name_below not in [l.dxf.name for l in output_doc.layers]:
        output_doc.layers.new(name=layer_name_below, dxfattribs={'color': 2})
    
    strata_output_layers = {}
    for layer in strata_layers:
        output_layer_name = f"{target_elevation}m_{layer}"
        strata_output_layers[layer] = output_layer_name
        if output_layer_name not in [l.dxf.name for l in output_doc.layers]:
            color = STRATA_COLORS.get(layer, 7)
            output_doc.layers.new(name=output_layer_name, dxfattribs={'color': color})
    
    results = []
    used_stations = set()
    
    for idx, sect in enumerate(final_section_list):
        sect_x_min = sect['x_min']
        sect_x_max = sect['x_max']
        sect_y_min = sect['y_min']
        sect_y_max = sect['y_max']
        sect_y_center = sect['y_center']
        sect_x_center = (sect_x_min + sect_x_max) / 2
        
        # 使用改进的桩号匹配
        nearest_st, dist = find_nearest_station(sect_x_center, sect_y_center, used_stations)
        
        if nearest_st and dist < 500:  # 距离阈值500
            station = nearest_st['text']
            used_stations.add(station)
        else:
            station = f"S{idx+1}"
        
        ruler_scale = detect_ruler_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max)
        
        if ruler_scale:
            elev_to_y, y_to_elev = ruler_scale
            target_line_y = elev_to_y(target_elevation)
            design_bottom_elev = y_to_elev(sect_y_min)
        else:
            target_line_y = 5.0 * target_elevation - 27.0
            design_bottom_elev = (sect_y_min + 27.0) / 5.0
        
        sect_coords = sect['pts']
        bottom_y = sect_y_min - 50
        total_open_poly = Polygon(sect_coords + [(sect_x_max, bottom_y), (sect_x_min, bottom_y)]).buffer(0)
        
        if total_open_poly.is_empty:
            results.append({
                '断面名称': station,
                '设计底高程': round(design_bottom_elev, 2),
                '分层线高程': target_elevation,
                '总面积': 0.0
            })
            continue
        
        # 修复逻辑：
        # - 当target_line_y >= sect_y_max时：高程线在断面顶部以上，整个断面在目标高程以下，使用整个断面
        # - 当target_line_y < sect_y_min时：高程线在断面底部以下，整个断面在目标高程以上，面积为0
        # - 当sect_y_min <= target_line_y < sect_y_max时：高程线穿过断面，需要计算交线以下部分
        
        if target_line_y < sect_y_min:
            # 高程线在断面底部以下，整个断面都在目标高程以上，面积为0
            results.append({
                '断面名称': station,
                '设计底高程': round(design_bottom_elev, 2),
                '分层线高程': target_elevation,
                '总面积': 0.0
            })
            continue
        
        if target_line_y >= sect_y_max:
            # 高程线在断面顶部以上，整个断面都在目标高程以下，使用整个断面
            below_layer_open = total_open_poly
            # 不绘制高程线（在断面外部）
        else:
            # 高程线穿过断面，计算交线以下部分
            below_layer_poly = box(sect_x_min - 10, sect_y_min - 100, sect_x_max + 10, target_line_y)
            below_layer_open = total_open_poly.intersection(below_layer_poly)
        
        if below_layer_open.is_empty:
            results.append({
                '断面名称': station,
                '设计底高程': round(design_bottom_elev, 2),
                '分层线高程': target_elevation,
                '总面积': 0.0
            })
            continue
        
        # 绘制高程线逻辑：
        # 1. 高程线穿过断面：在target_line_y位置绘制
        # 2. 高程线在断面顶部以上：在断面顶部位置绘制虚线标记
        # 3. 高程线在断面底部以下：不绘制（面积为0的情况已跳过）
        
        if target_line_y >= sect_y_max:
            # 高程线在断面顶部以上，在顶部位置绘制虚线标记
            line_pts = [(sect_x_min - 5, sect_y_max), (sect_x_max + 5, sect_y_max)]
            output_msp.add_lwpolyline(line_pts, dxfattribs={'layer': layer_name_elev, 'color': 1, 'linetype': 'DASHED'})
            
            try:
                mid_x = (sect_x_min + sect_x_max) / 2
                output_msp.add_text(
                    f"{target_elevation}m(顶)",
                    dxfattribs={
                        'layer': layer_name_elev,
                        'height': 2.5,
                        'color': 1
                    }
                ).set_placement((mid_x, sect_y_max + 3))
            except:
                pass
        elif target_line_y > sect_y_min:
            # 高程线穿过断面，在target_line_y位置绘制实线
            line_pts = [(sect_x_min - 5, target_line_y), (sect_x_max + 5, target_line_y)]
            output_msp.add_lwpolyline(line_pts, dxfattribs={'layer': layer_name_elev, 'color': 1})
            
            try:
                mid_x = (sect_x_min + sect_x_max) / 2
                output_msp.add_text(
                    f"{target_elevation}m",
                    dxfattribs={
                        'layer': layer_name_elev,
                        'height': 2.5,
                        'color': 1
                    }
                ).set_placement((mid_x, target_line_y + 3))
            except:
                pass
        
        boundary_box = box(sect_x_min - 20, sect_y_min - 50, sect_x_max + 20, sect_y_max + 50)
        
        strata_areas = {}
        total_area = 0.0
        
        for layer in strata_layers:
            layer_area = 0.0
            layer_polys = []
            
            for h_poly in strata_hatches[layer]:
                try:
                    if not boundary_box.intersects(h_poly):
                        continue
                    
                    inter = h_poly.intersection(below_layer_open)
                    if inter.is_empty:
                        continue
                    
                    if isinstance(inter, Polygon):
                        layer_area += inter.area
                        layer_polys.append(inter)
                    elif hasattr(inter, 'geoms'):
                        for g in inter.geoms:
                            if isinstance(g, Polygon):
                                layer_area += g.area
                                layer_polys.append(g)
                except:
                    pass
            
            if layer_area > 0.01:
                strata_areas[layer] = round(layer_area, 3)
                total_area += layer_area
                
                for poly in layer_polys:
                    try:
                        boundaries = polygon_to_boundary_points(poly)
                        if boundaries:
                            output_layer = strata_output_layers.get(layer, layer_name_below)
                            hatch = output_msp.add_hatch(
                                dxfattribs={
                                    'layer': output_layer,
                                    'hatch_style': 0,
                                    'color': STRATA_COLORS.get(layer, 7)
                                }
                            )
                            hatch.set_pattern_fill('SOLID', scale=1.0)
                            for boundary_pts in boundaries:
                                if len(boundary_pts) >= 3:
                                    hatch.paths.add_polyline_path(boundary_pts, is_closed=True)
                    except:
                        pass
        
        result = {
            '断面名称': station,
            '设计底高程': round(design_bottom_elev, 2),
            '分层线高程': target_elevation,
            '总面积': round(total_area, 3)
        }
        
        for layer in strata_layers:
            result[f'{layer}'] = strata_areas.get(layer, 0.0)
        
        results.append(result)
        
        if (idx + 1) % 50 == 0:
            print(f"  已处理 {idx+1}/{len(final_section_list)} 个断面...")
    
    results.sort(key=lambda x: station_sort_key(x['断面名称']))
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.basename(input_path).replace('.dxf', '')
    output_dir = os.path.dirname(input_path)
    output_dxf = os.path.join(output_dir, f"{base_name}_{target_elevation}m分层_{timestamp}.dxf")
    
    output_doc.saveas(output_dxf)
    print(f"[INFO] DXF文件已保存: {output_dxf}")
    
    return results, output_dxf


def main():
    """主函数"""
    input_path = r"D:\断面算量平台\测试文件\内湾段分层图（全航道）_RESULT_20260318_152025.dxf"
    
    # 批量处理多个高程
    target_elevations = [-10.0]
    
    for target_elevation in target_elevations:
        print(f"\n{'='*60}")
        print(f"[INFO] 开始处理高程: {target_elevation}m")
        print(f"{'='*60}\n")
        
        results, output_dxf = calc_area_below_elevation(input_path, target_elevation)
        
        if results:
            df = pd.DataFrame(results)
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = os.path.basename(input_path).replace('.dxf', '')
            output_dir = os.path.dirname(input_path)
            output_xlsx = os.path.join(output_dir, f"{base_name}_{target_elevation}m以下面积_{timestamp}.xlsx")
            
            with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='明细表', index=False)
                
                strata_cols = [c for c in df.columns if '级' in c]
                if strata_cols:
                    summary_data = {'地层': strata_cols, '面积(㎡)': [df[c].sum() for c in strata_cols]}
                    summary_df = pd.DataFrame(summary_data)
                    summary_df.to_excel(writer, sheet_name='地层汇总', index=False)
                
                total_data = {
                    '统计项': ['总断面数', f'{target_elevation}m以下总面积'],
                    '数值': [len(results), df['总面积'].sum()]
                }
                total_df = pd.DataFrame(total_data)
                total_df.to_excel(writer, sheet_name='汇总', index=False)
            
            print(f"\n[OK] 处理完成！")
            print(f"  结果Excel: {output_xlsx}")
            print(f"  结果DXF: {output_dxf}")
            print(f"  总断面数: {len(results)}")
            print(f"  {target_elevation}m以下总面积: {df['总面积'].sum():.3f} ㎡")
        else:
            print("[WARN] 未生成任何数据")


if __name__ == "__main__":
    main()