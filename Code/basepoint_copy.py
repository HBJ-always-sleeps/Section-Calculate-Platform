# -*- coding: utf-8 -*-
"""
带基点复制脚本
测试文件: D:\tunnel_build\测试文件\源基点检测测试集.dxf

文件结构分析:
- LWPOLYLINE: 841个
- TEXT: 702个
- 颜色分布: 0=1410(随层), 5=117(蓝色), 1=15(红色), 3=1(绿色-基点连线)
- 图层: XSECTION=840, LABELS=702, 0=1

功能:
1. 检测断面框（大矩形）
2. 获取每个断面的桩号
3. 获取断面线主体（小矩形内的红/蓝线）
4. 检测基点位置
"""

import ezdxf
import re
from dataclasses import dataclass
from typing import List, Tuple, Optional

@dataclass
class SectionFrame:
    """断面框"""
    entity: object
    bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2)
    width: float
    height: float
    station: Optional[str] = None  # 桩号
    small_rect: Optional[object] = None  # 小矩形
    basepoint: Optional[Tuple[float, float]] = None  # 基点

def get_bbox(entity) -> Tuple[float, float, float, float]:
    """获取实体的边界框"""
    pts = list(entity.get_points())
    xs = [pt[0] for pt in pts]
    ys = [pt[1] for pt in pts]
    return (min(xs), min(ys), max(xs), max(ys))

def is_point_in_bbox(x: float, y: float, bbox: Tuple[float, float, float, float]) -> bool:
    """检查点是否在边界框内"""
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]

def detect_section_frames(msp) -> List[SectionFrame]:
    """检测断面框（外框）"""
    pls = [e for e in msp if e.dxftype() == 'LWPOLYLINE' and e.dxf.layer == 'XSECTION']
    
    frames = []
    for p in pls:
        pts = list(p.get_points())
        if len(pts) >= 4:
            bbox = get_bbox(p)
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            # 外框条件: 宽度 > 160 或 高度 > 140
            if width > 160 or height > 140:
                frames.append(SectionFrame(entity=p, bbox=bbox, width=width, height=height))
    
    return frames

def detect_small_rectangles(msp) -> List[Tuple[object, Tuple[float, float, float, float]]]:
    """检测小矩形（内框）"""
    pls = [e for e in msp if e.dxftype() == 'LWPOLYLINE' and e.dxf.layer == 'XSECTION']
    
    small_rects = []
    for p in pls:
        pts = list(p.get_points())
        if len(pts) >= 4:
            bbox = get_bbox(p)
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            # 内框条件: 宽度 130-200, 高度 95-140 (放宽范围以适应不同形态)
            if 130 < width < 200 and 95 <= height < 140:
                small_rects.append((p, bbox))
    
    return small_rects

def get_station_text(msp, frame: SectionFrame) -> Optional[str]:
    """获取断面框内的桩号文字"""
    texts = [e for e in msp if e.dxftype() == 'TEXT' and e.dxf.layer == 'LABELS']
    
    # 桩号格式: 数字+数字.TIN
    station_pattern = re.compile(r'^\d+\+\d+\.TIN$')
    
    for txt in texts:
        x, y = txt.dxf.insert[0], txt.dxf.insert[1]
        if is_point_in_bbox(x, y, frame.bbox):
            text = txt.dxf.text.strip()
            if station_pattern.match(text):
                return text
    
    return None

def find_small_rect_in_frame(frame: SectionFrame, small_rects: List) -> Optional[Tuple[object, Tuple[float, float, float, float]]]:
    """找到断面框内的小矩形"""
    for rect, bbox in small_rects:
        # 检查小矩形中心是否在断面框内
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        if is_point_in_bbox(cx, cy, frame.bbox):
            return (rect, bbox)
    return None

def find_intersection_in_frame(msp, frame: SectionFrame, small_rect_bbox: Tuple[float, float, float, float]) -> Optional[Tuple[float, float]]:
    """在断面框内找到断面线的交点作为基点
    
    基点特征：中上部的交点，通常是多段线顶点的交汇处
    """
    # 获取断面框内的所有多段线
    pls = [e for e in msp if e.dxftype() == 'LWPOLYLINE' and e.dxf.layer == 'XSECTION']
    
    # 收集所有顶点
    all_vertices = []
    for p in pls:
        pts = list(p.get_points())
        for pt in pts:
            # 只收集在断面框内且在内框上方的点
            if is_point_in_bbox(pt[0], pt[1], frame.bbox):
                # 在内框顶部区域（内框顶边上方一定范围）
                if pt[1] > small_rect_bbox[1]:  # Y坐标大于内框底边
                    all_vertices.append((pt[0], pt[1]))
    
    if not all_vertices:
        return None
    
    # 寻找顶点密集区域（交点附近会有多个顶点聚集）
    # 统计每个顶点附近的点数
    cluster_radius = 3.0  # 聚类半径
    
    # 按Y坐标分组，找中上部的点
    y_values = sorted(set(v[1] for v in all_vertices))
    
    # 找到最上方的Y坐标群（内框顶边附近）
    top_y = small_rect_bbox[3]  # 内框顶边
    upper_vertices = [v for v in all_vertices if v[1] >= top_y - 20]
    
    if not upper_vertices:
        return None
    
    # 在中上部区域找X方向的聚类中心
    frame_center_x = (frame.bbox[0] + frame.bbox[2]) / 2
    
    # 找最接近中心线的顶点聚类
    center_vertices = sorted(upper_vertices, key=lambda v: abs(v[0] - frame_center_x))
    
    # 取前几个最接近中心的顶点，计算它们的平均位置
    candidate_count = min(10, len(center_vertices))
    candidates = center_vertices[:candidate_count]
    
    if candidates:
        avg_x = sum(v[0] for v in candidates) / len(candidates)
        avg_y = sum(v[1] for v in candidates) / len(candidates)
        return (avg_x, avg_y)
    
    return None

def calculate_basepoint(frame: SectionFrame, small_rect_bbox: Tuple[float, float, float, float]) -> Optional[Tuple[float, float]]:
    """计算基点位置：断面框中心线(X方向中点)与小矩形顶边的交点（已弃用，改用交点检测）"""
    # 断面框X方向中点
    frame_center_x = (frame.bbox[0] + frame.bbox[2]) / 2
    # 小矩形顶边Y坐标（Y值最大，因为Y向下为负）
    top_y = small_rect_bbox[3]  # max Y
    
    return (frame_center_x, top_y)

def get_reference_basepoints(msp) -> List[Tuple[float, float]]:
    """获取参考基点（绿色多段线的顶点）"""
    green_pls = [e for e in msp if e.dxftype() == 'LWPOLYLINE' 
                 and hasattr(e.dxf, 'color') and e.dxf.color == 3]
    
    basepoints = []
    for pl in green_pls:
        pts = list(pl.get_points())
        for pt in pts:
            basepoints.append((pt[0], pt[1]))
    
    return basepoints

def distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """计算两点距离"""
    return ((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)**0.5

def analyze_dxf(filepath):
    """分析DXF文件"""
    print(f"Analyzing: {filepath}")
    print("=" * 60)
    
    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()
    
    # 1. 检测断面框
    frames = detect_section_frames(msp)
    print(f"Detected {len(frames)} section frames")
    
    # 2. 检测小矩形
    small_rects = detect_small_rectangles(msp)
    print(f"Detected {len(small_rects)} small rectangles")
    
    # 3. 获取参考基点
    ref_basepoints = get_reference_basepoints(msp)
    print(f"Reference basepoints: {len(ref_basepoints)}")
    
    # 4. 处理每个断面框
    print("\n" + "=" * 60)
    print("Section Analysis:")
    print("=" * 60)
    
    matched = 0
    sections_with_basepoint = []
    for i, frame in enumerate(frames):
        # 获取桩号
        station = get_station_text(msp, frame)
        frame.station = station
        
        # 找小矩形
        small_rect_info = find_small_rect_in_frame(frame, small_rects)
        if small_rect_info:
            frame.small_rect = small_rect_info[0]
            small_rect_bbox = small_rect_info[1]
            
            # 计算基点
            frame.basepoint = calculate_basepoint(frame, small_rect_bbox)
        
        # 输出结果
        print(f"\nFrame {i+1}:")
        print(f"  BBox: ({frame.bbox[0]:.1f}, {frame.bbox[1]:.1f}) - ({frame.bbox[2]:.1f}, {frame.bbox[3]:.1f})")
        print(f"  Station: {frame.station or 'N/A'}")
        if frame.basepoint:
            print(f"  Calculated Basepoint: ({frame.basepoint[0]:.2f}, {frame.basepoint[1]:.2f})")
            
            # 查找最近的参考基点（如果有）
            if ref_basepoints:
                min_dist = float('inf')
                nearest_ref = None
                for ref in ref_basepoints:
                    d = distance(frame.basepoint, ref)
                    if d < min_dist:
                        min_dist = d
                        nearest_ref = ref
                
                print(f"  Nearest Reference: ({nearest_ref[0]:.2f}, {nearest_ref[1]:.2f})")
                print(f"  Distance: {min_dist:.2f}")
                
                if min_dist < 5:  # 5单位容差
                    matched += 1
                    print(f"  Status: MATCHED")
                    sections_with_basepoint.append(frame)
                else:
                    print(f"  Status: MISMATCH")
            else:
                # 没有参考基点，直接接受计算结果
                matched += 1
                sections_with_basepoint.append(frame)
                print(f"  Status: DETECTED (no reference)")
        else:
            print(f"  No basepoint detected (no inner frame found)")
    
    print("\n" + "=" * 60)
    print(f"Summary: {matched}/{len(frames)} basepoints matched")
    print(f"Sections with valid basepoint: {len(sections_with_basepoint)}")
    print("=" * 60)
    
    return frames, sections_with_basepoint

def analyze_frame_contents(msp, frame: SectionFrame):
    """分析断面框内的所有实体"""
    pls = [e for e in msp if e.dxftype() == 'LWPOLYLINE' and e.dxf.layer == 'XSECTION']
    
    inner_entities = []
    for p in pls:
        pts = list(p.get_points())
        if len(pts) >= 2:
            # 检查是否在框内
            cx = sum(pt[0] for pt in pts) / len(pts)
            cy = sum(pt[1] for pt in pts) / len(pts)
            if is_point_in_bbox(cx, cy, frame.bbox):
                bbox = get_bbox(p)
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
                # 排除外框本身
                if width < frame.width - 10 or height < frame.height - 10:
                    inner_entities.append({
                        'entity': p,
                        'bbox': bbox,
                        'width': width,
                        'height': height,
                        'pts_count': len(pts),
                        'color': p.dxf.color if hasattr(p.dxf, 'color') else 0
                    })
    
    return inner_entities

def mark_basepoints(filepath, output_path=None):
    """在DXF文件中标注基点"""
    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()
    
    # 检测断面框和小矩形
    frames = detect_section_frames(msp)
    small_rects = detect_small_rectangles(msp)
    
    # 处理每个断面框
    marked_count = 0
    for frame in frames:
        station = get_station_text(msp, frame)
        frame.station = station
        
        small_rect_info = find_small_rect_in_frame(frame, small_rects)
        if small_rect_info:
            frame.small_rect = small_rect_info[0]
            small_rect_bbox = small_rect_info[1]
            frame.basepoint = calculate_basepoint(frame, small_rect_bbox)
            
            # 在基点位置画一个红色圆圈标记
            if frame.basepoint:
                x, y = frame.basepoint
                msp.add_circle(
                    center=(x, y),
                    radius=3,
                    dxfattribs={'color': 1}  # 红色
                )
                # 添加十字标记
                msp.add_line((x-5, y), (x+5, y), dxfattribs={'color': 1})
                msp.add_line((x, y-5), (x, y+5), dxfattribs={'color': 1})
                marked_count += 1
    
    # 保存文件
    if output_path is None:
        import os
        base, ext = os.path.splitext(filepath)
        output_path = f"{base}_基点标注{ext}"
    
    doc.saveas(output_path)
    print(f"Saved: {output_path}")
    print(f"Marked {marked_count} basepoints")
    
    return marked_count

def build_vertex_grid(msp) -> dict:
    """预先构建所有多段线顶点的网格索引"""
    pls = list(e for e in msp if e.dxftype() == 'LWPOLYLINE' and e.dxf.layer == 'XSECTION')
    
    grid_size = 5.0  # 网格大小
    grid = {}
    
    for p in pls:
        pts = list(p.get_points())
        for pt in pts:
            gx = int(pt[0] / grid_size)
            gy = int(pt[1] / grid_size)
            key = (gx, gy)
            if key not in grid:
                grid[key] = []
            grid[key].append((pt[0], pt[1]))
    
    return grid, grid_size

def get_vertices_in_bbox(grid, grid_size, bbox) -> List[Tuple[float, float]]:
    """快速获取边界框内的所有顶点"""
    gx1 = int(bbox[0] / grid_size)
    gy1 = int(bbox[1] / grid_size)
    gx2 = int(bbox[2] / grid_size) + 1
    gy2 = int(bbox[3] / grid_size) + 1
    
    vertices = []
    for gx in range(gx1, gx2 + 1):
        for gy in range(gy1, gy2 + 1):
            key = (gx, gy)
            if key in grid:
                for v in grid[key]:
                    if bbox[0] <= v[0] <= bbox[2] and bbox[1] <= v[1] <= bbox[3]:
                        vertices.append(v)
    
    return vertices

def find_nearest_intersection(grid, grid_size, base_x: float, base_y: float, search_radius: float = 20.0) -> Optional[Tuple[float, float]]:
    """在基础基点位置附近找最近的交点（顶点聚类）
    
    Args:
        grid: 顶点网格索引
        grid_size: 网格大小
        base_x: 基础基点X坐标
        base_y: 基础基点Y坐标
        search_radius: 搜索半径
    
    Returns:
        最近交点坐标，如果没有找到返回None
    """
    # 计算搜索范围
    gx1 = int((base_x - search_radius) / grid_size)
    gy1 = int((base_y - search_radius) / grid_size)
    gx2 = int((base_x + search_radius) / grid_size) + 1
    gy2 = int((base_y + search_radius) / grid_size) + 1
    
    # 收集搜索范围内的顶点
    vertices = []
    for gx in range(gx1, gx2 + 1):
        for gy in range(gy1, gy2 + 1):
            key = (gx, gy)
            if key in grid:
                for v in grid[key]:
                    # 检查是否在搜索半径内
                    dist = ((v[0] - base_x)**2 + (v[1] - base_y)**2)**0.5
                    if dist <= search_radius:
                        vertices.append(v)
    
    if not vertices:
        return None
    
    # 使用网格聚类找交点
    cluster_grid_size = 2.0
    cluster_grid = {}
    
    for v in vertices:
        gx = round(v[0] / cluster_grid_size)
        gy = round(v[1] / cluster_grid_size)
        key = (gx, gy)
        if key not in cluster_grid:
            cluster_grid[key] = []
        cluster_grid[key].append(v)
    
    # 找聚类中心
    clusters = []
    for key, verts in cluster_grid.items():
        if len(verts) >= 2:  # 至少2个顶点才算交点
            avg_x = sum(v[0] for v in verts) / len(verts)
            avg_y = sum(v[1] for v in verts) / len(verts)
            count = len(verts)
            # 计算到基础基点的距离
            dist = ((avg_x - base_x)**2 + (avg_y - base_y)**2)**0.5
            clusters.append((avg_x, avg_y, count, dist))
    
    if not clusters:
        # 如果没有聚类，返回最近的顶点
        nearest = min(vertices, key=lambda v: ((v[0] - base_x)**2 + (v[1] - base_y)**2)**0.5)
        return nearest
    
    # 选择最近的聚类中心（优先距离近，其次顶点多）
    clusters.sort(key=lambda c: (c[3], -c[2]))  # 按距离升序，顶点数降序
    best = clusters[0]
    
    return (best[0], best[1])

def find_slope_tops_in_frame(grid, grid_size, frame: SectionFrame, small_rect_bbox: Tuple[float, float, float, float]) -> List[Tuple[float, float]]:
    """找到航道底斜线顶端点
    
    关键发现：
    红线文件斜线顶端: 左X=15.2, 右X=156.8, 中点=(15.2+156.8)/2=86.0
    这些顶端点的Y坐标正好在内框顶边附近（Y≈内框顶边）
    
    所以算法改为：
    1. 在内框顶边附近搜索顶点
    2. 找左右两侧最远的顶点作为斜线顶端
    3. 计算中点作为基点X
    """
    inner_top = small_rect_bbox[3]  # 内框顶边Y
    inner_left = small_rect_bbox[0]
    inner_right = small_rect_bbox[2]
    inner_center = (inner_left + inner_right) / 2
    
    # 搜索范围：内框顶边附近（上下10单位）
    search_bbox = (frame.bbox[0], inner_top - 10, frame.bbox[2], inner_top + 10)
    
    # 获取该区域的所有顶点
    vertices = get_vertices_in_bbox(grid, grid_size, search_bbox)
    
    if not vertices:
        return []
    
    # 按X坐标分成左右两组
    left_vertices = [v for v in vertices if v[0] < inner_center]
    right_vertices = [v for v in vertices if v[0] >= inner_center]
    
    slope_tops = []
    
    # 左侧：找最左边的点（斜线顶端应该在边缘）
    if left_vertices:
        left_top = min(left_vertices, key=lambda v: v[0])  # 最左边
        slope_tops.append(left_top)
    
    # 右侧：找最右边的点
    if right_vertices:
        right_top = max(right_vertices, key=lambda v: v[0])  # 最右边
        slope_tops.append(right_top)
    
    return slope_tops

def calculate_basepoint_with_intersection(grid, grid_size, frame: SectionFrame, small_rect_bbox: Tuple[float, float, float, float]) -> Optional[Tuple[float, float]]:
    """计算基点位置：用航道底斜线顶端中点确定X坐标
    
    核心思路：
    航道底是倒梯形，两条斜线的顶端中点就是正确的基点X坐标
    这个位置在不同文件中应该是一致的
    
    步骤：
    1. 找到航道底斜线的顶端点
    2. 计算左右斜线顶端的中点作为基点X
    3. Y坐标使用内框顶边
    """
    # 方法1：用斜线顶端中点（最可靠）
    slope_tops = find_slope_tops_in_frame(grid, grid_size, frame, small_rect_bbox)
    
    if len(slope_tops) >= 2:
        # 计算中点
        base_x = (slope_tops[0][0] + slope_tops[1][0]) / 2
        top_y = small_rect_bbox[3]  # 内框顶边Y坐标
        
        # 找最近的交点
        nearest_intersection = find_nearest_intersection(grid, grid_size, base_x, top_y, search_radius=15.0)
        
        if nearest_intersection:
            return nearest_intersection
        
        return (base_x, top_y)
    
    # 方法2：使用内框中心线（备选）
    inner_center_x = (small_rect_bbox[0] + small_rect_bbox[2]) / 2
    top_y = small_rect_bbox[3]
    
    # 找最近的交点
    nearest_intersection = find_nearest_intersection(grid, grid_size, inner_center_x, top_y, search_radius=15.0)
    
    if nearest_intersection:
        return nearest_intersection
    
    return (inner_center_x, top_y)

def batch_analyze(filepaths, verbose=False):
    """批量分析多个文件"""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    for filepath in filepaths:
        print("\n" + "=" * 70)
        print(f"FILE: {filepath}")
        print("=" * 70)
        
        try:
            doc = ezdxf.readfile(filepath)
            msp = doc.modelspace()
            
            # 检测
            frames = detect_section_frames(msp)
            small_rects = detect_small_rectangles(msp)
            
            print(f"Detected {len(frames)} section frames")
            print(f"Detected {len(small_rects)} small rectangles")
            
            # 预先构建顶点网格索引
            grid, grid_size = build_vertex_grid(msp)
            print(f"Built vertex grid with {len(grid)} cells")
            
            # 处理每个断面框
            marked_count = 0
            no_basepoint_count = 0
            sections_with_basepoint = []
            
            for frame in frames:
                station = get_station_text(msp, frame)
                frame.station = station
                
                small_rect_info = find_small_rect_in_frame(frame, small_rects)
                if small_rect_info:
                    small_rect_bbox = small_rect_info[1]
                    # 使用中心线+内框顶边交点，再找最近交点
                    frame.basepoint = calculate_basepoint_with_intersection(grid, grid_size, frame, small_rect_bbox)
                    
                    if frame.basepoint:
                        sections_with_basepoint.append(frame)
                        marked_count += 1
                        
                        if verbose and marked_count <= 5:
                            print(f"  {station}: ({frame.basepoint[0]:.2f}, {frame.basepoint[1]:.2f})")
                    else:
                        no_basepoint_count += 1
                else:
                    no_basepoint_count += 1
            
            print(f"\nBasepoints detected: {marked_count}/{len(frames)}")
            if no_basepoint_count > 0:
                print(f"Frames without basepoint: {no_basepoint_count}")
            
            # 标注基点
            import os
            base, ext = os.path.splitext(filepath)
            output_path = f"{base}_基点标注_{timestamp}{ext}"
            
            for frame in sections_with_basepoint:
                if frame.basepoint:
                    x, y = frame.basepoint
                    msp.add_circle(center=(x, y), radius=3, dxfattribs={'color': 1})
                    msp.add_line((x-5, y), (x+5, y), dxfattribs={'color': 1})
                    msp.add_line((x, y-5), (x, y+5), dxfattribs={'color': 1})
            
            doc.saveas(output_path)
            print(f"Saved: {output_path}")
            
        except Exception as e:
            import traceback
            print(f"Error: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    # 测试文件列表
    test_files = [
        r"D:\tunnel_build\测试文件\蓝线源文件.dxf",
        r"D:\tunnel_build\测试文件\批量粘贴测试源.dxf",
    ]
    
    batch_analyze(test_files, verbose=True)