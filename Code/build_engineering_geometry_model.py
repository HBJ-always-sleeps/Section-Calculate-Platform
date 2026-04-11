# -*- coding: utf-8 -*-
"""
航道三维模型工程几何驱动版本 V3 - 统一曲面逻辑 + Chaikin平滑

核心改进：
1. 统一超挖线算法：不再拆分左/底/右，使用与DMX相同的参数化比例映射
2. Chaikin割角平滑：地质多边形在重采样前先磨圆角（2次迭代）
3. 放宽聚类约束：area_ratio从0.8降到0.3，centroid阈值30m
4. 纵向平滑：Z坐标高斯滤波（sigma=1.0）
5. 退化逻辑：地层消失时向质心平滑收缩

作者: @黄秉俊
日期: 2026-04-03
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
SCIPY_AVAILABLE = None


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


def check_scipy():
    """延迟检查scipy是否可用"""
    global SCIPY_AVAILABLE
    if SCIPY_AVAILABLE is None:
        try:
            from scipy.ndimage import gaussian_filter1d
            SCIPY_AVAILABLE = True
        except ImportError:
            SCIPY_AVAILABLE = False
    return SCIPY_AVAILABLE


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


# ==================== 核心算法：V3统一曲面逻辑 ====================

def smooth_corner_chaikin(points: np.ndarray, iterations: int = 2) -> np.ndarray:
    """
    Chaikin割角算法：将多边形尖角磨圆
    通过迭代切割多边形的每一个角，将尖锐的折角转变为平滑的圆弧角
    
    Args:
        points: (N, 2) or (N, 3) array of polygon vertices
        iterations: 迭代次数（默认2次）
    
    Returns:
        smoothed points
    """
    if len(points) < 3:
        return points
    
    pts = np.array(points, dtype=float)
    is_3d = pts.shape[1] == 3
    
    for _ in range(iterations):
        new_pts = []
        n = len(pts)
        for i in range(n):
            p0 = pts[i]
            p1 = pts[(i + 1) % n]
            # 在每条边的 1/4 和 3/4 处取点
            q = 0.75 * p0 + 0.25 * p1
            r = 0.25 * p0 + 0.75 * p1
            new_pts.append(q)
            new_pts.append(r)
        pts = np.array(new_pts)
    
    return pts


def gaussian_smooth_z(values: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    """
    对Z坐标应用高斯滤波，消除断面间的阶梯感
    
    Args:
        values: 1D array of Z values
        sigma: 高斯滤波标准差
    
    Returns:
        smoothed Z values
    """
    if len(values) < 3:
        return values
    
    if check_scipy():
        from scipy.ndimage import gaussian_filter1d
        return gaussian_filter1d(values, sigma=sigma)
    else:
        # 简单移动平均作为备选
        kernel_size = max(3, int(sigma * 3) * 2 + 1)
        kernel = np.ones(kernel_size) / kernel_size
        return np.convolve(values, kernel, mode='same')


def resample_line_by_ratio(line: np.ndarray, num_samples: int = 50) -> np.ndarray:
    """
    基于相对索引比例(Index Ratio)重采样线条
    使用 t = i / (N-1) 的比例定位点
    
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


def resample_polygon_equidistant(points: np.ndarray, n_samples: int = 64) -> np.ndarray:
    """
    将地质多边形归一化为固定点数
    先应用Chaikin平滑，再等距离重采样
    
    Args:
        points: (N, 2) or (N, 3) array of polygon vertices
        n_samples: 目标采样点数
    
    Returns:
        (n_samples, 2) or (n_samples, 3) resampled points
    """
    if len(points) < 3:
        return points
    
    # 1. 先应用Chaikin割角平滑
    smoothed = smooth_corner_chaikin(points, iterations=2)
    
    # 2. 等距离重采样
    is_3d = smoothed.shape[1] == 3
    
    if not check_shapely():
        return _resample_polygon_simple(smoothed, n_samples)
    
    from shapely.geometry import Polygon
    
    try:
        # 创建闭合多边形
        if is_3d:
            pts_2d = smoothed[:, [0, 2]]
        else:
            pts_2d = smoothed
        
        # 确保闭合
        if not np.allclose(pts_2d[0], pts_2d[-1]):
            pts_2d = np.vstack([pts_2d, pts_2d[0]])
        
        poly = Polygon(pts_2d)
        
        if not poly.is_valid:
            poly = poly.buffer(0)
        
        if poly.is_empty:
            return smoothed
        
        # 等距离重采样
        distances = np.linspace(0, poly.exterior.length, n_samples, endpoint=False)
        resampled_2d = np.array([poly.exterior.interpolate(d).coords[0] for d in distances])
        
        if is_3d:
            avg_y = np.mean(smoothed[:, 1])
            resampled_3d = np.zeros((n_samples, 3))
            resampled_3d[:, 0] = resampled_2d[:, 0]
            resampled_3d[:, 1] = avg_y
            resampled_3d[:, 2] = resampled_2d[:, 1]
            return resampled_3d
        else:
            return resampled_2d
            
    except Exception:
        return _resample_polygon_simple(smoothed, n_samples)


def _resample_polygon_simple(points: np.ndarray, n_samples: int) -> np.ndarray:
    """简化版多边形重采样"""
    if len(points) < 3:
        return points
    
    pts = np.array(points)
    if not np.allclose(pts[0], pts[-1]):
        pts = np.vstack([pts, pts[0]])
    
    diff = np.diff(pts, axis=0)
    dist = np.sqrt((diff**2).sum(axis=1))
    s = np.concatenate(([0], np.cumsum(dist)))
    
    if s[-1] == 0:
        return np.tile(pts[0], (n_samples, 1))
    
    target_s = np.linspace(0, s[-1], n_samples, endpoint=False)
    resampled = np.zeros((n_samples, pts.shape[1]))
    for i in range(pts.shape[1]):
        resampled[:, i] = np.interp(target_s, s, pts[:, i])
    
    return resampled


def normalize_polygon_orientation(points: np.ndarray) -> np.ndarray:
    """统一多边形绕向（逆时针）并将最左侧点作为起点"""
    if len(points) < 3:
        return points
    
    pts = np.array(points)
    is_3d = pts.shape[1] == 3
    
    x_idx, z_idx = (0, 2) if is_3d else (0, 1)
    
    # 计算有向面积
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
    """计算多边形面积"""
    if len(points) < 3:
        return 0.0
    
    pts = np.array(points)
    is_3d = pts.shape[1] == 3
    x_idx, z_idx = (0, 2) if is_3d else (0, 1)
    
    area = 0
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        area += pts[i, x_idx] * pts[j, z_idx] - pts[j, x_idx] * pts[i, z_idx]
    
    return abs(area) / 2.0


def calculate_centroid(points: np.ndarray) -> Tuple[float, float]:
    """计算多边形质心（X, Z坐标）"""
    if len(points) < 3:
        return (points[0, 0], points[0, 2])
    
    return (np.mean(points[:, 0]), np.mean(points[:, 2]))


def match_geological_polygons_relaxed(
        polys_a: List[Dict], polys_b: List[Dict], 
        distance_threshold: float = 30.0,
        area_ratio_threshold: float = 0.3) -> List[Tuple[Dict, Dict]]:
    """
    放宽约束的地质体聚类连接
    
    Args:
        polys_a: 断面A的多边形列表
        polys_b: 断面B的多边形列表
        distance_threshold: 最大质心距离阈值（米）- 放宽到30m
        area_ratio_threshold: 面积比例阈值 - 放宽到0.3
    
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
        
        # 距离阈值放宽到30m
        if min_dist > distance_threshold:
            continue
        
        # 面积比例阈值放宽到0.3
        if best_match and area_a > 0:
            area_b = best_match.get('area', 0)
            if area_b > 0:
                area_ratio = min(area_a, area_b) / max(area_a, area_b)
                if area_ratio < area_ratio_threshold:
                    continue
        
        if best_match:
            connections.append((p_a, best_match))
    
    return connections


def generate_ribbon_mesh(line_a: np.ndarray, line_b: np.ndarray, 
                         num_samples: int = 50,
                         apply_z_smooth: bool = True) -> Tuple[np.ndarray, List]:
    """
    基于参数化重采样构造三角网（Ribbon Mesh）
    统一的曲面生成逻辑
    
    Args:
        line_a: 断面A的线条 (N, 3)
        line_b: 断面B的线条 (M, 3)
        num_samples: 重采样点数
        apply_z_smooth: 是否应用Z轴平滑
    
    Returns:
        vertices: (2*num_samples, 3) array
        faces: list of triangle indices
    """
    # 参数化重采样到相同点数
    pts_a = resample_line_by_ratio(line_a, num_samples)
    pts_b = resample_line_by_ratio(line_b, num_samples)
    
    # Z轴纵向平滑
    if apply_z_smooth:
        pts_a[:, 2] = gaussian_smooth_z(pts_a[:, 2], sigma=1.0)
        pts_b[:, 2] = gaussian_smooth_z(pts_b[:, 2], sigma=1.0)
    
    # 构造顶点
    vertices = np.vstack([pts_a, pts_b])
    
    # 构造三角面片索引
    faces = []
    for i in range(num_samples - 1):
        p1 = i
        p2 = i + 1
        p3 = i + num_samples
        p4 = i + num_samples + 1
        
        faces.append([p1, p2, p3])
        faces.append([p2, p4, p3])
    
    return vertices, faces


def generate_volume_mesh(poly_a: np.ndarray, poly_b: np.ndarray,
                         num_samples: int = 64) -> Tuple[np.ndarray, List]:
    """
    为两个闭合多边形生成体积网格（Lofting）
    包含Chaikin平滑和等步长重采样
    
    Args:
        poly_a: 断面A的闭合多边形 (N, 3)
        poly_b: 断面B的闭合多边形 (M, 3)
        num_samples: 重采样点数
    
    Returns:
        vertices: (2*num_samples, 3) array
        faces: list of triangle indices
    """
    # 统一绕向和起点
    poly_a = normalize_polygon_orientation(poly_a)
    poly_b = normalize_polygon_orientation(poly_b)
    
    # Chaikin平滑 + 等步长重采样
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
        
        faces.append([p1, p2, p3])
        faces.append([p2, p4, p3])
    
    return vertices, faces


def generate_taper_volume(poly: np.ndarray, centroid: Tuple[float, float],
                          taper_distance: float = 10.0,
                          num_samples: int = 64) -> Tuple[np.ndarray, List]:
    """
    生成地层消失时的退化体积（向质心收缩）
    
    Args:
        poly: 多边形 (N, 3)
        centroid: 质心 (x, z)
        taper_distance: 收缩距离（米）
        num_samples: 重采样点数
    
    Returns:
        vertices, faces
    """
    # 重采样多边形
    pts = resample_polygon_equidistant(poly, num_samples)
    
    # 创建收缩到质心的点
    centroid_3d = np.array([centroid[0], np.mean(pts[:, 1]), centroid[1]])
    taper_pts = np.tile(centroid_3d, (num_samples, 1))
    
    # 构造顶点
    vertices = np.vstack([pts, taper_pts])
    
    # 构造三角面片
    faces = []
    for i in range(num_samples):
        next_i = (i + 1) % num_samples
        
        p1 = i
        p2 = next_i
        p3 = i + num_samples
        
        faces.append([p1, p2, p3])
    
    return vertices, faces


# ==================== 模型构建器 V3 ====================

class EngineeringGeometryModelBuilderV3:
    """工程几何驱动三维模型构建器 V3 - 统一曲面逻辑"""
    
    def __init__(self, section_json_path: str, spine_json_path: str, 
                 num_samples_geo: int = 64,
                 num_samples_ribbon: int = 50,
                 distance_threshold: float = 30.0,
                 area_ratio_threshold: float = 0.3):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.num_samples_geo = num_samples_geo
        self.num_samples_ribbon = num_samples_ribbon
        self.distance_threshold = distance_threshold
        self.area_ratio_threshold = area_ratio_threshold
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
        """将断面数据转换为工程坐标3D数据"""
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
        
        # 超挖线转换（不拆分，保持完整）
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
        """构建DMX Ribbon曲面（统一逻辑）"""
        print(f"\n=== Building DMX Ribbon (Unified Logic) ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
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
            return {'vertices': np.array([]), 'faces': [], 'valid': False}
        
        all_vertices = []
        all_faces = []
        vertex_offset = 0
        
        for i in range(len(section_data_list) - 1):
            sec_a = section_data_list[i]
            sec_b = section_data_list[i + 1]
            
            verts, faces = generate_ribbon_mesh(
                sec_a['dmx_3d'], sec_b['dmx_3d'],
                self.num_samples_ribbon,
                apply_z_smooth=True
            )
            
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
    
    def build_overbreak_ribbon(self) -> Dict:
        """
        构建超挖线Ribbon曲面（统一逻辑，不拆分）
        使用与DMX完全相同的算法
        """
        print(f"\n=== Building Overbreak Ribbon (Unified - No Split) ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        # 收集所有断面的超挖线数据
        section_overbreak_list = []
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                continue
            
            data = self._get_section_3d_data(section, spine_match)
            if data['overbreak_3d']:
                # 合并该断面的所有超挖线为一条
                all_ob_points = []
                for ob_3d in data['overbreak_3d']:
                    all_ob_points.extend(ob_3d.tolist())
                
                if len(all_ob_points) >= 2:
                    section_overbreak_list.append({
                        'overbreak_3d': np.array(all_ob_points),
                        'spine_y': data['spine_y']
                    })
        
        print(f"  Overbreak sections: {len(section_overbreak_list)}")
        
        if len(section_overbreak_list) < 2:
            return {'vertices': np.array([]), 'faces': [], 'valid': False}
        
        # 按里程排序
        sorted_obs = sorted(section_overbreak_list, key=lambda s: s['spine_y'])
        
        all_vertices = []
        all_faces = []
        vertex_offset = 0
        
        # 相邻断面连线（与DMX完全相同的逻辑）
        for i in range(len(sorted_obs) - 1):
            ob_a = sorted_obs[i]
            ob_b = sorted_obs[i + 1]
            
            verts, faces = generate_ribbon_mesh(
                ob_a['overbreak_3d'], ob_b['overbreak_3d'],
                self.num_samples_ribbon,
                apply_z_smooth=True
            )
            
            faces_offset = [[f[0] + vertex_offset, f[1] + vertex_offset, f[2] + vertex_offset] 
                           for f in faces]
            
            all_vertices.extend(verts)
            all_faces.extend(faces_offset)
            vertex_offset += len(verts)
        
        print(f"  Overbreak ribbon vertices: {len(all_vertices)}, faces: {len(all_faces)}")
        
        return {
            'vertices': np.array(all_vertices),
            'faces': all_faces,
            'valid': True
        }
    
    def build_geological_volumes(self) -> Dict[str, Dict]:
        """
        构建地质体积实体（放宽约束 + Chaikin平滑）
        """
        print(f"\n=== Building Geological Volumes (Relaxed + Chaikin) ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        section_data_list = []
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                continue
            
            data = self._get_section_3d_data(section, spine_match)
            section_data_list.append(data)
        
        print(f"  Sections with geological data: {len(section_data_list)}")
        
        category_volumes = {}
        for cat_key in LAYER_CATEGORIES.keys():
            category_volumes[cat_key] = {
                'vertices_list': [],
                'faces_list': [],
                'color': LAYER_CATEGORIES[cat_key]['color'],
                'name_cn': LAYER_CATEGORIES[cat_key]['name_cn']
            }
        
        # 相邻断面之间进行放宽约束的匹配
        for i in range(len(section_data_list) - 1):
            sec_a = section_data_list[i]
            sec_b = section_data_list[i + 1]
            
            connections = match_geological_polygons_relaxed(
                sec_a['geological_polys'],
                sec_b['geological_polys'],
                self.distance_threshold,
                self.area_ratio_threshold
            )
            
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
                       overbreak_data: Dict,
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
                    flatshading=True,
                    lighting=dict(
                        ambient=0.6,
                        diffuse=0.8,
                        specular=0.3,
                        roughness=0.5,
                        fresnel=0.2
                    )
                ))
        
        # 2. 超挖线Ribbon（统一曲面）
        if overbreak_data['valid']:
            verts = overbreak_data['vertices']
            faces = overbreak_data['faces']
            
            if len(verts) >= 3 and len(faces) >= 1:
                i_list = [f[0] for f in faces]
                j_list = [f[1] for f in faces]
                k_list = [f[2] for f in faces]
                
                fig.add_trace(go.Mesh3d(
                    x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
                    i=i_list, j=j_list, k=k_list,
                    color='red', opacity=0.7,
                    name='超挖线',
                    legendgroup='Overbreak',
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
            title='Engineering Geometry Driven 3D Channel Model V3 (Unified + Chaikin)',
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
        print("Engineering Geometry Driven 3D Model Builder V3")
        print("  - Unified ribbon logic (DMX + Overbreak)")
        print("  - Chaikin corner smoothing (2 iterations)")
        print("  - Relaxed clustering (dist=30m, area_ratio=0.3)")
        print("  - Longitudinal Z smoothing (Gaussian sigma=1.0)")
        print("=" * 60)
        
        if not self.load_data():
            return None
        
        dmx_data = self.build_dmx_ribbon()
        overbreak_data = self.build_overbreak_ribbon()
        geological_data = self.build_geological_volumes()
        
        self.export_to_html(output_path, dmx_data, overbreak_data, geological_data)
        
        print("\n" + "=" * 60)
        print("SUCCESS: Model exported!")
        print("=" * 60)
        
        return output_path


def main():
    section_json = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    spine_json = r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    output_html = r'D:\断面算量平台\测试文件\engineering_geometry_model_v3.html'
    
    builder = EngineeringGeometryModelBuilderV3(
        section_json, spine_json,
        num_samples_geo=64,
        num_samples_ribbon=50,
        distance_threshold=30.0,      # 放宽到30m
        area_ratio_threshold=0.3      # 放宽到0.3
    )
    builder.build_and_export(output_html)


if __name__ == '__main__':
    main()