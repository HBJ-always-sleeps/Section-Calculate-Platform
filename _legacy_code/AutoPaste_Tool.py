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
    print("      断面自动粘贴工具 v1.0 (生产版)")
    print("="*50)
    
    # 1. 文件输入
    src_path = input("\n请输入源文件名 (默认 vt.dxf): ") or "vt.dxf"
    dst_path = input("请输入目标文件名 (默认 vt2.dxf): ") or "vt2.dxf"
    
    if not os.path.exists(src_path) or not os.path.exists(dst_path):
        print(f"\n[错误] 找不到文件，请检查 {src_path} 或 {dst_path} 是否在当前文件夹！")
        input("\n按回车键退出..."); sys.exit()

    # 2. 参数输入
    try:
        print("\n[源端参数设置]")
        s00x = float(input(" -> 源端 '0.00' 文字 X (默认 86.854): ") or 86.854)
        s00y = float(input(" -> 源端 '0.00' 文字 Y (默认 -15.062): ") or -15.062)
        sbx = float(input(" -> 源端基点 X (默认 86.003): ") or 86.003)
        sby = float(input(" -> 源端基点 Y (默认 -35.298): ") or -35.298)
        
        print("\n[目标端参数设置]")
        dty = float(input(" -> 目标桩号文字参考 Y (如 -1470.529): ") or -1470.529)
        dby = float(input(" -> 目标基点参考 Y (如 -1363.500): ") or -1363.500)
        
        src_dx, src_dy = sbx - s00x, sby - s00y
        dist_y = dby - dty
    except ValueError:
        print("\n[错误] 输入必须为数字！")
        input("\n按回车键退出..."); sys.exit()

    # 3. 处理逻辑
    print("\n--- 正在处理中，请稍候... ---")
    try:
        src_msp = ezdxf.readfile(src_path).modelspace()
        dst_doc = ezdxf.readfile(dst_path)
        dst_msp = dst_doc.modelspace()

        # 扫描源端
        all_texts = src_msp.query('TEXT MTEXT')
        red_lines = [e for e in src_msp.query('LWPOLYLINE') if e.dxf.color == 1]
        sections = {}

        for i in range(30): # 增加扫描深度
            y_ref = sby + (i * -148.476)
            m_id, n00 = None, None
            for t in all_texts:
                p = get_best_pt(t)
                if abs(p[1] - y_ref) < 100:
                    txt = get_txt(t).strip()
                    if ".TIN" in txt.upper() and abs(p[0] - 75.5) < 40:
                        match = re.search(r'(\d+\+\d+)', txt)
                        if match: m_id = match.group(1)
                    if txt == "0.00" and abs(p[0] - s00x) < 20:
                        n00 = p
            if m_id and n00 and m_id not in sections:
                sections[m_id] = {"bx": n00[0] + src_dx, "by": n00[1] + src_dy, "ents": []}
                print(f" [识别] 桩号: {m_id:<8} 源基点: ({sections[m_id]['bx']:.3f}, {sections[m_id]['by']:.3f})")

        # 实体分配
        for red in red_lines:
            pts = red.get_points(); avg_y = sum(p[1] for p in pts) / len(pts)
            best_mid = min(sections.keys(), key=lambda k: abs(avg_y - (sections[k]["by"] - 40)), default=None)
            if best_mid and abs(avg_y - (sections[best_mid]["by"] - 40)) < 80:
                sections[best_mid]["ents"].append(red)

        # 目标粘贴
        count = 0
        for lb in dst_msp.query('TEXT MTEXT[layer=="0-桩号"]'):
            mid_match = re.search(r'(\d+\+\d+)', get_txt(lb))
            if mid_match and mid_match.group(1) in sections:
                mid = mid_match.group(1); s_data = sections[mid]
                if not s_data["ents"]: continue
                p_dst = get_best_pt(lb)
                tx, ty = p_dst[0], p_dst[1] + dist_y
                dx, dy = tx - s_data["bx"], ty - s_data["by"]
                for e in s_data["ents"]:
                    new_e = e.copy(); new_e.translate(dx, dy, 0)
                    new_e.dxf.layer = "0-已粘贴断面"; new_e.dxf.color = 3
                    dst_msp.add_entity(new_e)
                count += 1
                print(f" [粘贴] {mid:<8} -> 目标基点:({tx:.3f}, {ty:.3f})")

        dst_doc.saveas("result.dxf")
        print(f"\n[成功] 处理完成！共粘贴 {count} 个断面。结果已保存至: result.dxf")
    except Exception as e:
        print(f"\n[运行异常] {e}")

    print("\n" + "="*50)
    input("所有操作已完成，按回车键关闭窗口...")

if __name__ == "__main__":
    main()