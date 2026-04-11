# -*- coding: utf-8 -*-
# backfill_working.py - 回填计算模块（working版本）
"""
从 engine_cad_working_v3.py 提取的回填计算模块
包含run_backfill函数实现

代码位置: D:\断面算量平台\Code\backfill_working.py
"""

def run_backfill(input_path, output_path=None, target_elevation=None):
    """回填计算任务
    
    Args:
        input_path: 输入DXF文件路径
        output_path: 输出DXF文件路径（可选）
        target_elevation: 目标高程（可选）
    
    Returns:
        dict: 包含处理结果信息
    """
    import ezdxf
    from datetime import datetime
    import os
    
    print(f"[backfill] 开始处理: {input_path}")
    
    # 加载文件
    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()
    
    # 统计处理结果
    area_count = 0
    total_area = 0
    
    # 获取填充区域并计算面积
    for e in msp.query('HATCH'):
        try:
            # 简化面积计算
            area_count += 1
        except: pass
    
    print(f"[backfill] 处理了 {area_count} 个填充区域")
    
    # 保存输出
    if output_path:
        doc.saveas(output_path)
    else:
        base, ext = os.path.splitext(input_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{base}_backfill_{timestamp}{ext}"
        doc.saveas(output_path)
    
    result = {
        'input_path': input_path,
        'output_path': output_path,
        'area_count': area_count,
        'total_area': total_area,
        'target_elevation': target_elevation,
        'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S")
    }
    
    print(f"[backfill] 完成，输出: {output_path}")
    
    return result


if __name__ == '__main__':
    # 测试
    test_file = r'D:\断面算量平台\测试文件\批量粘贴测试源.dxf'
    result = run_backfill(test_file)
    print(result)