# -*- coding: utf-8 -*-
"""
航道三维模型特征点对齐版本 V4 - Feature-based Alignment

核心改进：
1. 超挖线分段对齐：识别底角点，分段重采样（左坡15点、底板30点、右坡15点）
2. 纵向平滑：滑动平均滤波（window=3）消除锯齿
3. 地质体起始点归一化：X最小点作为Index 0，强制逆时针绕向
4. 地质尖灭：地层消失时向质心平滑收缩（bullet head）

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


# ==================== V4核心算法：特征点对齐 ====================

def find_bottom_corners(points: np.ndarray, z_tolerance: float = 0.3) -> Tuple[int, int]:
    """
    识别梯形槽的底角点（斜率变化剧烈位置）
    
    Args:
        points: (N, 3) array - 超挖线点，[x, y, z]
        z_tolerance: 底板识别容差（米）
    
    Returns:
        (left_corner_idx, right_corner_idx): 底角点索引
    """
    if len(points) < 4:
        return (0, len(points) - 1)
    
    # 方法1：基于Z坐标找底板区域
    z_min = np.min(points[:, 2])
    bottom_threshold = z_min + z_tolerance
    
    # 找所有接近底板高程的点
    bottom_indices = np.where(points[:, 2] <= bottom_threshold)[0]
    
    if len(bottom_indices) >= 2:
        # 底板区域的左右边界即为底角
        left_corner = bottom_indices[0]
        right_corner = bottom_indices[-1]
        return (left_corner, right_corner)
    
    # 方法2：基于斜率变化检测
    # 计算相邻点的斜率变化
    dz = np.diff(points[:, 2])
    dx = np.diff(points[:, 0])
    
    # 避免除零
    dx = np.where(np.abs(dx) < 1e-6, 1e-6, dx)
    slope = dz / dx
    
    # 斜率变化率
    slope_change = np.abs(np.diff(slope))
    
    # 找斜率变化最大的两个位置
    if len(slope_change) >= 2:
        # 排序找最大变化点
        top_changes = np.argsort(slope_change)[-2:]
        # 按位置排序
        top_changes = sorted(top_changes)
        return (top_changes[0] + 1, top_changes[1] + 1)
    
    return (0, len(points) - 1)


def resample_trench_segmented(points: np.ndarray, 
                               n_slope: int = 15, 
                               n_bottom: int = 30) -> np.ndarray:
    """
    超挖线分段重采样：左坡 + 底板 + 右坡
    确保底角点纵向对齐，形成规整梯形槽
    
    Args:
        points: (N, 3) array - 超挖线点
        n_slope: 坡面采样点数
        n_bottom: 底板采样点数
    
    Returns:
        (n_slope + n_bottom + n_slope, 3) resampled points
    """
    if len(points) < 4:
        # 点数不足，简单重采样
        print(f"  [WARN] Trench points too few: {len(points)}")
        return resample_line_uniform(points, n_slope * 2 + n_bottom)
    
    # 识别底角
    left_corner, right_corner = find_bottom_corners(points)
    
    # 边界检查
    if left_corner >= right_corner:
        print(f"  [WARN] Invalid corners: left={left_corner}, right={right_corner}")
        return resample_line_uniform(points, n_slope * 2 + n_bottom)
    
    if left_corner >= len(points) or right_corner >= len(points):
        print(f"  [WARN] Corner out of bounds: left={left_corner}, right={right_corner}, total={len(points)}")
        return resample_line_uniform(points, n_slope * 2 + n_bottom)
    
    # 分段
    left_slope_pts = points[:left_corner + 1]
    bottom_pts = points[left_corner:right_corner + 1]
    right_slope_pts = points[right_corner:]
    
    # 检查分段有效性
    if len(left_slope_pts) < 2 or len(bottom_pts) < 2 or len(right_slope_pts) < 2:
        print(f"  [WARN] Invalid segments: left={len(left_slope_pts)}, bottom={len(bottom_pts)}, right={len(right_slope_pts)}")
        return resample_line_uniform(points, n_slope * 2 + n_bottom)
    
    # 各段重采样
    left_resampled = resample_line_uniform(left_slope_pts, n_slope)
    bottom_resampled = resample_line_uniform(bottom_pts, n_bottom)
    right_resampled = resample_line_uniform(right_slope_pts, n_slope)
    
    # 合并（去除重复的底角点）
    result = np.vstack([
        left_resampled,
        bottom_resampled[1:-1] if len(bottom_resampled) > 2 else bottom_resampled,
        right_resampled[1:] if len(right_resampled) > 1 else right_resampled
    ])
    
    return result


def resample_line_uniform(points: np.ndarray, num_samples: int) -> np.ndarray:
    """
    等弧长重采样线条
    
    Args:
        points: (N, 3) array
        num_samples: 目标点数
    
    Returns:
        (num_samples, 3) resampled points
    """
    if len(points) < 2:
        return np.tile(points[0] if len(points) == 1 else [0, 0, 0], (num_samples, 1))
    
    # 计算累积弧长
    diff = np.diff(points, axis=0)
    dist = np.sqrt((diff**2).sum(axis=1))
    s = np.concatenate(([0], np.cumsum(dist)))
    
    if s[-1] == 0:
        return np.tile(points[0], (num_samples, 1))
    
    # 等弧长采样
    target_s = np.linspace(0, s[-1], num_samples)
    resampled = np.zeros((num_samples, 3))
    for i in range(3):
        resampled[:, i] = np.interp(target_s, s, points[:, i])
    
    return resampled


def smooth_longitudinal(vertices: np.ndarray, window_size: int = 3) -> np.ndarray:
    """
    沿里程方向（Y轴）平滑，消除锯齿
    对每个对应的顶点沿断面序列进行滑动平均
    
    Args:
        vertices: (n_sections, n_points_per_section, 3) array
        window_size: 滑动平均窗口大小
    
    Returns:
        smoothed vertices
    """
    if vertices.shape[0] < window_size:
        return vertices
    
    smoothed = vertices.copy()
    
    # 对每个顶点位置沿断面序列平滑
    for i in range(vertices.shape[1]):
        for j in range(3):  # x, y, z
            values = vertices[:, i, j]
            # 滑动平均 - 使用边缘填充避免零填充导致的坐标漂移
            # np.convolve默认使用零填充，会导致Y坐标（约237万）被平滑到约158万
            # 解决方案：手动实现边缘填充的滑动平均
            half_window = window_size // 2
            padded = np.pad(values, half_window, mode='edge')
            kernel = np.ones(window_size) / window_size
            convolved = np.convolve(padded, kernel, mode='valid')
            # 确保输出长度与输入一致
            smoothed[:, i, j] = convolved[:len(values)]
    
    return smoothed


def normalize_polygon_startpoint(points: np.ndarray) -> np.ndarray:
    """
    地质多边形起始点归一化：
    1. 强制逆时针绕向
    2. X最小点作为Index 0
    
    Args:
        points: (N, 2) or (N, 3) array
    
    Returns:
        normalized points
    """
    if len(points) < 3:
        return points
    
    pts = np.array(points)
    is_3d = pts.shape[1] == 3
    x_idx, z_idx = (0, 2) if is_3d else (0, 1)
    
    # 计算有向面积判断绕向
    area = 0
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        area += pts[i, x_idx] * pts[j, z_idx] - pts[j, x_idx] * pts[i, z_idx]
    
    # 如果面积为负（顺时针），翻转
    if area < 0:
        pts = pts[::-1]
    
    # 找X最小点作为起点
    min_x_idx = np.argmin(pts[:, x_idx])
    pts = np.roll(pts, -min_x_idx, axis=0)
    
    return pts


def resample_polygon_equidistant(points: np.ndarray, n_samples: int = 50) -> np.ndarray:
    """
    地质多边形等距离重采样
    
    Args:
        points: (N, 2) or (N, 3) array
        n_samples: 目标采样点数
    
    Returns:
        (n_samples, dim) resampled points
    """
    if len(points) < 3:
        return points
    
    # 先归一化起始点
    pts = normalize_polygon_startpoint(points)
    
    # 确保闭合
    if not np.allclose(pts[0], pts[-1]):
        pts = np.vstack([pts, pts[0]])
    
    # 计算累积弧长
    diff = np.diff(pts, axis=0)
    dist = np.sqrt((diff**2).sum(axis=1))
    s = np.concatenate(([0], np.cumsum(dist)))
    
    if s[-1] == 0:
        return np.tile(pts[0], (n_samples, 1))
    
    # 等弧长采样（不包含终点，因为是闭合多边形）
    target_s = np.linspace(0, s[-1], n_samples, endpoint=False)
    resampled = np.zeros((n_samples, pts.shape[1]))
    for i in range(pts.shape[1]):
        resampled[:, i] = np.interp(target_s, s, pts[:, i])
    
    return resampled


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
        return (points[0, 0], points[0, 2] if points.shape[1] == 3 else points[0, 1])
    
    return (np.mean(points[:, 0]), np.mean(points[:, 2] if points.shape[1] == 3 else points[:, 1]))


def match_geological_polygons(
        polys_a: List[Dict], polys_b: List[Dict], 
        distance_threshold: float = 50.0,
        area_ratio_threshold: float = 0.3) -> List[Tuple[Dict, Dict]]:
    """
    地质体聚类连接（放宽约束）
    
    Args:
        polys_a: 断面A的多边形列表
        polys_b: 断面B的多边形列表
        distance_threshold: 最大质心距离阈值（米）- 放宽到50m
        area_ratio_threshold: 面积比例阈值
    
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
        
        # 距离阈值放宽到50m
        if min_dist > distance_threshold:
            continue
        
        # 面积比例阈值
        if best_match and area_a > 0:
            area_b = best_match.get('area', 0)
            if area_b > 0:
                area_ratio = min(area_a, area_b) / max(area_a, area_b)
                if area_ratio < area_ratio_threshold:
                    continue
        
        if best_match:
            connections.append((p_a, best_match))
    
    return connections


def generate_trench_ribbon(section_data_list: List[Dict], 
                           n_slope: int = 15, 
                           n_bottom: int = 30,
                           apply_smooth: bool = True) -> Tuple[np.ndarray, List]:
    """
    构建梯形槽Ribbon曲面（分段对齐）
    
    Args:
        section_data_list: 断面数据列表
        n_slope: 坡面采样点数
        n_bottom: 底板采样点数
        apply_smooth: 是否应用纵向平滑
    
    Returns:
        vertices, faces
    """
    if len(section_data_list) < 2:
        return np.array([]), []
    
    total_points = n_slope * 2 + n_bottom
    
    # 收集所有断面的超挖线
    all_lines = []
    valid_section_count = 0
    for data in section_data_list:
        # 取最长的超挖线（主槽）
        if data['overbreak_3d']:
            longest = max(data['overbreak_3d'], key=lambda x: len(x))
            
            # 诊断：检查Y坐标是否异常（里程应在70000以上）
            y_min = np.min(longest[:, 1])
            y_max = np.max(longest[:, 1])
            if y_min < 1000:  # Y坐标异常（可能是0或极小值）
                print(f"  [WARN] Skipping section with abnormal Y range: {y_min:.2f} to {y_max:.2f}")
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
            print(f"  [WARN] Section {i} resampled shape mismatch: expected {expected_shape}, got {resampled.shape[0]}")
            # 强制修正形状
            if resampled.shape[0] < expected_shape:
                # 重复最后一个点来填充
                padding = np.tile(resampled[-1], (expected_shape - resampled.shape[0], 1))
                resampled = np.vstack([resampled, padding])
            elif resampled.shape[0] > expected_shape:
                # 截断
                resampled = resampled[:expected_shape]
        resampled_lines.append(resampled)
    
    # 构建顶点数组 (n_sections, n_points, 3)
    vertices_3d = np.array(resampled_lines)
    
    # 纵向平滑
    if apply_smooth and vertices_3d.shape[0] >= 3:
        vertices_3d = smooth_longitudinal(vertices_3d, window_size=3)
    
    # 展平为顶点列表
    all_vertices = []
    for i, line in enumerate(vertices_3d):
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


def generate_volume_mesh(poly_a: np.ndarray, poly_b: np.ndarray,
                         num_samples: int = 50) -> Tuple[np.ndarray, List]:
    """
    为两个闭合多边形生成体积网格（Lofting）
    起始点归一化 + 等步长重采样
    
    Args:
        poly_a: 断面A的闭合多边形 (N, 3)
        poly_b: 断面B的闭合多边形 (M, 3)
        num_samples: 重采样点数
    
    Returns:
        vertices, faces
    """
    # 起始点归一化
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
                          num_samples: int = 50) -> Tuple[np.ndarray, List]:
    """
    生成地层消失时的退化体积（向质心收缩 - bullet head）
    
    Args:
        poly: 多边形 (N, 3)
        centroid: 质心 (x, z)
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


# ==================== 模型构建器 V4 ====================

class FeatureAlignedModelBuilderV4:
    """特征点对齐三维模型构建器 V4"""
    
    def __init__(self, section_json_path: str, spine_json_path: str, 
                 num_samples_geo: int = 50,
                 n_slope: int = 15,
                 n_bottom: int = 30,
                 distance_threshold: float = 50.0,
                 area_ratio_threshold: float = 0.3):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.num_samples_geo = num_samples_geo
        self.n_slope = n_slope
        self.n_bottom = n_bottom
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
        
        # 预计算spine_x和spine_y插值参数（用于fallback）
        spine_matches_sorted = sorted(self.spine_matches.get('matches', []), key=lambda m: m['station_value'])
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
        else:
            self.spine_interpolation = None
        
        return True
    
    def _get_interpolated_spine_match(self, station_value: float) -> Dict:
        """使用线性插值计算缺失断面的完整spine_match（包含spine_x和spine_y）"""
        if not self.spine_interpolation:
            # 无插值参数时返回基于station_value的fallback
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
            # 线性插值
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
        
        # 诊断：检查ref坐标是否为零（会导致坐标归零问题）
        station_value = section.get('station_value', 0)
        if ref_x == 0 or ref_y == 0:
            print(f"  [WARN] ref_3d is zero at station {station_value}: ref=({ref_x:.2f}, {ref_y:.2f})")
            print(f"         This may cause coordinate drift. Using station_value as fallback Y.")
        
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
        
        # 超挖线转换 - 合并所有短线段为完整线
        overbreak_points = section.get('overbreak_points', [])
        all_ob_points = []
        for ob_line in overbreak_points:
            if len(ob_line) >= 2:
                for pt in ob_line:
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    # 调试：检查异常坐标
                    if eng_x < 400000 or eng_x > 600000 or eng_y < 2000000 or eng_y > 3000000:
                        print(f"  [WARN] Abnormal coord at station {section['station_value']}: eng=({eng_x:.2f}, {eng_y:.2f}, {z:.2f})")
                        print(f"         CAD=({pt[0]:.2f}, {pt[1]:.2f}), ref=({ref_x:.2f}, {ref_y:.2f}), spine=({spine_x:.2f}, {spine_y:.2f})")
                    all_ob_points.append([eng_x, eng_y, z])
        
        # 按X坐标排序，形成完整的超挖线
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
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        section_data_list = []
        skipped_count = 0
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                # 修复：使用线性插值计算完整的spine_match（包含spine_x和spine_y）
                station_value = section.get('station_value', 0)
                spine_match = self._get_interpolated_spine_match(station_value)
                print(f"  [WARN] No spine match for station {station_value}, using interpolated spine_x={spine_match['spine_x']:.2f}, spine_y={spine_match['spine_y']:.2f}")
            
            data = self._get_section_3d_data(section, spine_match)
            if data['dmx_3d'] is not None:
                # 诊断：检查DMX的Y坐标是否异常
                y_min = np.min(data['dmx_3d'][:, 1])
                if y_min < 1000:
                    print(f"  [WARN] Skipping DMX section with abnormal Y: {y_min:.2f}")
                    skipped_count += 1
                    continue
                section_data_list.append(data)
            else:
                skipped_count += 1
        
        print(f"  DMX sections: {len(section_data_list)}, Skipped: {skipped_count}")
        
        # 诊断：打印首尾断面坐标
        if len(section_data_list) >= 2:
            first_section = section_data_list[0]
            last_section = section_data_list[-1]
            print(f"  First DMX station: {first_section['station_value']}, spine_y: {first_section['spine_y']:.2f}")
            print(f"  Last DMX station: {last_section['station_value']}, spine_y: {last_section['spine_y']:.2f}")
        
        if len(section_data_list) < 2:
            return {'vertices': np.array([]), 'faces': [], 'valid': False}
        
        # 简单重采样DMX
        all_vertices = []
        all_faces = []
        vertex_offset = 0
        
        for i in range(len(section_data_list) - 1):
            data_a = section_data_list[i]
            data_b = section_data_list[i + 1]
            
            pts_a = resample_line_uniform(data_a['dmx_3d'], 50)
            pts_b = resample_line_uniform(data_b['dmx_3d'], 50)
            
            verts, faces = generate_ribbon_mesh_simple(pts_a, pts_b)
            
            # 偏移索引
            for f in faces:
                all_faces.append([f[0] + vertex_offset, f[1] + vertex_offset, f[2] + vertex_offset])
            
            all_vertices.extend(verts)
            vertex_offset += len(verts)
        
        return {
            'vertices': np.array(all_vertices),
            'faces': all_faces,
            'valid': True
        }
    
    def build_overbreak_ribbon(self) -> Dict:
        """构建超挖线梯形槽Ribbon曲面（分段对齐）"""
        print(f"\n=== Building Overbreak Trench (Segmented Alignment) ===")
        print(f"  n_slope={self.n_slope}, n_bottom={self.n_bottom}")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        section_data_list = []
        skipped_count = 0
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                # 修复：使用线性插值计算完整的spine_match（包含spine_x和spine_y）
                station_value = section.get('station_value', 0)
                spine_match = self._get_interpolated_spine_match(station_value)
                print(f"  [WARN] No spine match for station {station_value}, using interpolated spine_x={spine_match['spine_x']:.2f}, spine_y={spine_match['spine_y']:.2f}")
            
            data = self._get_section_3d_data(section, spine_match)
            if data['overbreak_3d']:
                section_data_list.append(data)
            else:
                skipped_count += 1
        
        print(f"  Overbreak sections: {len(section_data_list)}, Skipped: {skipped_count}")
        
        # 诊断：打印首尾断面坐标
        if len(section_data_list) >= 2:
            first_section = section_data_list[0]
            last_section = section_data_list[-1]
            print(f"  First section station: {first_section['station_value']}, spine_y: {first_section['spine_y']:.2f}")
            print(f"  Last section station: {last_section['station_value']}, spine_y: {last_section['spine_y']:.2f}")
            
            # 检查首尾断面的超挖线坐标范围
            if first_section['overbreak_3d']:
                first_pts = first_section['overbreak_3d'][0]
                print(f"  First overbreak Y range: {np.min(first_pts[:, 1]):.2f} to {np.max(first_pts[:, 1]):.2f}")
            if last_section['overbreak_3d']:
                last_pts = last_section['overbreak_3d'][0]
                print(f"  Last overbreak Y range: {np.min(last_pts[:, 1]):.2f} to {np.max(last_pts[:, 1]):.2f}")
        
        vertices, faces = generate_trench_ribbon(
            section_data_list, 
            self.n_slope, 
            self.n_bottom,
            apply_smooth=True
        )
        
        print(f"  Vertices: {len(vertices)}, Faces: {len(faces)}")
        
        # 调试：检查坐标范围
        if len(vertices) > 0:
            x_min, x_max = np.min(vertices[:, 0]), np.max(vertices[:, 0])
            y_min, y_max = np.min(vertices[:, 1]), np.max(vertices[:, 1])
            z_min, z_max = np.min(vertices[:, 2]), np.max(vertices[:, 2])
            print(f"  X range: {x_min:.2f} to {x_max:.2f}, span={x_max-x_min:.2f}")
            print(f"  Y range: {y_min:.2f} to {y_max:.2f}, span={y_max-y_min:.2f}")
            print(f"  Z range: {z_min:.2f} to {z_max:.2f}, span={z_max-z_min:.2f}")
            
            # 检查异常值
            x_span = x_max - x_min
            y_span = y_max - y_min
            if x_span > 1000 or y_span > 10000:
                print(f"  [WARNING] Abnormal span detected!")
                x_median = np.median(vertices[:, 0])
                y_median = np.median(vertices[:, 1])
                x_outliers = vertices[np.abs(vertices[:, 0] - x_median) > x_span * 0.5]
                y_outliers = vertices[np.abs(vertices[:, 1] - y_median) > y_span * 0.5]
                if len(x_outliers) > 0:
                    print(f"  X outliers: {len(x_outliers)} points")
                    print(f"    Sample: {x_outliers[:5]}")
                if len(y_outliers) > 0:
                    print(f"  Y outliers: {len(y_outliers)} points")
                    print(f"    Sample: {y_outliers[:5]}")
        
        return {
            'vertices': vertices,
            'faces': faces,
            'valid': len(vertices) > 0
        }
    
    def build_category_volumes(self) -> Dict[str, Dict]:
        """构建地质分类体积"""
        print(f"\n=== Building Geological Volumes ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        section_data_list = []
        skipped_count = 0
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                # 修复：使用线性插值计算完整的spine_match（包含spine_x和spine_y）
                station_value = section.get('station_value', 0)
                spine_match = self._get_interpolated_spine_match(station_value)
                print(f"  [WARN] No spine match for station {station_value}, using interpolated spine_x={spine_match['spine_x']:.2f}, spine_y={spine_match['spine_y']:.2f}")
            
            data = self._get_section_3d_data(section, spine_match)
            
            # 诊断：检查地质多边形的Y坐标是否异常
            has_valid_polys = False
            for poly in data.get('geological_polys', []):
                y_min = np.min(poly['points'][:, 1])
                if y_min >= 1000:  # Y坐标正常
                    has_valid_polys = True
                    break
            
            if has_valid_polys or data.get('dmx_3d') is not None:
                section_data_list.append(data)
            else:
                skipped_count += 1
        
        print(f"  Processed sections: {len(section_data_list)}, Skipped: {skipped_count}")
        
        # 诊断：打印首尾断面坐标
        if len(section_data_list) >= 2:
            first_section = section_data_list[0]
            last_section = section_data_list[-1]
            print(f"  First section station: {first_section['station_value']}, spine_y: {first_section['spine_y']:.2f}")
            print(f"  Last section station: {last_section['station_value']}, spine_y: {last_section['spine_y']:.2f}")
        
        results = {}
        for cat_key in LAYER_CATEGORIES.keys():
            results[cat_key] = {
                'vertices': [],
                'faces': [],
                'volumes': 0
            }
        
        # 遍历相邻断面
        for i in range(len(section_data_list) - 1):
            data_a = section_data_list[i]
            data_b = section_data_list[i + 1]
            
            polys_a = data_a['geological_polys']
            polys_b = data_b['geological_polys']
            
            # 匹配地质体
            connections = match_geological_polygons(
                polys_a, polys_b,
                self.distance_threshold,
                self.area_ratio_threshold
            )
            
            for p_a, p_b in connections:
                cat_key = p_a['layer']
                
                verts, faces = generate_volume_mesh(
                    p_a['points'], p_b['points'],
                    self.num_samples_geo
                )
                
                # 偏移索引
                offset = len(results[cat_key]['vertices'])
                for f in faces:
                    results[cat_key]['faces'].append([f[0] + offset, f[1] + offset, f[2] + offset])
                
                results[cat_key]['vertices'].extend(verts)
                results[cat_key]['volumes'] += 1
        
        # 处理地层尖灭（未匹配的多边形）
        for i, data in enumerate(section_data_list):
            polys = data['geological_polys']
            
            # 找未匹配的多边形
            if i < len(section_data_list) - 1:
                next_polys = section_data_list[i + 1]['geological_polys']
                matched_ids = set()
                connections = match_geological_polygons(polys, next_polys)
                for p_a, p_b in connections:
                    matched_ids.add(id(p_a))
                
                for p in polys:
                    if id(p) not in matched_ids:
                        cat_key = p['layer']
                        verts, faces = generate_taper_volume(
                            p['points'], p['centroid'],
                            self.num_samples_geo
                        )
                        
                        offset = len(results[cat_key]['vertices'])
                        for f in faces:
                            results[cat_key]['faces'].append([f[0] + offset, f[1] + offset, f[2] + offset])
                        
                        results[cat_key]['vertices'].extend(verts)
                        results[cat_key]['volumes'] += 1
        
        # 转换为numpy数组
        for cat_key in results:
            results[cat_key]['vertices'] = np.array(results[cat_key]['vertices'])
            print(f"  {LAYER_CATEGORIES[cat_key]['name_cn']}: {results[cat_key]['volumes']} volumes, "
                  f"{len(results[cat_key]['vertices'])} vertices, {len(results[cat_key]['faces'])} faces")
        
        return results
    
    def export_to_html(self, output_path: str, category_data: Dict,
                       dmx_data: Dict, overbreak_data: Dict):
        """导出为Plotly HTML"""
        print(f"\n=== Exporting to HTML ===")
        
        try:
            import plotly.graph_objects as go
        except ImportError:
            print("  [ERROR] plotly not available")
            return
        
        fig = go.Figure()
        trace_count = 0
        
        # 添加地质体积
        for cat_key, data in category_data.items():
            verts = data['vertices']
            faces = data['faces']
            
            print(f"  {cat_key}: vertices shape = {verts.shape if hasattr(verts, 'shape') else len(verts)}, faces = {len(faces)}")
            
            if len(verts) == 0:
                print(f"    SKIP: no vertices")
                continue
            
            if len(faces) == 0:
                print(f"    SKIP: no faces")
                continue
            
            # 确保verts是numpy数组
            if not isinstance(verts, np.ndarray):
                verts = np.array(verts)
            
            print(f"    Adding Mesh3d with {len(verts)} vertices, {len(faces)} faces")
            
            i_list = [f[0] for f in faces]
            j_list = [f[1] for f in faces]
            k_list = [f[2] for f in faces]
            
            mesh = go.Mesh3d(
                x=verts[:, 0],
                y=verts[:, 1],
                z=verts[:, 2],
                i=i_list,
                j=j_list,
                k=k_list,
                color=LAYER_CATEGORIES[cat_key]['color'],
                opacity=0.7,
                name=LAYER_CATEGORIES[cat_key]['name_cn'],
                hoverinfo='name',
                visible=True  # 图层管理器：默认可见
            )
            fig.add_trace(mesh)
            trace_count += 1
        
        # 添加DMX Ribbon
        if dmx_data['valid'] and len(dmx_data['vertices']) > 0:
            verts = dmx_data['vertices']
            faces = dmx_data['faces']
            
            if len(faces) > 0:
                i_list = [f[0] for f in faces]
                j_list = [f[1] for f in faces]
                k_list = [f[2] for f in faces]
                
                mesh = go.Mesh3d(
                    x=verts[:, 0],
                    y=verts[:, 1],
                    z=verts[:, 2],
                    i=i_list,
                    j=j_list,
                    k=k_list,
                    color='#3498db',
                    opacity=0.8,  # DMX透明度调高（更不透明）
                    name='DMX断面线',
                    hoverinfo='name',
                    visible=True  # 图层管理器：默认可见
                )
                fig.add_trace(mesh)
        
        # 添加超挖线梯形槽
        if overbreak_data['valid'] and len(overbreak_data['vertices']) > 0:
            verts = overbreak_data['vertices']
            faces = overbreak_data['faces']
            
            if len(faces) > 0:
                i_list = [f[0] for f in faces]
                j_list = [f[1] for f in faces]
                k_list = [f[2] for f in faces]
                
                mesh = go.Mesh3d(
                    x=verts[:, 0],
                    y=verts[:, 1],
                    z=verts[:, 2],
                    i=i_list,
                    j=j_list,
                    k=k_list,
                    color='#e74c3c',
                    opacity=0.3,  # 超挖槽透明度降低（更透明）
                    name='超挖线梯形槽',
                    hoverinfo='name',
                    visible=True  # 图层管理器：默认可见
                )
                fig.add_trace(mesh)
        
        # 设置布局（包含图层管理器）
        fig.update_layout(
            title='航道三维地质模型 V4 - 特征点对齐',
            scene=dict(
                xaxis_title='X (m)',
                yaxis_title='Y (里程 m)',
                zaxis_title='Z (高程 m)',
                aspectmode='data'
            ),
            showlegend=True,
            legend=dict(
                x=0.02,  # 左侧位置
                y=0.98,  # 顶部位置
                bgcolor='rgba(255,255,255,0.8)',
                bordercolor='rgba(0,0,0,0.3)',
                borderwidth=1,
                font=dict(size=12),
                title=dict(text='图层管理器', font=dict(size=14, weight='bold'))
            ),
            # 添加图层切换按钮
            updatemenus=[
                dict(
                    type='buttons',
                    showactive=True,
                    y=0.05,
                    x=0.02,
                    xanchor='left',
                    yanchor='bottom',
                    buttons=[
                        dict(
                            label='全部显示',
                            method='update',
                            args=[{'visible': [True] * len(fig.data)}]
                        ),
                        dict(
                            label='仅地质层',
                            method='update',
                            args=[{'visible': [True, True, True, False, False]}]
                        ),
                        dict(
                            label='仅DMX',
                            method='update',
                            args=[{'visible': [False, False, False, True, False]}]
                        ),
                        dict(
                            label='仅超挖槽',
                            method='update',
                            args=[{'visible': [False, False, False, False, True]}]
                        ),
                        dict(
                            label='DMX+超挖',
                            method='update',
                            args=[{'visible': [False, False, False, True, True]}]
                        )
                    ]
                )
            ]
        )
        
        print(f"  Total traces in figure: {len(fig.data)}")
        for i, trace in enumerate(fig.data):
            print(f"    Trace {i}: type={trace.type if hasattr(trace, 'type') else 'unknown'}, name={trace.name if hasattr(trace, 'name') else 'unknown'}")
        
        fig.write_html(output_path)
        print(f"  Output: {output_path}")
    
    def build_and_export(self, output_path: str) -> str:
        """完整构建流程"""
        if not self.load_data():
            return ""
        
        dmx_data = self.build_dmx_ribbon()
        overbreak_data = self.build_overbreak_ribbon()
        category_data = self.build_category_volumes()
        
        self.export_to_html(output_path, category_data, dmx_data, overbreak_data)
        
        return output_path


def generate_ribbon_mesh_simple(line_a: np.ndarray, line_b: np.ndarray, 
                                num_samples: int = 50) -> Tuple[np.ndarray, List]:
    """简单Ribbon网格生成"""
    pts_a = resample_line_uniform(line_a, num_samples)
    pts_b = resample_line_uniform(line_b, num_samples)
    
    vertices = np.vstack([pts_a, pts_b])
    
    faces = []
    for i in range(num_samples - 1):
        p1 = i
        p2 = i + 1
        p3 = i + num_samples
        p4 = i + num_samples + 1
        
        faces.append([p1, p2, p3])
        faces.append([p2, p4, p3])
    
    return vertices, faces


def main():
    """主函数"""
    section_json = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    spine_json = r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    output_path = r'D:\断面算量平台\测试文件\feature_aligned_model_v4.html'
    
    builder = FeatureAlignedModelBuilderV4(
        section_json_path=section_json,
        spine_json_path=spine_json,
        num_samples_geo=50,
        n_slope=15,
        n_bottom=30,
        distance_threshold=50.0,
        area_ratio_threshold=0.3
    )
    
    builder.build_and_export(output_path)


if __name__ == '__main__':
    main()