# -*- coding: utf-8 -*-
# engine_cad.py - 核心CAD计算引擎（整合版）
"""
包含所有算量脚本的核心逻辑，整合五个工具：
- autoline: 断面线合并
- autopaste: 批量粘贴
- autohatch: 快速填充
- autoclassify: 分类算量
- autocut: 分层算量
"""

import ezdxf
import os
import traceback
import math
import re
import datetime
import pandas as pd
from collections import defaultdict, Counter
from shapely.geometry import LineString, MultiLineString, Point, box, Polygon, MultiPolygon
from shapely.ops import unary_union, linemerge, polygonize

# ==================== 通用辅助函数 ====================

def entity_to_linestring(e):
    """统一处理各种线类型"""
    try:
        if e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
            pts = [(p[0], p[1]) for p in e.get_points()]
        elif e.dxftype() == 'LINE':
            pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        else:
            return None
        return LineString(pts) if len(pts) > 1 else None
    except:
        return None

def get_y_at_x(line, x):
    """获取指定 X 处的 Y 值"""
    b = line.bounds
    v_line = LineString([(x, b[1] - 100), (x, b[3] + 100)])
    try:
        inter = line.intersection(v_line)
        if inter.is_empty: return None
        if inter.geom_type == 'Point': return inter.y
        if inter.geom_type in ('MultiPoint', 'LineString'):
            coords = inter.coords if inter.geom_type == 'LineString' else [p.coords[0] for p in inter.geoms]
            return min(c[1] for c in coords)
    except: return None
    return None

def get_best_pt(e):
    """获取文本实体的最佳点"""
    try:
        if e.dxftype() == 'TEXT':
            return (e.dxf.align_point.x, e.dxf.align_point.y) if (e.dxf.halign or e.dxf.valign) else (e.dxf.insert.x, e.dxf.insert.y)
        return (e.dxf.insert.x, e.dxf.insert.y)
    except: return (0, 0)

def get_txt(e):
    """获取文本内容"""
    return e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text

def get_lines_raw(msp, layer):
    """从指定图层提取所有线段"""
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
    """简单延长线"""
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

def station_sort_key(station_str):
    """桩号排序键"""
    nums = re.findall(r'\d+', str(station_str))
    return int("".join(nums)) if nums else 0

def find_intersections(line1, line2):
    """找出两条线的所有交点"""
    try:
        inter = line1.intersection(line2)
        if inter.is_empty:
            return []
        if inter.geom_type == 'Point':
            return [(inter.x, inter.y)]
        if inter.geom_type == 'MultiPoint':
            return [(p.x, p.y) for p in inter.geoms]
        if inter.geom_type == 'LineString':
            return list(inter.coords)
        if inter.geom_type == 'GeometryCollection':
            pts = []
            for g in inter.geoms:
                if g.geom_type == 'Point':
                    pts.append((g.x, g.y))
            return pts
    except:
        pass
    return []

def generate_complete_final_section(dmx, section_lines):
    """生成完整的最终断面线 - 交点附近密集采样确保贴合"""
    all_x_coords = set()
    for pt in dmx.coords:
        all_x_coords.add(round(pt[0], 3))
    for sec in section_lines:
        for pt in sec.coords:
            all_x_coords.add(round(pt[0], 3))
    
    intersection_x = set()
    all_lines = [dmx] + list(section_lines)
    for i in range(len(all_lines)):
        for j in range(i + 1, len(all_lines)):
            intersections = find_intersections(all_lines[i], all_lines[j])
            for ix, iy in intersections:
                intersection_x.add(round(ix, 3))
                for delta in [-1.0, -0.5, 0.5, 1.0]:
                    intersection_x.add(round(ix + delta, 3))
    
    all_x_coords.update(intersection_x)
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
        dmx_y = get_y_at_x(dmx, x)
        if dmx_y is not None:
            all_ys.append(dmx_y)
        for sec in section_lines:
            sec_y = get_y_at_x(sec, x)
            if sec_y is not None:
                all_ys.append(sec_y)
        if all_ys:
            min_y = min(all_ys)
            coords.append((x, min_y))
    
    if len(coords) >= 2:
        return LineString(coords)
    return None

# ==================== 1. 断面线合并 (autoline) ====================

def run_autoline(params, LOG):
    """断面合并任务"""
    try:
        layer_new = params.get('图层A名称')
        layer_old = params.get('图层B名称')
        
        if not layer_new or not layer_old:
            LOG("[ERROR] 脚本错误：无法从UI获取图层名称。")
            return
            
        layer_out = "FINAL_BOTTOM_SURFACE"
        file_list = params.get('files', [])

        if not file_list:
            LOG("[WARN] 请先添加文件。")
            return

        for input_file in file_list:
            LOG(f"--- [WAIT] 正在处理(下包络): {os.path.basename(input_file)} ---")
            
            if not os.path.exists(input_file):
                LOG(f"[ERROR] 错误: 找不到文件 {input_file}")
                continue

            doc = ezdxf.readfile(input_file)
            msp = doc.modelspace()
            
            query_str = 'LWPOLYLINE POLYLINE LINE'
            new_lss = [entity_to_linestring(e) for e in msp.query(f'{query_str}[layer=="{layer_new}"]')]
            old_lss = [entity_to_linestring(e) for e in msp.query(f'{query_str}[layer=="{layer_old}"]')]
            
            new_lss = [ls for ls in new_lss if ls]
            old_lss = [ls for ls in old_lss if ls]

            if not new_lss and not old_lss:
                LOG(f"[WARN] 跳过：指定图层没有线段。")
                continue

            groups = []
            used_old = set()
            for n_ls in new_lss:
                current_group = [n_ls]
                for idx, o_ls in enumerate(old_lss):
                    if n_ls.intersects(o_ls) or n_ls.distance(o_ls) < 0.5:
                        current_group.append(o_ls)
                        used_old.add(idx)
                groups.append(current_group)
            
            for idx, o_ls in enumerate(old_lss):
                if idx not in used_old:
                    groups.append([o_ls])

            if layer_out not in doc.layers:
                doc.layers.new(name=layer_out, dxfattribs={'color': 3})

            success_count = 0
            for group in groups:
                if len(group) < 2:
                    msp.add_lwpolyline(list(group[0].coords), dxfattribs={'layer': layer_out})
                    success_count += 1
                    continue
                
                dmx = group[0]
                section_lines = group[1:]
                final_line = generate_complete_final_section(dmx, section_lines)
                
                if final_line and final_line.length > 0.01:
                    msp.add_lwpolyline(list(final_line.coords), dxfattribs={'layer': layer_out})
                    success_count += 1

            output_name = input_file.replace(".dxf", "_下包络合并.dxf")
            doc.saveas(output_name)
            LOG(f"[OK] 完成！已提取下包络线，保存至: {os.path.basename(output_name)}")

        LOG("[DONE] [下包络任务全部结束]")

    except Exception as e:
        LOG(f"[ERROR] 脚本崩溃:\n{traceback.format_exc()}")

# ==================== 2. 批量粘贴 (autopaste) ====================

def find_source_basepoints(src_msp, LOG):
    """检测源文件的基点（断面框上边中点）
    
    基点特征：
    - 是断面框上边中点
    - 断面框是闭合LWPOLYLINE（color=0, layer=XSECTION）
    - X≈86.00（断面框中心），Y=上边的Y值
    
    返回: [(x, y, y_center), ...] 按Y从大到小排序
    """
    basepoints = []
    
    # 找所有闭合的断面框（color=0的LWPOLYLINE）
    for e in src_msp.query('LWPOLYLINE'):
        try:
            if e.dxf.color != 0:
                continue
            
            pts = list(e.get_points())
            if len(pts) < 4:
                continue
            
            # 检查是否闭合
            first, last = pts[0], pts[-1]
            if abs(first[0] - last[0]) > 1 or abs(first[1] - last[1]) > 1:
                continue
            
            # 计算边界框
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            width = max(xs) - min(xs)
            height = max(ys) - min(ys)
            
            # 断面框尺寸筛选（宽度约148-170，高度约100-148）
            if width < 100 or width > 200:
                continue
            if height < 50 or height > 200:
                continue
            
            # 找上边（Y最大的边）
            max_y = max(ys)
            
            # 找Y接近max_y的顶点（上边的端点）
            top_pts = [p for p in pts if abs(p[1] - max_y) < 1]
            
            if len(top_pts) >= 2:
                # 上边的两个端点
                left_pt = min(top_pts, key=lambda p: p[0])
                right_pt = max(top_pts, key=lambda p: p[0])
                
                # 上边中点即基点
                mid_x = (left_pt[0] + right_pt[0]) / 2
                mid_y = (left_pt[1] + right_pt[1]) / 2
                
                # 断面框中心Y
                center_y = (min(ys) + max(ys)) / 2
                
                basepoints.append((mid_x, mid_y, center_y))
        except:
            pass
    
    # 按Y从大到小排序
    basepoints.sort(key=lambda bp: bp[1], reverse=True)
    
    LOG(f"  源基点检测: 找到{len(basepoints)}个断面框上边中点")
    
    return basepoints

def find_dest_basepoints(dst_msp, LOG):
    """检测目标文件的基点（倒三角顶点）
    
    基点特征：
    - 是LINE形成的倒三角顶点
    - 两条LINE向上汇聚到一个点
    - 角度特征：两条线的角度绝对值都>90度（约±135°）
    
    返回: [(x, y), ...] 按Y从大到小排序
    """
    from collections import defaultdict
    
    # 收集所有LINE
    lines = list(dst_msp.query('LINE'))
    
    # 按端点分组LINE（精确到0.1）
    endpoint_lines = defaultdict(list)
    for line in lines:
        try:
            sx = round(line.dxf.start.x, 1)
            sy = round(line.dxf.start.y, 1)
            ex = round(line.dxf.end.x, 1)
            ey = round(line.dxf.end.y, 1)
            
            endpoint_lines[(sx, sy)].append(line)
            endpoint_lines[(ex, ey)].append(line)
        except:
            pass
    
    # 找倒三角顶点：两条线相交，角度都向上
    basepoints = []
    
    for pt, line_list in endpoint_lines.items():
        if len(line_list) < 2:
            continue
        
        x, y = pt
        
        # 检查这些线的走向
        up_count = 0
        for line in line_list:
            try:
                sx, sy = line.dxf.start.x, line.dxf.start.y
                ex, ey = line.dxf.end.x, line.dxf.end.y
                
                # 计算从pt出发的方向
                if abs(sx - x) < 0.2 and abs(sy - y) < 0.2:
                    # pt是start，方向是end
                    dx, dy = ex - sx, ey - sy
                else:
                    # pt是end，方向是start
                    dx, dy = sx - ex, sy - ey
                
                # 计算角度
                angle = math.atan2(dy, dx) * 180 / math.pi
                
                # 向上的线：角度绝对值>90度
                if abs(angle) > 90:
                    up_count += 1
            except:
                pass
        
        # 倒三角顶点：至少有两条向上的线
        if up_count >= 2:
            basepoints.append((x, y))
    
    # 按Y从大到小排序
    basepoints.sort(key=lambda bp: bp[1], reverse=True)
    
    LOG(f"  目标基点检测: 找到{len(basepoints)}个倒三角顶点")
    
    return basepoints

def auto_detect_source_params(src_msp, LOG):
    """自动检测源文件参数（保留兼容性）"""
    basepoints = find_source_basepoints(src_msp, LOG)
    if not basepoints:
        return None, None, None, []
    
    first_bp = basepoints[0]
    s00x, s00y = first_bp[0], first_bp[1]
    
    # 计算断面间距
    if len(basepoints) >= 2:
        y_diffs = [abs(basepoints[i][1] - basepoints[i+1][1]) 
                   for i in range(len(basepoints)-1)]
        step_y = sorted(y_diffs)[len(y_diffs)//2]
    else:
        step_y = 150
    
    LOG(f"  断面间距: {step_y:.1f}")
    
    # 转换为导航点格式
    grouped_nav = [{'x': bp[0], 'y': bp[1], 'base_x': bp[0], 'base_y': bp[1]} 
                   for bp in basepoints]
    
    return s00x, s00y, step_y, grouped_nav

def auto_detect_dest_params(dst_msp, LOG):
    """自动检测目标文件参数"""
    station_pattern = re.compile(r'(\d+\+\d+)')
    stations = {}
    
    for e in dst_msp.query('TEXT MTEXT'):
        try:
            text = get_txt(e).upper()
            match = station_pattern.search(text)
            if match:
                pt = get_best_pt(e)
                stations[match.group(1)] = pt
        except:
            pass
    
    if not stations:
        return None, {}
    
    sorted_stations = sorted(stations.items(), key=lambda x: x[1][1], reverse=True)
    first_station_y = sorted_stations[0][1][1]
    
    LOG(f"  目标桩号检测: 共{len(stations)}个，首个Y={first_station_y:.1f}")
    
    return first_station_y, stations

def run_autopaste(params, LOG):
    """批量粘贴任务 - 严格按照原代码autopaste.py原理
    
    核心原理（用户说明）：
    1. 首先得到第一个0.00位置和源基点位置
    2. 后续的0.00与基点的相对位置不变，所以找到0.00等于找到源基点
    3. 用断面间距找到下一个0.00
    4. 各要素的格式固定，但位置随断面形状而变
    5. 自动检测变化的要素，用不变的距离去对应正确的基点
    
    关键发现（源端分析）：
    - 源端桩号489个，红线163条（红线只在部分断面存在）
    - 同一桩号ID在多个位置出现（多列排布）
    - 红线X ≈ 桩号X + 偏移量，偏移量取决于桩号所在列
    - 红线X - 0.00X 平均≈1.0（红线和0.00在同一X列）
    """
    try:
        src_path = params.get('源文件名')
        dst_path = params.get('目标文件名')
        
        if not src_path or not dst_path:
            LOG("[ERROR] 请先选择源文件和目标文件")
            return
        
        if not os.path.exists(src_path):
            LOG(f"[ERROR] 找不到源文件: {src_path}")
            return
        
        LOG(f"正在读取源文件: {os.path.basename(src_path)} ...")
        src_doc = ezdxf.readfile(src_path)
        src_msp = src_doc.modelspace()
        
        station_pattern = re.compile(r'(\d+\+\d+)')
        
        # ===== 1. 收集源端所有关键实体 =====
        LOG("[SCAN] 收集源端实体...")
        
        # 收集桩号文本
        src_stations = {}  # {桩号ID: [{'x': x, 'y': y}, ...]}
        for e in src_msp.query('TEXT MTEXT'):
            try:
                txt = get_txt(e).strip()
                if ".TIN" in txt.upper():
                    m = station_pattern.search(txt)
                    if m:
                        pt = get_best_pt(e)
                        sid = m.group(1)
                        if sid not in src_stations:
                            src_stations[sid] = []
                        src_stations[sid].append({'x': pt[0], 'y': pt[1]})
            except:
                pass
        
        # 收集0.00导航点
        src_nav_00s = []  # [{'x': x, 'y': y}, ...]
        for e in src_msp.query('TEXT MTEXT'):
            try:
                txt = get_txt(e).strip()
                if txt == "0.00":
                    pt = get_best_pt(e)
                    src_nav_00s.append({'x': pt[0], 'y': pt[1]})
            except:
                pass
        
        # 收集红线（color=1）
        src_reds = []  # [{'ent': entity, 'x': x, 'y': y}, ...]
        for e in src_msp.query('LWPOLYLINE'):
            try:
                if e.dxf.color == 1:  # 红色
                    pts = list(e.get_points())
                    avg_y = sum(p[1] for p in pts) / len(pts)
                    avg_x = sum(p[0] for p in pts) / len(pts)
                    src_reds.append({'ent': e, 'x': avg_x, 'y': avg_y})
            except:
                pass
        
        LOG(f"  源端桩号ID: {len(src_stations)}个（共{sum(len(v) for v in src_stations.values())}个文本）")
        LOG(f"  源端0.00导航点: {len(src_nav_00s)}个")
        LOG(f"  源端红线: {len(src_reds)}条")
        
        if not src_reds:
            LOG("[ERROR] 未找到源端红线（color=1的LWPOLYLINE）")
            return
        
        # ===== 2. 按Y坐标对0.00和红线排序 =====
        src_nav_00s.sort(key=lambda n: n['y'], reverse=True)
        src_reds.sort(key=lambda r: r['y'], reverse=True)
        
        # ===== 3. 通过Y坐标匹配红线与0.00（关键改进）=====
        # 红线X - 0.00X ≈ 1.0，红线和0.00在同一列
        # 通过X坐标分组，然后在组内按Y匹配
        LOG("[SCAN] 匹配红线与0.00...")
        
        # 按X坐标分组（容差20像素）
        def get_x_group(x):
            return round(x / 20) * 20
        
        nav_00_by_x = {}
        for nav in src_nav_00s:
            xg = get_x_group(nav['x'])
            if xg not in nav_00_by_x:
                nav_00_by_x[xg] = []
            nav_00_by_x[xg].append(nav)
        
        reds_by_x = {}
        for red in src_reds:
            xg = get_x_group(red['x'])
            if xg not in reds_by_x:
                reds_by_x[xg] = []
            reds_by_x[xg].append(red)
        
        # 在每个X组内，匹配红线与最近的0.00
        red_to_nav = {}  # {红线索引: 0.00坐标}
        used_navs = set()
        
        for xg in reds_by_x:
            reds_in_group = reds_by_x[xg]
            navs_in_group = nav_00_by_x.get(xg, [])
            
            # 在组内按Y排序
            reds_in_group.sort(key=lambda r: r['y'], reverse=True)
            navs_in_group.sort(key=lambda n: n['y'], reverse=True)
            
            # 为每条红线找最近的0.00（Y方向）
            for red in reds_in_group:
                best_nav = None
                best_y_diff = float('inf')
                
                for i, nav in enumerate(navs_in_group):
                    if i in used_navs:
                        continue
                    y_diff = abs(red['y'] - nav['y'])
                    if y_diff < best_y_diff:
                        best_y_diff = y_diff
                        best_nav = (i, nav)
                
                if best_nav and best_y_diff < 200:  # Y容差200像素
                    used_navs.add(best_nav[0])
                    red_to_nav[id(red['ent'])] = best_nav[1]
        
        LOG(f"  匹配红线-0.00: {len(red_to_nav)}对")
        
        # ===== 4. 通过0.00找到对应的桩号 =====
        # 0.00与桩号的相对位置固定
        LOG("[SCAN] 匹配0.00与桩号...")
        
        src_sections = {}  # {桩号ID: {'red': 红线实体, 'nav_00': 0.00坐标}}
        
        # 收集所有桩号文本点
        all_station_pts = []
        for sid, pts in src_stations.items():
            for pt in pts:
                all_station_pts.append({'id': sid, 'x': pt['x'], 'y': pt['y']})
        
        # 为每个0.00找最近的桩号
        used_stations = set()
        for red_ent_id, nav in red_to_nav.items():
            nav_x, nav_y = nav['x'], nav['y']
            
            best_station = None
            best_dist = float('inf')
            
            for st in all_station_pts:
                if (st['id'], st['x'], st['y']) in used_stations:
                    continue
                
                # 计算距离
                dist = math.sqrt((st['x'] - nav_x)**2 + (st['y'] - nav_y)**2)
                if dist < best_dist:
                    best_dist = dist
                    best_station = st
            
            if best_station and best_dist < 200:  # 距离容差200像素
                used_stations.add((best_station['id'], best_station['x'], best_station['y']))
                
                # 找到对应的红线实体
                red_ent = None
                for red in src_reds:
                    if id(red['ent']) == red_ent_id:
                        red_ent = red
                        break
                
                if red_ent:
                    sid = best_station['id']
                    # 只保留第一个匹配的桩号
                    if sid not in src_sections:
                        src_sections[sid] = {
                            'red': red_ent['ent'],
                            'red_x': red_ent['x'],
                            'red_y': red_ent['y'],
                            'nav_x': nav_x,
                            'nav_y': nav_y,
                            'station_x': best_station['x'],
                            'station_y': best_station['y']
                        }
        
        LOG(f"  匹配成功的断面: {len(src_sections)}个")
        
        # ===== 5. 读取目标文件 =====
        if not os.path.exists(dst_path):
            LOG(f"[ERROR] 目标文件不存在: {dst_path}")
            return
        
        LOG(f"正在读取目标文件: {os.path.basename(dst_path)} ...")
        dst_doc = ezdxf.readfile(dst_path)
        dst_msp = dst_doc.modelspace()
        
        # ===== 6. 收集目标端桩号 =====
        LOG("[SCAN] 收集目标端桩号...")
        dst_stations = {}  # {桩号ID: (x, y)}
        for e in dst_msp.query('TEXT MTEXT'):
            try:
                txt = get_txt(e).upper()
                m = station_pattern.search(txt)
                if m:
                    pt = get_best_pt(e)
                    dst_stations[m.group(1)] = pt
            except:
                pass
        
        LOG(f"  目标端桩号: {len(dst_stations)}个")
        
        # ===== 7. 执行粘贴（关键改进：用红线X作为平移基准）=====
        LOG("[GO] 执行粘贴...")
        
        if "0-已粘贴断面" not in dst_doc.layers:
            dst_doc.layers.new(name="0-已粘贴断面", dxfattribs={'color': 3})
        
        count = 0
        matched_count = 0
        
        # 匹配源端和目标端的桩号
        matched_stations = set(src_sections.keys()) & set(dst_stations.keys())
        LOG(f"  匹配的桩号: {len(matched_stations)}个")
        
        for station_id in sorted(matched_stations, key=lambda s: int(s.replace('+', ''))):
            s_data = src_sections[station_id]
            
            if station_id not in dst_stations:
                continue
            
            dst_sx, dst_sy = dst_stations[station_id]
            
            # 源红线位置
            src_red_x = s_data['red_x']
            src_red_y = s_data['red_y']
            
            # 目标红线位置
            # X方向：红线X应该与目标桩号X在同一列（红线是断面的一部分）
            # Y方向：红线相对桩号的Y偏移保持不变
            # 计算源端红线相对源端桩号的偏移
            src_offset_x = src_red_x - s_data['station_x']
            src_offset_y = src_red_y - s_data['station_y']
            
            # 应用相同的偏移到目标端
            dst_red_x = dst_sx + src_offset_x
            dst_red_y = dst_sy + src_offset_y
            
            # 平移向量
            dx = dst_red_x - src_red_x
            dy = dst_red_y - src_red_y
            
            # 复制红线到目标位置
            red_e = s_data['red']
            new_e = red_e.copy()
            new_e.translate(dx, dy, 0)
            new_e.dxf.layer = "0-已粘贴断面"
            new_e.dxf.color = 3
            dst_msp.add_entity(new_e)
            count += 1
            
            matched_count += 1
            
            if matched_count <= 5 or matched_count % 20 == 0:
                LOG(f"  [{matched_count}] {station_id}: 平移量({dx:.1f}, {dy:.1f})")
        
        # ===== 8. 保存结果 =====
        dst_dir = os.path.dirname(dst_path) or "."
        dst_basename = os.path.basename(dst_path).replace(".dxf", "")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_name = os.path.join(dst_dir, f"{dst_basename}_已粘贴断面_{timestamp}.dxf")
        dst_doc.saveas(save_name)
        
        LOG(f"[OK] 处理完成！成果已保存至: {os.path.basename(save_name)}")
        LOG(f"[STATS] 统计：源断面{len(src_sections)}个，目标桩号{len(dst_stations)}个，匹配{matched_count}个，粘贴红线{count}条")

    except Exception as e:
        LOG(f"[ERROR] 脚本执行崩溃:\n{traceback.format_exc()}")

# ==================== 3. 快速填充 (autohatch) ====================

def run_autohatch(params, LOG):
    """快速填充任务"""
    try:
        target_layer = params.get('填充层名称', 'AA_填充算量层')
        fixed_text_height = 3.0  
        file_list = params.get('files', [])

        if not file_list:
            LOG("[WARN] 请先选择 DXF 文件。")
            return

        for input_path in file_list:
            LOG(f"--- [WAIT] 正在处理: {os.path.basename(input_path)} ---")
            
            try:
                doc = ezdxf.readfile(input_path)
                msp = doc.modelspace()
            except Exception as e:
                LOG(f"[ERROR] 读取失败: {e}")
                continue

            visible_layers = {layer.dxf.name for layer in doc.layers if not layer.is_off()}
            raw_lines = []
            all_coords = []

            for ent in msp:
                if ent.dxftype() in ('LINE', 'LWPOLYLINE', 'POLYLINE'):
                    if ent.dxf.layer in visible_layers or ent.dxf.layer.startswith("AA_"):
                        try:
                            if ent.dxftype() == 'LINE':
                                pts = [ent.dxf.start.vec2, ent.dxf.end.vec2]
                            else:
                                pts = [p[:2] for p in ent.get_points()] if ent.dxftype() == 'LWPOLYLINE' else [p.vtx.vec2 for p in ent.vertices]
                            if len(pts) >= 2:
                                all_coords.extend(pts)
                                for i in range(len(pts)-1):
                                    raw_lines.append(LineString([pts[i], pts[i+1]]))
                        except: continue

            if not raw_lines: continue

            if all_coords:
                xs = [p[0] for p in all_coords]; ys = [p[1] for p in all_coords]
                global_diag = math.sqrt((max(xs)-min(xs))**2 + (max(ys)-min(ys))**2)
                global_hatch_scale = max(0.5, global_diag * 0.02) 
            else:
                global_hatch_scale = 1.0

            merged_lines = unary_union(raw_lines)
            polygons = list(polygonize(merged_lines))
            valid_regions = [p for p in polygons if p.area > 0.01]
            valid_regions = sorted(valid_regions, key=lambda p: p.representative_point().y, reverse=True)

            rgb_list = [(255,100,100), (100,255,100), (100,100,255), (255,215,0), (255,100,255), (0,255,255)]
            data_for_excel = []
            dxf_groups = doc.groups 

            for i, poly in enumerate(valid_regions):
                index_no = i + 1
                area_val = round(poly.area, 3)
                current_rgb = rgb_list[i % len(rgb_list)]
                
                data_for_excel.append({"编号": index_no, "面积(㎡)": area_val})

                try:
                    hatch = msp.add_hatch(dxfattribs={'layer': target_layer})
                    hatch.rgb = current_rgb
                    hatch.set_pattern_fill('ANSI31', scale=global_hatch_scale)
                    hatch.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True)
                    for interior in poly.interiors:
                        hatch.paths.add_polyline_path(list(interior.coords)[:-1], is_closed=True)
                    
                    in_point = poly.representative_point()
                    label_content = f"{{\\fArial|b1;{index_no}\\PS={area_val}}}"
                    mtext = msp.add_mtext(label_content, dxfattribs={
                        'layer': target_layer + "_标注",
                        'insert': (in_point.x, in_point.y),
                        'char_height': fixed_text_height,
                        'attachment_point': 5,
                    })
                    mtext.rgb = current_rgb 
                    
                    try:
                        mtext.dxf.bg_fill_setting = 1 
                        mtext.dxf.bg_fill_scale_factor = 1.5
                    except: pass

                    try:
                        new_group = dxf_groups.new()
                        new_group.add_entities([hatch, mtext])
                    except: pass

                except Exception as e:
                    LOG(f"[WARN] 块 {index_no} 生成出错: {e}")
                    continue

            output_dxf = input_path.replace(".dxf", "_填充完成.dxf")
            doc.saveas(output_dxf)
            
            if data_for_excel:
                try:
                    df = pd.DataFrame(data_for_excel)
                    output_xlsx = input_path.replace(".dxf", "_面积明细表.xlsx")
                    df.to_excel(output_xlsx, index=False)
                    LOG(f"[STATS] 面积表已生成: {os.path.basename(output_xlsx)}")
                except Exception as ex:
                    LOG(f"[ERROR] Excel 导出失败: {ex}")

            LOG(f"[OK] 处理完成！总数量: {len(data_for_excel)}")

        LOG("[DONE] [全任务圆满结束]")

    except Exception as e:
        LOG(f"[ERROR] 脚本崩溃:\n{traceback.format_exc()}")

# ==================== 4. 分类算量 (autoclassify) ====================

STRATA_REGEX = r'^\d+级.*'
EXTEND_DIST = 100.0
LY_FINAL_SECTION = "AA_最终断面线"
LY_OUTPUT_HATCH = "AA_分类填充"
LY_OUTPUT_LABEL = "AA_分类标注"
TEXT_HEIGHT = 2.5

HIGH_CONTRAST_COLORS = [
    (255, 0, 0), (0, 200, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255),
    (255, 128, 0), (128, 0, 255), (0, 128, 255), (255, 0, 128), (128, 255, 0), (0, 255, 128),
    (128, 128, 0), (0, 128, 128), (128, 0, 128), (200, 100, 50), (50, 200, 100), (100, 50, 200),
]

def hatch_to_polygon(hatch_entity):
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
                    try: pts.extend([(p.x, p.y) for p in edge.flattening(distance=0.01)])
                    except: pass
        if len(pts) >= 3:
            poly = Polygon(pts)
            if not poly.is_valid: poly = poly.buffer(0)
            if not poly.is_empty:
                polygons.append(Polygon(poly.exterior))
    return unary_union(polygons)

def get_strata_color(strata_name, strata_list):
    if strata_name in strata_list:
        idx = strata_list.index(strata_name) % len(HIGH_CONTRAST_COLORS)
        return HIGH_CONTRAST_COLORS[idx]
    return HIGH_CONTRAST_COLORS[0]

def add_hatch_with_label(msp, poly, rgb_color, pattern, scale, text_height, strata_name, is_design):
    """添加填充和标注，按地层+类型分图层
    
    图层命名规则：
    - 设计区："{地层名}设计" 如 "1级淤泥设计"
    - 超挖区："{地层名}超挖" 如 "1级淤泥超挖"
    - 标注层："{地层名}{类型}_标注" 如 "1级淤泥设计_标注"
    """
    if not poly or poly.is_empty: return 0.0
    if isinstance(poly, (LineString, Point)):
        return 0.0
    
    # 按地层+类型生成分层图层名
    label_type = "设计" if is_design else "超挖"
    layer_hatch = f"{strata_name}{label_type}"
    layer_label = f"{strata_name}{label_type}_标注"
    
    geoms = [poly] if isinstance(poly, Polygon) else list(poly.geoms) if hasattr(poly, 'geoms') else [poly]
    total_area = 0.0
    full_label = f"{strata_name}{label_type}"
    
    for p in geoms:
        if isinstance(p, (LineString, Point)): continue
        if p.area < 0.01: continue
        total_area += p.area
        hatch = msp.add_hatch(dxfattribs={'layer': layer_hatch})
        hatch.rgb = rgb_color
        hatch.set_pattern_fill(pattern, scale=scale)
        hatch.paths.add_polyline_path(list(p.exterior.coords), is_closed=True)
        for interior in p.interiors:
            hatch.paths.add_polyline_path(list(interior.coords), is_closed=True)
        area_val = round(p.area, 3)
        if area_val > 0.1:
            try:
                in_point = p.representative_point()
                label_content = f"{{\\fArial|b1;{full_label}\\P{area_val}}}"
                mtext = msp.add_mtext(label_content, dxfattribs={
                    'layer': layer_label, 'insert': (in_point.x, in_point.y),
                    'char_height': text_height, 'attachment_point': 5,
                })
                mtext.rgb = rgb_color
                try:
                    mtext.dxf.bg_fill_setting = 1
                    mtext.dxf.bg_fill_scale_factor = 1.3
                except: pass
            except: pass
    return total_area

def get_layer_lines(msp, layer_name):
    res = []
    for e in msp.query(f'*[layer=="{layer_name}"]'):
        try:
            if e.dxftype() == 'LWPOLYLINE':
                pts = [p[:2] for p in e.get_points()]
                if len(pts) >= 2: res.append(LineString(pts))
            elif e.dxftype() == 'POLYLINE':
                pts = [v.dxf.location.vec2 for v in e.vertices]
                if len(pts) >= 2: res.append(LineString(pts))
            elif e.dxftype() == 'LINE':
                res.append(LineString([e.dxf.start.vec2, e.dxf.end.vec2]))
        except: pass
    return res

def connect_nearby_endpoints(lines, tolerance=2.0):
    if not lines: return []
    if len(lines) == 1: return lines
    endpoints = []
    for i, line in enumerate(lines):
        coords = list(line.coords)
        if len(coords) >= 2:
            endpoints.append((coords[0][0], coords[0][1], i, True))
            endpoints.append((coords[-1][0], coords[-1][1], i, False))
    connections = []
    used = set()
    for i in range(len(endpoints)):
        if i in used: continue
        x1, y1, line_idx1, is_start1 = endpoints[i]
        best_j = -1
        best_dist = tolerance + 1
        for j in range(len(endpoints)):
            if i == j or j in used: continue
            x2, y2, line_idx2, is_start2 = endpoints[j]
            if line_idx1 == line_idx2: continue
            dist = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_j = j
        if best_j >= 0 and best_dist <= tolerance:
            x2, y2, line_idx2, is_start2 = endpoints[best_j]
            connections.append((line_idx1, is_start1, line_idx2, is_start2, x1, y1, x2, y2))
            used.add(i)
            used.add(best_j)
    all_lines = list(lines)
    for line_idx1, is_start1, line_idx2, is_start2, x1, y1, x2, y2 in connections:
        conn_line = LineString([(x1, y1), (x2, y2)])
        all_lines.append(conn_line)
    merged = linemerge(unary_union(all_lines))
    if isinstance(merged, MultiLineString):
        return list(merged.geoms)
    elif isinstance(merged, LineString):
        return [merged]
    else:
        return all_lines

def get_y_on_line_at_x(line, x):
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

def build_design_polygon(excav_lines, section_line, sect_x_min, sect_x_max, min_excav_y):
    if not excav_lines:
        return None, sect_x_min, sect_x_max
    
    all_points = []
    for l in excav_lines:
        for pt in l.coords:
            all_points.append(pt)
    
    if not all_points:
        return None, sect_x_min, sect_x_max
    
    excav_x_min = min(p[0] for p in all_points)
    excav_x_max = max(p[0] for p in all_points)
    
    design_x_min = max(excav_x_min, sect_x_min)
    design_x_max = min(excav_x_max, sect_x_max)
    
    vertex_points = []
    for l in excav_lines:
        for pt in l.coords:
            x, y = pt
            if excav_x_min - 1 <= x <= excav_x_max + 1:
                vertex_points.append((x, y))
    
    x_to_min_y = {}
    for x, y in vertex_points:
        x_key = round(x, 2)
        if x_key not in x_to_min_y or y < x_to_min_y[x_key]:
            x_to_min_y[x_key] = y
    
    sample_step = 1.0
    x_samples = []
    y_samples = []
    
    x_current = design_x_min
    while x_current <= design_x_max:
        min_y_at_x = None
        x_key = round(x_current, 2)
        if x_key in x_to_min_y:
            min_y_at_x = x_to_min_y[x_key]
        for line in excav_lines:
            y_on_line = get_y_on_line_at_x(line, x_current)
            if y_on_line is not None:
                if min_y_at_x is None or y_on_line < min_y_at_x:
                    min_y_at_x = y_on_line
        if min_y_at_x is not None:
            x_samples.append(x_current)
            y_samples.append(min_y_at_x)
        x_current += sample_step
    
    gap_threshold = 20.0
    final_x = []
    final_y = []
    
    for i in range(len(x_samples)):
        final_x.append(x_samples[i])
        final_y.append(y_samples[i])
        if i < len(x_samples) - 1:
            gap = x_samples[i + 1] - x_samples[i]
            if gap > gap_threshold:
                num_insert = int(gap / 2.0)
                for j in range(1, num_insert + 1):
                    t = j / (num_insert + 1)
                    interp_x = x_samples[i] + t * gap
                    interp_y = y_samples[i] + t * (y_samples[i + 1] - y_samples[i])
                    final_x.append(interp_x)
                    final_y.append(interp_y)
    
    if final_x:
        sorted_pairs = sorted(zip(final_x, final_y), key=lambda p: p[0])
        x_samples = [p[0] for p in sorted_pairs]
        y_samples = [p[1] for p in sorted_pairs]
    
    if len(x_samples) < 2:
        return None, sect_x_min, sect_x_max
    
    sect_y_max = max(p[1] for p in section_line.coords) if section_line else min_excav_y + 50
    
    polygon_coords = []
    for x, y in zip(x_samples, y_samples):
        polygon_coords.append((x, y))
    right_x = x_samples[-1]
    right_y = y_samples[-1]
    polygon_coords.append((right_x, sect_y_max + 10))
    left_x = x_samples[0]
    polygon_coords.append((left_x, sect_y_max + 10))
    polygon_coords.append(polygon_coords[0])
    
    if len(polygon_coords) >= 4:
        poly = Polygon(polygon_coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        left_over_x = (sect_x_min, design_x_min) if design_x_min > sect_x_min else None
        right_over_x = (design_x_max, sect_x_max) if design_x_max < sect_x_max else None
        return poly, left_over_x, right_over_x
    
    return None, sect_x_min, sect_x_max

def build_virtual_boxes_from_overexcav(overexc_lines):
    if not overexc_lines:
        return []
    
    line_info = []
    for line in overexc_lines:
        bounds = line.bounds
        mid_x = (bounds[0] + bounds[2]) / 2
        mid_y = (bounds[1] + bounds[3]) / 2
        line_info.append({'line': line, 'mid_x': mid_x, 'mid_y': mid_y, 'bounds': bounds})
    
    def cluster_by_x(lines, x_threshold=200):
        if not lines: return []
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
        if not lines: return []
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
            if not y_cluster: continue
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

def extend_line_to_pierce(line, dist):
    coords = list(line.coords)
    if len(coords) < 2: return line
    p1, p2 = Point(coords[0]), Point(coords[1])
    dx, dy = p1.x - p2.x, p1.y - p2.y
    length = math.sqrt(dx**2 + dy**2) or 1
    coords.insert(0, (p1.x + dx/length * dist, p1.y + dy/length * dist))
    p_last, p_prev = Point(coords[-1]), Point(coords[-2])
    dx, dy = p_last.x - p_prev.x, p_last.y - p_prev.y
    length = math.sqrt(dx**2 + dy**2) or 1
    coords.append((p_last.x + dx/length * dist, p_last.y + dy/length * dist))
    return LineString(coords)

def run_autoclassify(params, LOG):
    """分类算量任务"""
    try:
        file_list = params.get('files', [])
        if not file_list:
            LOG("[WARN] 请先选择 DXF 文件。")
            return
        
        section_layers_str = params.get('断面线图层', 'DMX')
        section_layers = [s.strip() for s in section_layers_str.split(',') if s.strip()]
        station_layer = params.get('桩号图层', '0-桩号')
        merge_section = params.get('合并断面线', True)
        if isinstance(merge_section, str):
            merge_section = merge_section.lower() in ('true', '1', 'yes', '是')
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for input_path in file_list:
            LOG(f"--- [WAIT] 正在处理: {os.path.basename(input_path)} ---")
            
            doc = ezdxf.readfile(input_path)
            msp = doc.modelspace()

            if LY_FINAL_SECTION not in doc.layers:
                doc.layers.add(LY_FINAL_SECTION, color=4)
            if LY_OUTPUT_HATCH not in doc.layers:
                doc.layers.add(LY_OUTPUT_HATCH, color=7)
            if LY_OUTPUT_LABEL not in doc.layers:
                doc.layers.add(LY_OUTPUT_LABEL, color=7)

            strata_layers = [l.dxf.name for l in doc.layers if re.match(STRATA_REGEX, l.dxf.name)]
            def strata_sort_key(name):
                nums = re.findall(r'^(\d+)', name)
                return int(nums[0]) if nums else 999
            strata_layers = sorted(strata_layers, key=strata_sort_key)
            LOG(f"地层图层: {strata_layers}")
            
            for layer_name in strata_layers:
                try: doc.layers.get(layer_name).off()
                except: pass

            excav_lines_all = get_layer_lines(msp, "开挖线")
            overexc_lines_all = get_layer_lines(msp, "超挖线")
            
            dmx_lines_all = []
            for layer in section_layers:
                dmx_lines_all.extend(get_layer_lines(msp, layer))
            
            LOG(f"开挖线总数: {len(excav_lines_all)}")
            LOG(f"超挖线总数: {len(overexc_lines_all)}")
            LOG(f"断面线总数: {len(dmx_lines_all)}")

            virtual_boxes = build_virtual_boxes_from_overexcav(overexc_lines_all)
            LOG(f"虚拟断面框: {len(virtual_boxes)} 个")

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
                        except: pass
            
            LOG(f"桩号总数: {len(station_texts)}")
            
            report_data = []

            for idx, v_box in enumerate(virtual_boxes):
                minx, miny, maxx, maxy = v_box.bounds
                virtual_y_center = (miny + maxy) / 2
                virtual_x_center = (minx + maxx) / 2
                
                station = f"S{idx+1}"
                best_dist = float('inf')
                for st in station_texts:
                    pt = Point(st['x'], st['y'])
                    if v_box.distance(pt) < 200:
                        dist = pt.distance(Point((minx + maxx) / 2, miny))
                        if dist < best_dist:
                            best_dist = dist
                            station = st['text']
                
                LOG(f"处理断面 {idx+1}: {station}")

                dmx = None
                min_y_diff = float('inf')
                dmx_layer_lines = get_layer_lines(msp, "DMX")
                for l in dmx_layer_lines:
                    b = l.bounds
                    if b[0] <= virtual_x_center <= b[2]:
                        dmx_y_mid = (b[1] + b[3]) / 2
                        y_diff = abs(dmx_y_mid - virtual_y_center)
                        if y_diff < min_y_diff:
                            min_y_diff = y_diff
                            dmx = l
                
                if dmx is None:
                    for l in dmx_lines_all:
                        b = l.bounds
                        if b[0] <= virtual_x_center <= b[2]:
                            dmx_y_mid = (b[1] + b[3]) / 2
                            y_diff = abs(dmx_y_mid - virtual_y_center)
                            if y_diff < min_y_diff:
                                min_y_diff = y_diff
                                dmx = l
                
                if not dmx:
                    LOG(f"  警告：未找到DMX，跳过")
                    continue
                
                dmx_bounds = dmx.bounds
                dmx_x_min, dmx_x_max = dmx_bounds[0], dmx_bounds[2]
                
                boundary_box = box(minx - 20, miny - 25, maxx + 20, maxy + 25)
                
                if merge_section:
                    local_section = [l for l in get_layer_lines(msp, "断面线") if boundary_box.intersects(l)]
                    for layer in section_layers:
                        if layer != "DMX":
                            layer_lines = get_layer_lines(msp, layer)
                            for l in layer_lines:
                                if boundary_box.intersects(l):
                                    local_section.append(l)
                    final_sect = generate_complete_final_section(dmx, local_section)
                else:
                    final_sect = dmx
                
                if not final_sect:
                    LOG(f"  警告：最终断面线生成失败，跳过")
                    continue
                
                sect_coords = list(final_sect.coords)
                sect_x_min = min(c[0] for c in sect_coords)
                sect_x_max = max(c[0] for c in sect_coords)
                
                msp.add_lwpolyline(sect_coords, dxfattribs={'layer': LY_FINAL_SECTION})

                excav_list = [l for l in excav_lines_all if boundary_box.intersects(l)]
                
                if not excav_list:
                    LOG(f"  警告：未找到开挖线，跳过")
                    continue

                excav_in_section = []
                for l in excav_list:
                    l_bounds = l.bounds
                    if l_bounds[2] >= sect_x_min - 5 and l_bounds[0] <= sect_x_max + 5:
                        excav_in_section.append(l)
                
                if not excav_in_section:
                    LOG(f"  警告：断面线X范围内没有开挖线，跳过")
                    continue
                
                excav_connected = connect_nearby_endpoints(excav_in_section, tolerance=2.0)
                
                all_excav_pts = [p for l in excav_connected for p in l.coords]
                min_excav_y = min(p[1] for p in all_excav_pts) if all_excav_pts else miny
                
                design_result = build_design_polygon(excav_in_section, final_sect, sect_x_min, sect_x_max, min_excav_y)
                
                if design_result[0] is None:
                    LOG(f"  警告：设计区多边形构建失败，跳过")
                    continue
                
                design_polygon, left_over_x, right_over_x = design_result
                
                if design_polygon is None or design_polygon.is_empty:
                    LOG(f"  警告：设计区多边形为空，跳过")
                    continue

                excav_extended = [extend_line_to_pierce(l, EXTEND_DIST) for l in excav_connected]
                section_extended = extend_line_to_pierce(final_sect, EXTEND_DIST)

                boundary_line = LineString(boundary_box.exterior.coords)
                cutters = [boundary_line, section_extended] + excav_extended
                zones = list(polygonize(unary_union(cutters)))

                if not zones:
                    LOG(f"  警告：切割区域为空，跳过")
                    continue
                
                design_zones = []
                over_zones = []
                
                for z in zones:
                    z_center = z.representative_point()
                    if design_polygon.contains(z_center):
                        design_zones.append(z)
                    else:
                        inter = z.intersection(design_polygon)
                        if inter.is_empty or inter.area < 0.1:
                            over_zones.append(z)
                        else:
                            if inter.area > z.area * 0.5:
                                design_zones.append(z)
                            else:
                                over_zones.append(z)

                design_zone_poly = unary_union(design_zones) if design_zones else None

                over_y_bottom = miny
                total_open_poly = Polygon(sect_coords + [(sect_x_max, over_y_bottom), (sect_x_min, over_y_bottom)]).buffer(0)
                
                if total_open_poly.is_empty:
                    LOG(f"  警告：总开挖区域无效，跳过")
                    continue

                for layer in strata_layers:
                    layer_hatches = []
                    for h in msp.query(f'HATCH[layer=="{layer}"]'):
                        h_poly = hatch_to_polygon(h)
                        if h_poly.intersects(boundary_box):
                            layer_hatches.append(h_poly)
                    if not layer_hatches: continue

                    combined_hatch = unary_union(layer_hatches).intersection(total_open_poly)
                    if combined_hatch.is_empty: continue

                    poly_design = combined_hatch.intersection(design_zone_poly) if design_zone_poly else None
                    poly_over = combined_hatch.difference(design_zone_poly) if design_zone_poly else combined_hatch

                    layer_color = get_strata_color(layer, strata_layers)
                    design_area = add_hatch_with_label(msp, poly_design, layer_color, 'ANGLE', 0.1, TEXT_HEIGHT, layer, is_design=True)
                    over_area = add_hatch_with_label(msp, poly_over, layer_color, 'ANSI31', 0.1, TEXT_HEIGHT, layer, is_design=False)

                    if design_area > 0.01 or over_area > 0.01:
                        report_data.append({"断面": f"S{idx+1}", "桩号": station, "地层": layer, "设计面积": round(design_area, 3), "超挖面积": round(over_area, 3)})

            if report_data:
                df = pd.DataFrame(report_data)
                df['sort_key'] = df['桩号'].apply(station_sort_key)
                df_sorted = df.sort_values(by='sort_key')

                # 处理输出文件名：移除.bak后缀，确保扩展名正确
                base_path = input_path.replace(".bak", "").replace(".dxf", "")
                output_xlsx = f"{base_path}_分类汇总_{timestamp}.xlsx"
                with pd.ExcelWriter(output_xlsx) as writer:
                    df_design = df_sorted.pivot_table(index='桩号', columns='地层', values='设计面积', aggfunc='sum', sort=False).fillna(0)
                    df_design.to_excel(writer, sheet_name='设计量汇总')
                    df_over = df_sorted.pivot_table(index='桩号', columns='地层', values='超挖面积', aggfunc='sum', sort=False).fillna(0)
                    df_over.to_excel(writer, sheet_name='超挖汇总')
                    df_sorted[['断面', '桩号', '地层', '设计面积', '超挖面积']].to_excel(writer, sheet_name='明细表', index=False)

                output_dxf = input_path.replace(".dxf", f"_RESULT_{timestamp}.dxf")
                doc.saveas(output_dxf)
                LOG(f"[OK] 处理完成！")
                LOG(f"   DXF: {os.path.basename(output_dxf)}")
                LOG(f"   Excel: {os.path.basename(output_xlsx)}")
            else:
                LOG("未生成任何数据")

        LOG("[DONE] [分类算量任务全部结束]")

    except Exception as e:
        LOG(f"[ERROR] 脚本崩溃:\n{traceback.format_exc()}")

# ==================== 5. 分层算量 (autocut) ====================

LY_LAYER_5M = "AA_计算分层线"  # 避免和人工画的"5m分层线"冲突
LY_LAYER_5M_LABEL = "AA_计算分层线_标注"
LY_ABOVE_HATCH = "AA_分层算量填充"
LY_ABOVE_LABEL = "AA_分层算量标注"

# 高程与Y坐标映射关系：每个断面有自己的标尺，需要动态检测

def detect_ruler_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max):
    """检测断面附近的标尺，返回高程到Y坐标的映射函数
    
    返回：(elev_to_y_func, y_to_elev_func) 或 None
    
    注意：标尺可能是INSERT（块引用），需要进入块内部读取几何
    改进：使用Y范围重叠度来匹配正确的标尺
    """
    # 查找断面附近的标尺实体（标尺图层）
    ruler_layers = ['标尺', '0-标尺', 'RULER']
    ruler_candidates = []  # [(insert_x, insert_y, y_min, y_max), ...]
    
    for layer_name in ruler_layers:
        for e in msp.query(f'*[layer=="{layer_name}"]'):
            try:
                if e.dxftype() == 'INSERT':
                    # 块引用 - 获取插入点和范围
                    insert_x = e.dxf.insert.x
                    insert_y = e.dxf.insert.y
                    
                    # 检查是否在断面X范围内
                    if sect_x_min - 100 <= insert_x <= sect_x_max + 100:
                        # 从块内高程文本计算实际的Y范围
                        y_min = insert_y
                        y_max = insert_y
                        has_text = False
                        
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
                                            has_text = True
                                        except:
                                            pass
                        except:
                            pass
                        
                        if not has_text:
                            # 没有找到文本，使用默认估算
                            y_min = insert_y - 50
                            y_max = insert_y + 50
                        
                        ruler_candidates.append({
                            'x': insert_x,
                            'y_min': y_min,
                            'y_max': y_max,
                            'y_center': (y_min + y_max) / 2,
                            'entity': e
                        })
                
                elif e.dxftype() == 'LINE':
                    # 直接是LINE实体
                    x1, y1 = e.dxf.start.x, e.dxf.start.y
                    x2, y2 = e.dxf.end.x, e.dxf.end.y
                    # 标尺应该是垂直线（X相近）
                    if abs(x1 - x2) < 5:
                        ruler_x = (x1 + x2) / 2
                        if sect_x_min - 100 <= ruler_x <= sect_x_max + 100:
                            ruler_candidates.append({
                                'x': ruler_x,
                                'y_min': min(y1, y2),
                                'y_max': max(y1, y2),
                                'y_center': (y1 + y2) / 2,
                                'entity': None
                            })
            
            except Exception as ex:
                pass
    
    if not ruler_candidates:
        return None
    
    # 计算断面的X中心
    sect_x_center = (sect_x_min + sect_x_max) / 2
    
    # 改进：使用Y范围重叠度来筛选标尺
    # 断面的Y范围是 [sect_y_min, sect_y_max]
    # 标尺的Y范围是 [ruler['y_min'], ruler['y_max']]
    best_ruler = None
    best_overlap = -1
    best_x_diff = float('inf')
    
    for ruler in ruler_candidates:
        # 计算Y范围重叠
        overlap_start = max(sect_y_min, ruler['y_min'])
        overlap_end = min(sect_y_max, ruler['y_max'])
        overlap = max(0, overlap_end - overlap_start)
        
        # 计算标尺高度
        ruler_height = ruler['y_max'] - ruler['y_min']
        
        # 计算重叠比例（相对于标尺高度）
        overlap_ratio = overlap / ruler_height if ruler_height > 0 else 0
        
        # 计算X位置差异
        x_diff = abs(ruler['x'] - sect_x_center)
        
        # 选择策略：优先选重叠比例高的，其次选X位置近的
        if overlap_ratio > best_overlap or (overlap_ratio == best_overlap and x_diff < best_x_diff):
            best_overlap = overlap_ratio
            best_x_diff = x_diff
            best_ruler = ruler
    
    # 如果没有重叠，尝试用Y中心距离
    if best_overlap <= 0:
        min_y_diff = float('inf')
        for ruler in ruler_candidates:
            y_diff = abs(ruler['y_center'] - sect_y_center)
            x_diff = abs(ruler['x'] - sect_x_center)
            # 综合评分：Y距离为主，X距离为辅
            score = y_diff + x_diff * 0.1
            if score < min_y_diff:
                min_y_diff = score
                best_ruler = ruler
    
    if not best_ruler:
        return None
    
    # 收集标尺的高程文本
    elevation_points = []  # [(y, elev), ...]
    
    # 从最佳标尺实体直接获取高程文本
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
                            
                            # 尝试解析为浮点数（高程值）
                            try:
                                elev = float(text)
                                elevation_points.append((world_y, elev))
                            except ValueError:
                                pass
                        except:
                            pass
        except:
            pass
    
    if len(elevation_points) < 2:
        return None
    
    # 使用最小二乘法拟合: y = a * elev + b
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
    
    def elev_to_y(elev):
        return a * elev + b
    
    def y_to_elev(y):
        return (y - b) / a
    
    return (elev_to_y, y_to_elev)

# 默认高程转换函数（作为备用）
def elevation_to_y_default(elev):
    """默认高程转Y坐标"""
    return 5.0 * elev - 27.0

def y_to_elevation_default(y):
    """默认Y坐标转高程"""
    return (y + 27.0) / 5.0

# 地层排序规则：按类别和序号
STRATA_TYPE_ORDER = {
    '淤泥': 1, '砂': 2, '填土': 3, '粘土': 4, '岩石': 5, '砾': 6, '卵': 7, '粉': 8
}

def get_strata_sort_key(strata_name):
    """获取地层的排序键：先按类别，再按序号"""
    # 提取序号
    num_match = re.match(r'^(\d+)', strata_name)
    num = int(num_match.group(1)) if num_match else 99
    
    # 判断类别
    type_order = 99
    for type_name, order in STRATA_TYPE_ORDER.items():
        if type_name in strata_name:
            type_order = order
            break
    
    return (type_order, num)

def strata_sort_key(name):
    """地层图层排序键 - 提取数字序号"""
    nums = re.findall(r'^(\d+)', name)
    return int(nums[0]) if nums else 999

def sort_strata_columns(columns):
    """对地层列名排序"""
    # 过滤出地层列（非基础列）
    base_cols = ['断面名称', '设计底高程', '分层线高程', '总面积']
    strata_cols = [c for c in columns if c not in base_cols]
    
    # 排序地层列
    sorted_strata = sorted(strata_cols, key=get_strata_sort_key)
    
    return sorted_strata

def run_autocut(params, LOG):
    """分层算量任务 - 完整实现
    
    分层线高程参数：用户输入绝对高程值（如-5表示-5m高程）
    系统自动将高程转换为Y坐标进行计算
    
    设计区判断：开挖线最低Y值以内的区域为设计区，以外为超挖区
    """
    try:
        file_list = params.get('files', [])
        if not file_list:
            LOG("[WARN] 请先选择 DXF 文件。")
            return
        
        # 分层线高程：用户输入的是绝对高程值（如-5表示-5m高程）
        layer_elevation = float(params.get('分层线高程', '-5'))
        output_hatch = params.get('输出填充', True)
        if isinstance(output_hatch, str):
            output_hatch = output_hatch.lower() in ('true', '1', 'yes', '是')
        
        LOG(f"[INFO] 目标分层线高程: {layer_elevation}m")
        
        for input_path in file_list:
            LOG(f"--- [WAIT] 正在处理: {os.path.basename(input_path)} ---")
            
            doc = ezdxf.readfile(input_path)
            msp = doc.modelspace()
            
            # 添加图层
            for layer_name in [LY_LAYER_5M, LY_LAYER_5M_LABEL, LY_ABOVE_HATCH, LY_ABOVE_LABEL]:
                if layer_name not in doc.layers:
                    doc.layers.new(name=layer_name, dxfattribs={'color': 6})
            
            # 关闭AA_分类填充和AA_分类标注图层，避免混淆
            for layer_name in ['AA_分类填充', 'AA_分类标注']:
                try:
                    layer = doc.layers.get(layer_name)
                    layer.off()
                    LOG(f"[INFO] 已关闭图层: {layer_name}")
                except:
                    pass
            
            # 获取DMX列表 - 这是遍历断面的基础
            dmx_list = []
            for e in msp.query('*[layer=="DMX"]'):
                if e.dxftype() == 'LWPOLYLINE':
                    pts = [p[:2] for p in e.get_points()]
                    if pts:
                        x_min = min(p[0] for p in pts)
                        x_max = max(p[0] for p in pts)
                        y_min = min(p[1] for p in pts)
                        y_max = max(p[1] for p in pts)
                        dmx_list.append({
                            'x_min': x_min, 'x_max': x_max,
                            'y_min': y_min, 'y_max': y_max,
                            'pts': pts, 'line': LineString(pts),
                            'y_center': (y_min + y_max) / 2
                        })
            
            # 按Y坐标排序（从大到小，即从上到下）
            dmx_list = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
            LOG(f"DMX数量: {len(dmx_list)}")
            
            # 获取开挖线
            excav_lines_all = get_layer_lines(msp, "开挖线")
            LOG(f"开挖线数量: {len(excav_lines_all)}")
            
            # 获取超挖线构建虚拟框
            overexc_lines_all = get_layer_lines(msp, "超挖线")
            virtual_boxes = build_virtual_boxes_from_overexcav(overexc_lines_all)
            LOG(f"虚拟断面框: {len(virtual_boxes)} 个")
            
            # 获取桩号
            station_texts = []
            for layer in ["0-桩号", "桩号"]:
                for e in msp.query(f'*[layer=="{layer}"]'):
                    if e.dxftype() in ('TEXT', 'MTEXT'):
                        try:
                            x, y = e.dxf.insert.x, e.dxf.insert.y
                            text = e.dxf.text if e.dxftype() == 'TEXT' else e.text
                            text = text.split(";")[-1].replace("}", "").strip()
                            station_texts.append({'text': text, 'x': x, 'y': y})
                        except: pass
            
            # 获取地层列表（1级淤泥、2级淤泥等）
            strata_layers = [l.dxf.name for l in doc.layers if re.match(r'^\d+级', l.dxf.name)]
            strata_layers = sorted(set(strata_layers), key=strata_sort_key)
            LOG(f"地层图层: {strata_layers}")
            
            # 读取地层填充 - 直接从地层图层读取
            strata_hatches = {}  # {地层名: [polygon列表]}
            for layer in strata_layers:
                strata_hatches[layer] = []
                for h in msp.query(f'HATCH[layer=="{layer}"]'):
                    poly = hatch_to_polygon(h)
                    if not poly.is_empty:
                        strata_hatches[layer].append(poly)
            
            # 统计每个地层的填充数量
            total_hatches = sum(len(v) for v in strata_hatches.values())
            LOG(f"地层填充数量: {total_hatches}")
            
            # 按虚拟框遍历处理每个断面（参考autoclassify的逻辑）
            # 这样确保每个桩号只出现一次
            results = []
            generated_layer_lines = 0
            processed_stations = set()  # 记录已处理的桩号，避免重复
            
            # 将DMX按Y中心分组到虚拟框
            def find_dmx_for_vbox(vbox, dmx_list):
                """找到属于此虚拟框的DMX"""
                minx, miny, maxx, maxy = vbox.bounds
                vbox_x_center = (minx + maxx) / 2
                vbox_y_center = (miny + maxy) / 2
                
                best_dmx = None
                min_y_diff = float('inf')
                
                for dmx in dmx_list:
                    # DMX中心X在虚拟框X范围内
                    dmx_x_center = (dmx['x_min'] + dmx['x_max']) / 2
                    dmx_y_center = dmx['y_center']
                    
                    if minx - 20 <= dmx_x_center <= maxx + 20:
                        y_diff = abs(dmx_y_center - vbox_y_center)
                        if y_diff < min_y_diff:
                            min_y_diff = y_diff
                            best_dmx = dmx
                
                return best_dmx
            
            for idx, v_box in enumerate(virtual_boxes):
                minx, miny, maxx, maxy = v_box.bounds
                vbox_y_center = (miny + maxy) / 2
                
                # 获取桩号
                station = f"S{idx+1}"
                best_dist = float('inf')
                for st in station_texts:
                    pt = Point(st['x'], st['y'])
                    if v_box.distance(pt) < 200:
                        dist = pt.distance(Point((minx + maxx) / 2, miny))
                        if dist < best_dist:
                            best_dist = dist
                            station = st['text']
                
                # 检查桩号是否已处理
                if station in processed_stations:
                    continue
                processed_stations.add(station)
                
                # 找到属于此虚拟框的DMX
                dmx = find_dmx_for_vbox(v_box, dmx_list)
                
                if not dmx:
                    # 没有找到DMX，但仍要记录这个桩号（面积为0）
                    LOG(f"处理断面 {idx+1}/{len(virtual_boxes)}: {station} - 无DMX，面积为0")
                    results.append({
                        '断面名称': station,
                        '设计底高程': 0.0,
                        '分层线高程': layer_elevation,
                        '总面积': 0.0
                    })
                    continue
                
                sect_x_min = dmx['x_min']
                sect_x_max = dmx['x_max']
                sect_y_min = dmx['y_min']
                sect_y_max = dmx['y_max']
                sect_y_center = dmx['y_center']
                
                LOG(f"处理断面 {idx+1}/{len(virtual_boxes)}: {station}")
                
                # 检测此断面的标尺，获取高程-Y坐标映射
                ruler_scale = detect_ruler_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max)
                
                if ruler_scale:
                    elev_to_y, y_to_elev = ruler_scale
                    layer_line_y = elev_to_y(layer_elevation)
                    design_bottom_elev = y_to_elev(sect_y_min)
                    LOG(f"  [INFO] 检测到标尺，分层线Y={layer_line_y:.1f}，设计底高程={design_bottom_elev:.2f}m")
                else:
                    # 没有检测到标尺，使用默认转换
                    layer_line_y = elevation_to_y_default(layer_elevation)
                    design_bottom_elev = y_to_elevation_default(sect_y_min)
                    LOG(f"  [INFO] 未检测到标尺，使用默认转换，分层线Y={layer_line_y:.1f}")
                
                design_bottom_y = sect_y_min  # 设计底高程（DMX最低点Y坐标）
                
                # 生成分层线（使用转换后的Y坐标）
                layer_line_pts = [(sect_x_min, layer_line_y), (sect_x_max, layer_line_y)]
                msp.add_lwpolyline(layer_line_pts, dxfattribs={'layer': LY_LAYER_5M, 'color': 6})
                generated_layer_lines += 1
                
                # 添加分层线标注（显示高程值）
                label_x = (sect_x_min + sect_x_max) / 2
                label_content = f"{layer_elevation}m"
                msp.add_text(label_content, dxfattribs={
                    'layer': LY_LAYER_5M_LABEL,
                    'height': 2.5,
                    'insert': (label_x, layer_line_y + 3)
                })
                
                # 构建开挖区域多边形（DMX + 底部闭合）
                sect_coords = dmx['pts']
                bottom_y = sect_y_min - 50  # 底部Y值
                total_open_poly = Polygon(sect_coords + [(sect_x_max, bottom_y), (sect_x_min, bottom_y)]).buffer(0)
                
                if total_open_poly.is_empty:
                    LOG(f"  [WARN] 开挖区域无效，记录面积为0")
                    results.append({
                        '断面名称': station,
                        '设计底高程': round(design_bottom_elev, 2),
                        '分层线高程': layer_elevation,
                        '总面积': 0.0
                    })
                    continue
                
                # 添加调试信息
                LOG(f"  [DEBUG] DMX Y范围: [{sect_y_min:.1f}, {sect_y_max:.1f}], 分层线Y={layer_line_y:.1f}")
                
                # 判断分层线与设计底高程的关系
                # 注意：在CAD坐标系中，Y值越大越靠上（高程越低）
                # 分层线高程=-5m 比设计底高程=-18m 更高
                # 所以分层线Y值应该比设计底Y值大（更靠上）
                
                if layer_line_y > sect_y_max:
                    # 分层线在整个DMX上方，没有有效区域
                    LOG(f"  [INFO] 分层线Y={layer_line_y:.1f}在DMX上方(Ymax={sect_y_max:.1f})，跳过")
                    # 但仍要记录这个桩号（面积为0）
                    results.append({
                        '断面名称': station,
                        '设计底高程': round(design_bottom_elev, 2),
                        '分层线高程': layer_elevation,
                        '总面积': 0.0
                    })
                    continue
                elif layer_line_y <= sect_y_min:
                    # 分层线在设计底以下，整个开挖区域都在分层线以上
                    above_layer_open = total_open_poly
                    LOG(f"  [INFO] 分层线Y={layer_line_y:.1f}在设计底以下(Ymin={sect_y_min:.1f})，计算全部开挖区域")
                else:
                    # 分层线在DMX范围内，计算分层线以上区域
                    # 分层线以上 = 从分层线Y到DMX顶部Y的区域
                    above_layer_poly = box(sect_x_min - 10, layer_line_y, sect_x_max + 10, sect_y_max + 100)
                    above_layer_open = total_open_poly.intersection(above_layer_poly)
                    LOG(f"  [INFO] 分层线Y={layer_line_y:.1f}在DMX范围内，计算分层线以上区域")
                    
                    if above_layer_open.is_empty:
                        LOG(f"  [WARN] 分层线以上区域计算为空")
                        # 记录面积为0
                        results.append({
                            '断面名称': station,
                            '设计底高程': round(design_bottom_elev, 2),
                            '分层线高程': layer_elevation,
                            '总面积': 0.0
                        })
                        continue
                
                # 获取此断面范围内的开挖线
                boundary_box = box(sect_x_min - 20, sect_y_min - 50, sect_x_max + 20, sect_y_max + 50)
                excav_in_section = [l for l in excav_lines_all if boundary_box.intersects(l)]
                
                # 构建设计区多边形（参考autoclassify的逻辑）
                design_polygon = None
                if excav_in_section:
                    # 连接开挖线
                    excav_connected = connect_nearby_endpoints(excav_in_section, tolerance=2.0)
                    all_excav_pts = [p for l in excav_connected for p in l.coords]
                    
                    if all_excav_pts:
                        excav_x_min = min(p[0] for p in all_excav_pts)
                        excav_x_max = max(p[0] for p in all_excav_pts)
                        excav_y_min = min(p[1] for p in all_excav_pts)
                        
                        # 设计区：开挖线X范围内，从开挖线最低点到DMX上方
                        # 构建设计区多边形
                        design_x_min = max(excav_x_min, sect_x_min)
                        design_x_max = min(excav_x_max, sect_x_max)
                        
                        if design_x_max > design_x_min:
                            # 采样开挖线上的点
                            x_samples = []
                            y_samples = []
                            x_current = design_x_min
                            while x_current <= design_x_max:
                                min_y_at_x = None
                                for line in excav_connected:
                                    y_on_line = get_y_on_line_at_x(line, x_current)
                                    if y_on_line is not None:
                                        if min_y_at_x is None or y_on_line < min_y_at_x:
                                            min_y_at_x = y_on_line
                                if min_y_at_x is not None:
                                    x_samples.append(x_current)
                                    y_samples.append(min_y_at_x)
                                x_current += 1.0
                            
                            if len(x_samples) >= 2:
                                # 构建设计区多边形
                                design_coords = []
                                for x, y in zip(x_samples, y_samples):
                                    design_coords.append((x, y))
                                # 右边界向上
                                design_coords.append((x_samples[-1], sect_y_max + 10))
                                # 左边界
                                design_coords.append((x_samples[0], sect_y_max + 10))
                                design_coords.append(design_coords[0])  # 闭合
                                
                                design_polygon = Polygon(design_coords)
                                if not design_polygon.is_valid:
                                    design_polygon = design_polygon.buffer(0)
                
                # 统计各地层填充
                strata_stats = {}
                
                for strata_name, hatch_list in strata_hatches.items():
                    if not hatch_list:
                        continue
                    
                    total_design_area = 0.0
                    total_over_area = 0.0
                    
                    for hatch_poly in hatch_list:
                        # 检查填充是否与此断面相交
                        if not boundary_box.intersects(hatch_poly):
                            continue
                        
                        try:
                            # 计算在分层线以上区域的填充
                            intersect_above = hatch_poly.intersection(above_layer_open)
                            if intersect_above.is_empty:
                                continue
                            
                            # 分离设计区和超挖区
                            if design_polygon and not design_polygon.is_empty:
                                design_part = intersect_above.intersection(design_polygon)
                                over_part = intersect_above.difference(design_polygon)
                                
                                if not design_part.is_empty:
                                    if isinstance(design_part, Polygon):
                                        total_design_area += design_part.area
                                    elif hasattr(design_part, 'geoms'):
                                        for g in design_part.geoms:
                                            if isinstance(g, Polygon):
                                                total_design_area += g.area
                                
                                if not over_part.is_empty:
                                    if isinstance(over_part, Polygon):
                                        total_over_area += over_part.area
                                    elif hasattr(over_part, 'geoms'):
                                        for g in over_part.geoms:
                                            if isinstance(g, Polygon):
                                                total_over_area += g.area
                                
                                # 输出填充
                                if output_hatch:
                                    if total_design_area > 0.1:
                                        add_hatch_with_label(msp, design_part,
                                            get_strata_color(strata_name, strata_layers), 'ANGLE', 0.1, 2.0, strata_name, True)
                                    if total_over_area > 0.1:
                                        add_hatch_with_label(msp, over_part,
                                            get_strata_color(strata_name, strata_layers), 'ANSI31', 0.1, 2.0, strata_name, False)
                            else:
                                # 没有设计区，全部算设计
                                total_design_area = intersect_above.area if isinstance(intersect_above, Polygon) else 0
                                if hasattr(intersect_above, 'geoms'):
                                    for g in intersect_above.geoms:
                                        if isinstance(g, Polygon):
                                            total_design_area += g.area
                                
                                if output_hatch and total_design_area > 0.1:
                                    add_hatch_with_label(msp, intersect_above,
                                        get_strata_color(strata_name, strata_layers), 'ANGLE', 0.1, 2.0, strata_name, True)
                        
                        except Exception as ex:
                            LOG(f"  [WARN] 填充处理错误: {ex}")
                            continue
                    
                    if total_design_area > 0.01 or total_over_area > 0.01:
                        key_design = f"{strata_name}_设计"
                        key_over = f"{strata_name}_超挖"
                        strata_stats[key_design] = round(total_design_area, 3)
                        strata_stats[key_over] = round(total_over_area, 3)
                
                # 无论是否有地层填充数据，都记录结果
                if strata_stats:
                    results.append({
                        '断面名称': station,
                        '设计底高程': round(design_bottom_elev, 2),
                        '分层线高程': layer_elevation,
                        **strata_stats,
                        '总面积': round(sum(strata_stats.values()), 3)
                    })
                else:
                    # 没有地层填充数据，记录面积为0
                    results.append({
                        '断面名称': station,
                        '设计底高程': round(design_bottom_elev, 2),
                        '分层线高程': layer_elevation,
                        '总面积': 0.0
                    })
            
            LOG(f"生成分层线: {generated_layer_lines} 条")
            
            # 输出结果
            if results:
                df = pd.DataFrame(results)
                
                # 排序
                df['sort_key'] = df['断面名称'].apply(station_sort_key)
                df = df.sort_values(by='sort_key').drop(columns=['sort_key'])
                
                # 保存Excel
                timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                output_xlsx = input_path.replace('.dxf', f'_分层算量_{timestamp}.xlsx')
                
                with pd.ExcelWriter(output_xlsx) as writer:
                    # 明细表
                    df.to_excel(writer, sheet_name='明细表', index=False)
                    
                    # 设计量汇总
                    design_cols = [c for c in df.columns if c.endswith('_设计')]
                    if design_cols:
                        # 按地层排序
                        sorted_design_cols = sorted(design_cols, key=get_strata_sort_key)
                        df_design = df[['断面名称'] + sorted_design_cols].copy()
                        df_design.columns = ['断面名称'] + [c.replace('_设计', '') for c in sorted_design_cols]
                        df_design.to_excel(writer, sheet_name='设计量汇总', index=False)
                    
                    # 超挖量汇总
                    over_cols = [c for c in df.columns if c.endswith('_超挖')]
                    if over_cols:
                        # 按地层排序
                        sorted_over_cols = sorted(over_cols, key=get_strata_sort_key)
                        df_over = df[['断面名称'] + sorted_over_cols].copy()
                        df_over.columns = ['断面名称'] + [c.replace('_超挖', '') for c in sorted_over_cols]
                        df_over.to_excel(writer, sheet_name='超挖量汇总', index=False)
                    
                    # 总量汇总（设计+超挖）
                    all_strata_cols = list(set([c.replace('_设计', '').replace('_超挖', '') for c in df.columns if c.endswith('_设计') or c.endswith('_超挖')]))
                    all_strata_cols = sorted(all_strata_cols, key=get_strata_sort_key)
                    
                    if all_strata_cols:
                        df_total = df[['断面名称']].copy()
                        for strata in all_strata_cols:
                            design_col = f"{strata}_设计"
                            over_col = f"{strata}_超挖"
                            total_val = 0.0
                            if design_col in df.columns:
                                total_val = total_val + df[design_col].fillna(0)
                            if over_col in df.columns:
                                total_val = total_val + df[over_col].fillna(0)
                            df_total[strata] = total_val
                        df_total.to_excel(writer, sheet_name='总量汇总', index=False)
                
                # 保存DXF
                output_dxf = input_path.replace('.dxf', f'_带{layer_elevation}m分层线_{timestamp}.dxf')
                doc.saveas(output_dxf)
                
                LOG(f"[OK] 处理完成！")
                LOG(f"   DXF: {os.path.basename(output_dxf)}")
                LOG(f"   Excel: {os.path.basename(output_xlsx)}")
                LOG(f"[STATS] 共处理 {len(results)} 个断面")
            else:
                LOG(f"[WARN] 未找到有效数据")
            
    except Exception as e:
        LOG(f"[ERROR] 分层算量执行错误: {e}")
        LOG(traceback.format_exc())

# ==================== 命令行接口 ====================

def main():
    """命令行入口点"""
    import sys
    import json
    
    if len(sys.argv) < 3:
        print("用法: python engine_cad.py <任务类型> <参数JSON文件>")
        print("任务类型: autoline, autopaste, autohatch, autoclassify, autocut")
        return
    
    task_type = sys.argv[1]
    param_file = sys.argv[2]
    
    try:
        with open(param_file, 'r', encoding='utf-8') as f:
            params = json.load(f)
    except Exception as e:
        print(f"[ERROR] 无法读取参数文件: {e}")
        return
    
    def log_func(msg):
        msg = msg.replace('✅', '[OK]').replace('❌', '[ERROR]').replace('⚠️', '[WARN]')
        msg = msg.replace('⏳', '[WAIT]').replace('✨', '[DONE]').replace('🔍', '[SCAN]')
        msg = msg.replace('🎨', '[PAINT]').replace('🚀', '[GO]').replace('📊', '[STATS]')
        msg = msg.replace('💡', '[TIP]').replace('📐', '[CALC]').replace('♻️', '[RECYCLE]')
        print(msg)
    
    if task_type == 'autoline':
        run_autoline(params, log_func)
    elif task_type == 'autopaste':
        run_autopaste(params, log_func)
    elif task_type == 'autohatch':
        run_autohatch(params, log_func)
    elif task_type == 'autoclassify':
        run_autoclassify(params, log_func)
    elif task_type == 'autocut':
        run_autocut(params, log_func)
    else:
        print(f"[ERROR] 未知任务类型: {task_type}")

if __name__ == "__main__":
    main()