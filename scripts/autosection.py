# -*- coding: utf-8 -*-
import ezdxf
import pandas as pd
import os
import math
import re
import traceback
from shapely.geometry import LineString, Point, box, Polygon
from shapely.ops import unary_union, linemerge, polygonize
from collections import defaultdict, Counter

# ================= 助手函数 =================
def get_lines_raw(msp, layer):
    lines = []
    try: 
        ents = msp.query(f'*[layer=="{layer}"]')
    except: 
        return []
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
    if not all_pts: return None
    poly_pts = [(all_pts[0][0], top_y), (all_pts[-1][0], top_y), (all_pts[-1][0], all_pts[-1][1])] + all_pts[::-1] + [(all_pts[0][0], all_pts[0][1])]
    ext_box = Polygon(poly_pts).buffer(0)
    return ext_box.intersection(ground_poly)

def station_sort_key(station_str):
    nums = re.findall(r'\d+', str(station_str))
    return int("".join(nums)) if nums else 0

def add_hatch_and_text(msp, poly, color, layer, text_height):
    """添加填充和文字标注并返回实体列表用于成组"""
    entities = []
    try:
        # A. 填充
        hatch = msp.add_hatch(dxfattribs={'layer': layer})
        hatch.rgb = color
        hatch.set_pattern_fill('ANSI31', scale=0.8)
        hatch.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True)
        for interior in poly.interiors:
            hatch.paths.add_polyline_path(list(interior.coords)[:-1], is_closed=True)
        entities.append(hatch)

        # B. 文字标注 (参考 adaptive 样式)
        area_val = round(poly.area, 3)
        in_point = poly.representative_point()
        # 不带序号，只带数值
        label_content = f"{{\\fArial|b1;{area_val}}}"
        mtext = msp.add_mtext(label_content, dxfattribs={
            'layer': layer + "_标注",
            'insert': (in_point.x, in_point.y),
            'char_height': text_height,
            'attachment_point': 5,
        })
        mtext.rgb = color
        # 增加背景遮罩兼容性设置
        try:
            mtext.dxf.bg_fill_setting = 1
            mtext.dxf.bg_fill_scale_factor = 1.3
        except: pass
        entities.append(mtext)
    except:
        pass
    return entities

# ================= 测试入口 =================
def run_test():
    """固定输入输出的测试入口"""
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    input_path = os.path.join(base_dir, "测试文件", "断面分类算量测试.dxf")
    
    def print_log(msg):
        print(msg)
    
    print(f"=== 测试模式: autosection.py ===")
    print(f"输入文件: {input_path}")
    
    if not os.path.exists(input_path):
        print(f"❌ 输入文件不存在!")
        return
    
    run_task({'files': [input_path]}, print_log, test_mode=True)

# ================= 主入口 =================
def run_task(params, LOG, test_mode=False):
    try:
        LY_OVER = params.get('超挖框', '超挖框')
        LY_DESIGN = params.get('设计线', '开挖线')
        LY_GROUND = params.get('断面线', '断面线')
        LY_GEO = params.get('地层层', '地质分层')
        LY_STATION = params.get('桩号层', '桩号')
        LY_HATCH = "AA_填充算量层" 

        MARGIN_X, MARGIN_Y = 20.0, 25.0
        CYAN_EXTEND = 1.0
        TEXT_H = 2.5 # 标注字高

        file_list = params.get('files', [])
        if not file_list:
            LOG("⚠️ 请先在 UI 界面选择 DXF 文件。")
            return

        for input_path in file_list:
            LOG(f"--- ⏳ 处理航道断面: {os.path.basename(input_path)} ---")
            doc = ezdxf.readfile(input_path)
            msp = doc.modelspace()
            dxf_groups = doc.groups

            if LY_HATCH not in doc.layers: doc.layers.add(LY_HATCH, color=7)
            if (LY_HATCH + "_标注") not in doc.layers: doc.layers.add(LY_HATCH + "_标注", color=7)

            # 1. 预提取全局数据
            all_design_raw = get_lines_raw(msp, LY_DESIGN)
            if not all_design_raw: continue
            
            group_polys = list(unary_union([l.buffer(5.0) for l in all_design_raw]).geoms) if hasattr(unary_union([l.buffer(5.0) for l in all_design_raw]), 'geoms') else [unary_union([l.buffer(5.0) for l in all_design_raw])]
            group_polys.sort(key=lambda p: p.bounds[0])

            all_ground = get_lines_raw(msp, LY_GROUND)
            all_over_raw = get_lines_raw(msp, LY_OVER)
            all_geo_raw = get_lines_raw(msp, LY_GEO)
            all_texts = [e for e in msp.query(f'*[layer=="{LY_GEO}"]') if e.dxftype() in ('TEXT', 'MTEXT')]
            station_texts = [e for e in msp.query(f'*[layer=="{LY_STATION}"]') if e.dxftype() in ('TEXT', 'MTEXT')]
            
            merged_geo = linemerge(unary_union(all_geo_raw))
            geo_list = list(merged_geo.geoms) if hasattr(merged_geo, 'geoms') else [merged_geo]

            final_report_data = []
            rgb_list = [(255,100,100), (100,255,100), (100,100,255), (255,215,0), (0,255,255), (255,0,255)]

            # 2. 逐断面处理
            for idx, g_poly in enumerate(group_polys, 1):
                x1, y1, x2, y2 = g_poly.bounds
                min_x, max_x, min_y, max_y = x1-MARGIN_X, x2+MARGIN_X, y1-MARGIN_Y, y2+MARGIN_Y
                sec_box = box(min_x, min_y, max_x, max_y)
                
                # 桩号识别
                current_st = f"S{idx}"; best_d = 1e6
                for st in station_texts:
                    ins_pt = Point(st.dxf.insert.vec2)
                    if sec_box.contains(ins_pt):
                        d = ins_pt.distance(Point((x1+x2)/2, y1))
                        if d < best_d: 
                            best_d = d; current_st = (st.dxf.text if st.dxftype()=='TEXT' else st.text).split(";")[-1].replace("}", "").strip()

                # 地形多边形生成
                local_ground = [l for l in all_ground if sec_box.intersects(l)]
                if not local_ground: continue
                g_pts = sorted([p for l in local_ground for p in l.coords], key=lambda x: x[0])
                red_geom = LineString([(min_x, g_pts[0][1])] + g_pts + [(max_x, g_pts[-1][1])])
                ground_poly = Polygon([(min_x, min_y), (max_x, min_y), (max_x, g_pts[-1][1])] + g_pts[::-1] + [(min_x, g_pts[0][1])]).buffer(0)
                
                yellow_final = build_final_poly([l for l in all_design_raw if sec_box.intersects(l)], ground_poly, max_y)
                total_over = build_final_poly([l for l in all_over_raw if sec_box.intersects(l)], ground_poly, max_y)
                purple_final = total_over.difference(yellow_final) if (total_over and yellow_final) else total_over

                # 绿线边界推断
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
                
                blue_cutters = unary_union([LineString([(min_x, min_y), (max_x, min_y)]), LineString([(min_x, min_y), (min_x, max_y)]), LineString([(max_x, min_y), (max_x, max_y)]), red_geom, unary_union([extend_line_simple(l, CYAN_EXTEND) for l in green_lines])])
                
                # --- 地层切分与绘图成组逻辑 ---
                section_agg = defaultdict(lambda: {'d': 0.0, 'o': 0.0})
                # 用于存储当前断面、当前地层的所有 CAD 实体，方便成组
                group_collector = defaultdict(list) 

                for p in polygonize(blue_cutters):
                    if sec_box.contains(p.centroid) and p.area > 0.05 and p.centroid.y < red_geom.interpolate(red_geom.project(p.centroid)).y:
                        name = "未知"
                        for txt_e in all_texts:
                            if p.buffer(0.3).contains(Point(txt_e.dxf.insert.vec2)):
                                name = (txt_e.dxf.text if txt_e.dxftype()=='TEXT' else txt_e.text).split(";")[-1].replace("}", "").strip(); break
                        
                        # 处理设计量
                        if yellow_final and p.intersects(yellow_final):
                            p_design = p.intersection(yellow_final)
                            if p_design.area > 0.05:
                                color = rgb_list[abs(hash(name)) % len(rgb_list)]
                                ents = add_hatch_and_text(msp, p_design, color, LY_HATCH, TEXT_H)
                                group_collector[f"{name}_设计"].extend(ents)
                                section_agg[name]['d'] += p_design.area

                        # 处理净超挖量
                        if purple_final and p.intersects(purple_final):
                            p_over = p.intersection(purple_final)
                            if p_over.area > 0.05:
                                color = rgb_list[(abs(hash(name)) + 1) % len(rgb_list)]
                                ents = add_hatch_and_text(msp, p_over, color, LY_HATCH, TEXT_H)
                                group_collector[f"{name}_超挖"].extend(ents)
                                section_agg[name]['o'] += p_over.area

                # 执行 CAD 成组：同一个断面内，同地层同类型的块编为一个组
                for g_name, ents in group_collector.items():
                    if len(ents) > 1:
                        try:
                            new_group = dxf_groups.new()
                            new_group.add_entities(ents)
                        except: pass

                for name, areas in section_agg.items():
                    if areas['d'] > 0.05 or areas['o'] > 0.05:
                        final_report_data.append({'断面': f'S{idx}', '桩号': current_st, '地层': name, '设计': round(areas['d'], 3), '净超挖': round(areas['o'], 3)})

            # 3. 汇总导出
            if final_report_data:
                df = pd.DataFrame(final_report_data)
                df['sort_key'] = df['桩号'].apply(station_sort_key)
                df_sorted = df.sort_values(by='sort_key')
                # 测试模式使用 v2 后缀避免撞名
                if test_mode:
                    report_name = input_path.replace(".dxf", "_autosection_v2_test.xlsx")
                    res_dxf = input_path.replace(".dxf", "_autosection_v2_test.dxf")
                else:
                    report_name = input_path.replace(".dxf", "_算量汇总_v2.xlsx")
                    res_dxf = input_path.replace(".dxf", "_RESULT_v2.dxf")
                with pd.ExcelWriter(report_name) as writer:
                    df_sorted[['断面', '桩号', '地层', '设计', '净超挖']].to_excel(writer, sheet_name='Sheet1', index=False)
                    df_sorted.pivot_table(index='桩号', columns='地层', values='设计', aggfunc='sum', sort=False).fillna(0).to_excel(writer, sheet_name='设计量汇总')
                    df_sorted.pivot_table(index='桩号', columns='地层', values='净超挖', aggfunc='sum', sort=False).fillna(0).to_excel(writer, sheet_name='净超挖汇总')
                
                doc.saveas(res_dxf)
                LOG(f"✅ 处理成功！断面数: {len(group_polys)}")
                LOG(f"   输出DXF: {res_dxf}")
                LOG(f"   输出Excel: {report_name}")
            else:
                LOG(f"⚠️ {os.path.basename(input_path)} 未识别到有效计算区域。")

        LOG("✨ [航道地层分类算量任务全部结束]")

    except Exception as e:
        LOG(f"❌ 脚本执行崩溃:\n{traceback.format_exc()}")

if __name__ == "__main__":
    run_test()
