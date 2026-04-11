# -*- coding: utf-8 -*-
"""
航道三维地质模型 V7 改进版 - 解决穿模问题

核心改进：
1. 保留V7的显式几何生成能力（点→线→面→体）
2. 只解决"穿模"问题：把"质心最近" → "带顺序约束的全局匹配"
3. 同一截面内按"Z顺序"排序
4. 只允许"相邻层"匹配
5. 禁止交叉匹配（order-preserving）

作者: @黄秉俊
日期: 2026-04-06
"""

import json
import numpy as np
import os
from typing import List, Dict, Tuple, Optional
import math
import sys
from collections import defaultdict

try:
    from shapely.geometry import Point, Polygon
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False
    print("[WARN] Shapely not available")

sys.path.insert(0, r'D:\断面算量平台\Code')


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


# ==================== 几何工具函数 ====================

def resample_polygon_equidistant(points: np.ndarray, n_samples: int = 64) -> np.ndarray:
    """等步长重采样多边形边界"""
    if len(points) < 3:
        return points
    
    dists = [0]
    for i in range(1, len(points)):
        d = np.linalg.norm(points[i] - points[i-1])
        dists.append(dists[-1] + d)
    
    d_close = np.linalg.norm(points[0] - points[-1])
    total_len = dists[-1] + d_close
    
    if total_len < 1e-6:
        return points
    
    step = total_len / n_samples
    new_points = []
    
    for i in range(n_samples):
        target_dist = i * step
        
        for j in range(len(dists) - 1):
            if dists[j] <= target_dist <= dists[j+1]:
                seg_len = dists[j+1] - dists[j]
                if seg_len < 1e-6:
                    new_points.append(points[j])
                else:
                    t = (target_dist - dists[j]) / seg_len
                    pt = points[j] + t * (points[j+1] - points[j])
                    new_points.append(pt)
                break
        else:
            if target_dist > dists[-1]:
                t = (target_dist - dists[-1]) / d_close if d_close > 1e-6 else 0
                pt = points[-1] + t * (points[0] - points[-1])
                new_points.append(pt)
    
    return np.array(new_points)


def normalize_polygon_orientation(points: np.ndarray) -> np.ndarray:
    """统一多边形绕向（逆时针）"""
    if len(points) < 3:
        return points
    
    area = 0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        area += points[i, 0] * points[j, 1]
        area -= points[j, 0] * points[i, 1]
    
    if area < 0:
        return points[::-1]
    return points


def calculate_polygon_area(points: np.ndarray) -> float:
    """计算多边形面积（2D投影）"""
    if len(points) < 3:
        return 0
    
    area = 0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        area += points[i, 0] * points[j, 1]
        area -= points[j, 0] * points[i, 1]
    
    return abs(area) / 2


def calculate_centroid(points: np.ndarray) -> Tuple[float, float]:
    """计算多边形质心（2D投影）"""
    if len(points) < 1:
        return (0, 0)
    
    return (np.mean(points[:, 0]), np.mean(points[:, 1]))


def resample_line_uniform(points: np.ndarray, num_samples: int) -> np.ndarray:
    """均匀重采样线段"""
    if len(points) < 2:
        return points
    
    dists = [0]
    for i in range(1, len(points)):
        d = np.linalg.norm(points[i] - points[i-1])
        dists.append(dists[-1] + d)
    
    total_len = dists[-1]
    if total_len < 1e-6:
        return points
    
    step = total_len / (num_samples - 1)
    new_points = [points[0]]
    
    for i in range(1, num_samples - 1):
        target_dist = i * step
        
        for j in range(len(dists) - 1):
            if dists[j] <= target_dist <= dists[j+1]:
                seg_len = dists[j+1] - dists[j]
                if seg_len < 1e-6:
                    new_points.append(points[j])
                else:
                    t = (target_dist - dists[j]) / seg_len
                    pt = points[j] + t * (points[j+1] - points[j])
                    new_points.append(pt)
                break
    
    new_points.append(points[-1])
    return np.array(new_points)


def smooth_longitudinal(vertices: np.ndarray, window_size: int = 3) -> np.ndarray:
    """纵向平滑顶点"""
    if len(vertices) < window_size:
        return vertices
    
    smoothed = np.copy(vertices)
    half_window = window_size // 2
    
    for i in range(half_window, len(vertices) - half_window):
        start = i - half_window
        end = i + half_window + 1
        smoothed[i] = np.mean(vertices[start:end], axis=0)
    
    return smoothed


# ==================== 核心改进：顺序约束匹配 ====================

def sort_polygons_by_depth(polys: List[Dict]) -> List[Dict]:
    """
    按深度（Z坐标）排序多边形
    
    关键：从上到下排序，确保拓扑顺序一致
    """
    if not polys:
        return polys
    
    # 计算每个多边形的平均Z值
    polys_with_z = []
    for poly in polys:
        pts = poly.get('points', np.array([]))
        if len(pts) >= 3:
            avg_z = np.mean(pts[:, 2])
            polys_with_z.append((avg_z, poly))
    
    # 按Z降序排列（从上到下）
    polys_with_z.sort(key=lambda x: x[0], reverse=True)
    
    return [p for _, p in polys_with_z]


def lateral_overlap(poly_a: Dict, poly_b: Dict) -> bool:
    """
    检查两个多边形在X方向是否有重叠
    
    防止左右错连
    """
    pts_a = poly_a.get('points', np.array([]))
    pts_b = poly_b.get('points', np.array([]))
    
    if len(pts_a) < 2 or len(pts_b) < 2:
        return False
    
    xa = pts_a[:, 0]
    xb = pts_b[:, 0]
    
    min_a, max_a = xa.min(), xa.max()
    min_b, max_b = xb.min(), xb.max()
    
    overlap = min(max_a, max_b) - max(min_a, min_b)
    return overlap > 0


def match_polygons_ordered(polys_a: List[Dict], polys_b: List[Dict],
                           dist_thresh: float = 50.0,
                           area_thresh: float = 0.3) -> List[Tuple[int, int]]:
    """
    带拓扑顺序约束的匹配（防穿模核心）
    
    核心原则：
    1. 同一截面内按Z顺序排序
    2. 只允许相邻层匹配
    3. 禁止交叉匹配（order-preserving）
    
    Args:
        polys_a: 截面A的多边形列表（已按Z排序）
        polys_b: 截面B的多边形列表（已按Z排序）
        dist_thresh: 质心距离阈值
        area_thresh: 面积相似性阈值
    
    Returns:
        List of (idx_a, idx_b) matched pairs
    """
    matches = []
    
    # 先按类别分组
    by_category_a = defaultdict(list)
    by_category_b = defaultdict(list)
    
    for i, poly in enumerate(polys_a):
        cat = poly.get('category', 'unknown')
        by_category_a[cat].append((i, poly))
    
    for j, poly in enumerate(polys_b):
        cat = poly.get('category', 'unknown')
        by_category_b[cat].append((j, poly))
    
    # 对每个类别分别匹配
    for category in by_category_a.keys():
        cat_polys_a = by_category_a[category]
        cat_polys_b = by_category_b.get(category, [])
        
        if not cat_polys_b:
            continue
        
        # 双指针匹配
        i, j = 0, 0
        
        while i < len(cat_polys_a) and j < len(cat_polys_b):
            idx_a, poly_a = cat_polys_a[i]
            idx_b, poly_b = cat_polys_b[j]
            
            # 计算质心距离
            ca = calculate_centroid(poly_a['points'])
            cb = calculate_centroid(poly_b['points'])
            dist = np.sqrt((ca[0] - cb[0])**2 + (ca[1] - cb[1])**2)
            
            # 计算面积相似性
            area_a = calculate_polygon_area(poly_a['points'])
            area_b = calculate_polygon_area(poly_b['points'])
            
            if area_a > 0 and area_b > 0:
                area_ratio = min(area_a, area_b) / max(area_a, area_b)
            else:
                area_ratio = 0
            
            # 检查横向重叠
            has_overlap = lateral_overlap(poly_a, poly_b)
            
            # 满足条件 -> 匹配
            if dist < dist_thresh and area_ratio > area_thresh and has_overlap:
                matches.append((idx_a, idx_b))
                i += 1
                j += 1
            else:
                # 不匹配 -> 决策移动方向（关键：按Z顺序）
                z_a = np.mean(poly_a['points'][:, 2])
                z_b = np.mean(poly_b['points'][:, 2])
                
                # 谁更"上层"，谁先跳过
                if z_a > z_b:
                    i += 1
                else:
                    j += 1
    
    return matches


def match_polygons_with_split_merge(polys_a: List[Dict], polys_b: List[Dict],
                                    dist_thresh: float = 50.0,
                                    area_thresh: float = 0.3) -> List[Tuple[int, int]]:
    """
    增强版匹配：处理分裂/合并情况
    
    情况：
    - A有1层，B有2层 -> 一对多
    - A有2层，B有1层 -> 多对一
    """
    matches = []
    
    # 先按类别分组
    by_category_a = defaultdict(list)
    by_category_b = defaultdict(list)
    
    for i, poly in enumerate(polys_a):
        cat = poly.get('category', 'unknown')
        by_category_a[cat].append((i, poly))
    
    for j, poly in enumerate(polys_b):
        cat = poly.get('category', 'unknown')
        by_category_b[cat].append((j, poly))
    
    for category in by_category_a.keys():
        cat_polys_a = by_category_a[category]
        cat_polys_b = by_category_b.get(category, [])
        
        if not cat_polys_b:
            continue
        
        i, j = 0, 0
        
        while i < len(cat_polys_a) and j < len(cat_polys_b):
            idx_a, poly_a = cat_polys_a[i]
            idx_b, poly_b = cat_polys_b[j]
            
            ca = calculate_centroid(poly_a['points'])
            cb = calculate_centroid(poly_b['points'])
            dist = np.sqrt((ca[0] - cb[0])**2 + (ca[1] - cb[1])**2)
            
            area_a = calculate_polygon_area(poly_a['points'])
            area_b = calculate_polygon_area(poly_b['points'])
            area_ratio = min(area_a, area_b) / max(area_a, area_b) if max(area_a, area_b) > 0 else 0
            
            has_overlap = lateral_overlap(poly_a, poly_b)
            
            if dist < dist_thresh and area_ratio > area_thresh and has_overlap:
                matches.append((idx_a, idx_b))
                i += 1
                j += 1
            else:
                # 尝试一对多（分裂情况）
                if j + 1 < len(cat_polys_b):
                    idx_b2, poly_b2 = cat_polys_b[j + 1]
                    cb2 = calculate_centroid(poly_b2['points'])
                    dist2 = np.sqrt((ca[0] - cb2[0])**2 + (ca[1] - cb2[1])**2)
                    
                    if dist2 < dist_thresh and lateral_overlap(poly_a, poly_b2):
                        # 一对多匹配
                        matches.append((idx_a, idx_b))
                        matches.append((idx_a, idx_b2))
                        i += 1
                        j += 2
                        continue
                
                # 尝试多对一（合并情况）
                if i + 1 < len(cat_polys_a):
                    idx_a2, poly_a2 = cat_polys_a[i + 1]
                    ca2 = calculate_centroid(poly_a2['points'])
                    dist2 = np.sqrt((ca2[0] - cb[0])**2 + (ca2[1] - cb[1])**2)
                    
                    if dist2 < dist_thresh and lateral_overlap(poly_a2, poly_b):
                        # 多对一匹配
                        matches.append((idx_a, idx_b))
                        matches.append((idx_a2, idx_b))
                        i += 2
                        j += 1
                        continue
                
                # 按Z顺序决定移动方向
                z_a = np.mean(poly_a['points'][:, 2])
                z_b = np.mean(poly_b['points'][:, 2])
                
                if z_a > z_b:
                    i += 1
                else:
                    j += 1
    
    return matches


# ==================== 体积生成函数 ====================

def generate_volume_mesh(poly_a: np.ndarray, poly_b: np.ndarray,
                         num_samples: int = 64) -> Tuple[np.ndarray, List]:
    """为两个闭合多边形生成体积网格（Lofting）"""
    poly_a = normalize_polygon_orientation(poly_a)
    poly_b = normalize_polygon_orientation(poly_b)
    
    pts_a = resample_polygon_equidistant(poly_a, num_samples)
    pts_b = resample_polygon_equidistant(poly_b, num_samples)
    
    vertices = np.vstack([pts_a, pts_b])
    
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
                          num_samples: int = 64) -> Tuple[np.ndarray, List]:
    """生成地层消失时的退化体积（向质心收缩）"""
    pts = resample_polygon_equidistant(poly, num_samples)
    centroid_pt = np.array([centroid[0], centroid[1], np.mean(poly[:, 2])])
    vertices = np.vstack([pts, centroid_pt.reshape(1, 3)])
    
    faces = []
    centroid_idx = num_samples
    for i in range(num_samples):
        next_i = (i + 1) % num_samples
        faces.append([i, next_i, centroid_idx])
    
    return vertices, faces


def generate_dmx_ribbon(section_data_list: List[Dict], 
                        num_samples: int = 60) -> Tuple[np.ndarray, List]:
    """构建DMX Ribbon曲面"""
    if len(section_data_list) < 2:
        return np.array([]), []
    
    all_lines = []
    for data in section_data_list:
        if data.get('dmx_3d') is not None and len(data['dmx_3d']) >= 2:
            all_lines.append(data['dmx_3d'])
    
    if len(all_lines) < 2:
        return np.array([]), []
    
    resampled_lines = [resample_line_uniform(line, num_samples) for line in all_lines]
    
    all_vertices = []
    for line in resampled_lines:
        for pt in line:
            all_vertices.append(pt)
    
    vertices = np.array(all_vertices)
    
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


def resample_trench_segmented(points: np.ndarray, 
                               n_slope: int = 15, 
                               n_bottom: int = 30) -> np.ndarray:
    """分段重采样梯形槽超挖线"""
    if len(points) < 4:
        return points
    
    z_values = points[:, 2]
    min_z = np.min(z_values)
    z_tolerance = 0.5
    
    bottom_mask = z_values < min_z + z_tolerance
    bottom_pts = points[bottom_mask]
    slope_pts = points[~bottom_mask]
    
    total_points = n_slope * 2 + n_bottom
    
    if len(bottom_pts) < 2 or len(slope_pts) < 2:
        return resample_line_uniform(points, total_points)
    
    slope_pts = slope_pts[np.argsort(slope_pts[:, 0])]
    half_slope = len(slope_pts) // 2
    
    left_slope = slope_pts[:half_slope]
    right_slope = slope_pts[half_slope:]
    
    left_resampled = resample_line_uniform(left_slope, n_slope) if len(left_slope) >= 2 else np.tile(left_slope[0] if len(left_slope) > 0 else points[0], (n_slope, 1))
    bottom_resampled = resample_line_uniform(bottom_pts, n_bottom) if len(bottom_pts) >= 2 else np.tile(bottom_pts[0] if len(bottom_pts) > 0 else points[0], (n_bottom, 1))
    right_resampled = resample_line_uniform(right_slope, n_slope) if len(right_slope) >= 2 else np.tile(right_slope[0] if len(right_slope) > 0 else points[-1], (n_slope, 1))
    
    combined = np.vstack([left_resampled, bottom_resampled, right_resampled])
    
    return combined


def generate_trench_ribbon(section_data_list: List[Dict], 
                           n_slope: int = 15, 
                           n_bottom: int = 30,
                           apply_smooth: bool = True) -> Tuple[np.ndarray, List]:
    """构建梯形槽Ribbon曲面"""
    if len(section_data_list) < 2:
        return np.array([]), []
    
    total_points = n_slope * 2 + n_bottom
    
    all_lines = []
    valid_section_count = 0
    for data in section_data_list:
        overbreak_3d = data.get('overbreak_3d', [])
        if overbreak_3d:
            longest = max(overbreak_3d, key=lambda x: len(x))
            
            if len(longest) >= 4:
                all_lines.append(np.array(longest))
                valid_section_count += 1
    
    print(f"  Valid overbreak lines: {valid_section_count}")
    
    if len(all_lines) < 2:
        return np.array([]), []
    
    resampled_lines = []
    expected_shape = total_points
    for i, line in enumerate(all_lines):
        resampled = resample_trench_segmented(line, n_slope, n_bottom)
        if resampled.shape[0] != expected_shape:
            if resampled.shape[0] < expected_shape:
                padding = np.tile(resampled[-1], (expected_shape - resampled.shape[0], 1))
                resampled = np.vstack([resampled, padding])
            elif resampled.shape[0] > expected_shape:
                resampled = resampled[:expected_shape]
        resampled_lines.append(resampled)
    
    vertices_3d = np.array(resampled_lines)
    
    if apply_smooth and vertices_3d.shape[0] >= 3:
        vertices_3d = smooth_longitudinal(vertices_3d, window_size=3)
    
    all_vertices = []
    for line in vertices_3d:
        for pt in line:
            all_vertices.append(pt)
    
    vertices = np.array(all_vertices)
    
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


# ==================== V7改进版模型构建器 ====================

class GeologyModelBuilderV7Improved:
    """
    V7改进版地质模型构建器
    
    核心改进：只解决穿模问题，保留V7的显式几何生成能力
    
    改进点：
    1. 按Z顺序排序多边形
    2. 使用顺序约束匹配（order-preserving）
    3. 横向重叠检查
    4. 处理分裂/合并情况
    """
    
    def __init__(self, section_json_path: str, spine_json_path: str):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        
        self.sections_data = None
        self.spine_matches = None
        self.sections_3d = []
        
        self.v7_meshes = {}
    
    def load_data(self) -> bool:
        """加载截面和脊梁数据"""
        print("\n=== Loading Data ===")
        
        try:
            with open(self.section_json_path, 'r', encoding='utf-8') as f:
                self.sections_data = json.load(f)
            print(f"  Sections loaded: {len(self.sections_data.get('sections', []))}")
            
            with open(self.spine_json_path, 'r', encoding='utf-8') as f:
                self.spine_matches = json.load(f)
            print(f"  Spine matches loaded: {len(self.spine_matches.get('matches', []))}")
            
            return True
        except Exception as e:
            print(f"  [ERROR] Failed to load data: {e}")
            return False
    
    def _get_interpolated_spine_match(self, station_value: float) -> Dict:
        """插值获取脊梁匹配数据"""
        matches = self.spine_matches.get('matches', [])
        if not matches:
            return {}
        
        stations = [m.get('station_value', 0) for m in matches]
        
        if station_value <= min(stations):
            return matches[0]
        if station_value >= max(stations):
            return matches[-1]
        
        for i in range(len(stations) - 1):
            if stations[i] <= station_value <= stations[i+1]:
                t = (station_value - stations[i]) / (stations[i+1] - stations[i])
                match_a = matches[i]
                match_b = matches[i+1]
                
                interpolated = {}
                for key in ['spine_x', 'spine_y', 'tangent_angle']:
                    val_a = match_a.get(key, 0)
                    val_b = match_b.get(key, 0)
                    interpolated[key] = val_a + t * (val_b - val_a)
                
                return interpolated
        
        return matches[-1]
    
    def _transform_section_to_3d(self, section: Dict) -> Dict:
        """将截面数据转换为3D坐标"""
        station_value = section.get('station_value', 0)
        spine_match = self._get_interpolated_spine_match(station_value)
        
        if not spine_match:
            return None
        
        spine_x = spine_match.get('spine_x', 0)
        spine_y = spine_match.get('spine_y', 0)
        tangent_angle = spine_match.get('tangent_angle', 0)
        rotation_angle = tangent_angle + math.pi / 2
        
        l1_ref = section.get('l1_ref_point', {})
        ref_x = l1_ref.get('ref_x', 0)
        ref_y = l1_ref.get('ref_y', 0)
        
        # DMX转换
        dmx_2d = section.get('dmx_points', [])
        dmx_3d = []
        for pt in dmx_2d:
            cad_x, cad_y = pt[0], pt[1]
            eng_x, eng_y, z = transform_to_spine_aligned(
                cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
            )
            dmx_3d.append([eng_x, eng_y, z])
        
        # 超挖线转换
        overbreak_2d = section.get('overbreak_points', [])
        overbreak_3d = []
        for seg in overbreak_2d:
            seg_3d = []
            for pt in seg:
                cad_x, cad_y = pt[0], pt[1]
                eng_x, eng_y, z = transform_to_spine_aligned(
                    cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                )
                seg_3d.append([eng_x, eng_y, z])
            overbreak_3d.append(seg_3d)
        
        # 地质层转换
        fill_boundaries = section.get('fill_boundaries', {})
        geology_3d = {}
        
        for layer_name, polygons in fill_boundaries.items():
            category = categorize_layer(layer_name)
            if category is None:
                continue
            
            if category not in geology_3d:
                geology_3d[category] = []
            
            for poly in polygons:
                poly_3d = []
                for pt in poly:
                    cad_x, cad_y = pt[0], pt[1]
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    poly_3d.append([eng_x, eng_y, z])
                
                geology_3d[category].append({
                    'layer_name': layer_name,
                    'category': category,
                    'points': np.array(poly_3d)
                })
        
        return {
            'station_value': station_value,
            'dmx_3d': np.array(dmx_3d) if dmx_3d else None,
            'overbreak_3d': overbreak_3d,
            'geology_3d': geology_3d,
            'spine_match': spine_match
        }
    
    def build_model(self) -> Dict:
        """完整构建流程"""
        print("\n" + "="*60)
        print("V7 Improved Geology Model Builder")
        print("Core Improvement: Order-Preserving Matching (No Penetration)")
        print("="*60)
        
        if not self.load_data():
            return {}
        
        # 转换所有截面到3D
        print("\n=== Transforming Sections to 3D ===")
        self.sections_3d = []
        sections = self.sections_data.get('sections', [])
        
        for section in sections:
            section_3d = self._transform_section_to_3d(section)
            if section_3d:
                self.sections_3d.append(section_3d)
        
        print(f"  Sections transformed: {len(self.sections_3d)}")
        
        if not self.sections_3d:
            return {}
        
        # 构建DMX Ribbon
        print("\n=== Building DMX Ribbon ===")
        dmx_vertices, dmx_faces = generate_dmx_ribbon(self.sections_3d, num_samples=60)
        self.v7_meshes['dmx'] = {
            'vertices': dmx_vertices,
            'faces': dmx_faces,
            'color': '#3498db'
        }
        print(f"  DMX ribbon: {len(dmx_vertices)} vertices, {len(dmx_faces)} faces")
        
        # 构建超挖线Ribbon
        print("\n=== Building Overbreak Ribbon ===")
        trench_vertices, trench_faces = generate_trench_ribbon(self.sections_3d, n_slope=15, n_bottom=30)
        self.v7_meshes['overbreak'] = {
            'vertices': trench_vertices,
            'faces': trench_faces,
            'color': '#e74c3c'
        }
        print(f"  Overbreak ribbon: {len(trench_vertices)} vertices, {len(trench_faces)} faces")
        
        # 构建地质体积（核心改进）
        geology_volumes = self._build_geological_volumes_improved()
        self.v7_meshes['geology'] = geology_volumes
        
        return self.v7_meshes
    
    def _build_geological_volumes_improved(self) -> Dict[str, Dict]:
        """
        使用改进的匹配算法生成地质体积
        
        核心改进：
        1. 按Z顺序排序多边形
        2. 使用顺序约束匹配
        3. 处理分裂/合并情况
        """
        print("\n=== Building Geological Volumes (Improved Matching) ===")
        print("  Using order-preserving matching to prevent penetration")
        
        volumes = {'mud_fill': [], 'clay': [], 'sand_and_gravel': []}
        
        # 收集所有截面的地质多边形
        all_section_geology = []
        for section in self.sections_3d:
            geology = section.get('geology_3d', {})
            all_section_geology.append(geology)
        
        # 遍历相邻截面
        for i in range(len(all_section_geology) - 1):
            geology_a = all_section_geology[i]
            geology_b = all_section_geology[i + 1]
            
            for category in ['mud_fill', 'clay', 'sand_and_gravel']:
                polys_a = geology_a.get(category, [])
                polys_b = geology_b.get(category, [])
                
                if not polys_a and not polys_b:
                    continue
                
                # 关键改进1：按Z顺序排序
                polys_a_sorted = sort_polygons_by_depth(polys_a)
                polys_b_sorted = sort_polygons_by_depth(polys_b)
                
                # 关键改进2：使用顺序约束匹配
                matches = match_polygons_with_split_merge(
                    polys_a_sorted, polys_b_sorted,
                    dist_thresh=50.0,
                    area_thresh=0.3
                )
                
                # 生成体积mesh
                for idx_a, idx_b in matches:
                    pts_a = polys_a_sorted[idx_a]['points']
                    pts_b = polys_b_sorted[idx_b]['points']
                    
                    if len(pts_a) >= 3 and len(pts_b) >= 3:
                        vertices, faces = generate_volume_mesh(pts_a, pts_b, num_samples=64)
                        volumes[category].append({
                            'vertices': vertices,
                            'faces': faces,
                            'section_pair': (i, i+1)
                        })
                
                # 处理地层消失（taper volume）
                matched_a_indices = set(m[0] for m in matches)
                for idx_a, poly_a in enumerate(polys_a_sorted):
                    if idx_a not in matched_a_indices and len(poly_a['points']) >= 3:
                        pts_a = poly_a['points']
                        centroid = calculate_centroid(pts_a)
                        vertices, faces = generate_taper_volume(pts_a, centroid, num_samples=64)
                        volumes[category].append({
                            'vertices': vertices,
                            'faces': faces,
                            'section_pair': (i, i+1),
                            'is_taper': True
                        })
        
        # 统计
        print("\n  Volume Statistics:")
        for cat, vol_list in volumes.items():
            total_verts = sum(len(v['vertices']) for v in vol_list)
            total_faces = sum(len(v['faces']) for v in vol_list)
            cat_name = LAYER_CATEGORIES[cat]['name_cn']
            print(f"    {cat_name}: {len(vol_list)} volumes, {total_verts} vertices, {total_faces} faces")
        
        return volumes
    
    def export_to_html(self, output_path: str) -> None:
        """导出为Plotly HTML"""
        print(f"\n=== Exporting to HTML: {output_path} ===")
        
        try:
            import plotly.graph_objects as go
        except ImportError:
            print("  [ERROR] Plotly not available")
            return
        
        fig = go.Figure()
        
        # DMX Ribbon
        if 'dmx' in self.v7_meshes:
            verts = self.v7_meshes['dmx']['vertices']
            faces = self.v7_meshes['dmx']['faces']
            
            if len(verts) > 0 and len(faces) > 0:
                i = [f[0] for f in faces]
                j = [f[1] for f in faces]
                k = [f[2] for f in faces]
                
                fig.add_trace(go.Mesh3d(
                    x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
                    i=i, j=j, k=k,
                    color='#3498db',
                    opacity=0.5,
                    name='DMX Ribbon',
                    legendgroup='dmx'
                ))
        
        # Overbreak Ribbon
        if 'overbreak' in self.v7_meshes:
            verts = self.v7_meshes['overbreak']['vertices']
            faces = self.v7_meshes['overbreak']['faces']
            
            if len(verts) > 0 and len(faces) > 0:
                i = [f[0] for f in faces]
                j = [f[1] for f in faces]
                k = [f[2] for f in faces]
                
                fig.add_trace(go.Mesh3d(
                    x=verts[:, 0], y=verts[:, 1], z=verts[:, 2],
                    i=i, j=j, k=k,
                    color='#e74c3c',
                    opacity=0.5,
                    name='Overbreak Ribbon',
                    legendgroup='overbreak'
                ))
        
        # 地质体积
        colors = {
            'mud_fill': '#7f8c8d',
            'clay': '#A52A2A',
            'sand_and_gravel': '#f1c40f'
        }
        
        for category, vol_list in self.v7_meshes.get('geology', {}).items():
            all_verts = []
            all_faces = []
            vertex_offset = 0
            
            for vol in vol_list:
                verts = vol['vertices']
                faces = vol['faces']
                
                all_verts.extend(verts)
                for f in faces:
                    all_faces.append([f[0] + vertex_offset, f[1] + vertex_offset, f[2] + vertex_offset])
                
                vertex_offset += len(verts)
            
            if all_verts:
                all_verts = np.array(all_verts)
                i = [f[0] for f in all_faces]
                j = [f[1] for f in all_faces]
                k = [f[2] for f in all_faces]
                
                cat_name = LAYER_CATEGORIES[category]['name_cn']
                
                fig.add_trace(go.Mesh3d(
                    x=all_verts[:, 0], y=all_verts[:, 1], z=all_verts[:, 2],
                    i=i, j=j, k=k,
                    color=colors.get(category, '#888888'),
                    opacity=0.9,
                    name=f'{cat_name} ({len(vol_list)} volumes)',
                    legendgroup=category
                ))
        
        # 布局
        fig.update_layout(
            title='V7 Improved Geology Model (Order-Preserving Matching)',
            scene=dict(
                xaxis_title='X (East)',
                yaxis_title='Y (North)',
                zaxis_title='Z (Elevation)',
                aspectmode='data'
            ),
            legend=dict(x=0.02, y=0.98),
            margin=dict(l=0, r=0, t=50, b=0)
        )
        
        fig.write_html(output_path)
        print(f"  HTML saved: {output_path}")
        
        file_size = os.path.getsize(output_path) / 1024 / 1024
        print(f"  File size: {file_size:.2f} MB")
    
    def build_and_export(self, output_path: str) -> str:
        """一键构建并导出"""
        self.build_model()
        self.export_to_html(output_path)
        return output_path


# ==================== 主函数 ====================

def main():
    """测试V7改进版模型构建器"""
    import argparse
    
    parser = argparse.ArgumentParser(description='V7 Improved Geology Model Builder')
    parser.add_argument('--section-json', type=str, required=True, help='Section JSON path')
    parser.add_argument('--spine-json', type=str, required=True, help='Spine JSON path')
    parser.add_argument('--output', type=str, default='geology_model_v7_improved.html', help='Output HTML path')
    
    args = parser.parse_args()
    
    builder = GeologyModelBuilderV7Improved(args.section_json, args.spine_json)
    output_path = builder.build_and_export(args.output)
    
    if output_path:
        print(f"\n[SUCCESS] Model exported to: {output_path}")
    else:
        print(f"\n[FAILED] Model build failed")


if __name__ == '__main__':
    main()