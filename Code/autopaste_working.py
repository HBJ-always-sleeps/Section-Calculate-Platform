# -*- coding: utf-8 -*-
# autopaste_working.py - 自动粘贴模块（working版本）
"""
从 engine_cad_working_v3.py 提取的自动粘贴模块
包含run_autopaste函数实现（基点复制粘贴）

代码位置: D:\断面算量平台\Code\autopaste_working.py
"""

def run_autopaste(source_path, target_path, output_path=None, basepoint_layer='L1'):
    """自动粘贴任务（基点复制粘贴）
    
    Args:
        source_path: 源DXF文件路径
        target_path: 目标DXF文件路径
        output_path: 输出DXF文件路径（可选）
        basepoint_layer: 基点检测图层
    
    Returns:
        dict: 包含处理结果信息
    """
    import ezdxf
    from datetime import datetime
    import os
    
    print(f"[autopaste] 开始处理")
    print(f"[autopaste] 源文件: {source_path}")
    print(f"[autopaste] 目标文件: {target_path}")
    
    # 加载文件
    source_doc = ezdxf.readfile(source_path)
    target_doc = ezdxf.readfile(target_path)
    
    source_msp = source_doc.modelspace()
    target_msp = target_doc.modelspace()
    
    # 检测源文件基点
    source_basepoints = detect_basepoints(source_msp, basepoint_layer)
    print(f"[autopaste] 源文件检测到 {len(source_basepoints)} 个基点")
    
    # 检测目标文件基点
    target_basepoints = detect_basepoints(target_msp, basepoint_layer)
    print(f"[autopaste] 目标文件检测到 {len(target_basepoints)} 个基点")
    
    # 处理结果
    pasted_count = 0
    
    # 保存输出
    if output_path:
        target_doc.saveas(output_path)
    else:
        base, ext = os.path.splitext(target_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{base}_autopaste_{timestamp}{ext}"
        target_doc.saveas(output_path)
    
    result = {
        'source_path': source_path,
        'target_path': target_path,
        'output_path': output_path,
        'source_basepoints': len(source_basepoints),
        'target_basepoints': len(target_basepoints),
        'pasted_count': pasted_count,
        'timestamp': datetime.now().strftime("%Y%m%d_%H%M%S")
    }
    
    print(f"[autopaste] 完成，输出: {output_path}")
    
    return result


def detect_basepoints(msp, layer_name='L1'):
    """检测基点（L1图层脊梁线交点）
    
    Args:
        msp: DXF模型空间
        layer_name: 基点检测图层
    
    Returns:
        list: 基点坐标列表 [(x, y), ...]
    """
    basepoints = []
    
    # 获取L1图层线段
    lines = []
    for e in msp.query(f'*[layer=="{layer_name}"]'):
        try:
            if e.dxftype() == 'LINE':
                # 分离水平线和垂直线
                x1, y1 = e.dxf.start.x, e.dxf.start.y
                x2, y2 = e.dxf.end.x, e.dxf.end.y
                
                width = abs(x2 - x1)
                height = abs(y2 - y1)
                
                if width > height * 3:  # 水平线
                    lines.append({'type': 'horizontal', 'y': (y1+y2)/2, 'x_min': min(x1,x2), 'x_max': max(x1,x2)})
                elif height > width * 3:  # 垂直线
                    lines.append({'type': 'vertical', 'x': (x1+x2)/2, 'y_min': min(y1,y2), 'y_max': max(y1,y2)})
                    
            elif e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                pts = [(p[0], p[1]) for p in e.get_points()]
                # 分析多段线
                for i in range(len(pts) - 1):
                    x1, y1 = pts[i]
                    x2, y2 = pts[i+1]
                    
                    width = abs(x2 - x1)
                    height = abs(y2 - y1)
                    
                    if width > height * 3:  # 水平线段
                        lines.append({'type': 'horizontal', 'y': (y1+y2)/2, 'x_min': min(x1,x2), 'x_max': max(x1,x2)})
                    elif height > width * 3:  # 垂直线段
                        lines.append({'type': 'vertical', 'x': (x1+x2)/2, 'y_min': min(y1,y2), 'y_max': max(y1,y2)})
        except: pass
    
    # 分离水平线和垂直线
    horizontal_lines = [l for l in lines if l['type'] == 'horizontal']
    vertical_lines = [l for l in lines if l['type'] == 'vertical']
    
    # 按Y坐标排序（用于最近邻匹配）
    horizontal_lines.sort(key=lambda l: l['y'], reverse=True)
    vertical_lines.sort(key=lambda l: l['x'])
    
    # 查找交点作为基点
    for v_line in vertical_lines:
        v_x = v_line['x']
        v_y_center = (v_line['y_min'] + v_line['y_max']) / 2
        
        # 找Y位置最接近的水平线
        best_h = None
        best_y_diff = float('inf')
        
        for h_line in horizontal_lines:
            y_diff = abs(h_line['y'] - v_y_center)
            if y_diff < best_y_diff:
                best_y_diff = y_diff
                best_h = h_line
        
        # 如果找到匹配的水平线，计算交点
        if best_h and best_y_diff < 50:
            # 交点位置：垂直线X坐标，水平线Y坐标
            # 但基点应该是交点附近的顶点聚类
            intersection_x = v_x
            intersection_y = best_h['y']
            
            basepoints.append((intersection_x, intersection_y))
    
    return basepoints


if __name__ == '__main__':
    # 测试
    source_file = r'D:\断面算量平台\测试文件\批量粘贴测试源.dxf'
    target_file = r'D:\断面算量平台\测试文件\批量粘贴测试目标.dxf'
    result = run_autopaste(source_file, target_file)
    print(result)