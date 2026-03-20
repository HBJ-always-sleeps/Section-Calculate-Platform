# -*- coding: utf-8 -*-
import ezdxf
import pandas as pd
import os
import math
import traceback
from shapely.geometry import LineString, Point, box, Polygon, MultiLineString
from shapely.ops import unary_union, linemerge, polygonize
from collections import defaultdict, Counter

# ================= 辅助函数 =================
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

def get_line_direction(line, endpoint_idx):
    """获取线段在端点处的方向（角度，弧度）"""
    coords = list(line.coords)
    if len(coords) < 2:
        return 0
    if endpoint_idx == 0:
        # 起点方向：用前两个点
        dx = coords[1][0] - coords[0][0]
        dy = coords[1][1] - coords[0][1]
    else:
        # 终点方向：用最后两个点
        dx = coords[-1][0] - coords[-2][0]
        dy = coords[-1][1] - coords[-2][1]
    return math.atan2(dy, dx)  # 返回弧度

def extend_line_along_dir(line, dist, endpoint_idx):
    """沿端点方向延伸线段"""
    coords = list(line.coords)
    if len(coords) < 2:
        return line
    
    # 获取端点处的方向
    angle = get_line_direction(line, endpoint_idx)
    dx = dist * math.cos(angle)
    dy = dist * math.sin(angle)
    
    new_coords = list(coords)
    if endpoint_idx == 0:
        # 在起点前插入新点
        new_start = (coords[0][0] - dx, coords[0][1] - dy)
        new_coords.insert(0, new_start)
    else:
        # 在终点后追加新点
        new_end = (coords[-1][0] + dx, coords[-1][1] + dy)
        new_coords.append(new_end)
    
    return LineString(new_coords)

def get_segment_midpoint(p1, p2):
    """获取两个断面边界中点"""
    return (p1 + p2) / 2

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
    import re
    nums = re.findall(r'\d+', str(station_str))
    return int("".join(nums)) if nums else 0

def add_hatch_and_text(msp, poly, color, layer, text_height):
    """添加填充和文字标注并返回实体列表用于成组"""
    entities = []
    try:
        hatch = msp.add_hatch(dxfattribs={'layer': layer})
        hatch.rgb = color
        hatch.set_pattern_fill('ANSI31', scale=0.8)
        hatch.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True)
        for interior in poly.interiors:
            hatch.paths.add_polyline_path(list(interior.coords)[:-1], is_closed=True)
        entities.append(hatch)

        area_val = round(poly.area, 3)
        in_point = poly.representative_point()
        label_content = f"{{\\fArial|b1;{area_val}}}"
        mtext = msp.add_mtext(label_content, dxfattribs={
            'layer': layer + "_标注",
            'insert': (in_point.x, in_point.y),
            'char_height': text_height,
            'attachment_point': 5,
        })
        mtext.rgb = color
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
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    input_path = os.path.join(base_dir, "测试文件", "断面分类算量测试.dxf")
    
    def print_log(msg):
        print(msg)
    
    print(f"=== 测试模式: autosection_new.py ===")
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
        EXTEND_DIST = 50.0  # 延伸距离
        TEXT_H = 2.5

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

            # 调试图层
            LY_DEBUG = "AA_调试显示"
            if LY_DEBUG not in doc.layers: doc.layers.add(LY_DEBUG, color=1)
            for e in list(msp.query(f'*[layer=="{LY_DEBUG}"]')):
                msp.delete_entity(e)

            # 1. 预提取全局数据
            all_design_raw = get_lines_raw(msp, LY_DESIGN)
            if not all_design_raw: continue
            
            group_polys = list(unary_union([l.buffer(5.0) for l in all_design_raw]).geoms)
            group_polys.sort(key=lambda p: p.bounds[0])

            all_ground = get_lines_raw(msp, LY_GROUND)
            all_over_raw = get_lines_raw(msp, LY_OVER)
            all_geo_raw = get_lines_raw(msp, LY_GEO)
            all_texts = [e for e in msp.query(f'*[layer=="{LY_GEO}"]') if e.dxftype() in ('TEXT', 'MTEXT')]
            station_texts = [e for e in msp.query(f'*[layer=="{LY_STATION}"]') if e.dxftype() in ('TEXT', 'MTEXT')]

            final_report_data = []
            rgb_list = [(255,100,100), (100,255,100), (100,100,255), (255,215,0), (0,255,255), (255,0,255)]

            # 计算所有断面的 x 边界用于后续断面框对齐
            all_left_bounds = [p.bounds[0] for p in group_polys]
            all_right_bounds = [p.bounds[2] for p in group_polys]

            # 2. 逐断面处理
            for idx, g_poly in enumerate(group_polys, 1):
                x1, y1, x2, y2 = g_poly.bounds
                
                # 断面框对齐：使用相邻断面边界中点，避免重叠
                if idx == 1:
                    left_bound = x1
                else:
                    left_bound = get_segment_midpoint(all_right_bounds[idx-2], x1)
                
                if idx == len(group_polys):
                    right_bound = x2
                else:
                    right_bound = get_segment_midpoint(x2, all_left_bounds[idx])
                
                min_x, max_x = left_bound - MARGIN_X, right_bound + MARGIN_X
                min_y, max_y = y1 - MARGIN_Y, y2 + MARGIN_Y
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
                
                local_design = [l for l in all_design_raw if sec_box.intersects(l)]
                local_over = [l for l in all_over_raw if sec_box.intersects(l)]
                
                yellow_final = build_final_poly(local_design, ground_poly, max_y)
                total_over = build_final_poly(local_over, ground_poly, max_y)
                purple_final = total_over.difference(yellow_final) if (total_over and yellow_final) else total_over

                # ========== NEW: 合并所有线并延伸逻辑 ==========
                # 先合并所有本地断面线、开挖线、超挖框
                merged_lines = linemerge(unary_union(local_ground + local_design + local_over))
                merged_lines_list = list(merged_lines.geoms) if hasattr(merged_lines, 'geoms') else [merged_lines]
                
                # debug: 添加合并后的线到 debug 层（青色）
                for l in merged_lines_list:
                    coords = list(l.coords)
                    if len(coords) >= 2:
                        msp.add_polyline2d(coords, dxfattribs={'layer': LY_DEBUG, 'color': 4})
                
                # 构建节点度（用于识别末端）
                nodes = Counter([p for g in merged_lines_list for p in [tuple(round(v,3) for v in g.coords[0]), tuple(round(v,3) for v in g.coords[-1])]])
                
                # 所有末端都延伸
                extended_lines = []
                extended_count = 0
                
                for l in merged_lines_list:
                    # 检查两个端点
                    for i in [0, -1]:
                        node_key = tuple(round(v,3) for v in l.coords[i])
                        # 如果是末端（度为1），则延伸
                        if nodes[node_key] == 1:
                            # 沿末端方向延伸
                            new_line = extend_line_along_dir(l, EXTEND_DIST, i)
                            if new_line != l:
                                l = new_line
                                extended_count += 1
                    
                    extended_lines.append(l)
                
                # debug: 添加延伸后的线到 debug 层（绿色）
                for l in extended_lines:
                    coords = list(l.coords)
                    if len(coords) >= 2:
                        msp.add_polyline2d(coords, dxfattribs={'layer': LY_DEBUG, 'color': 3})
                
                LOG(f"   断面 {idx}: 合并 {len(merged_lines_list)} 条线 -> 延伸 {extended_count} 个端点")
                
                # ========== 地质线单独处理 ==========
                local_geo_raw = [l for l in all_geo_raw if sec_box.intersects(l)]
                
                # debug: 添加原始本地地质线到 debug 层（蓝色）
                for l in local_geo_raw:
                    coords = list(l.coords)
                    if len(coords) >= 2:
                        msp.add_polyline2d(coords, dxfattribs={'layer': LY_DEBUG, 'color': 5})
                
                if local_geo_raw:
                    # 地质线先合并成一个整体
                    merged_geo = linemerge(unary_union(local_geo_raw))
                    geo_list = list(merged_geo.geoms) if hasattr(merged_geo, 'geoms') else [merged_geo]
                    
                    # debug: 添加合并后的地质线到 debug 层（洋红色）
                    for l in geo_list:
                        coords = list(l.coords)
                        if len(coords) >= 2:
                            msp.add_polyline2d(coords, dxfattribs={'layer': LY_DEBUG, 'color': 6})
                    
                    # 计算地质线节点度
                    geo_nodes = Counter([p for g in geo_list for p in [tuple(round(v,3) for v in g.coords[0]), tuple(round(v,3) for v in g.coords[-1])]])
                    
                    # 延伸地质线末端
                    extended_geo = []
                    geo_extended_count = 0
                    
                    for l in geo_list:
                        for i in [0, -1]:
                            node_key = tuple(round(v,3) for v in l.coords[i])
                            if geo_nodes[node_key] == 1:
                                new_line = extend_line_along_dir(l, EXTEND_DIST, i)
                                if new_line != l:
                                    l = new_line
                                    geo_extended_count += 1
                        
                        extended_geo.append(l)
                    
                    # debug: 添加延伸后的地质线到 debug 层（黄色）
                    for l in extended_geo:
                        coords = list(l.coords)
                        if len(coords) >= 2:
                            msp.add_polyline2d(coords, dxfattribs={'layer': LY_DEBUG, 'color': 2})
                    
                    LOG(f"   地质线: 原始 {len(local_geo_raw)} 条 -> 合并 {len(geo_list)} 条 -> 延伸 {geo_extended_count} 个端点")
                else:
                    extended_geo = []
                
                # ==================================================
                
                # 添加断面框到 debug 层（红色）
                msp.add_polyline2d([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y), (min_x, min_y)], dxfattribs={'layer': LY_DEBUG, 'color': 1})
                
                # 添加地表线到 debug 层（白色）
                coords_red = list(red_geom.coords)
                msp.add_polyline2d(coords_red, dxfattribs={'layer': LY_DEBUG, 'color': 7})
                
                # 构建切割线集合
                boundary_poly = Polygon([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y), (min_x, min_y)])
                all_cutting_lines = unary_union([boundary_poly.exterior, red_geom] + extended_geo)
                
                # --- 地层切分与绘图成组逻辑 ---
                section_agg = defaultdict(lambda: {'d': 0.0, 'o': 0.0})
                group_collector = defaultdict(list) 

                # polygonize 生成面
                try:
                    all_zones = list(polygonize(all_cutting_lines))
                    LOG(f"   polygonize 生成 {len(all_zones)} 个面")
                except Exception as e:
                    all_zones = []
                    LOG(f"   polygonize 错误: {e}")
                
                if len(all_zones) == 0:
                    LOG(f"   ⚠️ 未生成有效面，跳过此断面")
                    continue
                
                for p in all_zones:
                    centroid = p.centroid
                    if not (min_x < centroid.x < max_x and min_y < centroid.y < max_y):
                        continue
                    if p.area < 0.05:
                        continue
                    
                    # 判定是否在地表线下方
                    try:
                        proj = red_geom.project(Point(centroid.x, centroid.y))
                        red_y = red_geom.interpolate(proj).y
                        if centroid.y >= red_y:
                            continue
                    except:
                        continue
                    
                    # 识别地质属性
                    name = "未知"
                    for txt_e in all_texts:
                        if p.buffer(0.3).contains(Point(txt_e.dxf.insert.vec2)):
                            name = (txt_e.dxf.text if txt_e.dxftype()=='TEXT' else txt_e.text).split(";")[-1].replace("}", "").strip()
                            break
                    
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

                # 执行 CAD 成组
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
                
                if test_mode:
                    base_name = os.path.basename(input_path).replace(".dxf", "")
                    report_name = os.path.join(os.path.dirname(input_path), f"{base_name}_autosection_new_test.xlsx")
                    res_dxf = os.path.join(os.path.dirname(input_path), f"{base_name}_autosection_new_test.dxf")
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

        LOG("✨ [地质拓扑增强算量任务全部结束]")

    except Exception as e:
        LOG(f"❌ 脚本执行崩溃:\n{traceback.format_exc()}")

if __name__ == "__main__":
    run_test()