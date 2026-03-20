import ezdxf
import math
import os
import sys
import time
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

def process_dxf_final(input_path):
    output_path = input_path.replace(".dxf", "_算量自适应版.dxf")
    try:
        doc = ezdxf.readfile(input_path)
        msp = doc.modelspace()
    except Exception as e:
        print(f"读取失败: {e}")
        return 0

    # 1. 更加稳健的图层状态获取
    # 只要图层不是明确被关闭 (Off)，就认为它是可见的
    visible_layers = set()
    for layer in doc.layers:
        if not layer.is_off():
            visible_layers.add(layer.dxf.name)

    raw_lines = []
    # 2. 提取线条
    for ent in msp:
        if ent.dxftype() in ('LINE', 'LWPOLYLINE', 'POLYLINE'):
            # 过滤逻辑：如果在关闭图层且不是我们自己建的层，则跳过
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
        print("\n[错误] 在当前开启的图层中未找到任何线条，请检查 LAYISO 是否正确。")
        return 0

    # 3. 0误差核心算法
    merged_lines = unary_union(raw_lines)
    polygons = list(polygonize(merged_lines))
    
    # 过滤掉杂质 (面积太小的不要)
    valid_regions = [p for p in polygons if p.area > 0.01]
    valid_regions = sorted(valid_regions, key=lambda p: p.area, reverse=True)

    if "AA_填充算量层" not in doc.layers:
        doc.layers.add("AA_填充算量层", color=7)

    rgb_list = [(255,150,150), (150,255,150), (150,150,255), (255,255,100), (255,100,255), (100,255,255)]
    patterns = ['ANSI31', 'ANSI32', 'ANSI33']
    
    count = 0
    for i, poly in enumerate(valid_regions):
        try:
            # 核心修正：先尝试计算比例，如果失败则给一个保底值
            try:
                min_x, min_y, max_x, max_y = poly.bounds
                diagonal = math.sqrt((max_x - min_x)**2 + (max_y - min_y)**2)
                adaptive_scale = min(0.8, diagonal * 0.01)
            except:
                adaptive_scale = 1.0 # 保底比例
            
            hatch = msp.add_hatch(dxfattribs={'layer': 'AA_填充算量层'})
            hatch.rgb = rgb_list[i % len(rgb_list)]
            hatch.set_pattern_fill(patterns[i % len(patterns)], scale=adaptive_scale)
            
            # 坐标写入
            hatch.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True)
            for interior in poly.interiors:
                hatch.paths.add_polyline_path(list(interior.coords)[:-1], is_closed=True)
            count += 1
        except Exception as e:
            continue

    doc.saveas(output_path)
    return count

def main():
    print("="*50)
    print("      断面填充算量版 (极致稳定/自适应比例)")
    print("="*50)
    print("说明: 1. 支持 LAYISO 后的可见层处理")
    print("      2. 填充比例随区域大小自动缩放")
    print("      3. 0 误差算量内核")
    print("="*50 + "\n")

    files = sys.argv[1:]
    if not files:
        print("[提示] 请将一个或多个 DXF 拖动到此图标上运行。")
        time.sleep(5)
        return

    for f in files:
        if f.lower().endswith('.dxf'):
            print(f"正在处理: {os.path.basename(f)} ... ", end="", flush=True)
            num = process_dxf_final(f)
            print(f"完成！生成填充块: {num}")
    
    print("\n[任务结束] 请在 CAD 中核对生成的文件。")
    input("按回车键退出程序...")

if __name__ == "__main__":
    main()