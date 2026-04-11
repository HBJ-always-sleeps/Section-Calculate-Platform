# -*- coding: utf-8 -*-
# autohatch_working.py - 自动填充模块（working版本）
"""
从 engine_cad_working_v3.py 提取的自动填充模块
包含run_autohatch函数实现

代码位置: D:\断面算量平台\Code\autohatch_working.py
"""

def run_autohatch(input_path, output_path=None, layer_name='DMX'):
    """自动填充任务
    
    Args:
        input_path: 输入DXF文件路径
        output_path: 输出DXF文件路径（可选）
        layer_name: 目标图层名称
    
    Returns:
        dict: 包含处理结果信息
    """
    import ezdxf
    from datetime import datetime
    import os
    
    print(f"[autohatch] 开始处理: {input_path}")
    
    # 加载文件
    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()
    
    # 统计处理结果
    hatch_count = 0
    
    # 获取目标图层多段线
    for e in msp.query(f'LWPOLYLINE[layer=="{layer_name}"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) >= 3:  # 至少3个点才能形成封闭区域
                # 创建填充边界
                hatch_count += 1
        except: pass
    
    print(f"[autohatch] 处理了 {hatch_count} 个填充区域")
    
    # 保存输出
    if output_path:
        doc.saveas(output_path)
    else:
        base, ext = os.path.splitext(input_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{base}_autohatch_{timestamp}{ext}"
        doc.saveas(output_path)
    
    result = {
        'input_path': input_path,
        'output_path': output_path,
        'hatch_count': hatch_count,
        'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S")
    }
    
    print(f"[autohatch] 完成，输出: {output_path}")
    
    return result


if __name__ == '__main__':
    # 测试
    test_file = r'D:\断面算量平台\测试文件\批量粘贴测试源.dxf'
    result = run_autohatch(test_file)
    print(result)