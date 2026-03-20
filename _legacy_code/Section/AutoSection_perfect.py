import ezdxf
import pandas as pd
from shapely.geometry import LineString, Point, box, Polygon
from shapely.ops import unary_union, snap, linemerge, polygonize
from collections import defaultdict, Counter

# ================= 配置区域 =================
INPUT_FILE = "tt.dxf"
OUTPUT_DXF = "tt_optimized.dxf"
OUTPUT_EXCEL = "t_final_report.xlsx"

LAYER_OVER = "超挖框"     # 你手动闭合后的图层
LAYER_DESIGN = "开挖线"   
LAYER_GROUND = "断面线"   
LAYER_GEO = "地质分层"   

MARGIN_X = 20.0        
MARGIN_Y = 15.0        
EXTEND_DIST = 3.0       # 预延伸距离（米），确保穿透红线
# ===========================================

def get_lines_raw(msp, layer):
    lines = []
    try: ents = msp.query(f'*[layer=="{layer}"]')
    except: return []
    for ent in ents:
        if ent.dxftype() == 'LINE':
            lines.append(LineString([ent.dxf.start.vec2, ent.dxf.end.vec2]))
        elif ent.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
            pts = [p[:2] for p in ent.get_points()] if ent.dxftype() == 'LWPOLYLINE' else [v.vtx.vec2 for v in ent.vertices]
            if len(pts) >= 2: lines.append(LineString(pts))
    return lines

def extend_line_simple(line, dist):
    """ 沿端点方向物理延伸线条 """
    coords = list(line.coords)
    if len(coords) < 2: return line
    # 起点延伸
    p1, p2 = Point(coords[0]), Point(coords[1])
    vec_s = (p1.x - p2.x, p1.y - p2.y)
    mag_s = (vec_s[0]**2 + vec_s[1]**2)**0.5
    new_start = (p1.x + vec_s[0]/mag_s*dist, p1.y + vec_s[1]/mag_s*dist)
    # 终点延伸
    p_n1, p_n = Point(coords[-2]), Point(coords[-1])
    vec_e = (p_n.x - p_n1.x, p_n.y - p_n1.y)
    mag_e = (vec_e[0]**2 + vec_e[1]**2)**0.5
    new_end = (p_n.x + vec_e[0]/mag_e*dist, p_n.y + vec_e[1]/mag_e*dist)
    return LineString([new_start] + coords + [new_end])

def main():
    print("🚀 启动优化版：先行延伸 + 业务图层复制 + 智能地层识别...")
    doc = ezdxf.readfile(INPUT_FILE)
    msp = doc.modelspace()

    # 1. 断面识别
    all_biz = get_lines_raw(msp, LAYER_OVER) + get_lines_raw(msp, LAYER_DESIGN)
    if not all_biz: return
    group_polys = list(unary_union([l.buffer(5.0) for l in all_biz]).geoms)
    group_polys.sort(key=lambda p: p.bounds[0])

    all_ground = get_lines_raw(msp, LAYER_GROUND)
    all_geo_raw = get_lines_raw(msp, LAYER_GEO)
    all_texts = [e for e in msp.query(f'*[layer=="{LAYER_GEO}"]') if e.dxftype() in ('TEXT', 'MTEXT')]
    
    # 地质线初步焊接
    merged_geo = linemerge(unary_union(all_geo_raw))
    geo_list = list(merged_geo.geoms) if hasattr(merged_geo, 'geoms') else [merged_geo]

    final_report_data = []

    for idx, g_poly in enumerate(group_polys, 1):
        x1, y1, x2, y2 = g_poly.bounds
        min_x, max_x, min_y, max_y = x1-MARGIN_X, x2+MARGIN_X, y1-MARGIN_Y, y2+MARGIN_Y
        sec_box = box(min_x, min_y, max_x, max_y)
        
        # --- A. 断面红线处理 ---
        local_ground = [l for l in all_ground if sec_box.intersects(l)]
        if not local_ground: continue
        # 断面线延伸至框边界
        red_geom = unary_union([LineString([(min_x, l.coords[0][1])] + list(l.coords) + [(max_x, l.coords[-1][1])]) for l in local_ground])

        # --- B. 黄紫框：先行延伸与构面 ---
        # 提取并延伸
        raw_y = [l for l in get_lines_raw(msp, LAYER_DESIGN) if sec_box.intersects(l)]
        raw_o = [l for l in get_lines_raw(msp, LAYER_OVER) if sec_box.intersects(l)]
        
        ext_y = [extend_line_simple(l, EXTEND_DIST) for l in raw_y]
        ext_o = [extend_line_simple(l, EXTEND_DIST) for l in raw_o]

        # 写入新图层“开挖框”
        quick_draw(msp, doc, unary_union(ext_y), "开挖框", 2)

        def build_fast_zone(ext_lines):
            if not ext_lines: return None
            # 延伸线与红线合并构面
            combined = unary_union([snap(unary_union(ext_lines), red_geom, 0.1), red_geom])
            ps = [p for p in polygonize(combined) if p.area > 0.1 and sec_box.intersects(p.centroid)]
            return unary_union(ps) if ps else None

        d_zone = build_fast_zone(ext_y) # 设计面（黄色）
        o_zone = build_fast_zone(ext_o) # 总开挖面
        n_zone = o_zone.difference(d_zone) if (o_zone and d_zone) else o_zone # 净超挖（紫色）

        # --- C. 智能绿线延伸 ---
        # 逻辑：只有端点不在 d_zone/o_zone 内部，且不是三岔路口的端点才延伸
        nodes = Counter([p for g in geo_list for p in [tuple(round(v,3) for v in g.coords[0]), tuple(round(v,3) for v in g.coords[-1])]])
        green_lines = []
        
        # 定义“挖掘区”范围，增加一点容差
        excavation_area = o_zone.buffer(0.5) if o_zone else d_zone.buffer(0.5) if d_zone else None

        for l in geo_list:
            if not sec_box.intersects(l): continue
            c = list(l.coords)
            for i in [0, -1]:
                pt = Point(c[i])
                # 条件：1. 是悬空端点(nodes==1) 2. 距离红线较远 3. 不在开挖区内部
                is_leaf = nodes[tuple(round(v,3) for v in c[i])] == 1
                is_far_red = red_geom.distance(pt) > 0.5
                is_outside = True if not excavation_area else not excavation_area.contains(pt)

                if is_leaf and is_far_red and is_outside:
                    tx = min_x if abs(c[i][0]-min_x) < abs(c[i][0]-max_x) else max_x
                    if i == 0: c.insert(0, (tx, c[i][1]))
                    else: c.append((tx, c[i][1]))
            green_lines.append(LineString(c))
        
        green_geom = unary_union(green_lines)

        # --- D. 蓝块切割与地层识别 ---
        frame_cutters = [
            LineString([(min_x, min_y), (max_x, min_y)]),
            LineString([(min_x, min_y), (min_x, max_y)]),
            LineString([(max_x, min_y), (max_x, max_y)])
        ]
        blue_cutters = unary_union(frame_cutters + [red_geom, green_geom])
        
        section_agg = defaultdict(lambda: {'d': 0.0, 'o': 0.0})

        for p in polygonize(blue_cutters):
            if sec_box.contains(p.centroid) and p.area > 0.1:
                name = "未知"
                for txt in all_texts:
                    try:
                        if p.buffer(0.3).contains(Point(txt.dxf.insert.vec2)):
                            name = txt.dxf.text if txt.dxftype()=='TEXT' else txt.text
                            if ";" in name: name = name.split(";")[-1].replace("}", "")
                            break
                    except: continue

                da = p.intersection(d_zone).area if (d_zone and p.intersects(d_zone)) else 0
                oa = p.intersection(n_zone).area if (n_zone and p.intersects(n_zone)) else 0
                section_agg[name]['d'] += da
                section_agg[name]['o'] += oa
                quick_draw(msp, doc, p, f"S{idx}_BLUE_GEO_BLOCK", 5, True)

        for name, areas in section_agg.items():
            if areas['d'] > 0.1 or areas['o'] > 0.1:
                final_report_data.append({'断面':f'S{idx}','地层':name,'设计':round(areas['d'],3),'净超挖':round(areas['o'],3)})

        # 可视化输出
        if d_zone: quick_draw(msp, doc, d_zone, f"S{idx}_YELLOW_DESIGN", 2, True)
        if n_zone: quick_draw(msp, doc, n_zone, f"S{idx}_PURPLE_NET_OVER", 6, True)
        quick_draw(msp, doc, red_geom, f"S{idx}_RED_GROUND", 1)
        quick_draw(msp, doc, green_geom, f"S{idx}_GREEN_GEO", 3)

    if final_report_data: pd.DataFrame(final_report_data).to_excel(OUTPUT_EXCEL, index=False)
    doc.saveas(OUTPUT_DXF)
    print(f"✅ 处理完成！新增图层：'开挖框'，计算顺序已优化。")

def quick_draw(msp, doc, geom, ly, col, closed=False):
    if not geom: return
    if ly not in doc.layers: doc.layers.add(ly, color=col)
    if hasattr(geom, 'geoms'):
        for g in geom.geoms: quick_draw(msp, doc, g, ly, col, closed)
    elif isinstance(geom, (LineString, Polygon)):
        pts = list(geom.coords) if isinstance(geom, LineString) else list(geom.exterior.coords)
        msp.add_lwpolyline(pts, dxfattribs={'layer': ly, 'closed': closed, 'color': col})

if __name__ == "__main__":
    main()