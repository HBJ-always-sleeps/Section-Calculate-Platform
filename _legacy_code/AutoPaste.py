import ezdxf
import re
import os
import sys

def get_best_pt(e):
    try:
        if e.dxftype() == 'TEXT':
            return (e.dxf.align_point.x, e.dxf.align_point.y) if (e.dxf.halign or e.dxf.valign) else (e.dxf.insert.x, e.dxf.insert.y)
        return (e.dxf.insert.x, e.dxf.insert.y)
    except: return (0, 0)

def get_txt(e):
    return e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text

def main():
    print("="*50)
    print("      断面自动粘贴工具 v2.2 (海量数据优化版)")
    print("="*50)
    
    src_path = input("\n请输入源文件名 (默认 vt.dxf): ") or "vt.dxf"
    dst_path = input("请输入目标文件名 (默认 vt2.dxf): ") or "vt2.dxf"
    
    if not os.path.exists(src_path) or not os.path.exists(dst_path):
        print("\n[错误] 找不到文件！"); input("回车退出..."); sys.exit()

    try:
        print("\n[参数设置] (回车使用默认)")
        s00x = float(input(" -> 源端 '0.00' 参考 X (86.854): ") or 86.854)
        s00y_first = float(input(" -> 源端第一个 '0.00' Y (-15.062): ") or -15.062)
        sbx_ref = float(input(" -> 源端基点参考 X (86.003): ") or 86.003)
        sby_first = float(input(" -> 源端第一个基点 Y (-35.298): ") or -35.298)
        step_y = float(input(" -> 断面间距 (默认 -148.476): ") or -148.476)
        
        dty_ref = float(input("\n -> 目标桩号参考 Y (-1470.529): ") or -1470.529)
        dby_ref = float(input(" -> 目标基点参考 Y (-1363.500): ") or -1363.500)
        
        src_dx, src_dy = sbx_ref - s00x, sby_first - s00y_first
        dist_y = dby_ref - dty_ref
    except ValueError:
        print("\n[错误] 请输入数字！"); input("回车退出..."); sys.exit()

    print("\n--- 正在读取 DXF 文件 (数据量大时可能需等待 10-20秒)... ---")
    try:
        src_msp = ezdxf.readfile(src_path).modelspace()
        dst_doc = ezdxf.readfile(dst_path)
        dst_msp = dst_doc.modelspace()
    except Exception as e:
        print(f"读取失败: {e}"); input(); sys.exit()

    # --- 1. 流式探测源端 (识别 160+ 断面) ---
    print("\n--- 第一步：探测源端断面... ---")
    all_src_texts = src_msp.query('TEXT MTEXT')
    sections = {}
    
    for i in range(1000): # 上限调高到 1000
        curr_y_limit = s00y_first + (i * step_y)
        m_id, nav_00 = None, None
        
        for t in all_src_texts:
            p = get_best_pt(t)
            if abs(p[1] - curr_y_limit) < 60:
                content = get_txt(t).strip()
                if ".TIN" in content.upper() and abs(p[0] - 75.5) < 40:
                    match = re.search(r'(\d+\+\d+)', content)
                    if match: m_id = match.group(1)
                if content == "0.00" and abs(p[0] - s00x) < 20:
                    nav_00 = p
        
        if nav_00 is None:
            print(f" [提示] 探测至第 {i} 层结束。")
            break
        if m_id:
            sections[m_id] = {"bx": nav_00[0] + src_dx, "by": nav_00[1] + src_dy, "ents": []}

    # --- 2. 实体分配 (分配红线) ---
    print("--- 第二步：分配红线实体... ---")
    red_lines = [e for e in src_msp.query('LWPOLYLINE') if e.dxf.color == 1]
    # 建立 Y 坐标索引以加速
    sorted_mids = sorted(sections.keys(), key=lambda k: sections[k]["by"], reverse=True)
    
    for red in red_lines:
        pts = red.get_points()
        avg_y = sum(p[1] for p in pts) / len(pts)
        # 寻找最近基点
        best_mid = None
        min_dist = 100
        for mid in sorted_mids:
            d = abs(avg_y - (sections[mid]["by"] - 40))
            if d < min_dist:
                min_dist = d
                best_mid = mid
            if avg_y > sections[mid]["by"] + 100: break # 优化搜索
        if best_mid:
            sections[best_mid]["ents"].append(red)

    # --- 3. 目标端极速匹配 (关键优化点) ---
    print("--- 第三步：匹配目标端并粘贴... ---")
    count = 0
    # 先把目标端所有桩号文字存入字典，只扫一遍目标图纸
    dst_index = {}
    for lb in dst_msp.query('TEXT MTEXT'):
        txt = get_txt(lb).upper()
        match = re.search(r'(\d+\+\d+)', txt)
        if match:
            dst_index[match.group(1)] = get_best_pt(lb)

    # 遍历源端识别到的断面，直接从字典取坐标
    for mid, s_data in sections.items():
        if mid in dst_index and s_data["ents"]:
            p_dst = dst_index[mid]
            tx, ty = p_dst[0], p_dst[1] + dist_y
            dx, dy = tx - s_data["bx"], ty - s_data["by"]
            
            for e in s_data["ents"]:
                new_e = e.copy()
                new_e.translate(dx, dy, 0)
                new_e.dxf.layer = "0-已粘贴断面"
                new_e.dxf.color = 3
                dst_msp.add_entity(new_e)
            count += 1
            if count % 20 == 0: print(f" 已粘贴 {count} 个...")

    dst_doc.saveas("result.dxf")
    print(f"\n[✅ 成功] 处理完成！共粘贴 {count} 个断面。")
    input("回车键退出程序...")

if __name__ == "__main__":
    main()