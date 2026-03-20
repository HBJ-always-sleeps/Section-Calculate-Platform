import ezdxf
import pandas as pd
import os
import math
import re
from shapely.geometry import LineString, Point, box, Polygon
from shapely.ops import unary_union, linemerge, polygonize
from collections import defaultdict, Counter

# ================= 核心配置 =================
INPUT_FILE = "nt.dxf"
OUTPUT_DXF = "nt_v82_final.dxf"
OUTPUT_EXCEL = "最终核准报表_V82.xlsx"

LAYER_OVER = "超挖框"
LAYER_DESIGN = "开挖线"
LAYER_GROUND = "断面线"
LAYER_GEO = "地质分层"
LAYER_STATION = "桩号"
LAYER_HATCH = "AA_填充算量层"

MARGIN_X = 20.0
MARGIN_Y = 25.0
CYAN_EXTEND = 1.0
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
    if not lines: return None
    all_pts = []
    for l in lines: all_pts.extend(list(l.coords))
    all_pts.sort(key=lambda p: p[0])
    poly_pts = [(all_pts[0][0], top_y), (all_pts[-1][0], top_y), (all_pts[-1][0], all_pts[-1][1])] + all_pts[::-1] + [(all_pts[0][0], all_pts[0][1])]
    ext_box = Polygon(poly_pts).buffer(0)
    return ext_box.intersection(ground_poly)

def quick_draw(msp, doc, geom, ly, col, closed=False):
    if not geom: return
    if ly not in doc.layers: doc.layers.add(ly, color=col)
    if hasattr(geom, 'geoms'):
        for g in geom.geoms: quick_draw(msp, doc, g, ly, col, closed)
    elif isinstance(geom, (LineString, Polygon)):
        pts = list(geom.coords) if isinstance(geom, LineString) else list(geom.exterior.coords)
        msp.add_lwpolyline(pts, dxfattribs={'layer': ly, 'closed': closed, 'color': col})

def station_sort_key(station_str):
    """ 提取桩号中的数字进行逻辑排序，如 K71+300 -> 71300 """
    nums = re.findall(r'\d+', str(station_str))
    return int("".join(nums)) if nums else 0

def main():
    print("🚀 启动 V82：独立填充先行 + V71 内核锁死 + 汇总表桩号排序...")
    doc = ezdxf.readfile(INPUT_FILE)
    msp = doc.modelspace()

    # --- 第一步：独立填充模块 (纯可视化，不参与后面计算) ---
    core_layers = {LAYER_OVER, LAYER_DESIGN, LAYER_GROUND, LAYER_GEO}
    fill_lines = []
    for ly in core_layers:
        fill_lines.extend(get_lines_raw(msp, ly))
    
    if fill_lines:
        if LAYER_HATCH not in doc.layers: doc.layers.add(LAYER_HATCH, color=7)
        # 仅针对可见的核心层线条进行封闭面填充
        pure_polys = list(polygonize(unary_union(fill_lines)))
        rgb_list = [(255,200,200), (200,255,200), (200,200,255), (255,255,180), (220,180,255)]
        for i, poly in enumerate([p for p in pure_polys if p.area > 0.1]):
            try:
                h = msp.add_hatch(dxfattribs={'layer': LAYER_HATCH})
                h.rgb = rgb_list[i % len(rgb_list)]
                h.set_pattern_fill('ANSI31', scale=0.8)
                h.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True)
            except: continue
        print(f" -> 已完成纯可视化填充：{len(pure_polys)} 块")

    # --- 第二步：严格复刻 V71 计算内核 ---
    all_design_raw = get_lines_raw(msp, LAYER_DESIGN)
    if not all_design_raw: return
    group_polys = list(unary_union([l.buffer(5.0) for l in all_design_raw]).geoms)
    group_polys.sort(key=lambda p: p.bounds[0]) # 保持 S1, S2 的水平排列顺序

    all_ground = get_lines_raw(msp, LAYER_GROUND)
    all_over_raw = get_lines_raw(msp, LAYER_OVER)
    all_geo_raw = get_lines_raw(msp, LAYER_GEO)
    all_texts = [e for e in msp.query(f'*[layer=="{LAYER_GEO}"]') if e.dxftype() in ('TEXT', 'MTEXT')]
    station_texts = [e for e in msp.query(f'*[layer=="{LAYER_STATION}"]') if e.dxftype() in ('TEXT', 'MTEXT')]
    
    merged_geo = linemerge(unary_union(all_geo_raw))
    geo_list = list(merged_geo.geoms) if hasattr(merged_geo, 'geoms') else [merged_geo]

    final_report_data = []

    for idx, g_poly in enumerate(group_polys, 1):
        x1, y1, x2, y2 = g_poly.bounds
        min_x, max_x, min_y, max_y = x1-MARGIN_X, x2+MARGIN_X, y1-MARGIN_Y, y2+MARGIN_Y
        sec_box = box(min_x, min_y, max_x, max_y)
        
        # 桩号映射获取
        current_st = f"S{idx}"
        best_d = 1e6
        for st in station_texts:
            pt = Point(st.dxf.insert.vec2)
            if sec_box.contains(pt):
                d = pt.distance(Point((x1+x2)/2, y1))
                if d < best_d:
                    best_d = d
                    txt = st.dxf.text if st.dxftype()=='TEXT' else st.text
                    current_st = txt.split(";")[-1].replace("}", "").strip()

        # --- 以下为 V71 原版几何逻辑 ---
        local_ground = [l for l in all_ground if sec_box.intersects(l)]
        if not local_ground: continue
        g_pts = sorted([p for l in local_ground for p in l.coords], key=lambda x: x[0])
        red_geom = LineString([(min_x, g_pts[0][1])] + g_pts + [(max_x, g_pts[-1][1])])
        ground_poly = Polygon([(min_x, min_y), (max_x, min_y), (max_x, g_pts[-1][1])] + g_pts[::-1] + [(min_x, g_pts[0][1])]).buffer(0)
        
        local_design = [l for l in all_design_raw if sec_box.intersects(l)]
        local_over = [l for l in all_over_raw if sec_box.intersects(l)]
        yellow_final = build_final_poly(local_design, ground_poly, max_y)
        total_over = build_final_poly(local_over, ground_poly, max_y)
        purple_final = total_over.difference(yellow_final) if (total_over and yellow_final) else total_over

        nodes = Counter([p for g in geo_list for p in [tuple(round(v,3) for v in g.coords[0]), tuple(round(v,3) for v in g.coords[-1])]])
        green_lines = []
        avoid_area = total_over.buffer(0.5) if total_over else None
        for l in geo_list:
            if not sec_box.intersects(l): continue
            c = list(l.coords)
            for i in [0, -1]:
                pt = Point(c[i])
                if nodes[tuple(round(v,3) for v in c[i])] == 1 and red_geom.distance(pt) > 0.5 and (not avoid_area or not avoid_area.contains(pt)):
                    tx = min_x if abs(c[i][0]-min_x) < abs(c[i][0]-max_x) else max_x
                    if i == 0: c.insert(0, (tx, c[i][1]))
                    else: c.append((tx, c[i][1]))
            green_lines.append(LineString(c))
        cyan_geom = unary_union([extend_line_simple(l, CYAN_EXTEND) for l in green_lines])

        frame_cutters = [LineString([(min_x, min_y), (max_x, min_y)]), LineString([(min_x, min_y), (min_x, max_y)]), LineString([(max_x, min_y), (max_x, max_y)])]
        blue_cutters = unary_union(frame_cutters + [red_geom, cyan_geom])
        
        section_agg = defaultdict(lambda: {'d': 0.0, 'o': 0.0})
        for p in polygonize(blue_cutters):
            if sec_box.contains(p.centroid) and p.area > 0.1 and p.centroid.y < red_geom.interpolate(red_geom.project(p.centroid)).y:
                name = "未知"
                for txt in all_texts:
                    if p.buffer(0.3).contains(Point(txt.dxf.insert.vec2)):
                        name = (txt.dxf.text if txt.dxftype()=='TEXT' else txt.text).split(";")[-1].replace("}", "").strip()
                        break
                da = p.intersection(yellow_final).area if (yellow_final and p.intersects(yellow_final)) else 0
                oa = p.intersection(purple_final).area if (purple_final and p.intersects(purple_final)) else 0
                section_agg[name]['d'] += da
                section_agg[name]['o'] += oa

        for name, areas in section_agg.items():
            if areas['d'] > 0.1 or areas['o'] > 0.1:
                final_report_data.append({'断面': f'S{idx}', '桩号': current_st, '地层': name, '设计': round(areas['d'], 3), '净超挖': round(areas['o'], 3)})

        # 辅助线画图 (维持 V71 原样)
        if yellow_final: quick_draw(msp, doc, yellow_final, f"S{idx}_YELLOW_V71", 2, True)
        if purple_final: quick_draw(msp, doc, purple_final, f"S{idx}_PURPLE_V71", 6, True)
        quick_draw(msp, doc, red_geom, f"S{idx}_RED_V71", 1)

    # --- 第三步：汇总导出 (按桩号逻辑排序) ---
    if final_report_data:
        df = pd.DataFrame(final_report_data)
        # 为汇总表准备：按桩号中的数字大小排序
        df['sort_key'] = df['桩号'].apply(station_sort_key)
        df_sorted = df.sort_values(by='sort_key')

        with pd.ExcelWriter(OUTPUT_EXCEL) as writer:
            # Sheet1: 严格原始清单 (断面, 地层, 设计, 净超挖)
            df[['断面', '地层', '设计', '净超挖']].to_excel(writer, sheet_name='Sheet1', index=False)
            
            # Sheet2 & 3: 汇总表 (按桩号排序，第一列桩号，横向地层)
            pivot_design = df_sorted.pivot_table(index='桩号', columns='地层', values='设计', aggfunc='sum', sort=False).fillna(0)
            pivot_over = df_sorted.pivot_table(index='桩号', columns='地层', values='净超挖', aggfunc='sum', sort=False).fillna(0)
            
            pivot_design.to_excel(writer, sheet_name='设计量汇总')
            pivot_over.to_excel(writer, sheet_name='净超挖汇总')
        print(f"✅ 报表导出完成：{OUTPUT_EXCEL}")

    doc.saveas(OUTPUT_DXF)
    print(f"✅ CAD文件保存完成：{OUTPUT_DXF}")

if __name__ == "__main__":
    main()