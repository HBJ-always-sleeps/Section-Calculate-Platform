# -*- coding: utf-8 -*-
"""
目标文件L1基点标注脚本
检测并标注批量粘贴测试目标.dxf中所有L1脊梁线组和交点

代码位置: D:\断面算量平台\Code\annotate_target_l1.py
"""

import ezdxf
import os
from datetime import datetime


def detect_l1_groups(msp):
    """检测L1图层脊梁线组（使用一对一匹配）"""
    horizontal_lines = []
    vertical_lines = []
    
    for e in msp.query('*[layer=="L1"]'):
        try:
            if e.dxftype() == 'LINE':
                x1, y1 = e.dxf.start.x, e.dxf.start.y
                x2, y2 = e.dxf.end.x, e.dxf.end.y
                
                width = abs(x2 - x1)
                height = abs(y2 - y1)
                
                if width > height * 3:  # 水平线
                    horizontal_lines.append({
                        'y': (y1 + y2) / 2,
                        'x_min': min(x1, x2),
                        'x_max': max(x1, x2),
                        'length': width
                    })
                elif height > width * 3:  # 垂直线
                    vertical_lines.append({
                        'x': (x1 + x2) / 2,
                        'y_min': min(y1, y2),
                        'y_max': max(y1, y2),
                        'y_center': (y1 + y2) / 2,
                        'length': height
                    })
        except: pass
    
    # 按坐标排序
    horizontal_lines.sort(key=lambda l: l['y'], reverse=True)  # Y从上到下
    vertical_lines.sort(key=lambda l: l['x'])  # X从左到右
    
    # 使用一对一匹配（每个垂直线匹配最接近的水平线）
    groups = []
    used_h_indices = set()
    
    for v_idx, v_line in enumerate(vertical_lines):
        v_x = v_line['x']
        v_y_center = v_line['y_center']
        
        # 找Y最接近的未使用水平线
        best_h_idx = -1
        best_y_diff = float('inf')
        
        for h_idx, h_line in enumerate(horizontal_lines):
            if h_idx in used_h_indices:
                continue
            
            y_diff = abs(h_line['y'] - v_y_center)
            if y_diff < best_y_diff:
                best_y_diff = y_diff
                best_h_idx = h_idx
        
        # 匹配成功（Y差异小于阈值）
        if best_h_idx >= 0 and best_y_diff < 50:
            used_h_indices.add(best_h_idx)
            h_line = horizontal_lines[best_h_idx]
            
            groups.append({
                'h_line': h_line,
                'v_line': v_line,
                'y': h_line['y'],
                'x': v_x,
                'y_diff': best_y_diff
            })
    
    # 按Y从上到下排序
    groups.sort(key=lambda g: g['y'], reverse=True)
    
    return groups


def detect_all_intersections(msp):
    """检测所有L1脊梁线交点（一对一匹配）"""
    groups = detect_l1_groups(msp)
    
    intersections = []
    intersection_id = 1
    
    for group in groups:
        x = group['x']
        y = group['y']
        intersections.append({
            'x': x,
            'y': y,
            'id': intersection_id,
            'y_diff': group['y_diff']
        })
        intersection_id += 1
    
    return intersections, groups


def annotate_l1_basepoints(target_path, output_path=None):
    """标注目标文件所有L1基点和交点"""
    print(f"\n{'='*60}")
    print(f"[L1基点标注] 开始")
    print(f"{'='*60}")
    print(f"目标文件: {target_path}")
    
    # 加载文件
    target_doc = ezdxf.readfile(target_path)
    target_msp = target_doc.modelspace()
    
    # 检测交点和组
    intersections, groups = detect_all_intersections(target_msp)
    
    print(f"\n[检测结果]")
    print(f"  L1脊梁线组数: {len(groups)}")
    print(f"  总交点数: {len(intersections)}")
    
    # 显示前10个基点详情
    print(f"\n  前10个基点详情:")
    for i, group in enumerate(groups[:10]):
        print(f"    [{i+1}] X={group['x']:.2f}, Y={group['y']:.2f}, Y偏移={group['y_diff']:.2f}")
    
    # 创建标注图层
    annotation_layer = 'L1_BASEPOINT_ANNOTATION'
    if annotation_layer not in target_doc.layers:
        target_doc.layers.new(name=annotation_layer)
    
    # 标注所有交点
    print(f"\n[标注交点]")
    for bp in intersections:
        x, y = bp['x'], bp['y']
        
        # 绘制基点标记（圆圈）
        target_msp.add_circle(
            center=(x, y),
            radius=5,
            dxfattribs={'layer': annotation_layer, 'color': 1}
        )
        
        # 绘制十字标记
        marker_size = 3
        target_msp.add_line(
            start=(x - marker_size, y),
            end=(x + marker_size, y),
            dxfattribs={'layer': annotation_layer, 'color': 2}
        )
        target_msp.add_line(
            start=(x, y - marker_size),
            end=(x, y + marker_size),
            dxfattribs={'layer': annotation_layer, 'color': 2}
        )
        
        # 添加序号标注
        target_msp.add_text(
            f"#{bp['id']}",
            dxfattribs={
                'layer': annotation_layer,
                'insert': (x + 8, y + 8),
                'height': 3,
                'color': 3
            }
        )
    
    # 标注基点位置信息
    print(f"\n[标注完成]")
    
    # 保存输出
    if output_path is None:
        base, ext = os.path.splitext(target_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{base}_L1基点标注_{timestamp}{ext}"
    
    target_doc.saveas(output_path)
    
    print(f"\n[输出文件]: {output_path}")
    print(f"  总标注基点: {len(intersections)}")
    print(f"  脊梁线组: {len(groups)}")
    
    return {
        'output_path': output_path,
        'intersection_count': len(intersections),
        'group_count': len(groups),
        'groups': groups
    }


if __name__ == '__main__':
    test_dir = r'D:\断面算量平台\测试文件'
    target_file = os.path.join(test_dir, '批量粘贴测试目标.dxf')
    
    result = annotate_l1_basepoints(target_file)
    
    print(f"\n{'='*60}")
    print(f"[完成]")
    print(f"{'='*60}")
    print(f"输出: {result['output_path']}")
    print(f"基点数: {result['intersection_count']}")
    print(f"组数: {result['group_count']}")