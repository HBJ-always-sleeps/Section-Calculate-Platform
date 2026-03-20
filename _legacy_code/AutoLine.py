import ezdxf
import os
import sys
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
    v_line = LineString([(x, b[1] - 50), (x, b[3] + 50)])
    try:
        inter = line.intersection(v_line)
        if inter.is_empty: return None
        if inter.geom_type == 'Point': return inter.y
        if inter.geom_type in ('MultiPoint', 'LineString'):
            coords = inter.coords if inter.geom_type == 'LineString' else [p.coords[0] for p in inter.geoms]
            return max(c[1] for c in coords)
    except: return None
    return None

def main():
    print("="*40)
    print("      断面线最高包络合并工具 (V9)")
    print("="*40)
    
    # --- 交互输入 ---
    input_file = input("请输入DXF文件名 (直接回车默认 vt222.dxf): ").strip() or "vt222.dxf"
    if not os.path.exists(input_file):
        print(f"错误: 找不到文件 {input_file}")
        input("按回车键退出..."); return

    layer_new = input("请输入【新】断面图层名: ").strip()
    layer_old = input("请输入【旧】断面图层名: ").strip()
    layer_out = "FINAL_TOP_SURFACE"

    print("\n[1/4] 正在读取文件...")
    try:
        doc = ezdxf.readfile(input_file)
        msp = doc.modelspace()
        
        query_str = 'LWPOLYLINE POLYLINE LINE'
        new_lss = [entity_to_linestring(e) for e in msp.query(f'{query_str}[layer=="{layer_new}"]')]
        old_lss = [entity_to_linestring(e) for e in msp.query(f'{query_str}[layer=="{layer_old}"]')]
        
        new_lss = [ls for ls in new_lss if ls]
        old_lss = [ls for ls in old_lss if ls]

        print(f"    - 新图层找到 {len(new_lss)} 条有效线段")
        print(f"    - 旧图层找到 {len(old_lss)} 条有效线段")

        if not new_lss:
            print("错误: 新图层中未发现有效线段，请检查图层名。")
            input("按回车键退出..."); return

        # --- 分组 ---
        print("[2/4] 正在按相交关系进行断面分组...")
        groups = []
        used_old = set()
        for n_ls in new_lss:
            current_group = [n_ls]
            for idx, o_ls in enumerate(old_lss):
                if n_ls.intersects(o_ls) or n_ls.distance(o_ls) < 0.5:
                    current_group.append(o_ls)
                    used_old.add(idx)
            groups.append(current_group)

        # --- 合并 ---
        print(f"[3/4] 正在处理 {len(groups)} 组断面并提取最高线...")
        if layer_out not in doc.layers:
            doc.layers.new(name=layer_out, dxfattribs={'color': 1})

        success_count = 0
        for group in groups:
            if len(group) < 2: continue
            
            u = unary_union(group)
            segs = u.geoms if isinstance(u, MultiLineString) else [u]
            
            valid_pieces = []
            for seg in segs:
                mid = seg.interpolate(0.5, normalized=True)
                max_y = -float('inf')
                found = False
                for ls in group:
                    y = get_y_at_x(ls, mid.x)
                    if y is not None:
                        max_y = max(max_y, y); found = True
                
                if found and mid.y >= max_y - 1e-4:
                    valid_pieces.append(seg)
            
            if valid_pieces:
                merged = linemerge(valid_pieces)
                res_list = merged.geoms if isinstance(merged, MultiLineString) else [merged]
                for r in res_list:
                    if r.length > 0.01:
                        msp.add_lwpolyline(list(r.coords), dxfattribs={'layer': layer_out})
                success_count += 1

        # --- 保存 ---
        output_name = f"merged_{input_file}"
        print(f"[4/4] 正在保存结果到 {output_name}...")
        doc.saveas(output_name)
        
        print("\n" + "-"*40)
        print(f"处理完成！成功生成 {success_count} 条断面线。")
        print(f"生成的图层名为: {layer_out}")
        print("-"*40)
        input("任务成功，按回车键退出...")

    except Exception as e:
        print(f"\n程序运行中出现错误: {e}")
        import traceback
        traceback.print_exc()
        input("\n按回车键退出...")

if __name__ == "__main__":
    main()