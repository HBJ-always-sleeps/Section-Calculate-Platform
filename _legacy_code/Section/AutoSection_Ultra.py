import ezdxf
import pandas as pd
from shapely.geometry import LineString, Point, box, Polygon
from shapely.ops import unary_union, snap, linemerge, polygonize
from collections import defaultdict, Counter

# ================= 配置区域 =================
INPUT_FILE = "nt.dxf"  # 已改回原始输入名
OUTPUT_DXF = "nt_v71_final_integration.dxf"
OUTPUT_EXCEL = "nt_final_report.xlsx"

LAYER_OVER = "超挖框"
LAYER_DESIGN = "开挖线"
LAYER_GROUND = "断面线"
LAYER_GEO = "地质分层"

MARGIN_X = 20.0
MARGIN_Y = 15.0
CYAN_EXTEND = 1.0  # 青线额外突出延伸，确保刺破框体
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
    """ 沿端点方向物理延伸线条 (用于绿线刺破) """
    coords = list(line.coords)
    if len(coords) < 2: return line
    p1, p2 = Point(coords[0]), Point(coords[1])
    vec_s = (p1.x - p2.x, p1.y - p2.y)
    mag_s = (vec_s[0]**2 + vec_s[1]**2)**0.5 or 1
    new_start = (p1.x + vec_s[0]/mag_s*dist, p1.y + vec_s[1]/mag_s*dist)
    p_n1, p_n = Point(coords[-2]), Point(coords[-1])
    vec_e = (p_n.x - p_n1.x, p_n.y - p_n1.y)
    mag_e = (vec_e[0]**2 + vec_e[1]**2)**0.5 or 1
    new_end = (p_n.x + vec_e[0]/mag_e*dist, p_n.y + vec_e[1]/mag_e*dist)
    return LineString([new_start] + coords + [new_end])

def build_final_poly(lines, ground_poly, top_y):
    """ 【核心替换：B部分新引擎】线段两端垂直延伸并与地面求交 """
    if not lines: return None
    all_pts = []
    for l in lines: all_pts.extend(list(l.coords))
    all_pts.sort(key=lambda p: p[0])
    # 向上垂直拉伸构面 (确保突出红线)
    poly_pts = [(all_pts[0][0], top_y), (all_pts[-1][0], top_y), (all_pts[-1][0], all_pts[-1][1])] + all_pts[::-1] + [(all_pts[0][0], all_pts[0][1])]
    ext_box = Polygon(poly_pts).buffer(0)
    return ext_box.intersection(ground_poly)

def main():
    print("🚀 启动 V71：基于 V51 骨架置换 Final 逻辑...")
    doc = ezdxf.readfile(INPUT_FILE)
    msp = doc.modelspace()

    # 1. 断面识别
    all_design_raw = get_lines_raw(msp, LAYER_DESIGN)
    if not all_design_raw: return
    group_polys = list(unary_union([l.buffer(5.0) for l in all_design_raw]).geoms)
    group_polys.sort(key=lambda p: p.bounds[0])

    all_ground = get_lines_raw(msp, LAYER_GROUND)
    all_over_raw = get_lines_raw(msp, LAYER_OVER)
    all_geo_raw = get_lines_raw(msp, LAYER_GEO)
    all_texts = [e for e in msp.query(f'*[layer=="{LAYER_GEO}"]') if e.dxftype() in ('TEXT', 'MTEXT')]
    
    merged_geo = linemerge(unary_union(all_geo_raw))
    geo_list = list(merged_geo.geoms) if hasattr(merged_geo, 'geoms') else [merged_geo]

    final_report_data = []

    for idx, g_poly in enumerate(group_polys, 1):
        x1, y1, x2, y2 = g_poly.bounds
        min_x, max_x, min_y, max_y = x1-MARGIN_X, x2+MARGIN_X, y1-MARGIN_Y, y2+MARGIN_Y
        sec_box = box(min_x, min_y, max_x, max_y)
        
        # --- A. 断面红线处理 (V51 原始逻辑) ---
        local_ground = [l for l in all_ground if sec_box.intersects(l)]
        if not local_ground: continue
        g_pts = sorted([p for l in local_ground for p in l.coords], key=lambda x: x[0])
        red_geom = LineString([(min_x, g_pts[0][1])] + g_pts + [(max_x, g_pts[-1][1])])

        # --- B. 计算 Yellow/Purple Final (注入新引擎，替换原 B 部分) ---
        ground_poly = Polygon([(min_x, min_y), (max_x, min_y), (max_x, g_pts[-1][1])] + g_pts[::-1] + [(min_x, g_pts[0][1])]).buffer(0)
        
        local_design = [l for l in all_design_raw if sec_box.intersects(l)]
        local_over = [l for l in all_over_raw if sec_box.intersects(l)]
        
        yellow_final = build_final_poly(local_design, ground_poly, max_y)
        total_over = build_final_poly(local_over, ground_poly, max_y)
        purple_final = total_over.difference(yellow_final) if (total_over and yellow_final) else total_over

        # --- C. 智能绿线生成 (V51 原始逻辑锁死) ---
        nodes = Counter([p for g in geo_list for p in [tuple(round(v,3) for v in g.coords[0]), tuple(round(v,3) for v in g.coords[-1])]])
        green_lines = []
        # 以 Final 框作为规避区域
        avoid_area = total_over.buffer(0.5) if total_over else None

        for l in geo_list:
            if not sec_box.intersects(l): continue
            c = list(l.coords)
            for i in [0, -1]:
                pt = Point(c[i])
                is_leaf = nodes[tuple(round(v,3) for v in c[i])] == 1
                is_far_red = red_geom.distance(pt) > 0.5
                is_outside = True if not avoid_area else not avoid_area.contains(pt)
                if is_leaf and is_far_red and is_outside:
                    tx = min_x if abs(c[i][0]-min_x) < abs(c[i][0]-max_x) else max_x
                    if i == 0: c.insert(0, (tx, c[i][1]))
                    else: c.append((tx, c[i][1]))
            green_lines.append(LineString(c))
        
        green_geom = unary_union(green_lines)
        cyan_geom = unary_union([extend_line_simple(l, CYAN_EXTEND) for l in green_lines])

        # --- D. 蓝块切割 (V51 原始逻辑锁死，仅算量关联 Final) ---
        frame_cutters = [
            LineString([(min_x, min_y), (max_x, min_y)]),
            LineString([(min_x, min_y), (min_x, max_y)]),
            LineString([(max_x, min_y), (max_x, max_y)])
        ]
        blue_cutters = unary_union(frame_cutters + [red_geom, cyan_geom])
        
        section_agg = defaultdict(lambda: {'d': 0.0, 'o': 0.0})
        for p in polygonize(blue_cutters):
            if sec_box.contains(p.centroid) and p.area > 0.1:
                # 重心必须在红线以下
                if p.centroid.y < red_geom.interpolate(red_geom.project(p.centroid)).y:
                    name = "未知"
                    for txt in all_texts:
                        if p.buffer(0.3).contains(Point(txt.dxf.insert.vec2)):
                            name = txt.dxf.text if txt.dxftype()=='TEXT' else txt.text
                            if ";" in name: name = name.split(";")[-1].replace("}", "")
                            break

                    # 算量使用新的 Final 模板
                    da = p.intersection(yellow_final).area if (yellow_final and p.intersects(yellow_final)) else 0
                    oa = p.intersection(purple_final).area if (purple_final and p.intersects(purple_final)) else 0
                    section_agg[name]['d'] += da
                    section_agg[name]['o'] += oa
                    quick_draw(msp, doc, p, f"S{idx}_BLUE_GEO_BLOCK", 5, True)

        for name, areas in section_agg.items():
            if areas['d'] > 0.1 or areas['o'] > 0.1:
                final_report_data.append({'断面':f'S{idx}','地层':name,'设计':round(areas['d'],3),'净超挖':round(areas['o'],3)})

        # --- 可视化输出：严格只画 Final 和 V51 基础线 ---
        if yellow_final: quick_draw(msp, doc, yellow_final, f"S{idx}_YELLOW_FINAL", 2, True)
        if purple_final: quick_draw(msp, doc, purple_final, f"S{idx}_PURPLE_FINAL", 6, True)
        quick_draw(msp, doc, red_geom, f"S{idx}_RED_GROUND", 1)
        quick_draw(msp, doc, green_geom, f"S{idx}_GREEN_GEO", 3)

    if final_report_data: pd.DataFrame(final_report_data).to_excel(OUTPUT_EXCEL, index=False)
    doc.saveas(OUTPUT_DXF)
    print(f"✅ V71 置换完成。红绿蓝逻辑锁死，黄紫框已更新为 Final 引擎，中间干扰层已剔除。")

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