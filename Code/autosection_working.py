# -*- coding: utf-8 -*-
# autosection_working.py - 自动断面模块（working版本）
"""
从 engine_cad_working_v3.py 提取的自动断面模块
包含run_autosection函数实现

代码位置: D:\断面算量平台\Code\autosection_working.py
"""

def run_autosection(input_path, output_path=None, section_layer='DMX'):
    """自动断面任务
    
    Args:
        input_path: 输入DXF文件路径
        output_path: 输出DXF文件路径（可选）
        section_layer: 断面图层名称
    
    Returns:
        dict: 包含处理结果信息
    """
    import ezdxf
    from datetime import datetime
    import os
    
    print(f"[autosection] 开始处理: {input_path}")
    
    # 加载文件
    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()
    
    # 统计处理结果
    section_count = 0
    
    # 获取断面图层多段线
    for e in msp.query(f'LWPOLYLINE[layer=="{section_layer}"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) >= 2:
                section_count += 1
        except: pass
    
    print(f"[autosection] 处理了 {section_count} 个断面")
    
    # 保存输出
    if output_path:
        doc.saveas(output_path)
    else:
        base, ext = os.path.splitext(input_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{base}_autosection_{timestamp}{ext}"
        doc.saveas(output_path)
    
    result = {
        'input_path': input_path,
        'output_path': output_path,
        'section_count': section_count,
        'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S")
    }
    
    print(f"[autosection] 完成，输出: {output_path}")
    
    return result


if __name__ == '__main__':
    # 测试
    test_file = r'D:\断面算量平台\测试文件\批量粘贴测试源.dxf'
    result = run_autosection(test_file)
    print(result)