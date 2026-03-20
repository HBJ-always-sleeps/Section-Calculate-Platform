"""
统计每个断面5m分层线以上的填充量
参考autoclassify_working_v3的分层线剔除逻辑
"""
import ezdxf
from shapely.geometry import Polygon, LineString, box, Point
from shapely.ops import unary_union
import pandas as pd
from datetime import datetime
import os

def hatch_to_polygon(hatch_entity):
    """将Hatch实体转换为Shapely多边形"""
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
    """获取图层中的所有线"""
    result = []
    for e in msp.query(f'*[layer=="{layer_name}"]'):
        try:
            if e.dxftype() == 'LWPOLYLINE':
                pts = [p[:2] for p in e.get_points()]
                if len(pts) >= 2:
                    result.append(LineString(pts))
            elif e.dxftype() == 'POLYLINE':
                pts = [v.dxf.location.vec2 for v in e.vertices]
                if len(pts) >= 2:
                    result.append(LineString(pts))
            elif e.dxftype() == 'LINE':
                result.append(LineString([e.dxf.start.vec2, e.dxf.end.vec2]))
        except:
            pass
    return result

def get_5m_layer_lines(msp):
    """获取5m分层线，返回 [{y, x_min, x_max, line}, ...]"""
    layer_lines = []
    for e in msp.query('*[layer=="5m分层线"]'):
        try:
            if e.dxftype() == 'LWPOLYLINE':
                pts = [p[:2] for p in e.get_points()]
                if len(pts) >= 2:
                    y_val = pts[0][1]
                    x_min = min(p[0] for p in pts)
                    x_max = max(p[0] for p in pts)
                    layer_lines.append({'y': y_val, 'x_min': x_min, 'x_max': x_max, 'line': LineString(pts)})
            elif e.dxftype() == 'LINE':
                y_val = e.dxf.start.y
                x_min = min(e.dxf.start.x, e.dxf.end.x)
                x_max = max(e.dxf.start.x, e.dxf.end.x)
                layer_lines.append({
                    'y': y_val, 'x_min': x_min, 'x_max': x_max,
                    'line': LineString([(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)])
                })
        except:
            pass
    return layer_lines

def get_layer_line_for_section(layer_5m_lines, sect_bounds):
    """获取适用于当前断面的5m分层线"""
    sect_x_min, sect_x_max = sect_bounds[0], sect_bounds[2]
    sect_y_min, sect_y_max = sect_bounds[1], sect_bounds[3]
    sect_x_mid = (sect_x_min + sect_x_max) / 2
    
    applicable_lines = []
    for ll in layer_5m_lines:
        # 断面中点必须在分层线X范围内
        if not (ll['x_min'] <= sect_x_mid <= ll['x_max']):
            continue
        # 分层线Y值应该接近断面顶Y值
        # 分层线Y = 设计底高程 + 5m，断面顶Y = 设计底高程
        # 所以分层线Y应该略大于断面顶Y（约5m左右）
        # 容差：断面顶Y - 10m 到 断面顶Y + 100m
        if ll['y'] >= sect_y_max - 10 and ll['y'] <= sect_y_max + 100:
            applicable_lines.append(ll)
    
    return applicable_lines

def build_virtual_boxes_from_overexcav(overexc_lines):
    """从超挖线构建虚拟断面框"""
    if not overexc_lines:
        return []
    
    line_info = []
    for line in overexc_lines:
        bounds = line.bounds
        mid_x = (bounds[0] + bounds[2]) / 2
        mid_y = (bounds[1] + bounds[3]) / 2
        line_info.append({'line': line, 'mid_x': mid_x, 'mid_y': mid_y, 'bounds': bounds})
    
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

def process_dxf(input_path):
    """处理DXF文件，统计AA_分类填充在5m分层线以上的面积"""
    print(f"正在读取: {input_path}")
    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()
    
    # 1. 获取虚拟断面框（从超挖线构建）
    overexc_lines_all = get_layer_lines(msp, "超挖线")
    print(f"超挖线数量: {len(overexc_lines_all)}")
    
    virtual_boxes = build_virtual_boxes_from_overexcav(overexc_lines_all)
    print(f"虚拟断面框: {len(virtual_boxes)} 个")
    
    # 2. 获取5m分层线
    layer_5m_lines = get_5m_layer_lines(msp)
    print(f"5m分层线数量: {len(layer_5m_lines)}")
    
    # 3. 获取最终断面线
    final_section_lines = get_layer_lines(msp, "AA_最终断面线")
    print(f"最终断面线数量: {len(final_section_lines)}")
    
    # 4. 获取桩号
    station_texts = []
    for layer in ["0-桩号", "桩号"]:
        for e in msp.query(f'*[layer=="{layer}"]'):
            if e.dxftype() in ('TEXT', 'MTEXT'):
                try:
                    x, y = e.dxf.insert.x, e.dxf.insert.y
                    text = e.dxf.text if e.dxftype() == 'TEXT' else e.text
                    text = text.split(";")[-1].replace("}", "").strip()
                    station_texts.append({'text': text, 'x': x, 'y': y})
                except:
                    pass
    print(f"桩号数量: {len(station_texts)}")
    
    # 5. 获取AA_分类填充图层的所有填充
    aa_hatches = []
    for h in msp.query('HATCH[layer=="AA_分类填充"]'):
        poly = hatch_to_polygon(h)
        if not poly.is_empty:
            aa_hatches.append({'poly': poly, 'layer': h.dxf.layer})
    print(f"AA_分类填充数量: {len(aa_hatches)}")
    
    # 6. 处理每个断面
    results = []
    stats = {'有分层线': 0, '无分层线': 0, '有填充': 0, '无填充': 0}
    
    for idx, v_box in enumerate(virtual_boxes):
        minx, miny, maxx, maxy = v_box.bounds
        virtual_y_center = (miny + maxy) / 2
        virtual_x_center = (minx + maxx) / 2
        
        # 获取桩号
        station = f"S{idx+1}"
        best_dist = float('inf')
        for st in station_texts:
            pt = Point(st['x'], st['y'])
            if v_box.distance(pt) < 200:
                dist = pt.distance(Point(virtual_x_center, miny))
                if dist < best_dist:
                    best_dist = dist
                    station = st['text']
        
        # 找到对应的最终断面线
        final_sect = None
        min_y_diff = float('inf')
        for line in final_section_lines:
            b = line.bounds
            if b[0] <= virtual_x_center <= b[2]:
                line_y_mid = (b[1] + b[3]) / 2
                y_diff = abs(line_y_mid - virtual_y_center)
                if y_diff < min_y_diff:
                    min_y_diff = y_diff
                    final_sect = line
        
        if not final_sect:
            continue
        
        sect_bounds = final_sect.bounds
        sect_x_min, sect_x_max = sect_bounds[0], sect_bounds[2]
        
        # 获取该断面的5m分层线
        current_layer_lines = get_layer_line_for_section(layer_5m_lines, sect_bounds)
        
        # 构建总开挖区域（断面线以下到虚拟框底部）
        sect_coords = list(final_sect.coords)
        total_open_poly = Polygon(sect_coords + [(sect_x_max, miny), (sect_x_min, miny)]).buffer(0)
        
        # 如果有分层线，应用分层线筛选：只保留分层线以上的区域
        if current_layer_lines:
            stats['有分层线'] += 1
            # 获取分层线Y值（这是5m高程面的位置）
            # DXF坐标系：Y轴向上为正，Y大=高程高，Y小=高程低
            # "5m分层线以上" = Y >= 分层线Y 的区域
            max_layer_y = max(ll['y'] for ll in current_layer_lines)
            # 构建上界多边形：从分层线Y往上
            upper_bound_poly = box(sect_x_min - 10, max_layer_y, sect_x_max + 10, maxy + 100)
            total_open_poly = total_open_poly.intersection(upper_bound_poly)
        else:
            stats['无分层线'] += 1
            max_layer_y = None
        
        if total_open_poly.is_empty:
            continue
        
        # 统计该断面框内的所有AA_分类填充
        strata_stats = {}
        total_area = 0
        
        for hatch_info in aa_hatches:
            hatch_poly = hatch_info['poly']
            
            # 检查填充是否在虚拟断面框内
            if not v_box.intersects(hatch_poly):
                continue
            
            # 计算填充在分层线以上区域的面积
            try:
                intersect_poly = hatch_poly.intersection(total_open_poly)
                if not intersect_poly.is_empty:
                    area = intersect_poly.area
                    if area > 0.01:
                        # 从填充图层名提取地层名
                        strata_name = hatch_info['layer'].replace('AA_分类填充', '').replace('_填充', '')
                        if strata_name not in strata_stats:
                            strata_stats[strata_name] = 0
                        strata_stats[strata_name] += area
                        total_area += area
            except:
                pass
        
        if strata_stats:
            results.append({
                '断面名称': station,
                'Y中心': virtual_y_center,
                '分层线Y': max_layer_y,
                **strata_stats,
                '总面积': total_area
            })
    
    print(f"统计: {stats}")
    print(f"处理了 {len(results)} 个断面")
    return results

def main():
    input_path = r"D:\tunnel_build\测试文件\内湾段分层图（全航道）_RESULT_20260310_123608.dxf"
    
    if not os.path.exists(input_path):
        print(f"错误: 文件不存在 {input_path}")
        return
    
    results = process_dxf(input_path)
    
    if not results:
        print("没有找到有效数据")
        return
    
    # 创建DataFrame
    df = pd.DataFrame(results)
    
    # 排序列
    cols = ['断面名称', 'Y中心', '分层线Y'] + [c for c in df.columns if c not in ['断面名称', 'Y中心', '分层线Y', '总面积']] + ['总面积']
    df = df[cols]
    
    # 保存Excel
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = input_path.replace('.dxf', f'_5m以上算量_{timestamp}.xlsx')
    df.to_excel(output_path, index=False)
    
    print(f"\n[OK] 统计完成!")
    print(f"输出: {output_path}")
    print(f"\n前10行预览:")
    print(df.head(10).to_string())

if __name__ == '__main__':
    main()