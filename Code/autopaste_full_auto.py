# -*- coding: utf-8 -*-
"""
全自动粘贴模块 - 无参数自动检测源基点、目标基点，实现粘贴
融合autopaste_working.py和基点检测逻辑

测试文件：
- 源文件：批量粘贴_源文件.dxf（XSECTION图层）
- 目标文件：批量粘贴_目标文件.dxf（L1图层）
- 验证文件：批量粘贴_目标文件_已粘贴断面.dxf（正确粘贴效果）

代码位置: D:\断面算量平台\Code\autopaste_full_auto.py
"""

import ezdxf
import os
from datetime import datetime
from collections import defaultdict


# ============== 源文件基点检测（XSECTION图层） ==============

def get_bbox(entity):
    """获取实体边界框"""
    pts = [(p[0], p[1]) for p in entity.get_points()]
    xs = [pt[0] for pt in pts]
    ys = [pt[1] for pt in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def is_point_in_bbox(x, y, bbox):
    """检查点是否在边界框内"""
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]


def detect_source_small_rects(msp):
    """检测源文件的小矩形（内框）- 每个小矩形对应一个基点"""
    small_rects = []
    for e in msp.query('LWPOLYLINE[layer=="XSECTION"]'):
        try:
            pts = [(p[0], p[1]) for p in e.get_points()]
            if len(pts) >= 4:
                bbox = get_bbox(e)
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
                # 内框条件: 宽度 130-200, 高度 95-140
                if 130 < width < 200 and 95 <= height < 140:
                    # 计算基点：内框中心线与顶边交点
                    center_x = (bbox[0] + bbox[2]) / 2
                    top_y = bbox[3]  # 顶边Y坐标
                    small_rects.append({
                        'entity': e,
                        'bbox': bbox,
                        'basepoint': (center_x, top_y)
                    })
        except: pass
    
    # 按基点Y坐标排序（从上到下）
    small_rects.sort(key=lambda r: r['basepoint'][1], reverse=True)
    
    # 添加序号
    for i, rect in enumerate(small_rects):
        rect['index'] = i + 1
    
    return small_rects


def detect_source_basepoints(msp):
    """检测源文件基点（基于小矩形）"""
    small_rects = detect_source_small_rects(msp)
    
    basepoints = []
    for rect in small_rects:
        bp = rect['basepoint']
        basepoints.append({
            'x': bp[0],
            'y': bp[1],
            'section_index': rect['index'],
            'small_rect': rect
        })
    
    return basepoints


# ============== 目标文件基点检测（L1图层） ==============

def detect_target_l1_lines(msp):
    """检测目标文件L1图层的脊梁线"""
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
                        'x_max': max(x1, x2)
                    })
                elif height > width * 3:  # 垂直线
                    vertical_lines.append({
                        'x': (x1 + x2) / 2,
                        'y_min': min(y1, y2),
                        'y_max': max(y1, y2),
                        'y_center': (y1 + y2) / 2
                    })
                    
            elif e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                pts = [(p[0], p[1]) for p in e.get_points()]
                for i in range(len(pts) - 1):
                    x1, y1 = pts[i]
                    x2, y2 = pts[i + 1]
                    
                    width = abs(x2 - x1)
                    height = abs(y2 - y1)
                    
                    if width > height * 3:
                        horizontal_lines.append({
                            'y': (y1 + y2) / 2,
                            'x_min': min(x1, x2),
                            'x_max': max(x1, x2)
                        })
                    elif height > width * 3:
                        vertical_lines.append({
                            'x': (x1 + x2) / 2,
                            'y_min': min(y1, y2),
                            'y_max': max(y1, y2),
                            'y_center': (y1 + y2) / 2
                        })
        except: pass
    
    return horizontal_lines, vertical_lines


def detect_target_basepoints(msp):
    """检测目标文件基点（L1脊梁线交点）"""
    horizontal_lines, vertical_lines = detect_target_l1_lines(msp)
    
    # 按Y坐标排序
    horizontal_lines.sort(key=lambda l: l['y'], reverse=True)
    vertical_lines.sort(key=lambda l: l['x'])
    
    basepoints = []
    used_h_indices = set()
    
    for v_idx, v_line in enumerate(vertical_lines):
        v_x = v_line['x']
        v_y_center = v_line['y_center']
        
        # 找Y位置最接近的未使用水平线
        best_h_idx = -1
        best_y_diff = float('inf')
        
        for h_idx, h_line in enumerate(horizontal_lines):
            if h_idx in used_h_indices:
                continue
            
            y_diff = abs(h_line['y'] - v_y_center)
            if y_diff < best_y_diff:
                best_y_diff = y_diff
                best_h_idx = h_idx
        
        # 匹配成功
        if best_h_idx >= 0 and best_y_diff < 50:
            used_h_indices.add(best_h_idx)
            h_line = horizontal_lines[best_h_idx]
            
            basepoints.append({
                'x': v_x,
                'y': h_line['y'],
                'section_index': v_idx + 1,
                'v_line': v_line,
                'h_line': h_line
            })
    
    return basepoints


# ============== 自动粘贴核心逻辑 ==============

def get_entities_in_bbox(msp, bbox, layer_filter=None):
    """获取边界框内的所有实体"""
    entities = []
    
    query = 'LWPOLYLINE' if layer_filter else '*'
    if layer_filter:
        query = f'LWPOLYLINE[layer=="{layer_filter}"]'
    
    for e in msp.query(query):
        try:
            # 获取实体中心点
            if e.dxftype() == 'LWPOLYLINE':
                pts = [(p[0], p[1]) for p in e.get_points()]
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
            elif e.dxftype() == 'TEXT':
                cx, cy = e.dxf.insert.x, e.dxf.insert.y
            else:
                continue
            
            # 检查是否在框内
            if is_point_in_bbox(cx, cy, bbox):
                entities.append(e)
        except: pass
    
    return entities


def copy_entity_to_target(source_msp, target_msp, entity, offset_x, offset_y, target_layer='0-已粘贴断面'):
    """复制实体到目标文件，应用偏移"""
    if entity.dxftype() == 'LWPOLYLINE':
        pts = list(entity.get_points())
        new_pts = [(p[0] + offset_x, p[1] + offset_y) for p in pts]
        
        target_msp.add_lwpolyline(
            new_pts,
            dxfattribs={
                'layer': target_layer,
                'color': entity.dxf.color if hasattr(entity.dxf, 'color') else 0
            }
        )
        return True
    
    elif entity.dxftype() == 'TEXT':
        insert = entity.dxf.insert
        target_msp.add_text(
            entity.dxf.text,
            dxfattribs={
                'layer': target_layer,
                'insert': (insert.x + offset_x, insert.y + offset_y),
                'height': entity.dxf.height if hasattr(entity.dxf, 'height') else 2.5
            }
        )
        return True
    
    return False


def run_autopaste_full_auto(source_path, target_path, output_path=None):
    """全自动粘贴 - 无参数
    
    自动检测：
    1. 源文件类型和基点
    2. 目标文件类型和基点
    3. 源文件断面内容（小矩形内的断面线）
    4. 执行粘贴到目标基点
    
    Args:
        source_path: 源DXF文件路径
        target_path: 目标DXF文件路径
        output_path: 输出文件路径（可选）
    
    Returns:
        dict: 处理结果
    """
    print(f"\n{'='*60}")
    print(f"[autopaste] 全自动粘贴开始")
    print(f"{'='*60}")
    print(f"源文件: {source_path}")
    print(f"目标文件: {target_path}")
    
    # 加载文件
    source_doc = ezdxf.readfile(source_path)
    target_doc = ezdxf.readfile(target_path)
    
    source_msp = source_doc.modelspace()
    target_msp = target_doc.modelspace()
    
    # 检测源文件基点
    print(f"\n[检测源文件]")
    source_basepoints = detect_source_basepoints(source_msp)
    print(f"  小矩形数: {len(source_basepoints)}")
    print(f"  基点数: {len(source_basepoints)}")
    
    # 检测目标文件基点
    print(f"\n[检测目标文件]")
    target_basepoints = detect_target_basepoints(target_msp)
    print(f"  L1脊梁线交点数: {len(target_basepoints)}")
    
    # 匹配基点对
    print(f"\n[匹配基点]")
    matched_pairs = match_basepoints(source_basepoints, target_basepoints)
    print(f"  匹配对数: {len(matched_pairs)}")
    
    # 执行粘贴
    print(f"\n[执行粘贴]")
    pasted_count = 0
    
    # 创建输出图层
    output_layer = '0-已粘贴断面'
    if output_layer not in target_doc.layers:
        target_doc.layers.new(name=output_layer)
    
    for pair in matched_pairs:
        src_bp = pair['source']
        tgt_bp = pair['target']
        small_rect = src_bp['small_rect']
        
        # 计算偏移量
        offset_x = tgt_bp['x'] - src_bp['x']
        offset_y = tgt_bp['y'] - src_bp['y']
        
        # 获取小矩形内的断面曲线（顶点数>50，宽度>100，高度<50）
        rect_bbox = small_rect['bbox']
        rect_entity = small_rect['entity']
        
        # 查找断面曲线（复杂曲线，>50顶点）
        section_curve = None
        for e in source_msp.query('LWPOLYLINE[layer=="XSECTION"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) > 50:  # 复杂曲线特征
                    cx = sum(p[0] for p in pts) / len(pts)
                    cy = sum(p[1] for p in pts) / len(pts)
                    if is_point_in_bbox(cx, cy, rect_bbox):
                        section_curve = e
                        break
            except: pass
        
        # 复制断面曲线到目标位置
        if section_curve:
            if copy_entity_to_target(source_msp, target_msp, section_curve, offset_x, offset_y, output_layer):
                pasted_count += 1
    
    print(f"  粘贴实体数: {pasted_count}")
    
    # 保存输出
    if output_path is None:
        base, ext = os.path.splitext(target_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{base}_自动粘贴_{timestamp}{ext}"
    
    target_doc.saveas(output_path)
    print(f"\n[输出文件]: {output_path}")
    
    return {
        'source_path': source_path,
        'target_path': target_path,
        'output_path': output_path,
        'source_basepoints': len(source_basepoints),
        'target_basepoints': len(target_basepoints),
        'matched_pairs': len(matched_pairs),
        'pasted_entities': pasted_count
    }


def match_basepoints(source_bps, target_bps):
    """匹配源基点和目标基点
    
    按顺序匹配（都已按Y坐标排序）
    """
    pairs = []
    
    # 源基点按Y排序（从上到下）
    source_sorted = sorted(source_bps, key=lambda bp: bp['y'], reverse=True)
    
    # 目标基点按Y排序（从上到下）
    target_sorted = sorted(target_bps, key=lambda bp: bp['y'], reverse=True)
    
    # 按顺序一对一匹配
    for i in range(min(len(source_sorted), len(target_sorted))):
        pairs.append({
            'source': source_sorted[i],
            'target': target_sorted[i],
            'index': i + 1
        })
    
    return pairs


# ============== 验证对比 ==============

def verify_paste_result(output_path, reference_path):
    """验证粘贴结果与参考文件对比"""
    print(f"\n{'='*60}")
    print(f"[验证粘贴结果]")
    print(f"{'='*60}")
    
    output_doc = ezdxf.readfile(output_path)
    ref_doc = ezdxf.readfile(reference_path)
    
    output_msp = output_doc.modelspace()
    ref_msp = ref_doc.modelspace()
    
    # 统计图层实体数
    output_layer = '0-已粘贴断面'
    
    output_count = len(list(output_msp.query(f'*[layer=="{output_layer}"]')))
    ref_count = len(list(ref_msp.query(f'*[layer=="{output_layer}"]')))
    
    print(f"  输出文件 '{output_layer}': {output_count}个实体")
    print(f"  参考文件 '{output_layer}': {ref_count}个实体")
    
    if output_count == ref_count:
        print(f"  ✓ 实体数量匹配!")
    else:
        print(f"  ✗ 实体数量不匹配，差异: {output_count - ref_count}")
    
    return {
        'output_count': output_count,
        'reference_count': ref_count,
        'match': output_count == ref_count
    }


if __name__ == '__main__':
    # 测试文件路径
    test_dir = r'D:\\断面算量平台\\测试文件\\平台专用测试'
    
    source_file = os.path.join(test_dir, '批量粘贴_源文件.dxf')
    target_file = os.path.join(test_dir, '批量粘贴_目标文件.dxf')
    reference_file = os.path.join(test_dir, '批量粘贴_目标文件_已粘贴断面.dxf')
    
    # 执行全自动粘贴
    result = run_autopaste_full_auto(source_file, target_file)
    
    # 验证结果
    verify_result = verify_paste_result(result['output_path'], reference_file)
    
    # 输出总结
    print(f"\n{'='*60}")
    print(f"[总结]")
    print(f"{'='*60}")
    print(f"源基点: {result['source_basepoints']}")
    print(f"目标基点: {result['target_basepoints']}")
    print(f"匹配对数: {result['matched_pairs']}")
    print(f"粘贴实体: {result['pasted_entities']}")
    print(f"验证结果: {'通过' if verify_result['match'] else '失败'}")