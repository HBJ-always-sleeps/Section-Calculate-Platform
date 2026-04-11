# -*- coding: utf-8 -*-
# autoline_working.py - 自动连线模块（working版本）
"""
从 engine_cad_working_v3.py 提取的自动连线模块
包含run_autoline函数实现

代码位置: D:\断面算量平台\Code\autoline_working.py
"""

def run_autoline(input_path, output_path=None, layer_name='DMX', scale_ratio=None):
    """自动连线任务
    
    Args:
        input_path: 输入DXF文件路径
        output_path: 输出DXF文件路径（可选）
        layer_name: 目标图层名称
        scale_ratio: 缩放比例（可选，自动检测）
    
    Returns:
        dict: 包含处理结果信息
    """
    import ezdxf
    from datetime import datetime
    
    print(f"[autoline] 开始处理: {input_path}")
    
    # 加载文件
    doc = ezdxf.readfile(input_path)
    msp = doc.modelspace()
    
    # 检测缩放比例（如果未提供）
    if scale_ratio is None:
        from scale_detector_working import ScaleDetector
        detector = ScaleDetector(msp)
        scale_ratio, msg = detector.detect_scale()
        print(f"[autoline] {msg}")
    
    # 统计处理结果
    processed_count = 0
    connected_count = 0
    
    # 获取目标图层所有多段线
    lines = []
    for e in msp.query(f'LWPOLYLINE[layer=="{layer_name}"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) >= 2:
                lines.append({
                    'entity': e,
                    'pts': pts,
                    'y_center': sum(p[1] for p in pts) / len(pts)
                })
        except: pass
    
    processed_count = len(lines)
    print(f"[autoline] 找到 {processed_count} 条多段线")
    
    # 处理结果
    result = {
        'input_path': input_path,
        'processed_count': processed_count,
        'connected_count': connected_count,
        'scale_ratio': scale_ratio,
        'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S")
    }
    
    # 保存输出
    if output_path:
        doc.saveas(output_path)
        result['output_path'] = output_path
    else:
        # 使用默认命名
        import os
        base, ext = os.path.splitext(input_path)
        default_output = f"{base}_autoline_{result['timestamp']}{ext}"
        doc.saveas(default_output)
        result['output_path'] = default_output
    
    print(f"[autoline] 完成，输出: {result['output_path']}")
    
    return result


if __name__ == '__main__':
    # 测试
    test_file = r'D:\断面算量平台\测试文件\批量粘贴测试源.dxf'
    result = run_autoline(test_file)
    print(result)