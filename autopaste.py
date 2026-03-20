# -*- coding: utf-8 -*-
import ezdxf
import re
import os
import traceback

def get_best_pt(e):
    try:
        if e.dxftype() == 'TEXT':
            return (e.dxf.align_point.x, e.dxf.align_point.y) if (e.dxf.halign or e.dxf.valign) else (e.dxf.insert.x, e.dxf.insert.y)
        return (e.dxf.insert.x, e.dxf.insert.y)
    except: return (0, 0)

def get_txt(e):
    return e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text

def run_task(params, LOG):
    """
    UI 传入参数适配层
    """
    try:
        # 1. 获取 UI 参数 (键名需与 main.py 对应)
        src_path = params.get('源文件名', 'vt.dxf')
        dst_path = params.get('目标文件名', 'vt2.dxf')
        
        s00x = float(params.get('源端0点X', 86.854))
        s00y_first = float(params.get('源端0点Y', -15.062))
        sbx_ref = float(params.get('源端基点X', 86.003))
        sby_first = float(params.get('源端基点Y', -35.298))
        step_y = float(params.get('断面间距', -148.476))
        
        dty_ref = float(params.get('目标桩号Y', -1470.529))
        dby_ref = float(params.get('目标基点Y', -1363.500))

        # 逻辑预算
        src_dx, src_dy = sbx_ref - s00x, sby_first - s00y_first
        dist_y = dby_ref - dty_ref

        if not os.path.exists(src_path):
            LOG(f"❌ 错误: 找不到源文件 {src_path}")
            return

        LOG(f"正在读取文件: {src_path} ...")
        src_doc = ezdxf.readfile(src_path)
        src_msp = src_doc.modelspace()
        
        if not os.path.exists(dst_path):
            LOG(f"⚠️ 目标文件 {dst_path} 不存在，将尝试保存为新文件")
            dst_doc = ezdxf.new()
        else:
            dst_doc = ezdxf.readfile(dst_path)
        dst_msp = dst_doc.modelspace()

        # --- 1. 探测源端 ---
        LOG("🔍 第一步：探测源端断面...")
        all_src_texts = src_msp.query('TEXT MTEXT')
        sections = {}
        
        for i in range(1000):
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
                LOG(f"💡 探测结束，共找到 {len(sections)} 个断面潜在区域。")
                break
            if m_id:
                sections[m_id] = {"bx": nav_00[0] + src_dx, "by": nav_00[1] + src_dy, "ents": []}

        # --- 2. 实体分配 (分配红线) ---
        LOG("🎨 第二步：提取红线实体 (Color 1)...")
        red_lines = [e for e in src_msp.query('LWPOLYLINE') if e.dxf.color == 1]
        sorted_mids = sorted(sections.keys(), key=lambda k: sections[k]["by"], reverse=True)
        
        for red in red_lines:
            pts = red.get_points()
            avg_y = sum(p[1] for p in pts) / len(pts)
            best_mid = None
            min_dist = 100
            for mid in sorted_mids:
                d = abs(avg_y - (sections[mid]["by"] - 40))
                if d < min_dist:
                    min_dist = d
                    best_mid = mid
                if avg_y > sections[mid]["by"] + 100: break
            if best_mid:
                sections[best_mid]["ents"].append(red)

        # --- 3. 目标端匹配并粘贴 ---
        LOG("🚀 第三步：匹配目标图纸桩号并执行粘贴...")
        count = 0
        dst_index = {}
        for lb in dst_msp.query('TEXT MTEXT'):
            txt = get_txt(lb).upper()
            match = re.search(r'(\d+\+\d+)', txt)
            if match:
                dst_index[match.group(1)] = get_best_pt(lb)

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
                if count % 20 == 0: LOG(f" 已粘贴 {count} 个...")

        save_name = "result_pasted.dxf"
        dst_doc.saveas(save_name)
        LOG(f"✅ 处理完成！成果已保存至: {save_name}")
        LOG(f"📊 统计：共匹配并粘贴 {count} 个断面。")

    except Exception as e:
        LOG(f"❌ 脚本执行崩溃:\n{traceback.format_exc()}")