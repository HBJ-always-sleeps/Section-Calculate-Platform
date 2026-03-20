import ezdxf
import pandas as pd
from shapely.geometry import LineString, Point, box, Polygon
from shapely.ops import unary_union, snap, linemerge, polygonize
from collections import defaultdict, Counter

# ================= 配置区域 =================
INPUT_FILE = "tt.dxf"
OUTPUT_DXF = "tt_v51_fixed.dxf"
OUTPUT_EXCEL = "t_final_report.xlsx"

LAYER_OVER = "超挖框"
LAYER_DESIGN = "开挖线"
LAYER_GROUND = "断面线"
LAYER_GEO = "地质分层"

MARGIN_X = 20.0
MARGIN_Y = 15.0
EXTEND_DIST = 3.0       # 业务线延伸
CYAN_EXTEND = 1.0       # 青线额外突出延伸，确保刺破框体
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
    mag_s = (vec_s[0]**2 + vec_s[1]**2)**0.5 or 1
    new_start = (p1.x + vec_s[0]/mag_s*dist, p1.y + vec_s[1]/mag_s*dist)
    # 终点延伸
    p_n1, p_n = Point(coords[-2]), Point(coords[-1])
    vec_e = (p_n.x - p_n1.x, p_n.y - p_n1.y)
    mag_e = (vec_e[0]**2 + vec_e[1]**2)**0.5 or 1
    new_end = (p_n.x + vec_e[0]/mag_e*dist, p_n.y + vec_e[1]/mag_e*dist)
    return LineString([new_start] + coords + [new_end])

def main():
    print("🚀 启动 V51：锁定原始线 -> 插入青线副本 -> 蓝块围合优化...")
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
    
    merged_geo = linemerge(unary_union(all_geo_raw))
    geo_list = list(merged_geo.geoms) if hasattr(merged_geo, 'geoms') else [merged_geo]

    final_report_data = []

    for idx, g_poly in enumerate(group_polys, 1):
        x1, y1, x2, y2 = g_poly.bounds
        min_x, max_x, min_y, max_y = x1-MARGIN_X, x2+MARGIN_X, y1-MARGIN_Y, y2+MARGIN_Y
        sec_box = box(min_x, min_y, max_x, max_y)
        
        # --- A. 断面红线处理 (严格不动) ---
        local_ground = [l for l in all_ground if sec_box.intersects(l)]
        if not local_ground: continue
        red_geom = unary_union([LineString([(min_x, l.coords[0][1])] + list(l.coords) + [(max_x, l.coords[-1][1])]) for l in local_ground])

        # --- B. 黄紫框 (严格不动) ---
        raw_y = [l for l in get_lines_raw(msp, LAYER_DESIGN) if sec_box.intersects(l)]
        raw_o = [l for l in get_lines_raw(msp, LAYER_OVER) if sec_box.intersects(l)]
        ext_y = [extend_line_simple(l, EXTEND_DIST) for l in raw_y]
        ext_o = [extend_line_simple(l, EXTEND_DIST) for l in raw_o]
        quick_draw(msp, doc, unary_union(ext_y), "开挖框", 2)

        def build_fast_zone(ext_lines):
            if not ext_lines: return None
            combined = unary_union([snap(unary_union(ext_lines), red_geom, 0.1), red_geom])
            ps = [p for p in polygonize(combined) if p.area > 0.1 and sec_box.intersects(p.centroid)]
            return unary_union(ps) if ps else None

        d_zone = build_fast_zone(ext_y)
        o_zone = build_fast_zone(ext_o)
        n_zone = o_zone.difference(d_zone) if (o_zone and d_zone) else o_zone

        # --- C. 智能绿线生成 (严格不动原始逻辑) ---
        nodes = Counter([p for g in geo_list for p in [tuple(round(v,3) for v in g.coords[0]), tuple(round(v,3) for v in g.coords[-1])]])
        green_lines = []
        excavation_area = o_zone.buffer(0.5) if o_zone else d_zone.buffer(0.5) if d_zone else None

        for l in geo_list:
            if not sec_box.intersects(l): continue
            c = list(l.coords)
            for i in [0, -1]:
                pt = Point(c[i])
                is_leaf = nodes[tuple(round(v,3) for v in c[i])] == 1
                is_far_red = red_geom.distance(pt) > 0.5
                is_outside = True if not excavation_area else not excavation_area.contains(pt)
                if is_leaf and is_far_red and is_outside:
                    tx = min_x if abs(c[i][0]-min_x) < abs(c[i][0]-max_x) else max_x
                    if i == 0: c.insert(0, (tx, c[i][1]))
                    else: c.append((tx, c[i][1]))
            green_lines.append(LineString(c))
        
        green_geom = unary_union(green_lines)

        # --- 新增：复制绿线生成青线并进行物理突出延伸 ---
        cyan_lines = [extend_line_simple(l, CYAN_EXTEND) for l in green_lines]
        cyan_geom = unary_union(cyan_lines)

        # --- D. 蓝块切割 (参数由 green_geom 改为 cyan_geom) ---
        frame_cutters = [
            LineString([(min_x, min_y), (max_x, min_y)]),
            LineString([(min_x, min_y), (min_x, max_y)]),
            LineString([(max_x, min_y), (max_x, max_y)])
        ]
        # 此处使用 cyan_geom 确保刺破
        blue_cutters = unary_union(frame_cutters + [red_geom, cyan_geom])
        
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
        quick_draw(msp, doc, cyan_geom, f"S{idx}_CYAN_CALC", 4) # 物理写入青线图层方便检查

    if final_report_data: pd.DataFrame(final_report_data).to_excel(OUTPUT_EXCEL, index=False)
    doc.saveas(OUTPUT_DXF)
    print(f"✅ V51 完成：业务线逻辑未动，已通过青线副本（CYAN_CALC）优化闭合判定。")

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