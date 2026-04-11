# -*- coding: utf-8 -*-
"""
航道三维模型工程几何驱动版本 V2 - 深度修复版

核心改进：
1. 鲁棒的梯形槽拆分：基于DMX底角横坐标投影拆分超挖线（不再用min_z容差）
2. 地质体顶点等步长重采样：固定64个点，以质心为原点按极角排序
3. 形状相似性检查：面积变化超过80%则断开
4. 顶点数优化：超挖ribbon采样50点，地质体64点

作者: @黄秉俊
日期: 2026-04-02
"""

import json
import numpy as np
import os
from typing import List, Dict, Tuple, Optional
import math
import sys

# 添加Code目录到路径
sys.path.insert(0, r'D:\断面算量平台\Code')

# shapely延迟导入
SHAPELY_AVAILABLE = None


def check_shapely():
    """延迟检查shapely是否可用"""
    global SHAPELY_AVAILABLE
    if SHAPELY_AVAILABLE is None:
        try:
            from shapely.geometry import Polygon
            SHAPELY_AVAILABLE = True
        except ImportError:
            SHAPELY_AVAILABLE = False
    return SHAPELY_AVAILABLE


# ==================== 地层分类 ====================

LAYER_CATEGORIES = {
    'mud_fill': {
        'name_cn': '淤泥与填土',
        'color': '#7f8c8d',
        'layers': ['1级淤泥', '2级淤泥', '3级淤泥', '4级淤泥', '1级填土', '2级填土', '3级填土', '4级填土'],
    },
    'clay': {
        'name_cn': '黏土',
        'color': '#A52A2A',
        'layers': ['3级黏土', '4级黏土', '5级黏土'],
    },
    'sand_and_gravel': {
        'name_cn': '砂与碎石类',
        'color': '#f1c40f',
        'layers': ['6级砂', '7级砂', '8级砂', '9级砂', '10级砂', '6级碎石', '9级碎石'],
    }
}


def categorize_layer(layer_name: str) -> Optional[str]:
    """将原始层名映射到分类类别"""
    for cat_key, cat_info in LAYER_CATEGORIES.items():
        if layer_name in cat_info['layers']:
            return cat_key
    return None


def load_metadata(json_path: str) -> Dict:
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_spine_matches(json_path: str) -> Dict:
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def transform_to_spine_aligned(cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle):
    """坐标转换：CAD局部坐标 -> 工程坐标"""
    z = cad_y - ref_y
    dx = cad_x - ref_x
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    rotated_dx = dx * cos_a
    rotated_dy = dx * sin_a
    eng_x = spine_x + rotated_dx
    eng_y = spine_y + rotated_dy
    return eng_x, eng_y, z


# ==================== 核心算法：深度修复版 ====================

def get_dmx_bottom_endpoints(dmx_pts: np.ndarray) -> Tuple[float, float]:
    """
    提取DMX线的底角横坐标
    DMX是设计断面线，底部两个端点定义了航道底宽
    
    Args:
        dmx_pts: (N, 3) array of DMX points
    
    Returns:
        (x_min, x_max): 底角横坐标范围
    """
    if len(dmx_pts) < 2:
        return (0, 0)
    
    # 找Z值最低的点作为底板区域
    z_coords = dmx_pts[:, 2]
    min_z = np.min(z_coords)
    
    # 容差0.5m，识别底板区域
    bottom_mask = z_coords < (min_z + 0.5)
    bottom_indices = np.where(bottom_mask)[0]
    
    if len(bottom_indices) < 2:
        # 如果只有一个最低点，取整体X范围
        return (np.min(dmx_pts[:, 0]), np.max(dmx_pts[:, 0]))
    
    # 取底板区域的X范围
    bottom_x = dmx_pts[bottom_mask, 0]
    return (np.min(bottom_x), np.max(bottom_x))


def split_overbreak_robustly(overbreak_pts: np.ndarray, dmx_x_range: Tuple[float, float],
                              buffer_m: float = 0.5) -> Dict[str, np.ndarray]:
    """
    利用DMX线的底角位置作为参照，精准拆分超挖线
    
    Args:
        overbreak_pts: (N, 3) array of overbreak points
        dmx_x_range: (x_min, x_max) from DMX bottom endpoints
        buffer_m: 缓冲区宽度（米），确保坡脚点被包含在底板内
    
    Returns:
        dict with 'left', 'bottom', 'right' segments
    """
    pts = np.array(overbreak_pts)
    if len(pts) < 3:
        return {'left': pts, 'bottom': pts, 'right': pts}
    
    x_min, x_max = dmx_x_range
    
    # 增加缓冲区，确保坡脚点被包含在底板内
    left_boundary = x_min - buffer_m
    right_boundary = x_max + buffer_m
    
    # 分段掩码
    left_mask = pts[:, 0] <= left_boundary
    right_mask = pts[:, 0] >= right_boundary
    bottom_mask = (pts[:, 0] > left_boundary) & (pts[:, 0] < right_boundary)
    
    # 提取各段
    left_slope = pts[left_mask]
    bottom_plate = pts[bottom_mask]
    right_slope = pts[right_mask]
    
    # 确保衔接点存在（避免缝隙）
    # 找到左坡最右侧点和底板最左侧点
    if len(left_slope) > 0 and len(bottom_plate) > 0:
        left_rightmost = left_slope[np.argmax(left_slope[:, 0])]
        bottom_leftmost = bottom_plate[np.argmin(bottom_plate[:, 0])]
        # 添加衔接点
        if not np.allclose(left_rightmost, bottom_leftmost):
            bottom_plate = np.vstack([left_rightmost, bottom_plate])
    
    if len(right_slope) > 0 and len(bottom_plate) > 0:
        right_leftmost = right_slope[np.argmin(right_slope[:, 0])]
        bottom_rightmost = bottom_plate[np.argmax(bottom_plate[:, 0])]
        if not np.allclose(right_leftmost, bottom_rightmost):
            bottom_plate = np.vstack([bottom_plate, right_leftmost])
    
    return {
        'left': left_slope,
        'bottom': bottom_plate,
        'right': right_slope
    }


def resample_polygon_equidistant(points: np.ndarray, n_samples: int = 64) -> np.ndarray:
    """
    将地质多边形归一化为固定点数，解决蒙皮扭曲和锯齿
    使用shapely的等距离重采样
    
    Args:
        points: (N, 2) or (N, 3) array of polygon vertices
        n_samples: 目标采样点数
    
    Returns:
        (n_samples, 2) or (n_samples, 3) resampled points
    """
    if len(points) < 3:
        return points
    
    is_3d = points.shape[1] == 3
    
    if not check_shapely():
        # shapely不可用，使用简化版本
        return _resample_polygon_simple(points, n_samples)
    
    from shapely.geometry import Polygon, LineString
    
    try:
        # 创建闭合多边形
        if is_3d:
            # 使用XZ平面（X为宽度，Z为高程）
            pts_2d = points[:, [0, 2]]
        else:
            pts_2d = points
        
        # 确保闭合
        if not np.allclose(pts_2d[0], pts_2d[-1]):
            pts_2d = np.vstack([pts_2d, pts_2d[0]])
        
        poly = Polygon(pts_2d)
        
        if not poly.is_valid:
            # 修复无效多边形
            poly = poly.buffer(0)
        
        if poly.is_empty:
            return points
        
        # 等距离重采样
        distances = np.linspace(0, poly.exterior.length, n_samples, endpoint=False)
        resampled_2d = np.array([poly.exterior.interpolate(d).coords[0] for d in distances])
        
        if is_3d:
            # 恢复Y坐标（里程）
            # 使用原始点的平均Y值
            avg_y = np.mean(points[:, 1])
            resampled_3d = np.zeros((n_samples, 3))
            resampled_3d[:, 0] = resampled_2d[:, 0]  # X
            resampled_3d[:, 1] = avg_y  # Y (里程)
            resampled_3d[:, 2] = resampled_2d[:, 1]  # Z
            return resampled_3d
        else:
            return resampled_2d
            
    except Exception as e:
        return _resample_polygon_simple(points, n_samples)


def _resample_polygon_simple(points: np.ndarray, n_samples: int) -> np.ndarray:
    """简化版多边形重采样（不依赖shapely）"""
    if len(points) < 3:
        return points
    
    # 确保闭合
    pts = np.array(points)
    if not np.allclose(pts[0], pts[-1]):
        pts = np.vstack([pts, pts[0]])
    
    # 计算累积弧长
    diff = np.diff(pts, axis=0)
    dist = np.sqrt((diff**2).sum(axis=1))
    s = np.concatenate(([0], np.cumsum(dist)))
    
    if s[-1] == 0:
        return np.tile(pts[0], (n_samples, 1))
    
    # 等弧长采样
    target_s = np.linspace(0, s[-1], n_samples, endpoint=False)
    resampled = np.zeros((n_samples, pts.shape[1]))
    for i in range(pts.shape[1]):
        resampled[:, i] = np.interp(target_s, s, pts[:, i])
    
    return resampled


def normalize_polygon_orientation(points: np.ndarray) -> np.ndarray:
    """
    统一多边形绕向（逆时针）并将最左侧点作为起点
    防止三维蒙皮扭曲
    
    Args:
        points: (N, 2) or (N, 3) array
    
    Returns:
        normalized points
    """
    if len(points) < 3:
        return points
    
    pts = np.array(points)
    is_3d = pts.shape[1] == 3
    
    # 计算有向面积（使用XZ平面）
    if is_3d:
        x_idx, z_idx = 0, 2
    else:
        x_idx, z_idx = 0, 1
    
    area = 0
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        area += pts[i, x_idx] * pts[j, z_idx] - pts[j, x_idx] * pts[i, z_idx]
    
    # 如果面积为负（顺时针），翻转
    if area < 0:
        pts = pts[::-1]
    
    # 找最左侧点作为起点
    min_idx = np.argmin(pts[:, x_idx])
    pts = np.roll(pts, -min_idx, axis=0)
    
    return pts


def calculate_polygon_area(points: np.ndarray) -> float:
    """
    计算多边形面积（使用XZ平面）
    
    Args:
        points: (N, 2) or (N, 3) array
    
    Returns:
        area (absolute value)
    """
    if len(points) < 3:
        return 0.0
    
    pts = np.array(points)
    is_3d = pts.shape[1] == 3
    
    if is_3d:
        x_idx, z_idx = 0, 2
    else:
        x_idx, z_idx = 0, 1
    
    area = 0
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        area += pts[i, x_idx] * pts[j, z_idx] - pts[j, x_idx] * pts[i, z_idx]
    
    return abs(area) / 2.0


def calculate_centroid(points: np.ndarray) -> Tuple[float, float]:
    """
    计算多边形质心（X, Z坐标）
    
    Args:
        points: (N, 3) array of 3D points
    
    Returns:
        (centroid_x, centroid_z)
    """
    if len(points) < 3:
        return (points[0, 0], points[0, 2])
    
    centroid_x = np.mean(points[:, 0])
    centroid_z = np.mean(points[:, 2])
    
    return (centroid_x, centroid_z)


def match_geological_polygons_with_similarity(
        polys_a: List[Dict], polys_b: List[Dict], 
        threshold: float = 50.0,
        area_change_threshold: float = 0.8) -> List[Tuple[Dict, Dict]]:
    """
    基于质心距离和形状相似性的地质体聚类连接
    
    Args:
        polys_a: 断面A的多边形列表
        polys_b: 断面B的多边形列表
        threshold: 最大匹配距离阈值（米）
        area_change_threshold: 面积变化阈值（比例）
    
    Returns:
        connections: 匹配成功的多边形对列表
    """
    connections = []
    
    for p_a in polys_a:
        layer_a = p_a['layer']
        centroid_a = p_a['centroid']
        area_a = p_a.get('area', 0)
        
        # 在下一断面找同类地层
        candidates = [p_b for p_b in polys_b if p_b['layer'] == layer_a]
        
        if not candidates:
            continue
        
        # 找质心距离最近的候选
        best_match = None
        min_dist = float('inf')
        
        for p_b in candidates:
            centroid_b = p_b['centroid']
            dist = math.sqrt((centroid_a[0] - centroid_b[0])**2 + 
                            (centroid_a[1] - centroid_b[1])**2)
            
            if dist < min_dist:
                min_dist = dist
                best_match = p_b
        
        # 如果距离超过阈值，断开
        if min_dist > threshold:
            continue
        
        # 形状相似性检查：面积变化不超过80%
        if best_match and area_a > 0:
            area_b = best_match.get('area', 0)
            if area_b > 0:
                area_ratio = min(area_a, area_b) / max(area_a, area_b)
                if area_ratio < area_change_threshold:
                    # 面积变化过大，可能是不同的地质透镜体
                    continue
        
        if best_match:
            connections.append((p_a, best_match))
    
    return connections


def generate_ribbon_mesh(line_a: np.ndarray, line_b: np.ndarray, 
                         num_samples: int = 50) -> Tuple[np.ndarray, List]:
    """
    基于参数化重采样构造三角网（Ribbon Mesh）
    
    Args:
        line_a: 断面A的线条 (N, 3)
        line_b: 断面B的线条 (M, 3)
        num_samples: 重采样点数（默认50，减少数据爆炸）
    
    Returns:
        vertices: (2*num_samples, 3) array
        faces: list of triangle indices
    """
    # 参数化重采样到相同点数
    pts_a = resample_line_by_ratio(line_a, num_samples)
    pts_b = resample_line_by_ratio(line_b, num_samples)
    
    # 构造顶点
    vertices = np.vstack([pts_a, pts_b])
    
    # 构造三角面片索引
    faces = []
    for i in range(num_samples - 1):
        p1 = i
        p2 = i + 1
        p3 = i + num_samples
        p4 = i + num_samples + 1
        
        # 两个三角形
        faces.append([p1, p2, p3])
        faces.append([p2, p4, p3])
    
    return vertices, faces


def resample_line_by_ratio(line: np.ndarray, num_samples: int = 50) -> np.ndarray:
    """
    基于相对索引比例(Index Ratio)重采样线条
    
    Args:
        line: (N, 3) array of 3D points
        num_samples: 目标采样点数
    
    Returns:
        (num_samples, 3) resampled points
    """
    if len(line) < 2:
        return np.tile(line[0] if len(line) == 1 else [0, 0, 0], (num_samples, 1))
    
    # 计算累积弧长
    diff = np.diff(line, axis=0)
    dist = np.sqrt((diff**2).sum(axis=1))
    s = np.concatenate(([0], np.cumsum(dist)))
    
    if s[-1] == 0:
        return np.tile(line[0], (num_samples, 1))
    
    # 使用等弧长采样
    target_s = np.linspace(0, s[-1], num_samples)
    resampled = np.zeros((num_samples, 3))
    for i in range(3):
        resampled[:, i] = np.interp(target_s, s, line[:, i])
    
    return resampled


def generate_volume_mesh(poly_a: np.ndarray, poly_b: np.ndarray,
                         num_samples: int = 64) -> Tuple[np.ndarray, List]:
    """
    为两个闭合多边形生成体积网格（Lofting）
    
    Args:
        poly_a: 断面A的闭合多边形 (N, 3)
        poly_b: 断面B的闭合多边形 (M, 3)
        num_samples: 重采样点数（默认64）
    
    Returns:
        vertices: (2*num_samples, 3) array
        faces: list of triangle indices
    """
    # 统一绕向和起点
    poly_a = normalize_polygon_orientation(poly_a)
    poly_b = normalize_polygon_orientation(poly_b)
    
    # 等步长重采样到固定点数
    pts_a = resample_polygon_equidistant(poly_a, num_samples)
    pts_b = resample_polygon_equidistant(poly_b, num_samples)
    
    # 构造顶点
    vertices = np.vstack([pts_a, pts_b])
    
    # 构造三角面片（闭合多边形）
    faces = []
    for i in range(num_samples):
        next_i = (i + 1) % num_samples
        
        p1 = i
        p2 = next_i
        p3 = i + num_samples
        p4 = next_i + num_samples
        
        # 两个三角形
        faces.append([p1, p2, p3])
        faces.append([p2, p4, p3])
    
    return vertices, faces


# ==================== 模型构建器 ====================

class EngineeringGeometryModelBuilderV2:
    """工程几何驱动三维模型构建器 V2 - 深度修复版"""
    
    def __init__(self, section_json_path: str, spine_json_path: str, 
                 num_samples_geo: int = 64,
                 num_samples_ribbon: int = 50,
                 centroid_threshold: float = 50.0,
                 area_change_threshold: float = 0.8):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.num_samples_geo = num_samples_geo  # 地质体采样点数
        self.num_samples_ribbon = num_samples_ribbon  # ribbon采样点数
        self.centroid_threshold = centroid_threshold
        self.area_change_threshold = area_change_threshold
        self.metadata = None
        self.spine_matches = None
        self.sections = []
    
    def load_data(self) -> bool:
        print(f"\n=== Loading Data ===")
        self.metadata = load_metadata(self.section_json_path)
        self.spine_matches = load_spine_matches(self.spine_json_path)
        if 'sections' not in self.metadata:
            return False
        self.sections = self.metadata['sections']
        print(f"  Sections: {len(self.sections)}, Spine matches: {len(self.spine_matches.get('matches', []))}")
        return True
    
    def _get_section_3d_data(self, section: Dict, spine_match: Dict) -> Dict:
        """
        将断面数据转换为工程坐标3D数据
        
        Returns:
            dict with dmx_3d, dmx_x_range, overbreak_3d, geological_polys
        """
        l1_ref = section.get('l1_ref_point', {})
        ref_x = l1_ref.get('ref_x', 0)
        ref_y = l1_ref.get('ref_y', 0)
        spine_x = spine_match['spine_x']
        spine_y = spine_match['spine_y']
        rotation_angle = spine_match['tangent_angle'] + math.pi / 2
        
        result = {
            'station_value': section['station_value'],
            'spine_y': spine_y,
            'dmx_3d': None,
            'dmx_x_range': (0, 0),
            'overbreak_3d': [],
            'geological_polys': []
        }
        
        # DMX转换
        dmx_points = section.get('dmx_points', [])
        if dmx_points and len(dmx_points) >= 2:
            dmx_3d = []
            for pt in dmx_points:
                eng_x, eng_y, z = transform_to_spine_aligned(
                    pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                )
                dmx_3d.append([eng_x, eng_y, z])
            result['dmx_3d'] = np.array(dmx_3d)
            # 提取DMX底角横坐标范围
            result['dmx_x_range'] = get_dmx_bottom_endpoints(result['dmx_3d'])
        
        # 超挖线转换
        overbreak_points = section.get('overbreak_points', [])
        for ob_line in overbreak_points:
            if len(ob_line) < 2:
                continue
            ob_3d = []
            for pt in ob_line:
                eng_x, eng_y, z = transform_to_spine_aligned(
                    pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                )
                ob_3d.append([eng_x, eng_y, z])
            result['overbreak_3d'].append(np.array(ob_3d))
        
        # 地质填充转换
        fill_boundaries = section.get('fill_boundaries', {})
        for layer_name, boundaries in fill_boundaries.items():
            cat_key = categorize_layer(layer_name)
            if cat_key is None:
                continue
            
            for boundary in boundaries:
                if len(boundary) < 3:
                    continue
                
                poly_3d = []
                for pt in boundary:
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    poly_3d.append([eng_x, eng_y, z])
                
                poly_3d = np.array(poly_3d)
                centroid = calculate_centroid(poly_3d)
                area = calculate_polygon_area(poly_3d)
                
                result['geological_polys'].append({
                    'layer': cat_key,
                    'points': poly_3d,
                    'centroid': centroid,
                    'area': area,
                    'layer_name': layer_name
                })
        
        return result
    
    def build_dmx_ribbon(self) -> Dict:
        """
        构建DMX Ribbon曲面（参数化重采样）
        """
        print(f"\n=== Building DMX Ribbon ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        # 收集所有断面的3D数据
        section_data_list = []
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                continue
            
            data = self._get_section_3d_data(section, spine_match)
            if data['dmx_3d'] is not None:
                section_data_list.append(data)
        
        print(f"  DMX sections: {len(section_data_list)}")
        
        if len(section_data_list) < 2:
            print("  WARNING: Not enough DMX sections for ribbon")
            return {'vertices': np.array([]), 'faces': [], 'valid': False}
        
        # 相邻断面之间生成ribbon mesh
        all_vertices = []
        all_faces = []
        vertex_offset = 0
        
        for i in range(len(section_data_list) - 1):
            sec_a = section_data_list[i]
            sec_b = section_data_list[i + 1]
            
            verts, faces = generate_ribbon_mesh(
                sec_a['dmx_3d'], sec_b['dmx_3d'],
                self.num_samples_ribbon
            )
            
            # 偏移面索引
            faces_offset = [[f[0] + vertex_offset, f[1] + vertex_offset, f[2] + vertex_offset] 
                           for f in faces]
            
            all_vertices.extend(verts)
            all_faces.extend(faces_offset)
            vertex_offset += len(verts)
        
        print(f"  DMX ribbon vertices: {len(all_vertices)}, faces: {len(all_faces)}")
        
        return {
            'vertices': np.array(all_vertices),
            'faces': all_faces,
            'valid': True
        }
    
    def build_overbreak_ribbons(self) -> Dict[str, Dict]:
        """
        构建超挖线分体Ribbon曲面（基于DMX引导的精准拆分）
        """
        print(f"\n=== Building Overbreak Ribbons (DMX-Guided Split) ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        # 收集所有断面的超挖线数据
        section_data_list = []
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                continue
            
            data = self._get_section_3d_data(section, spine_match)
            if data['overbreak_3d'] and data['dmx_x_range'] != (0, 0):
                section_data_list.append(data)
        
        print(f"  Overbreak sections with DMX guide: {len(section_data_list)}")
        
        # 分段存储
        segments_data = {
            'left': [],
            'bottom': [],
            'right': []
        }
        
        # 对每条超挖线进行DMX引导的精准拆分
        for sec_data in section_data_list:
            dmx_x_range = sec_data['dmx_x_range']
            
            for ob_3d in sec_data['overbreak_3d']:
                # 使用DMX底角横坐标进行精准拆分
                split_result = split_overbreak_robustly(ob_3d, dmx_x_range, buffer_m=0.5)
                
                if len(split_result['left']) >= 2:
                    segments_data['left'].append({
                        'points': split_result['left'],
                        'spine_y': sec_data['spine_y']
                    })
                
                if len(split_result['bottom']) >= 2:
                    segments_data['bottom'].append({
                        'points': split_result['bottom'],
                        'spine_y': sec_data['spine_y']
                    })
                
                if len(split_result['right']) >= 2:
                    segments_data['right'].append({
                        'points': split_result['right'],
                        'spine_y': sec_data['spine_y']
                    })
        
        print(f"  Left slopes: {len(segments_data['left'])}")
        print(f"  Bottom plates: {len(segments_data['bottom'])}")
        print(f"  Right slopes: {len(segments_data['right'])}")
        
        # 为每个段生成ribbon（按里程排序后相邻连线）
        result = {}
        
        for seg_name, seg_list in segments_data.items():
            if len(seg_list) < 2:
                result[seg_name] = {'vertices': np.array([]), 'faces': [], 'valid': False}
                continue
            
            # 按里程排序
            sorted_segs = sorted(seg_list, key=lambda s: s['spine_y'])
            
            all_vertices = []
            all_faces = []
            vertex_offset = 0
            
            # 相邻断面连线
            for i in range(len(sorted_segs) - 1):
                seg_a = sorted_segs[i]
                seg_b = sorted_segs[i + 1]
                
                verts, faces = generate_ribbon_mesh(
                    seg_a['points'], seg_b['points'],
                    self.num_samples_ribbon
                )
                
                faces_offset = [[f[0] + vertex_offset, f[1] + vertex_offset, f[2] + vertex_offset] 
                               for f in faces]
                
                all_vertices.extend(verts)
                all_faces.extend(faces_offset)
                vertex_offset += len(verts)
            
            result[seg_name] = {
                'vertices': np.array(all_vertices),
                'faces': all_faces,
                'valid': True
            }
            
            print(f"  {seg_name} ribbon: vertices={len(all_vertices)}, faces={len(all_faces)}")
        
        return result
    
    def build_geological_volumes(self) -> Dict[str, Dict]:
        """
        构建地质体积实体（质心聚类+形状相似性匹配）
        """
        print(f"\n=== Building Geological Volumes (Centroid + Similarity) ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        # 收集所有断面的地质数据
        section_data_list = []
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                continue
            
            data = self._get_section_3d_data(section, spine_match)
            section_data_list.append(data)
        
        print(f"  Sections with geological data: {len(section_data_list)}")
        
        # 按类别存储地质体
        category_volumes = {}
        for cat_key in LAYER_CATEGORIES.keys():
            category_volumes[cat_key] = {
                'vertices_list': [],
                'faces_list': [],
                'color': LAYER_CATEGORIES[cat_key]['color'],
                'name_cn': LAYER_CATEGORIES[cat_key]['name_cn']
            }
        
        # 相邻断面之间进行质心聚类匹配
        for i in range(len(section_data_list) - 1):
            sec_a = section_data_list[i]
            sec_b = section_data_list[i + 1]
            
            # 匹配地质多边形（带形状相似性检查）
            connections = match_geological_polygons_with_similarity(
                sec_a['geological_polys'],
                sec_b['geological_polys'],
                self.centroid_threshold,
                self.area_change_threshold
            )
            
            # 为每个匹配生成体积网格
            for poly_a, poly_b in connections:
                cat_key = poly_a['layer']
                
                verts, faces = generate_volume_mesh(
                    poly_a['points'], poly_b['points'],
                    self.num_samples_geo
                )
                
                category_volumes[cat_key]['vertices_list'].append(verts)
                category_volumes[cat_key]['faces_list'].append(faces)
        
        # 统计
        for cat_key, data in category_volumes.items():
            total_verts = sum(len(v) for v in data['vertices_list'])
            total_faces = sum(len(f) for f in data['faces_list'])
            print(f"  {data['name_cn']}: {len(data['vertices_list'])} volumes, "
                  f"{total_verts} vertices, {total_faces} faces")
        
        return category_volumes
    
    def export_to_html(self, output_path: str, 
                       dmx_data: Dict, 
                       overbreak_data: Dict[str, Dict],
                       geological_data: Dict[str, Dict]):
        """导出为Plotly HTML"""
        try:
            import plotly.graph_objects as go
        except ImportError:
            print("ERROR: Need plotly: pip install plotly")
            return None
        
        print(f"\n=== Exporting HTML ===")
        print(f"  Output: {output_path}")
        
        fig = go.Figure()
        
        # 1. 地质体积实体
        for cat_key, data in geological_data.items():
            color = data['color']
            name_cn = data['name_cn']
            
            for idx, (verts, faces) in enumerate(zip(data['vertices_list'], data['faces_list'])):
                if len(verts) < 3 or len(faces) < 1:
                    continue
                
                # 转换面索引格式
                i_list = [f[0] for f in faces]
                j_list = [f[1] for f in faces]
                k_list = [f[2] for f in faces]
                
                fig.add_trace(go.Mesh3d(
                    x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
                    i=i_list, j=j_list, k=k_list,
                    color=color, opacity=0.8,
                    name=f'{name_cn}-{idx+1}',
                    legendgroup=cat_key,
                    showlegend=(idx == 0),
                    flatshading=True,  # 实体感更强的着色
                    lighting=dict(
                        ambient=0.6,
                        diffuse=0.8,
                        specular=0.3,
                        roughness=0.5,
                        fresnel=0.2
                    )
                ))
        
        # 2. 超挖线Ribbon（分段）
        colors = {'left': 'orange', 'bottom': 'red', 'right': 'purple'}
        names = {'left': '左坡', 'bottom': '底板', 'right': '右坡'}
        
        for seg_name, seg_data in overbreak_data.items():
            if not seg_data['valid']:
                continue
            
            verts = seg_data['vertices']
            faces = seg_data['faces']
            
            if len(verts) < 3 or len(faces) < 1:
                continue
            
            i_list = [f[0] for f in faces]
            j_list = [f[1] for f in faces]
            k_list = [f[2] for f in faces]
            
            fig.add_trace(go.Mesh3d(
                x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
                i=i_list, j=j_list, k=k_list,
                color=colors[seg_name], opacity=0.7,
                name=f'超挖-{names[seg_name]}',
                legendgroup=f'Overbreak-{seg_name}',
                showlegend=True,
                flatshading=True,
                lighting=dict(
                    ambient=0.5,
                    diffuse=0.7,
                    specular=0.2,
                    roughness=0.6
                )
            ))
        
        # 3. DMX Ribbon
        if dmx_data['valid']:
            verts = dmx_data['vertices']
            faces = dmx_data['faces']
            
            if len(verts) >= 3 and len(faces) >= 1:
                i_list = [f[0] for f in faces]
                j_list = [f[1] for f in faces]
                k_list = [f[2] for f in faces]
                
                fig.add_trace(go.Mesh3d(
                    x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
                    i=i_list, j=j_list, k=k_list,
                    color='blue', opacity=0.6,
                    name='DMX设计线',
                    legendgroup='DMX',
                    showlegend=True,
                    flatshading=True,
                    lighting=dict(
                        ambient=0.4,
                        diffuse=0.6,
                        specular=0.4,
                        roughness=0.4
                    )
                ))
        
        fig.update_layout(
            title='Engineering Geometry Driven 3D Channel Model V2 (Fixed)',
            scene=dict(
                xaxis_title='Engineering X',
                yaxis_title='Engineering Y (Mileage)',
                zaxis_title='Elevation (Z)',
                aspectmode='data'
            ),
            legend=dict(x=0.02, y=0.98, bgcolor='rgba(255,255,255,0.8)')
        )
        
        fig.write_html(output_path)
        print(f"\n  HTML saved: {output_path}")
        return output_path
    
    def build_and_export(self, output_path: str) -> str:
        """完整构建流程"""
        print("=" * 60)
        print("Engineering Geometry Driven 3D Model Builder V2")
        print("  - DMX-guided overbreak splitting")
        print("  - Equidistant polygon resampling (64 pts)")
        print("  - Shape similarity check (80% threshold)")
        print("=" * 60)
        
        if not self.load_data():
            return None
        
        # 核心构建
        dmx_data = self.build_dmx_ribbon()
        overbreak_data = self.build_overbreak_ribbons()
        geological_data = self.build_geological_volumes()
        
        # 导出
        self.export_to_html(output_path, dmx_data, overbreak_data, geological_data)
        
        print("\n" + "=" * 60)
        print("SUCCESS: Model exported!")
        print("=" * 60)
        
        return output_path


def main():
    section_json = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    spine_json = r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    output_html = r'D:\断面算量平台\测试文件\engineering_geometry_model_v2.html'
    
    builder = EngineeringGeometryModelBuilderV2(
        section_json, spine_json,
        num_samples_geo=64,      # 地质体64点
        num_samples_ribbon=50,   # ribbon 50点
        centroid_threshold=50.0,
        area_change_threshold=0.8
    )
    builder.build_and_export(output_html)


if __name__ == '__main__':
    main()