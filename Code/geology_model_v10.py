# -*- coding: utf-8 -*-
"""
航道三维地质模型 V10 - V7几何骨架 + 体素分类优化

核心架构：
V7（几何骨架）→ Voxelization → V9（分类优化）→ Marching Cubes（可选）

关键特性：
1. 保留V7的显式坐标生成体系（点→线→面→体）
2. 保留V7的拓扑一致性（截面间点对点连接）
3. 将V7 mesh转换为voxel网格
4. 使用polygon.contains进行体素分类（而非centroid距离）
5. 可选Marching Cubes提取优化后的网格

作者: @黄秉俊
日期: 2026-04-06
"""

import json
import numpy as np
import os
from typing import List, Dict, Tuple, Optional
import math
import sys
from scipy.spatial import cKDTree
from scipy.ndimage import gaussian_filter
from collections import defaultdict

# Shapely用于点在多边形内判断
try:
    from shapely.geometry import Point, Polygon
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False
    print("[WARN] Shapely not available, polygon containment check disabled")

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
    """坐标转换：CAD局部坐标 -> 工程坐标
    
    关键：Z = cad_y - ref_y（高程）
    只旋转dx，不旋转dy（dy变成Z）
    """
    z = cad_y - ref_y
    dx = cad_x - ref_x
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    rotated_dx = dx * cos_a
    rotated_dy = dx * sin_a
    eng_x = spine_x + rotated_dx
    eng_y = spine_y + rotated_dy
    return eng_x, eng_y, z


# ==================== V7几何骨架函数 ====================

def resample_polygon_equidistant(points: np.ndarray, n_samples: int = 64) -> np.ndarray:
    """等步长重采样多边形边界"""
    if len(points) < 3:
        return points
    
    # 计算累积周长
    dists = [0]
    for i in range(1, len(points)):
        d = np.linalg.norm(points[i] - points[i-1])
        dists.append(dists[-1] + d)
    
    # 闭合
    d_close = np.linalg.norm(points[0] - points[-1])
    total_len = dists[-1] + d_close
    
    if total_len < 1e-6:
        return points
    
    # 等步长采样
    step = total_len / n_samples
    new_points = []
    
    for i in range(n_samples):
        target_dist = i * step
        
        # 找到对应的原始点区间
        for j in range(len(dists) - 1):
            if dists[j] <= target_dist <= dists[j+1]:
                # 线性插值
                seg_len = dists[j+1] - dists[j]
                if seg_len < 1e-6:
                    new_points.append(points[j])
                else:
                    t = (target_dist - dists[j]) / seg_len
                    pt = points[j] + t * (points[j+1] - points[j])
                    new_points.append(pt)
                break
        else:
            # 处理闭合段
            if target_dist > dists[-1]:
                t = (target_dist - dists[-1]) / d_close if d_close > 1e-6 else 0
                pt = points[-1] + t * (points[0] - points[-1])
                new_points.append(pt)
    
    return np.array(new_points)


def normalize_polygon_orientation(points: np.ndarray) -> np.ndarray:
    """统一多边形绕向（逆时针）"""
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
    
    cx = np.mean(points[:, 0])
    cy = np.mean(points[:, 1])
    return (cx, cy)


def match_geological_polygons_with_similarity(
    polygons_a: List[Dict], 
    polygons_b: List[Dict],
    area_threshold: float = 0.3,
    centroid_threshold: float = 50.0
) -> List[Tuple[int, int]]:
    """
    匹配两个截面的地质多边形（基于面积相似性和质心距离）
    
    Returns:
        List of (idx_a, idx_b) matched pairs
    """
    matches = []
    
    for i, poly_a in enumerate(polygons_a):
        best_match = -1
        best_score = 0
        
        cat_a = poly_a.get('category', '')
        pts_a = np.array(poly_a.get('points', []))
        
        if len(pts_a) < 3:
            continue
        
        area_a = calculate_polygon_area(pts_a)
        cent_a = calculate_centroid(pts_a)
        
        for j, poly_b in enumerate(polygons_b):
            cat_b = poly_b.get('category', '')
            
            # 必须同类别
            if cat_a != cat_b:
                continue
            
            pts_b = np.array(poly_b.get('points', []))
            if len(pts_b) < 3:
                continue
            
            area_b = calculate_polygon_area(pts_b)
            cent_b = calculate_centroid(pts_b)
            
            # 面积相似性
            area_ratio = min(area_a, area_b) / max(area_a, area_b) if max(area_a, area_b) > 0 else 0
            
            # 质心距离
            cent_dist = np.sqrt((cent_a[0] - cent_b[0])**2 + (cent_a[1] - cent_b[1])**2)
            
            # 综合评分
            if area_ratio > area_threshold and cent_dist < centroid_threshold:
                score = area_ratio * (1 - cent_dist / centroid_threshold)
                if score > best_score:
                    best_score = score
                    best_match = j
        
        if best_match >= 0:
            matches.append((i, best_match))
    
    return matches


def generate_volume_mesh(poly_a: np.ndarray, poly_b: np.ndarray,
                         num_samples: int = 64) -> Tuple[np.ndarray, List]:
    """
    为两个闭合多边形生成体积网格（Lofting）
    
    关键：点对点连接，保持拓扑一致性
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
    pts = resample_polygon_equidistant(poly, num_samples)
    centroid_pt = np.array([centroid[0], centroid[1], np.mean(poly[:, 2])])
    vertices = np.vstack([pts, centroid_pt.reshape(1, 3)])
    
    faces = []
    centroid_idx = num_samples
    for i in range(num_samples):
        next_i = (i + 1) % num_samples
        faces.append([i, next_i, centroid_idx])
    
    return vertices, faces


def resample_line_uniform(points: np.ndarray, num_samples: int) -> np.ndarray:
    """均匀重采样线段"""
    if len(points) < 2:
        return points
    
    # 计算累积长度
    dists = [0]
    for i in range(1, len(points)):
        d = np.linalg.norm(points[i] - points[i-1])
        dists.append(dists[-1] + d)
    
    total_len = dists[-1]
    if total_len < 1e-6:
        return points
    
    # 均匀采样
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
    """
    分段重采样梯形槽超挖线
    
    Args:
        points: 超挖线点集 (N, 3)
        n_slope: 每侧斜坡采样点数
        n_bottom: 底段采样点数
    
    Returns:
        重采样后的点集 (n_slope*2 + n_bottom, 3)
    """
    if len(points) < 4:
        return points
    
    # 找底部角点（Z最低的点）
    z_values = points[:, 2]
    min_z = np.min(z_values)
    z_tolerance = 0.5
    
    # 分离斜坡段和底段
    bottom_mask = z_values < min_z + z_tolerance
    bottom_pts = points[bottom_mask]
    slope_pts = points[~bottom_mask]
    
    total_points = n_slope * 2 + n_bottom
    
    if len(bottom_pts) < 2 or len(slope_pts) < 2:
        # 简单均匀采样
        return resample_line_uniform(points, total_points)
    
    # 按X坐标排序斜坡点，分成左右两侧
    slope_pts = slope_pts[np.argsort(slope_pts[:, 0])]
    half_slope = len(slope_pts) // 2
    
    left_slope = slope_pts[:half_slope]
    right_slope = slope_pts[half_slope:]
    
    # 重采样各段
    left_resampled = resample_line_uniform(left_slope, n_slope) if len(left_slope) >= 2 else np.tile(left_slope[0] if len(left_slope) > 0 else points[0], (n_slope, 1))
    bottom_resampled = resample_line_uniform(bottom_pts, n_bottom) if len(bottom_pts) >= 2 else np.tile(bottom_pts[0] if len(bottom_pts) > 0 else points[0], (n_bottom, 1))
    right_resampled = resample_line_uniform(right_slope, n_slope) if len(right_slope) >= 2 else np.tile(right_slope[0] if len(right_slope) > 0 else points[-1], (n_slope, 1))
    
    # 组合
    combined = np.vstack([left_resampled, bottom_resampled, right_resampled])
    
    return combined


def generate_trench_ribbon(section_data_list: List[Dict],
                           n_slope: int = 15,
                           n_bottom: int = 30) -> Tuple[np.ndarray, List]:
    """构建梯形槽Ribbon曲面（使用V7逻辑）"""
    if len(section_data_list) < 2:
        return np.array([]), []
    
    total_points = n_slope * 2 + n_bottom
    
    # 收集所有断面的超挖线（选择最长的）
    all_lines = []
    valid_section_count = 0
    for data in section_data_list:
        overbreak_3d = data.get('overbreak_3d', [])
        if overbreak_3d:
            # 选择最长的超挖线段
            longest = max(overbreak_3d, key=lambda x: len(x))
            
            # 检查是否有足够的点
            if len(longest) >= 4:
                all_lines.append(np.array(longest))
                valid_section_count += 1
    
    print(f"  Valid overbreak lines: {valid_section_count}")
    
    if len(all_lines) < 2:
        return np.array([]), []
    
    # 分段重采样每条超挖线
    resampled_lines = []
    expected_shape = total_points
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
    
    # 展平为顶点列表
    all_vertices = []
    for line in resampled_lines:
        for pt in line:
            all_vertices.append(pt)
    
    vertices = np.array(all_vertices)
    
    # 构造三角面片
    faces = []
    n_sections = len(resampled_lines)
    n_pts = total_points
    
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


# ==================== V10模型构建器 ====================

class GeologyModelBuilderV10:
    """
    V10地质模型构建器
    
    核心架构：V7几何骨架 + 体素分类优化
    
    流程：
    1. 使用V7的显式几何生成mesh（真实坐标）
    2. 将mesh转换为voxel网格
    3. 使用polygon.contains进行体素分类
    4. 可选Marching Cubes提取优化后的网格
    """
    
    def __init__(self, section_json_path: str, spine_json_path: str,
                 voxel_resolution: Tuple[int, int, int] = (100, 100, 30)):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.voxel_resolution = voxel_resolution
        
        self.sections_data = None
        self.spine_matches = None
        self.sections_3d = []
        
        # 分类ID映射
        self.category_ids = {'background': 0, 'mud_fill': 1, 'clay': 2, 'sand_and_gravel': 3}
        self.category_names = {0: 'background', 1: 'mud_fill', 2: 'clay', 3: 'sand_and_gravel'}
        
        # V7几何骨架数据
        self.v7_meshes = {}
        
        # 体素数据
        self.voxel_grid = None
        self.label_grid = None
        self.grid_bounds = None
    
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
        """
        将截面数据转换为3D坐标
        
        关键修复：
        - 使用ref_x/ref_y（而非x/y）
        - 使用tangent_angle + pi/2作为旋转角
        """
        station_value = section.get('station_value', 0)
        spine_match = self._get_interpolated_spine_match(station_value)
        
        if not spine_match:
            return None
        
        spine_x = spine_match.get('spine_x', 0)
        spine_y = spine_match.get('spine_y', 0)
        tangent_angle = spine_match.get('tangent_angle', 0)
        rotation_angle = tangent_angle + math.pi / 2
        
        # 修复：使用正确的字段名 ref_x/ref_y
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
    
    def build_v7_geometry_skeleton(self) -> Dict:
        """
        Step 1: 使用V7的显式几何生成mesh骨架
        
        关键：保留V7的坐标生成体系（点→线→面→体）
        """
        print("\n=== Step 1: Building V7 Geometry Skeleton ===")
        
        # 转换所有截面到3D
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
        dmx_vertices, dmx_faces = generate_dmx_ribbon(self.sections_3d, num_samples=60)
        self.v7_meshes['dmx'] = {
            'vertices': dmx_vertices,
            'faces': dmx_faces,
            'color': '#3498db'
        }
        print(f"  DMX ribbon: {len(dmx_vertices)} vertices, {len(dmx_faces)} faces")
        
        # 构建超挖线Ribbon
        trench_vertices, trench_faces = generate_trench_ribbon(self.sections_3d, n_slope=15, n_bottom=30)
        self.v7_meshes['overbreak'] = {
            'vertices': trench_vertices,
            'faces': trench_faces,
            'color': '#e74c3c'
        }
        print(f"  Overbreak ribbon: {len(trench_vertices)} vertices, {len(trench_faces)} faces")
        
        # 构建地质体积（V7核心逻辑）
        geology_volumes = self._build_geological_volumes_v7()
        self.v7_meshes['geology'] = geology_volumes
        
        return self.v7_meshes
    
    def _build_geological_volumes_v7(self) -> Dict[str, Dict]:
        """
        使用V7的显式几何生成地质体积
        
        关键：
        1. 截面间点对点连接（拓扑一致）
        2. 使用match_geological_polygons_with_similarity进行匹配
        3. 生成taper_volume处理地层消失
        """
        print("\n  Building Geological Volumes (V7 logic)...")
        
        volumes = {'mud_fill': [], 'clay': [], 'sand_and_gravel': []}
        
        # 按类别收集所有截面的地质多边形
        all_section_geology = []
        for section in self.sections_3d:
            geology = section.get('geology_3d', {})
            all_section_geology.append(geology)
        
        # 遍历相邻截面，匹配并生成体积
        for i in range(len(all_section_geology) - 1):
            geology_a = all_section_geology[i]
            geology_b = all_section_geology[i + 1]
            
            for category in ['mud_fill', 'clay', 'sand_and_gravel']:
                polys_a = geology_a.get(category, [])
                polys_b = geology_b.get(category, [])
                
                if not polys_a and not polys_b:
                    continue
                
                # 匹配多边形
                matches = match_geological_polygons_with_similarity(polys_a, polys_b)
                
                # 生成体积mesh
                for idx_a, idx_b in matches:
                    pts_a = polys_a[idx_a]['points']
                    pts_b = polys_b[idx_b]['points']
                    
                    if len(pts_a) >= 3 and len(pts_b) >= 3:
                        vertices, faces = generate_volume_mesh(pts_a, pts_b, num_samples=64)
                        volumes[category].append({
                            'vertices': vertices,
                            'faces': faces,
                            'section_pair': (i, i+1)
                        })
                
                # 处理地层消失（taper volume）
                # 在A截面存在但B截面消失的多边形
                matched_a_indices = set(m[0] for m in matches)
                for idx_a, poly_a in enumerate(polys_a):
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
        for cat, vol_list in volumes.items():
            total_verts = sum(len(v['vertices']) for v in vol_list)
            total_faces = sum(len(v['faces']) for v in vol_list)
            print(f"    {cat}: {len(vol_list)} volumes, {total_verts} vertices, {total_faces} faces")
        
        return volumes
    
    def voxelize_v7_meshes(self) -> Dict:
        """
        Step 2: 将V7 mesh转换为voxel网格
        
        关键：保留V7的真实坐标，只是转换为体素表示
        """
        print("\n=== Step 2: Voxelize V7 Meshes ===")
        
        # 收集所有顶点确定边界
        all_vertices = []
        
        if 'dmx' in self.v7_meshes:
            all_vertices.extend(self.v7_meshes['dmx']['vertices'])
        
        if 'overbreak' in self.v7_meshes:
            all_vertices.extend(self.v7_meshes['overbreak']['vertices'])
        
        for cat_volumes in self.v7_meshes.get('geology', {}).values():
            for vol in cat_volumes:
                all_vertices.extend(vol['vertices'])
        
        if not all_vertices:
            print("  [ERROR] No vertices found")
            return {}
        
        all_vertices = np.array(all_vertices)
        
        # 计算边界
        x_min, x_max = np.min(all_vertices[:, 0]), np.max(all_vertices[:, 0])
        y_min, y_max = np.min(all_vertices[:, 1]), np.max(all_vertices[:, 1])
        z_min, z_max = np.min(all_vertices[:, 2]), np.max(all_vertices[:, 2])
        
        print(f"  Bounds: X({x_min:.1f}~{x_max:.1f}), Y({y_min:.1f}~{y_max:.1f}), Z({z_min:.1f}~{z_max:.1f})")
        
        # 创建体素网格
        res_x, res_y, res_z = self.voxel_resolution
        
        x_grid = np.linspace(x_min, x_max, res_x)
        y_grid = np.linspace(y_min, y_max, res_y)
        z_grid = np.linspace(z_min, z_max, res_z)
        
        self.grid_bounds = {
            'x_min': x_min, 'x_max': x_max,
            'y_min': y_min, 'y_max': y_max,
            'z_min': z_min, 'z_max': z_max,
            'x_grid': x_grid, 'y_grid': y_grid, 'z_grid': z_grid
        }
        
        # 初始化体素网格
        self.voxel_grid = np.zeros((res_x, res_y, res_z), dtype=np.float32)
        self.label_grid = np.zeros((res_x, res_y, res_z), dtype=np.int32)  # 0=background
        
        print(f"  Voxel grid: {res_x}x{res_y}x{res_z} = {res_x*res_y*res_z} voxels")
        
        return self.grid_bounds
    
    def classify_voxels_by_polygon(self) -> Dict:
        """
        Step 3: 使用polygon.contains进行体素分类
        
        关键：使用Shapely的Polygon.contains(Point)而非centroid距离
        """
        print("\n=== Step 3: Classify Voxels by Polygon Containment ===")
        
        if not HAS_SHAPELY:
            print("  [ERROR] Shapely not available, cannot perform polygon containment")
            return {}
        
        if self.grid_bounds is None:
            print("  [ERROR] Voxel grid not initialized")
            return {}
        
        x_grid = self.grid_bounds['x_grid']
        y_grid = self.grid_bounds['y_grid']
        z_grid = self.grid_bounds['z_grid']
        
        # 为每个截面构建2D多边形（在XY平面投影）
        # 然后对每个Z切片进行分类
        
        # 收集所有截面的地质多边形，按Z值分组
        z_sections = {}
        for section in self.sections_3d:
            z_val = np.mean(section['dmx_3d'][:, 2]) if section.get('dmx_3d') is not None and len(section['dmx_3d']) > 0 else 0
            z_sections[z_val] = section
        
        # 对每个体素进行分类
        classified_count = 0
        
        for i, x in enumerate(x_grid):
            for j, y in enumerate(y_grid):
                for k, z in enumerate(z_grid):
                    # 找最近的截面
                    if not z_sections:
                        continue
                    
                    closest_z = min(z_sections.keys(), key=lambda z_s: abs(z_s - z))
                    section = z_sections[closest_z]
                    
                    geology = section.get('geology_3d', {})
                    
                    # 检查点是否在任何地质多边形内
                    point = Point(x, y)
                    
                    for category, polys in geology.items():
                        for poly_data in polys:
                            pts_2d = poly_data['points'][:, :2]  # XY投影
                            
                            if len(pts_2d) >= 3:
                                # 构建Shapely Polygon
                                try:
                                    polygon = Polygon(pts_2d)
                                    
                                    if polygon.contains(point) or polygon.touches(point):
                                        cat_id = self.category_ids.get(category, 0)
                                        self.label_grid[i, j, k] = cat_id
                                        classified_count += 1
                                        break  # 找到一个类别就停止
                                except Exception:
                                    # Polygon构建失败（如自相交）
                                    pass
        
        # 统计分类结果
        label_counts = {}
        for cat_id in range(4):
            count = np.sum(self.label_grid == cat_id)
            label_counts[self.category_names[cat_id]] = count
        
        print(f"  Classified voxels: {classified_count}")
        print(f"  Label distribution: {label_counts}")
        
        return label_counts
    
    def smooth_labels(self, sigma: float = 1.0) -> None:
        """
        Step 4: 高斯平滑标签场（可选优化）
        """
        print("\n=== Step 4: Smooth Label Field ===")
        
        if self.label_grid is None:
            return
        
        # 对每个类别的mask进行平滑
        smoothed_labels = np.zeros_like(self.label_grid)
        
        for cat_id in range(1, 4):  # 跳过background
            mask = (self.label_grid == cat_id).astype(np.float32)
            smoothed_mask = gaussian_filter(mask, sigma=sigma)
            
            # 阈值化
            threshold = 0.3
            smoothed_labels[smoothed_mask > threshold] = cat_id
        
        # 更新标签
        self.label_grid = smoothed_labels
        
        # 统计
        label_counts = {}
        for cat_id in range(4):
            count = np.sum(self.label_grid == cat_id)
            label_counts[self.category_names[cat_id]] = count
        
        print(f"  After smoothing: {label_counts}")
    
    def build_model(self) -> Dict:
        """完整构建流程"""
        print("\n" + "="*60)
        print("V10 Geology Model Builder")
        print("Architecture: V7 Skeleton + Voxel Classification")
        print("="*60)
        
        # Step 0: 加载数据
        if not self.load_data():
            return {}
        
        # Step 1: V7几何骨架
        self.build_v7_geometry_skeleton()
        
        # Step 2: 体素化
        self.voxelize_v7_meshes()
        
        # Step 3: 体素分类
        self.classify_voxels_by_polygon()
        
        # Step 4: 平滑（可选）
        self.smooth_labels(sigma=1.0)
        
        # 返回结果
        return {
            'v7_meshes': self.v7_meshes,
            'voxel_grid': self.voxel_grid,
            'label_grid': self.label_grid,
            'grid_bounds': self.grid_bounds
        }
    
    def export_to_html(self, output_path: str, model_data: Dict) -> None:
        """
        导出为Plotly HTML
        
        显示V7的mesh（真实坐标）
        """
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
            title='V10 Geology Model (V7 Skeleton + Voxel Classification)',
            scene=dict(
                xaxis_title='X (East)',
                yaxis_title='Y (North)',
                zaxis_title='Z (Elevation)',
                aspectmode='data'
            ),
            legend=dict(x=0.02, y=0.98),
            margin=dict(l=0, r=0, t=50, b=0)
        )
        
        # 保存
        fig.write_html(output_path)
        print(f"  HTML saved: {output_path}")
        
        # 文件大小
        file_size = os.path.getsize(output_path) / 1024 / 1024
        print(f"  File size: {file_size:.2f} MB")
    
    def build_and_export(self, output_path: str) -> str:
        """一键构建并导出"""
        model_data = self.build_model()
        
        if model_data:
            self.export_to_html(output_path, model_data)
            return output_path
        
        return ""


# ==================== 主函数 ====================

def main():
    """测试V10模型构建器"""
    import argparse
    
    parser = argparse.ArgumentParser(description='V10 Geology Model Builder')
    parser.add_argument('--section-json', type=str, required=True, help='Section JSON path')
    parser.add_argument('--spine-json', type=str, required=True, help='Spine JSON path')
    parser.add_argument('--output', type=str, default='geology_model_v10.html', help='Output HTML path')
    parser.add_argument('--voxel-res', type=int, nargs=3, default=[100, 100, 30], help='Voxel resolution')
    
    args = parser.parse_args()
    
    builder = GeologyModelBuilderV10(
        args.section_json,
        args.spine_json,
        voxel_resolution=tuple(args.voxel_res)
    )
    
    output_path = builder.build_and_export(args.output)
    
    if output_path:
        print(f"\n[SUCCESS] Model exported to: {output_path}")
    else:
        print(f"\n[FAILED] Model build failed")


if __name__ == '__main__':
    main()