# -*- coding: utf-8 -*-
import ezdxf
import math
import os
import traceback
import pandas as pd
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

def run_task(params, LOG):
    try:
        # 1. 参数设置
        target_layer = params.get('填充层名称', 'AA_填充算量层')
        fixed_text_height = 3.0  
        file_list = params.get('files', [])

        if not file_list:
            LOG("⚠️ 请先选择 DXF 文件。")
            return

        for input_path in file_list:
            LOG(f"--- ⏳ 正在处理: {os.path.basename(input_path)} ---")
            
            try:
                doc = ezdxf.readfile(input_path)
                msp = doc.modelspace()
            except Exception as e:
                LOG(f"❌ 读取失败: {e}")
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

            # 固定填充比例 0.1
            global_hatch_scale = 0.1

            # 几何处理
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
                
                # 记录数据
                data_for_excel.append({"编号": index_no, "面积(㎡)": area_val})

                try:
                    # A. 填充
                    hatch = msp.add_hatch(dxfattribs={'layer': target_layer})
                    hatch.rgb = current_rgb
                    hatch.set_pattern_fill('ANSI31', scale=global_hatch_scale)
                    hatch.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True)
                    for interior in poly.interiors:
                        hatch.paths.add_polyline_path(list(interior.coords)[:-1], is_closed=True)
                    
                    # B. 文字标注
                    in_point = poly.representative_point()
                    label_content = f"{{\\fArial|b1;{index_no}\\PS={area_val}}}"
                    mtext = msp.add_mtext(label_content, dxfattribs={
                        'layer': target_layer + "_标注",
                        'insert': (in_point.x, in_point.y),
                        'char_height': fixed_text_height,
                        'attachment_point': 5,
                    })
                    mtext.rgb = current_rgb 
                    
                    # --- 兼容旧版 ezdxf 的背景遮罩实现 ---
                    try:
                        # 0x01 表示使用背景色遮罩
                        mtext.dxf.bg_fill_setting = 1 
                        # 遮罩范围缩放，1.5 左右比较合适
                        mtext.dxf.bg_fill_scale_factor = 1.5
                    except:
                        pass # 如果连底层属性都没有，则放弃遮罩，保证填充能画出来

                    # C. 成组
                    try:
                        new_group = dxf_groups.new()
                        new_group.add_entities([hatch, mtext])
                    except: pass

                except Exception as e:
                    LOG(f"⚠️ 块 {index_no} 生成出错: {e}")
                    continue

            # 保存 DXF（添加时间戳避免文件占用）
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dxf = input_path.replace(".dxf", f"_填充完成_{timestamp}.dxf")
            doc.saveas(output_dxf)
            
            # 导出 Excel
            if data_for_excel:
                try:
                    df = pd.DataFrame(data_for_excel)
                    output_xlsx = input_path.replace(".dxf", f"_面积明细表_{timestamp}.xlsx")
                    df.to_excel(output_xlsx, index=False)
                    LOG(f"📊 面积表已生成: {os.path.basename(output_xlsx)}")
                except Exception as ex:
                    LOG(f"❌ Excel 导出失败: {ex}")

            LOG(f"✅ 处理完成！总数量: {len(data_for_excel)}")

        LOG("✨ [全任务圆满结束]")

    except Exception as e:
        LOG(f"❌ 脚本崩溃:\n{traceback.format_exc()}")

# ================= 测试入口 =================
if __name__ == "__main__":
    import sys
    
    # 固定测试文件
    test_file = r"d:\tunnel_build\测试文件\设计测试全图.dxf"
    
    if not os.path.exists(test_file):
        print(f"❌ 测试文件不存在: {test_file}")
        sys.exit(1)
    
    params = {
        'files': [test_file],
        '填充层名称': 'AA_填充算量层'
    }
    
    def log(msg):
        print(msg)
    
    print(f"=== 测试模式: adaptive.py ===")
    print(f"输入文件: {test_file}")
    run_task(params, log)
