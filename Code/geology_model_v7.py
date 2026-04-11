# -*- coding: utf-8 -*-
"""
航道三维地质模型 V7 - 组合版本

核心设计：
1. V4基础：正确的坐标变换 + DMX/超挖线分段对齐处理
2. geometry_working.py地质层逻辑：质心距离+面积相似性匹配 + 64点等距离重采样
3. Plotly legendgroup图层管理：点击legend独立开关各图层

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


# ==================== V4坐标变换（正确版本） ====================

def transform_to_spine_aligned(cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle):
    """
    坐标转换：CAD局部坐标 -> 工程坐标
    
    关键：Z是高程（cad_y - ref_y），只旋转dx（X偏移）
    """
    z = cad_y - ref_y  # Z是高程，不是里程偏移
    dx = cad_x - ref_x
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    rotated_dx = dx * cos_a
    rotated_dy = dx * sin_a
    eng_x = spine_x + rotated_dx  # 必须加上spine_x
    eng_y = spine_y + rotated_dy
    return eng_x, eng_y, z


# ==================== V4核心算法：特征点对齐 ====================

def find_bottom_corners(points: np.ndarray, z_tolerance: float = 0.3) -> Tuple[int, int]:
    """
    识别梯形槽的底角点（斜率变化剧烈位置）
    """
    if len(points) < 4:
        return (0, len(points) - 1)
    
    # 方法1：基于Z坐标找底板区域
    z_min = np.min(points[:, 2])
    bottom_threshold = z_min + z_tolerance
    
    bottom_indices = np.where(points[:, 2] <= bottom_threshold)[0]
    
    if len(bottom_indices) >= 2:
        left_corner = bottom_indices[0]
        right_corner = bottom_indices[-1]
        return (left_corner, right_corner)
    
    # 方法2：基于斜率变化检测
    dz = np.diff(points[:, 2])
    dx = np.diff(points[:, 0])
    dx = np.where(np.abs(dx) < 1e-6, 1e-6, dx)
    slope = dz / dx
    slope_change = np.abs(np.diff(slope))
    
    if len(slope_change) >= 2:
        top_changes = np.argsort(slope_change)[-2:]
        top_changes = sorted(top_changes)
        return (top_changes[0] + 1, top_changes[1] + 1)
    
    return (0, len(points) - 1)


def resample_line_uniform(points: np.ndarray, num_samples: int) -> np.ndarray:
    """均匀重采样线条"""
    if len(points) < 2:
        return points
    
    # 计算累积弧长
    diff = np.diff(points, axis=0)
    dist = np.sqrt((diff**2).sum(axis=1))
    s = np.concatenate(([0], np.cumsum(dist)))
    
    if s[-1] == 0:
        return np.tile(points[0], (num_samples, 1))
    
    target_s = np.linspace(0, s[-1], num_samples)
    resampled = np.zeros((num_samples, points.shape[1]))
    for i in range(points.shape[1]):
        resampled[:, i] = np.interp(target_s, s, points[:, i])
    
    return resampled


def resample_trench_segmented(points: np.ndarray, 
                               n_slope: int = 15, 
                               n_bottom: int = 30) -> np.ndarray:
    """
    超挖线分段重采样：左坡 + 底板 + 右坡
    确保底角点纵向对齐，形成规整梯形槽
    """
    if len(points) < 4:
        return resample_line_uniform(points, n_slope * 2 + n_bottom)
    
    left_corner, right_corner = find_bottom_corners(points)
    
    if left_corner >= right_corner or left_corner >= len(points) or right_corner >= len(points):
        return resample_line_uniform(points, n_slope * 2 + n_bottom)
    
    # 分段
    left_slope_pts = points[:left_corner + 1]
    bottom_pts = points[left_corner:right_corner + 1]
    right_slope_pts = points[right_corner:]
    
    if len(left_slope_pts) < 2 or len(bottom_pts) < 2 or len(right_slope_pts) < 2:
        return resample_line_uniform(points, n_slope * 2 + n_bottom)
    
    # 各段重采样
    left_resampled = resample_line_uniform(left_slope_pts, n_slope)
    bottom_resampled = resample_line_uniform(bottom_pts, n_bottom)
    right_resampled = resample_line_uniform(right_slope_pts, n_slope)
    
    # 合并（去除重复衔接点）
    result = np.vstack([left_resampled, bottom_resampled[1:-1], right_resampled])
    
    return result


def smooth_longitudinal(vertices: np.ndarray, window_size: int = 3) -> np.ndarray:
    """
    纵向平滑：沿里程方向滑动平均滤波
    使用边缘填充避免边界漂移
    """
    if vertices.shape[0] < window_size:
        return vertices
    
    smoothed = np.copy(vertices)
    
    # 对每个坐标分量进行平滑
    for coord_idx in range(vertices.shape[2]):
        for pt_idx in range(vertices.shape[1]):
            values = vertices[:, pt_idx, coord_idx]
            # 边缘填充（避免边界漂移）
            padded = np.pad(values, window_size // 2, mode='edge')
            # 滑动平均
            kernel = np.ones(window_size) / window_size
            smoothed_values = np.convolve(padded, kernel, mode='valid')
            smoothed[:, pt_idx, coord_idx] = smoothed_values
    
    return smoothed


# ==================== geometry_working.py地质层逻辑 ====================

def resample_polygon_equidistant(points: np.ndarray, n_samples: int = 64) -> np.ndarray:
    """
    将地质多边形归一化为固定点数，使用等距离重采样
    """
    if len(points) < 3:
        return points
    
    is_3d = points.shape[1] == 3
    
    if not check_shapely():
        return _resample_polygon_simple(points, n_samples)
    
    try:
        from shapely.geometry import Polygon, LineString
        
        # 创建闭合多边形
        if is_3d:
            xy_points = [(p[0], p[1]) for p in points]
        else:
            xy_points = [(p[0], p[1]) for p in points]
        
        # 确保闭合
        if xy_points[0] != xy_points[-1]:
            xy_points.append(xy_points[0])
        
        poly = Polygon(xy_points)
        if not poly.is_valid:
            return _resample_polygon_simple(points, n_samples)
        
        # 计算总周长
        perimeter = poly.length
        if perimeter == 0:
            return _resample_polygon_simple(points, n_samples)
        
        # 等距离采样
        distances = np.linspace(0, perimeter, n_samples, endpoint=False)
        
        # 使用exterior边界进行采样
        boundary = poly.exterior
        
        resampled_xy = []
        for d in distances:
            pt = boundary.interpolate(d)
            resampled_xy.append((pt.x, pt.y))
        
        # Z坐标插值
        if is_3d:
            # 计算原始点的累积距离
            dist_orig = [0]
            for i in range(1, len(points)):
                dx = points[i, 0] - points[i-1, 0]
                dy = points[i, 1] - points[i-1, 1]
                dist_orig.append(dist_orig[-1] + math.sqrt(dx*dx + dy*dy))
            
            total_dist = dist_orig[-1]
            if total_dist == 0:
                z_values = np.full(n_samples, points[0, 2])
            else:
                # 等距离采样Z
                target_dist = np.linspace(0, total_dist, n_samples, endpoint=False)
                z_values = np.interp(target_dist, dist_orig, points[:, 2])
            
            resampled = np.zeros((n_samples, 3))
            for i, (xy, z) in enumerate(zip(resampled_xy, z_values)):
                resampled[i, 0] = xy[0]
                resampled[i, 1] = xy[1]
                resampled[i, 2] = z
        else:
            resampled = np.zeros((n_samples, 2))
            for i, xy in enumerate(resampled_xy):
                resampled[i, 0] = xy[0]
                resampled[i, 1] = xy[1]
        
        return resampled
        
    except Exception as e:
        print(f"  [WARN] Shapely resample failed: {e}")
        return _resample_polygon_simple(points, n_samples)


def _resample_polygon_simple(points: np.ndarray, n_samples: int) -> np.ndarray:
    """简化版多边形重采样（无shapely时使用）"""
    if len(points) < 3:
        return points
    
    # 确保闭合
    closed_points = np.vstack([points, points[0]])
    
    # 计算累积距离
    diff = np.diff(closed_points, axis=0)
    dist = np.sqrt((diff**2).sum(axis=1))
    s = np.concatenate(([0], np.cumsum(dist)))
    
    if s[-1] == 0:
        return np.tile(points[0], (n_samples, 1))
    
    # 等距离采样
    target_s = np.linspace(0, s[-1], n_samples, endpoint=False)
    
    resampled = np.zeros((n_samples, points.shape[1]))
    for i in range(points.shape[1]):
        resampled[:, i] = np.interp(target_s, s, closed_points[:, i])
    
    return resampled


def normalize_polygon_orientation(points: np.ndarray) -> np.ndarray:
    """统一多边形绕向为逆时针"""
    if len(points) < 3:
        return points
    
    # 计算有向面积
    area = 0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        area += points[i, 0] * points[j, 1]
        area -= points[j, 0] * points[i, 1]
    
    # 如果是顺时针，反转
    if area < 0:
        return np.flip(points, axis=0)
    
    return points


def calculate_polygon_area(points: np.ndarray) -> float:
    """计算多边形面积（有向面积）"""
    if len(points) < 3:
        return 0
    
    area = 0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        area += points[i, 0] * points[j, 1]
        area -= points[j, 0] * points[i, 1]
    
    return abs(area) / 2


def calculate_centroid(points: np.ndarray) -> Tuple[float, float]:
    """计算多边形质心"""
    if len(points) == 0:
        return (0, 0)
    
    return (np.mean(points[:, 0]), np.mean(points[:, 1]))


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
        area_change_threshold: 面积变化阈值（比例）- 80%
    
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


def generate_taper_volume(poly: np.ndarray, centroid: Tuple[float, float],
                          num_samples: int = 64) -> Tuple[np.ndarray, List]:
    """
    生成地层消失时的退化体积（向质心收缩 - bullet head）
    """
    # 重采样多边形
    pts = resample_polygon_equidistant(poly, num_samples)
    
    # 质心点（收缩目标）
    centroid_pt = np.array([centroid[0], centroid[1], np.mean(poly[:, 2])])
    
    # 构造顶点
    vertices = np.vstack([pts, centroid_pt.reshape(1, 3)])
    
    # 构造三角面片（向质心收缩）
    faces = []
    centroid_idx = num_samples
    
    for i in range(num_samples):
        next_i = (i + 1) % num_samples
        
        # 一个三角形连接两个相邻点和质心
        faces.append([i, next_i, centroid_idx])
    
    return vertices, faces


# ==================== V4 Ribbon生成 ====================

def generate_dmx_ribbon(section_data_list: List[Dict], 
                        num_samples: int = 60) -> Tuple[np.ndarray, List]:
    """构建DMX Ribbon曲面"""
    if len(section_data_list) < 2:
        return np.array([]), []
    
    # 收集所有DMX线
    all_lines = []
    for data in section_data_list:
        if data['dmx_3d'] is not None and len(data['dmx_3d']) >= 2:
            all_lines.append(data['dmx_3d'])
    
    if len(all_lines) < 2:
        return np.array([]), []
    
    # 重采样每条线
    resampled_lines = []
    for line in all_lines:
        resampled = resample_line_uniform(line, num_samples)
        resampled_lines.append(resampled)
    
    # 展平为顶点列表
    all_vertices = []
    for line in resampled_lines:
        for pt in line:
            all_vertices.append(pt)
    
    vertices = np.array(all_vertices)
    
    # 构造三角面片
    faces = []
    n_sections = len(resampled_lines)
    n_pts = num_samples
    
    for sec_idx in range(n_sections - 1):
        base_a = sec_idx * n_pts
        base_b = (sec_idx + 1) * n_pts
        
        for pt_idx in range(n_pts - 1):
            p1 = base_a + pt_idx
            p2 = base_a + pt_idx + 1
            p3 = base_b + pt_idx
            p4 = base_b + pt_idx + 1
            
            faces.append([p1, p2, p3])
            faces.append([p2, p4, p3])
    
    return vertices, faces


def generate_trench_ribbon(section_data_list: List[Dict], 
                           n_slope: int = 15, 
                           n_bottom: int = 30,
                           apply_smooth: bool = True) -> Tuple[np.ndarray, List]:
    """
    构建梯形槽Ribbon曲面（分段对齐）
    """
    if len(section_data_list) < 2:
        return np.array([]), []
    
    total_points = n_slope * 2 + n_bottom
    
    # 收集所有断面的超挖线
    all_lines = []
    valid_section_count = 0
    for data in section_data_list:
        if data['overbreak_3d']:
            longest = max(data['overbreak_3d'], key=lambda x: len(x))
            
            # 检查Y坐标是否异常
            y_min = np.min(longest[:, 1])
            if y_min < 1000:
                print(f"  [WARN] Skipping section with abnormal Y range: {y_min:.2f}")
                continue
            
            all_lines.append(longest)
            valid_section_count += 1
    
    print(f"  Valid overbreak lines: {valid_section_count}")
    
    if len(all_lines) < 2:
        return np.array([]), []
    
    # 分段重采样每条超挖线
    resampled_lines = []
    expected_shape = n_slope * 2 + n_bottom
    for i, line in enumerate(all_lines):
        resampled = resample_trench_segmented(line, n_slope, n_bottom)
        # 检查形状一致性
        if resampled.shape[0] != expected_shape:
            if resampled.shape[0] < expected_shape:
                padding = np.tile(resampled[-1], (expected_shape - resampled.shape[0], 1))
                resampled = np.vstack([resampled, padding])
            elif resampled.shape[0] > expected_shape:
                resampled = resampled[:expected_shape]
        resampled_lines.append(resampled)
    
    # 构建顶点数组
    vertices_3d = np.array(resampled_lines)
    
    # 纵向平滑
    if apply_smooth and vertices_3d.shape[0] >= 3:
        vertices_3d = smooth_longitudinal(vertices_3d, window_size=3)
    
    # 展平为顶点列表
    all_vertices = []
    for line in vertices_3d:
        for pt in line:
            all_vertices.append(pt)
    
    vertices = np.array(all_vertices)
    
    # 构造三角面片
    faces = []
    n_sections = len(vertices_3d)
    n_pts = vertices_3d.shape[1]
    
    for sec_idx in range(n_sections - 1):
        base_a = sec_idx * n_pts
        base_b = (sec_idx + 1) * n_pts
        
        for pt_idx in range(n_pts - 1):
            p1 = base_a + pt_idx
            p2 = base_a + pt_idx + 1
            p3 = base_b + pt_idx
            p4 = base_b + pt_idx + 1
            
            faces.append([p1, p2, p3])
            faces.append([p2, p4, p3])
    
    return vertices, faces


# ==================== 模型构建器 V7 ====================

class GeologyModelBuilderV7:
    """
    航道三维地质模型构建器 V7
    
    组合设计：
    - V4坐标变换和DMX/超挖线处理
    - geometry_working.py地质层匹配逻辑（质心距离+面积相似性80%）
    - Plotly legendgroup图层管理（点击legend独立开关）
    """
    
    def __init__(self, section_json_path: str, spine_json_path: str, 
                 num_samples_geo: int = 64,
                 n_slope: int = 15,
                 n_bottom: int = 30,
                 num_samples_dmx: int = 60,
                 centroid_threshold: float = 50.0,
                 area_change_threshold: float = 0.8):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.num_samples_geo = num_samples_geo  # 地质体采样点数（64点）
        self.n_slope = n_slope  # 超挖线坡面采样点数
        self.n_bottom = n_bottom  # 超挖线底板采样点数
        self.num_samples_dmx = num_samples_dmx  # DMX采样点数
        self.centroid_threshold = centroid_threshold  # 质心距离阈值
        self.area_change_threshold = area_change_threshold  # 面积相似性阈值（80%）
        self.metadata = None
        self.spine_matches = None
        self.sections = []
        self.spine_interpolation = None
    
    def load_data(self) -> bool:
        print(f"\n=== Loading Data ===")
        self.metadata = load_metadata(self.section_json_path)
        self.spine_matches = load_spine_matches(self.spine_json_path)
        
        if 'sections' not in self.metadata:
            return False
        
        self.sections = self.metadata['sections']
        
        # 处理spine_matches格式（可能是matches数组或直接键值对）
        matches = self.spine_matches.get('matches', [])
        if not matches:
            # 尝试直接解析键值对
            matches = [v for k, v in self.spine_matches.items() if isinstance(v, dict) and 'station_value' in v]
        
        print(f"  Sections: {len(self.sections)}, Spine matches: {len(matches)}")
        
        # 预计算spine_x和spine_y插值参数
        spine_matches_sorted = sorted(matches, key=lambda m: m['station_value'])
        if spine_matches_sorted:
            self.spine_interpolation = {
                'station_min': spine_matches_sorted[0]['station_value'],
                'station_max': spine_matches_sorted[-1]['station_value'],
                'spine_x_min': spine_matches_sorted[0]['spine_x'],
                'spine_x_max': spine_matches_sorted[-1]['spine_x'],
                'spine_y_min': spine_matches_sorted[0]['spine_y'],
                'spine_y_max': spine_matches_sorted[-1]['spine_y']
            }
            print(f"  Spine interpolation: station {self.spine_interpolation['station_min']}->{self.spine_interpolation['station_max']}, "
                  f"spine_x {self.spine_interpolation['spine_x_min']:.2f}->{self.spine_interpolation['spine_x_max']:.2f}, "
                  f"spine_y {self.spine_interpolation['spine_y_min']:.2f}->{self.spine_interpolation['spine_y_max']:.2f}")
        
        return True
    
    def _get_interpolated_spine_match(self, station_value: float) -> Dict:
        """使用线性插值计算缺失断面的完整spine_match"""
        if not self.spine_interpolation:
            return {
                'spine_x': 0,
                'spine_y': station_value,
                'tangent_angle': 0
            }
        
        station_min = self.spine_interpolation['station_min']
        station_max = self.spine_interpolation['station_max']
        spine_x_min = self.spine_interpolation['spine_x_min']
        spine_x_max = self.spine_interpolation['spine_x_max']
        spine_y_min = self.spine_interpolation['spine_y_min']
        spine_y_max = self.spine_interpolation['spine_y_max']
        
        if station_max > station_min:
            ratio = (station_value - station_min) / (station_max - station_min)
            interpolated_spine_x = spine_x_min + ratio * (spine_x_max - spine_x_min)
            interpolated_spine_y = spine_y_min + ratio * (spine_y_max - spine_y_min)
        else:
            interpolated_spine_x = spine_x_min
            interpolated_spine_y = spine_y_min
        
        return {
            'spine_x': interpolated_spine_x,
            'spine_y': interpolated_spine_y,
            'tangent_angle': 0
        }
    
    def _get_section_3d_data(self, section: Dict, spine_match: Dict) -> Dict:
        """将断面数据转换为工程坐标3D数据"""
        l1_ref = section.get('l1_ref_point', {})
        ref_x = l1_ref.get('ref_x', 0)
        ref_y = l1_ref.get('ref_y', 0)
        
        station_value = section.get('station_value', 0)
        
        spine_x = spine_match['spine_x']
        spine_y = spine_match['spine_y']
        rotation_angle = spine_match['tangent_angle'] + math.pi / 2
        
        result = {
            'station_value': station_value,
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
        
        # 超挖线转换
        overbreak_points = section.get('overbreak_points', [])
        all_ob_points = []
        for ob_line in overbreak_points:
            if len(ob_line) >= 2:
                for pt in ob_line:
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    all_ob_points.append([eng_x, eng_y, z])
        
        # 按X坐标排序
        if len(all_ob_points) >= 2:
            all_ob_points = sorted(all_ob_points, key=lambda p: p[0])
            result['overbreak_3d'].append(np.array(all_ob_points))
        
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
        """构建DMX Ribbon曲面"""
        print(f"\n=== Building DMX Ribbon ===")
        
        matches = self.spine_matches.get('matches', [])
        if not matches:
            matches = [v for k, v in self.spine_matches.items() if isinstance(v, dict) and 'station_value' in v]
        
        spine_dict = {m['station_value']: m for m in matches}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        section_data_list = []
        skipped_count = 0
        
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                spine_match = self._get_interpolated_spine_match(section.get('station_value', 0))
            
            data = self._get_section_3d_data(section, spine_match)
            if data['dmx_3d'] is not None:
                y_min = np.min(data['dmx_3d'][:, 1])
                if y_min < 1000:
                    skipped_count += 1
                    continue
                section_data_list.append(data)
            else:
                skipped_count += 1
        
        print(f"  DMX sections: {len(section_data_list)}, Skipped: {skipped_count}")
        
        # 诊断坐标范围
        if len(section_data_list) >= 2:
            first_dmx = section_data_list[0]['dmx_3d']
            last_dmx = section_data_list[-1]['dmx_3d']
            print(f"  First section Y range: {np.min(first_dmx[:, 1]):.2f} - {np.max(first_dmx[:, 1]):.2f}")
            print(f"  Last section Y range: {np.min(last_dmx[:, 1]):.2f} - {np.max(last_dmx[:, 1]):.2f}")
        
        vertices, faces = generate_dmx_ribbon(section_data_list, self.num_samples_dmx)
        
        print(f"  DMX ribbon: {len(vertices)} vertices, {len(faces)} faces")
        
        return {
            'valid': len(vertices) > 0 and len(faces) > 0,
            'vertices': vertices,
            'faces': faces,
            'section_count': len(section_data_list)
        }
    
    def build_overbreak_ribbon(self) -> Dict:
        """构建超挖线梯形槽Ribbon曲面"""
        print(f"\n=== Building Overbreak Trench Ribbon ===")
        
        matches = self.spine_matches.get('matches', [])
        if not matches:
            matches = [v for k, v in self.spine_matches.items() if isinstance(v, dict) and 'station_value' in v]
        
        spine_dict = {m['station_value']: m for m in matches}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        section_data_list = []
        skipped_count = 0
        
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                spine_match = self._get_interpolated_spine_match(section.get('station_value', 0))
            
            data = self._get_section_3d_data(section, spine_match)
            if data['overbreak_3d']:
                section_data_list.append(data)
            else:
                skipped_count += 1
        
        print(f"  Overbreak sections: {len(section_data_list)}, Skipped: {skipped_count}")
        
        vertices, faces = generate_trench_ribbon(section_data_list, self.n_slope, self.n_bottom)
        
        print(f"  Overbreak ribbon: {len(vertices)} vertices, {len(faces)} faces")
        
        return {
            'valid': len(vertices) > 0 and len(faces) > 0,
            'vertices': vertices,
            'faces': faces,
            'section_count': len(section_data_list)
        }
    
    def build_geological_volumes(self) -> Dict[str, Dict]:
        """
        构建地质体积实体
        
        使用geometry_working.py的逻辑：
        - 质心距离+面积相似性匹配（80%阈值）
        - 64点等距离重采样
        """
        print(f"\n=== Building Geological Volumes ===")
        print(f"  Using centroid threshold: {self.centroid_threshold}m")
        print(f"  Using area similarity threshold: {self.area_change_threshold}")
        
        matches = self.spine_matches.get('matches', [])
        if not matches:
            matches = [v for k, v in self.spine_matches.items() if isinstance(v, dict) and 'station_value' in v]
        
        spine_dict = {m['station_value']: m for m in matches}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        # 转换所有断面数据
        section_data_list = []
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                spine_match = self._get_interpolated_spine_match(section.get('station_value', 0))
            
            data = self._get_section_3d_data(section, spine_match)
            section_data_list.append(data)
        
        print(f"  Total sections: {len(section_data_list)}")
        
        # 初始化各类别数据
        category_data = {}
        for cat_key, cat_info in LAYER_CATEGORIES.items():
            category_data[cat_key] = {
                'name_cn': cat_info['name_cn'],
                'color': cat_info['color'],
                'vertices_list': [],
                'faces_list': [],
                'volume_count': 0
            }
        
        # 遍历相邻断面对，匹配地质体
        total_connections = 0
        for i in range(len(section_data_list) - 1):
            polys_a = section_data_list[i]['geological_polys']
            polys_b = section_data_list[i + 1]['geological_polys']
            
            # 使用geometry_working.py的匹配逻辑
            connections = match_geological_polygons_with_similarity(
                polys_a, polys_b,
                threshold=self.centroid_threshold,
                area_change_threshold=self.area_change_threshold
            )
            
            total_connections += len(connections)
            
            for p_a, p_b in connections:
                cat_key = p_a['layer']
                
                # 生成体积网格
                vertices, faces = generate_volume_mesh(
                    p_a['points'], p_b['points'],
                    num_samples=self.num_samples_geo
                )
                
                category_data[cat_key]['vertices_list'].append(vertices)
                category_data[cat_key]['faces_list'].append(faces)
                category_data[cat_key]['volume_count'] += 1
        
        print(f"  Total connections matched: {total_connections}")
        
        # 处理地层尖灭（未匹配的多边形）
        for i, data in enumerate(section_data_list):
            for poly in data['geological_polys']:
                # 检查是否已被匹配
                # 简化处理：只处理首尾断面的未匹配多边形
                if i == 0 or i == len(section_data_list) - 1:
                    cat_key = poly['layer']
                    # 生成尖灭体积
                    vertices, faces = generate_taper_volume(
                        poly['points'],
                        poly['centroid'],
                        num_samples=self.num_samples_geo
                    )
                    category_data[cat_key]['vertices_list'].append(vertices)
                    category_data[cat_key]['faces_list'].append(faces)
                    category_data[cat_key]['volume_count'] += 1
        
        # 统计
        for cat_key, data in category_data.items():
            total_verts = sum(len(v) for v in data['vertices_list'])
            total_faces = sum(len(f) for f in data['faces_list'])
            print(f"  {data['name_cn']}: {data['volume_count']} volumes, {total_verts} vertices, {total_faces} faces")
        
        return category_data
    
    def export_to_html(self, output_path: str,
                       dmx_data: Dict,
                       overbreak_data: Dict,
                       geological_data: Dict[str, Dict]):
        """
        导出为Plotly HTML
        
        使用legendgroup实现点击legend独立开关各图层
        """
        print(f"\n=== Exporting HTML ===")
        print(f"  Output: {output_path}")
        
        try:
            import plotly.graph_objects as go
        except ImportError:
            print("ERROR: Need plotly: pip install plotly")
            return None
        
        fig = go.Figure()
        
        # 1. 地质体积实体 - 使用legendgroup分组
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
                    name=name_cn,
                    legendgroup=cat_key,  # 图层分组
                    showlegend=(idx == 0),  # 只在第一个trace显示legend项
                    flatshading=True,
                    lighting=dict(
                        ambient=0.6,
                        diffuse=0.8,
                        specular=0.3,
                        roughness=0.5,
                        fresnel=0.2
                    )
                ))
        
        # 2. DMX Ribbon - 独立legendgroup
        if dmx_data['valid'] and len(dmx_data['vertices']) > 0:
            verts = dmx_data['vertices']
            faces = dmx_data['faces']
            
            if len(faces) > 0:
                i_list = [f[0] for f in faces]
                j_list = [f[1] for f in faces]
                k_list = [f[2] for f in faces]
                
                fig.add_trace(go.Mesh3d(
                    x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
                    i=i_list, j=j_list, k=k_list,
                    color='#3498db', opacity=0.8,
                    name='DMX断面线',
                    legendgroup='DMX',
                    showlegend=True,
                    flatshading=True,
                    lighting=dict(
                        ambient=0.5,
                        diffuse=0.7,
                        specular=0.3,
                        roughness=0.4
                    )
                ))
        
        # 3. 超挖线梯形槽 - 独立legendgroup
        if overbreak_data['valid'] and len(overbreak_data['vertices']) > 0:
            verts = overbreak_data['vertices']
            faces = overbreak_data['faces']
            
            if len(faces) > 0:
                i_list = [f[0] for f in faces]
                j_list = [f[1] for f in faces]
                k_list = [f[2] for f in faces]
                
                fig.add_trace(go.Mesh3d(
                    x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
                    i=i_list, j=j_list, k=k_list,
                    color='#e74c3c', opacity=0.3,
                    name='超挖线梯形槽',
                    legendgroup='Overbreak',
                    showlegend=True,
                    flatshading=True,
                    lighting=dict(
                        ambient=0.5,
                        diffuse=0.6,
                        specular=0.2,
                        roughness=0.6
                    )
                ))
        
        # 设置布局 - legend支持点击开关图层
        fig.update_layout(
            title='航道三维地质模型 V7 - 组合版本',
            scene=dict(
                xaxis_title='X (m)',
                yaxis_title='Y (里程 m)',
                zaxis_title='Z (高程 m)',
                aspectmode='data'
            ),
            showlegend=True,
            legend=dict(
                x=0.02,
                y=0.98,
                bgcolor='rgba(255,255,255,0.8)',
                bordercolor='rgba(0,0,0,0.3)',
                borderwidth=1,
                font=dict(size=12),
                title=dict(text='图层管理器（点击开关）', font=dict(size=14))
            )
        )
        
        # 打印trace统计
        print(f"  Total traces: {len(fig.data)}")
        for i, trace in enumerate(fig.data):
            print(f"    Trace {i}: {trace.name}, legendgroup={trace.legendgroup}")
        
        fig.write_html(output_path)
        print(f"  HTML saved: {output_path}")
        
        return output_path
    
    def build_and_export(self, output_path: str) -> str:
        """完整构建流程"""
        print("=" * 60)
        print("Geology Model Builder V7")
        print("  - V4 coordinate transformation")
        print("  - V4 DMX/Overbreak segmented alignment")
        print("  - geometry_working.py geological matching (80% similarity)")
        print("  - Plotly legendgroup layer toggle")
        print("=" * 60)
        
        if not self.load_data():
            return None
        
        # 核心构建
        dmx_data = self.build_dmx_ribbon()
        overbreak_data = self.build_overbreak_ribbon()
        geological_data = self.build_geological_volumes()
        
        # 导出
        self.export_to_html(output_path, dmx_data, overbreak_data, geological_data)
        
        print("\n" + "=" * 60)
        print("SUCCESS: Model exported!")
        print("=" * 60)
        
        return output_path


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Geology Model Builder V7')
    parser.add_argument('--input', type=str, 
                        default=r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json',
                        help='Input JSON metadata file')
    parser.add_argument('--spine', type=str,
                        default=r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json',
                        help='Spine matches JSON file')
    parser.add_argument('--output', type=str,
                        default=r'D:\断面算量平台\测试文件\geology_model_v7.html',
                        help='Output HTML file')
    
    args = parser.parse_args()
    
    builder = GeologyModelBuilderV7(
        section_json_path=args.input,
        spine_json_path=args.spine,
        num_samples_geo=64,  # 地质体64点
        n_slope=15,  # 超挖线坡面15点
        n_bottom=30,  # 超挖线底板30点
        num_samples_dmx=60,  # DMX 60点
        centroid_threshold=50.0,  # 质心距离阈值
        area_change_threshold=0.8  # 面积相似性阈值80%
    )
    
    builder.build_and_export(args.output)


if __name__ == '__main__':
    main()