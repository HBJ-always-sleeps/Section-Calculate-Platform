# -*- coding: utf-8 -*-
import ezdxf
import os
import traceback
from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union, linemerge

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
    # 扩大垂直线范围，确保能交上
    v_line = LineString([(x, b[1] - 100), (x, b[3] + 100)])
    try:
        inter = line.intersection(v_line)
        if inter.is_empty: return None
        if inter.geom_type == 'Point': return inter.y
        if inter.geom_type in ('MultiPoint', 'LineString'):
            # 如果是线或多点，提取坐标。既然是找下包络，这里也应取其极值点
            coords = inter.coords if inter.geom_type == 'LineString' else [p.coords[0] for p in inter.geoms]
            # 注意：内部交点也取最小值，以符合下包络逻辑
            return min(c[1] for c in coords)
    except: return None
    return None

def run_task(params, LOG):
    try:
        layer_new = params.get('图层A名称')
        layer_old = params.get('图层B名称')
        
        if not layer_new or not layer_old:
            LOG("❌ 脚本错误：无法从UI获取图层名称。")
            return
            
        # 结果图层名改为下表面标识
        layer_out = "FINAL_BOTTOM_SURFACE"
        file_list = params.get('files', [])

        if not file_list:
            LOG("⚠️ 请先添加文件。")
            return

        for input_file in file_list:
            LOG(f"--- ⏳ 正在处理(下包络): {os.path.basename(input_file)} ---")
            
            if not os.path.exists(input_file):
                LOG(f"❌ 错误: 找不到文件 {input_file}")
                continue

            doc = ezdxf.readfile(input_file)
            msp = doc.modelspace()
            
            query_str = 'LWPOLYLINE POLYLINE LINE'
            new_lss = [entity_to_linestring(e) for e in msp.query(f'{query_str}[layer=="{layer_new}"]')]
            old_lss = [entity_to_linestring(e) for e in msp.query(f'{query_str}[layer=="{layer_old}"]')]
            
            new_lss = [ls for ls in new_lss if ls]
            old_lss = [ls for ls in old_lss if ls]

            if not new_lss and not old_lss:
                LOG(f"⚠️ 跳过：指定图层没有线段。")
                continue

            # --- 分组逻辑 ---
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

            # --- 合并提取最低包络 ---
            if layer_out not in doc.layers:
                doc.layers.new(name=layer_out, dxfattribs={'color': 3}) # 绿色区分

            success_count = 0
            for group in groups:
                if len(group) < 2:
                    msp.add_lwpolyline(list(group[0].coords), dxfattribs={'layer': layer_out})
                    success_count += 1
                    continue
                
                # 核心几何提取
                u = unary_union(group)
                segs = u.geoms if isinstance(u, MultiLineString) else [u]
                
                valid_pieces = []
                for seg in segs:
                    mid = seg.interpolate(0.5, normalized=True)
                    # --- 改动：取极小值 ---
                    min_y = float('inf') 
                    found = False
                    for ls in group:
                        y = get_y_at_x(ls, mid.x)
                        if y is not None:
                            min_y = min(min_y, y)
                            found = True
                    
                    # --- 改动：如果当前段的中点 Y 坐标等于(或小于)最小值，则保留该段 ---
                    if found and mid.y <= min_y + 1e-4:
                        valid_pieces.append(seg)
                
                if valid_pieces:
                    merged = linemerge(valid_pieces)
                    res_list = merged.geoms if isinstance(merged, MultiLineString) else [merged]
                    for r in res_list:
                        if r.length > 0.01:
                            msp.add_lwpolyline(list(r.coords), dxfattribs={'layer': layer_out})
                    success_count += 1

            output_name = input_file.replace(".dxf", "_bottom_merged.dxf")
            doc.saveas(output_name)
            LOG(f"✅ 完成！已提取下包络线，保存至: {os.path.basename(output_name)}")

        LOG("✨ [下包络任务全部结束]")

    except Exception as e:
        LOG(f"❌ 脚本崩溃:\n{traceback.format_exc()}")