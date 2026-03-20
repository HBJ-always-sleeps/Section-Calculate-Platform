import ezdxf
import math
import os
import sys
import time
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

def process_dxf_safe_filter(input_path):
    output_path = input_path.replace(".dxf", "_算量核准版.dxf")
    try:
        doc = ezdxf.readfile(input_path)
        msp = doc.modelspace()
    except Exception as e:
        print(f"读取失败: {e}")
        return 0

    # 获取所有图层，并增加详细的日志输出方便调试
    visible_layers = set()
    for layer in doc.layers:
        # 更加宽松的判断逻辑：只要不是明确标记为 OFF 的图层都认为可见
        # 很多时候 is_frozen() 会导致意外过滤
        if not layer.is_off():
            visible_layers.add(layer.dxf.name)

    raw_lines = []
    for ent in msp:
        if ent.dxftype() in ('LINE', 'LWPOLYLINE', 'POLYLINE'):
            # 过滤逻辑：如果图层在可见集合里，或者它是 AA_ 开头的（我们自己建的层）
            lname = ent.dxf.layer
            if lname not in visible_layers and not lname.startswith("AA_"):
                continue
                
            try:
                if ent.dxftype() == 'LINE':
                    raw_lines.append(LineString([ent.dxf.start.vec2, ent.dxf.end.vec2]))
                else:
                    pts = [p[:2] for p in ent.get_points()] if ent.dxftype() == 'LWPOLYLINE' else [p.vtx.vec2 for p in ent.vertices]
                    if len(pts) >= 2:
                        for i in range(len(pts)-1):
                            raw_lines.append(LineString([pts[i], pts[i+1]]))
            except: continue

    if not raw_lines:
        print("\n[警告] 未在可见图层中找到任何有效线条！")
        return 0

    # 核心算法（保持 Final Precise 的稳定逻辑）
    merged_lines = unary_union(raw_lines)
    polygons = list(polygonize(merged_lines))
    valid_regions = [p for p in polygons if p.area > 0.01]
    valid_regions = sorted(valid_regions, key=lambda p: p.area, reverse=True)

    if "AA_填充算量层" not in doc.layers:
        doc.layers.add("AA_填充算量层", color=7)

    rgb_list = [(255,150,150), (150,255,150), (150,150,255), (255,255,100), (255,100,255), (100,255,255)]
    patterns = ['ANSI31', 'ANSI32', 'ANSI33']
    
    count = 0
    for i, poly in enumerate(valid_regions):
        try:
            hatch = msp.add_hatch(dxfattribs={'layer': 'AA_填充算量层'})
            hatch.rgb = rgb_list[i % len(rgb_list)]
            diag = math.sqrt((poly.bounds[2]-poly.bounds[0])**2 + (poly.bounds[3]-poly.bounds[1])**2)
            hatch.set_pattern_fill(patterns[i % len(patterns)], scale=max(1.0, diag * 0.15))
            hatch.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True)
            for interior in poly.interiors:
                hatch.paths.add_polyline_path(list(interior.coords)[:-1], is_closed=True)
            count += 1
        except: continue

    doc.saveas(output_path)
    return count

def main():
    print("="*50)
    print("      断面填充算量版 (兼容性修正)")
    print("="*50)
    print("当前策略：自动识别 CAD '小灯泡' 开关状态")
    print("提示：如果依然无法填充，请确保参与计算的图层已打开")
    print("="*50 + "\n")

    files = sys.argv[1:]
    if not files:
        print("[提示] 请将 DXF 文件拖动到此图标上...")
        time.sleep(5); return

    for f in files:
        if f.lower().endswith('.dxf'):
            print(f"正在读取: {os.path.basename(f)} ... ", end="", flush=True)
            num = process_dxf_safe_filter(f)
            print(f"成功！生成填充块: {num}")
    
    input("\n按回车退出...")

if __name__ == "__main__":
    main()