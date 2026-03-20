# -*- coding: utf-8 -*-
"""
诊断脚本：用于诊断净超挖漏填充原因
"""
import ezdxf
import pandas as pd
import os
import traceback
from shapely.geometry import LineString, Point, box, Polygon, MultiPolygon
from shapely.ops import unary_union, linemerge, polygonize
from collections import defaultdict, Counter

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

def build_final_poly(lines, ground_poly, top_y):
    if not lines: return None
    all_pts = []
    for l in lines: all_pts.extend(list(l.coords))
    all_pts.sort(key=lambda p: p[0])
    if not all_pts: return None
    poly_pts = [(all_pts[0][0], top_y), (all_pts[-1][0], top_y), (all_pts[-1][0], all_pts[-1][1])] + all_pts[::-1] + [(all_pts[0][0], all_pts[0][1])]
    ext_box = Polygon(poly_pts).buffer(0)
    return ext_box.intersection(ground_poly)

def run_diagnostic(params, LOG):
    """
    诊断脚本：分析净超挖漏填充原因
    """
    try:
        LY_OVER = params.get('超挖框', '超挖框')
        LY_DESIGN = params.get('设计线', '开挖线')
        LY_GROUND = params.get('断面线', '断面线')
        LY_GEO = params.get('地层层', '地质分层')
        LY_STATION = params.get('桩号层', '桩号')
        
        MARGIN_X, MARGIN_Y = 20.0, 25.0
        EXTEND_DIST = 50.0

        file_list = params.get('files', [])
        if not file_list:
            LOG("⚠️ 请先在 UI 界面选择 DXF 文件。")
            return

        for input_path in file_list:
            LOG(f"=== 诊断测试: {os.path.basename(input_path)} ===")
            doc = ezdxf.readfile(input_path)
            msp = doc.modelspace()
            
            # 创建错误日志层
            if 'ERROR_LOG' not in doc.layers:
                doc.layers.add('ERROR_LOG', color=1)

            # 预提取全局数据
            all_design_raw = get_lines_raw(msp, LY_DESIGN)
            if not all_design_raw:
                LOG("❌ 没有找到设计线（开挖线）")
                continue
            
            group_polys = list(unary_union([l.buffer(5.0) for l in all_design_raw]).geoms)
            group_polys.sort(key=lambda p: p.bounds[0])

            all_ground = get_lines_raw(msp, LY_GROUND)
            all_over_raw = get_lines_raw(msp, LY_OVER)
            all_geo_raw = get_lines_raw(msp, LY_GEO)
            all_texts = [e for e in msp.query(f'*[layer=="{LY_GEO}"]') if e.dxftype() in ('TEXT', 'MTEXT')]

            # 逐断面诊断
            for idx, g_poly in enumerate(group_polys, 1):
                x1, y1, x2, y2 = g_poly.bounds
                min_x, max_x, min_y, max_y = x1-MARGIN_X, x2+MARGIN_X, y1-MARGIN_Y, y2+MARGIN_Y
                sec_box = box(min_x, min_y, max_x, max_y)
                
                LOG(f"\n--- 诊断断面 {idx}: ({x1:.1f}, {y1:.1f}) -> ({x2:.1f}, {y2:.1f}) ---")
                
                # 地形多边形生成
                local_ground = [l for l in all_ground if sec_box.intersects(l)]
                if not local_ground:
                    LOG(f"   ⚠️ 断面 {idx}: 没有找到断面线")
                    continue
                    
                g_pts = sorted([p for l in local_ground for p in l.coords], key=lambda x: x[0])
                red_geom = LineString([(min_x, g_pts[0][1])] + g_pts + [(max_x, g_pts[-1][1])])
                ground_poly = Polygon([(min_x, min_y), (max_x, min_y), (max_x, g_pts[-1][1])] + g_pts[::-1] + [(min_x, g_pts[0][1])]).buffer(0)
                
                local_design = [l for l in all_design_raw if sec_box.intersects(l)]
                local_over = [l for l in all_over_raw if sec_box.intersects(l)]
                
                yellow_final = build_final_poly(local_design, ground_poly, max_y)
                total_over = build_final_poly(local_over, ground_poly, max_y)
                
                # ============ 诊断点 A: 超挖总框 ============
                if not total_over or total_over.is_empty:
                    LOG("   ❌ 诊断[超挖总框]: 原始超挖线无法生成有效多边形")
                else:
                    LOG(f"   ✅ 诊断[超挖总框]: 有效，面积={total_over.area:.2f}")

                # ============ 诊断点 B: 设计框 ============
                if not yellow_final or yellow_final.is_empty:
                    LOG("   ⚠️ 诊断[设计框]: 设计线多边形为空")
                    yellow_final = ground_poly  # 退化为地表多边形
                else:
                    LOG(f"   ✅ 诊断[设计框]: 有效，面积={yellow_final.area:.2f}")

                # ============ 诊断点 C: 差集运算 ============
                # 使用小 buffer 消除浮点误差
                total_over_buf = total_over.buffer(0.001) if total_over else None
                yellow_buf = yellow_final.buffer(-0.001) if yellow_final else None
                purple_final = total_over_buf.difference(yellow_buf) if (total_over_buf and yellow_buf) else None
                
                if not purple_final or purple_final.is_empty:
                    LOG("   ❌ 诊断[差集结果]: 差集后结果为空（超挖线可能完全在设计线内部）")
                    continue
                else:
                    if isinstance(purple_final, MultiPolygon):
                        LOG(f"   ✅ 诊断[差集结果]: 生成 {len(list(purple_final.geoms))} 个独立区域")
                    else:
                        LOG(f"   ✅ 诊断[差集结果]: 面积={purple_final.area:.2f}")

                # ============ 诊断点 D: 地质线处理 ============
                local_geo_raw = [l for l in all_geo_raw if sec_box.intersects(l)]
                if local_geo_raw:
                    merged_geo = linemerge(unary_union(local_geo_raw))
                    geo_list = list(merged_geo.geoms) if hasattr(merged_geo, 'geoms') else [merged_geo]
                    
                    # 延伸地质线
                    nodes = Counter([p for g in geo_list for p in [tuple(round(v,3) for v in g.coords[0]), tuple(round(v,3) for v in g.coords[-1])]])
                    extended_geo = []
                    
                    for l in geo_list:
                        c = list(l.coords)
                        for i in [0, -1]:
                            if nodes[tuple(round(v,3) for v in c[i])] == 1:
                                # 沿末端方向延伸
                                if i == 0 and len(c) >= 2:
                                    dx = c[1][0] - c[0][0]
                                    dy = c[1][1] - c[0][1]
                                    mag = (dx**2 + dy**2)**0.5 or 1
                                    c.insert(0, (c[0][0] - dx/mag*EXTEND_DIST, c[0][1] - dy/mag*EXTEND_DIST))
                                elif i == -1 and len(c) >= 2:
                                    dx = c[-1][0] - c[-2][0]
                                    dy = c[-1][1] - c[-2][1]
                                    mag = (dx**2 + dy**2)**0.5 or 1
                                    c.append((c[-1][0] + dx/mag*EXTEND_DIST, c[-1][1] + dy/mag*EXTEND_DIST))
                        extended_geo.append(LineString(c))
                else:
                    extended_geo = []
                
                # ============ 诊断点 E: 构建切割线 ============
                boundary_poly = Polygon([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y), (min_x, min_y)])
                all_cutting_lines = unary_union([boundary_poly.exterior, red_geom] + extended_geo)
                
                # ============ 诊断点 F: polygonize 分析 ============
                try:
                    all_zones = list(polygonize(all_cutting_lines))
                    LOG(f"   polygonize 生成 {len(all_zones)} 个面")
                except Exception as e:
                    LOG(f"   ❌ polygonize 错误: {e}")
                    continue
                
                # ============ 诊断点 G: 每个面的详细分析 ============
                actual_count = 0
                missing_count = 0
                area_missing = 0
                
                for p in all_zones:
                    centroid = p.centroid
                    if not (min_x < centroid.x < max_x and min_y < centroid.y < max_y):
                        continue
                    if p.area < 0.05:
                        continue
                    
                    # 检查是否在地表线下
                    try:
                        proj = red_geom.project(Point(centroid.x, centroid.y))
                        red_y = red_geom.interpolate(proj).y
                        if centroid.y >= red_y:
                            continue
                    except:
                        continue
                    
                    # 诊断净超挖相交
                    if purple_final:
                        if p.intersects(purple_final):
                            p_over = p.intersection(purple_final)
                            if p_over.is_empty:
                                LOG(f"   ❓ 异常: 地块({centroid.x:.1f}) 有交集但 intersection 为空")
                                msp.add_circle((centroid.x, centroid.y), 0.5, dxfattribs={'layer': 'ERROR_LOG', 'color': 1})
                                missing_count += 1
                            elif p_over.area <= 0.05:
                                LOG(f"   🗑️ 过滤: 地块({centroid.x:.1f}) 面积={p_over.area:.4f} < 0.05")
                                msp.add_circle((centroid.x, centroid.y), 0.5, dxfattribs={'layer': 'ERROR_LOG', 'color': 1})
                                missing_count += 1
                                area_missing += p_over.area
                            else:
                                actual_count += 1
                        else:
                            # 检查是否在设计区
                            if yellow_final and p.intersects(yellow_final):
                                pass  # 设计区，正常
                            else:
                                LOG(f"   ❓ 孤儿块: 地块({centroid.x:.1f}) 既不属于设计区也不属于超挖区")
                                msp.add_circle((centroid.x, centroid.y), 0.3, dxfattribs={'layer': 'ERROR_LOG', 'color': 6})
                                missing_count += 1
                    else:
                        # 没有超挖框，跳过
                        pass
                
                LOG(f"   📊 诊断报告: 成功识别 {actual_count} 块, 缺失/孤儿 {missing_count} 块, 总漏填面积 {area_missing:.2f}")
                
                # 输出诊断结果到文件
                if input_path.endswith('.dxf'):
                    diag_path = input_path.replace('.dxf', '_diagnostic.dxf')
                else:
                    diag_path = input_path + '_diagnostic.dxf'
                doc.saveas(diag_path)
                LOG(f"   ✅ 诊断结果已保存到: {diag_path}")

        LOG("\n✨ [诊断任务全部结束]")

    except Exception as e:
        LOG(f"❌ 脚本执行崩溃:\n{traceback.format_exc()}")

def run_test():
    """固定输入输出的测试入口"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    input_path = os.path.join(base_dir, "测试文件", "断面算量测试S.dxf")
    
    def print_log(msg):
        print(msg)
    
    print(f"=== 诊断模式 ===")
    print(f"输入文件: {input_path}")
    
    if not os.path.exists(input_path):
        print(f"❌ 输入文件不存在!")
        return
    
    run_diagnostic({'files': [input_path]}, print_log)

if __name__ == "__main__":
    run_test()