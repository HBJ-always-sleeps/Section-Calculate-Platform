# -*- coding: utf-8 -*-
"""
航道三维地质模型 V9 - SDF隐式建模修复版

关键修复：
1. SDF加入内外信息：表面点f=0，内部点f<0，外部点f>0
2. 分类用点在多边形内判断（Shapely Polygon.contains）
3. 地层边界加入SDF约束
4. 体素分辨率提高到100

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


def estimate_normal(points: np.ndarray) -> np.ndarray:
    """
    估计点集的法向量（用于SDF内外偏移）
    
    简单方法：计算质心到各点的平均方向
    """
    center = np.mean(points, axis=0)
    vecs = points - center
    normal = np.mean(vecs, axis=0)
    norm = np.linalg.norm(normal)
    if norm > 1e-6:
        return normal / norm
    return np.array([0, 0, 1])


# ==================== V9模型构建器修复版 ====================

class GeologyModelBuilderV9Fixed:
    """
    V9地质模型构建器（修复版）
    
    关键修复：
    1. SDF有内外信息
    2. 分类用点在多边形内判断
    3. 地层边界加入SDF
    4. 体素分辨率提高到100
    """
    
    def __init__(self, section_json_path: str, spine_json_path: str, 
                 voxel_resolution: int = 100):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.voxel_resolution = voxel_resolution
        
        self.sections_data = None
        self.spine_matches = None
        self.sections_3d = []
        
        # 分类ID映射
        self.category_ids = {'background': 0, 'mud_fill': 1, 'clay': 2, 'sand_and_gravel': 3}
    
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
            if stations[i] <= station_value <= stations[i + 1]:
                t = (station_value - stations[i]) / (stations[i + 1] - stations[i])
                result = {}
                for key in matches[i]:
                    if isinstance(matches[i][key], (int, float)):
                        result[key] = matches[i][key] + t * (matches[i + 1][key] - matches[i][key])
                    else:
                        result[key] = matches[i][key]
                return result
        
        return matches[-1]
    
    def _transform_section_to_3d(self, section: Dict) -> Dict:
        """将截面数据转换到3D坐标"""
        spine_match = self._get_interpolated_spine_match(section.get('station_value', 0))
        
        if not spine_match:
            return {}
        
        # 修复：使用正确的字段名 ref_x/ref_y
        l1_ref = section.get('l1_ref_point', {})
        ref_x = l1_ref.get('ref_x', 0)
        ref_y = l1_ref.get('ref_y', 0)
        spine_x = spine_match.get('spine_x', 0)
        spine_y = spine_match.get('spine_y', 0)
        # 修复：使用 tangent_angle + pi/2 作为旋转角
        tangent_angle = spine_match.get('tangent_angle', 0)
        rotation_angle = tangent_angle + math.pi / 2
        
        result = {
            'station': section.get('station_value', 0),
            'dmx_3d': [],
            'overbreak_3d': [],
            'geological_regions': {}
        }
        
        # 转换DMX点
        dmx_points = section.get('dmx_points', [])
        if dmx_points:
            dmx_3d = []
            for pt in dmx_points:
                if len(pt) >= 2:
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    dmx_3d.append([eng_x, eng_y, z])
            result['dmx_3d'] = [np.array(dmx_3d)]
        
        # 转换超挖线
        overbreak_points = section.get('overbreak_points', [])
        if overbreak_points:
            all_ob_points = []
            for ob_line in overbreak_points:
                if len(ob_line) >= 2:
                    for pt in ob_line:
                        if len(pt) >= 2:
                            eng_x, eng_y, z = transform_to_spine_aligned(
                                pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                            )
                            all_ob_points.append([eng_x, eng_y, z])
            if all_ob_points:
                result['overbreak_3d'] = [np.array(all_ob_points)]
        
        # 转换地质区域（关键：保留2D多边形用于点在多边形内判断）
        fill_boundaries = section.get('fill_boundaries', {})
        for layer_name, polygons in fill_boundaries.items():
            category = categorize_layer(layer_name)
            if category is None:
                continue
            
            if category not in result['geological_regions']:
                result['geological_regions'][category] = []
            
            for polygon in polygons:
                if len(polygon) >= 3:
                    # 转换为3D坐标
                    poly_3d = []
                    for pt in polygon:
                        if len(pt) >= 2:
                            eng_x, eng_y, z = transform_to_spine_aligned(
                                pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                            )
                            poly_3d.append([eng_x, eng_y, z])
                    
                    if len(poly_3d) >= 3:
                        poly_3d = np.array(poly_3d)
                        # 保留2D投影用于点在多边形内判断
                        poly_2d = poly_3d[:, :2]  # X-Y投影
                        
                        result['geological_regions'][category].append({
                            'points_3d': poly_3d,
                            'polygon_2d': poly_2d,  # 用于点在多边形内判断
                            'layer_name': layer_name,
                            'centroid': np.mean(poly_3d, axis=0),
                            'z_range': (poly_3d[:, 2].min(), poly_3d[:, 2].max())
                        })
        
        return result
    
    def transform_all_sections(self) -> List[Dict]:
        """转换所有截面到3D"""
        print("\n=== Transforming Sections to 3D ===")
        
        sections = self.sections_data.get('sections', [])
        self.sections_3d = []
        
        for section in sections:
            section_3d = self._transform_section_to_3d(section)
            if section_3d:
                self.sections_3d.append(section_3d)
        
        print(f"  Transformed sections: {len(self.sections_3d)}")
        return self.sections_3d
    
    def build_sdf_with_inside_outside(self, sections_3d: List[Dict]) -> Dict:
        """
        构建带内外信息的SDF距离场
        
        关键修复：
        - 表面点：f = 0
        - 内部点：f < 0（负值）
        - 外部点：f > 0（正值）
        """
        print("\n=== Building SDF with Inside/Outside ===")
        
        constraint_points = []
        constraint_values = []  # SDF值：0=表面，负=内部，正=外部
        
        # 偏移距离（控制厚度）
        offset_distance = 5.0  # 米
        
        # 1. 从DMX和超挖线提取表面点
        for section in sections_3d:
            # DMX表面点
            for line in section.get('dmx_3d', []):
                if len(line) < 3:
                    continue
                pts = np.array(line)
                normal = estimate_normal(pts)
                
                for pt in pts:
                    # 表面点 f=0
                    constraint_points.append(pt[:3])
                    constraint_values.append(0.0)
                    
                    # 内部点 f<0（向法向反方向偏移）
                    inner_pt = pt[:3] - offset_distance * normal
                    constraint_points.append(inner_pt)
                    constraint_values.append(-offset_distance)
                    
                    # 外部点 f>0（向法向正方向偏移）
                    outer_pt = pt[:3] + offset_distance * normal
                    constraint_points.append(outer_pt)
                    constraint_values.append(offset_distance)
            
            # 超挖线表面点
            for line in section.get('overbreak_3d', []):
                if len(line) < 3:
                    continue
                pts = np.array(line)
                normal = estimate_normal(pts)
                
                for pt in pts:
                    constraint_points.append(pt[:3])
                    constraint_values.append(0.0)
                    
                    inner_pt = pt[:3] - offset_distance * normal
                    constraint_points.append(inner_pt)
                    constraint_values.append(-offset_distance)
                    
                    outer_pt = pt[:3] + offset_distance * normal
                    constraint_points.append(outer_pt)
                    constraint_values.append(offset_distance)
        
        # 2. 从地质层边界提取表面点（关键修复：地层边界也加入SDF）
        for section in sections_3d:
            for category, regions in section.get('geological_regions', {}).items():
                for region in regions:
                    pts_3d = region['points_3d']
                    if len(pts_3d) < 3:
                        continue
                    
                    normal = estimate_normal(pts_3d)
                    
                    for pt in pts_3d:
                        # 地层边界表面点 f=0
                        constraint_points.append(pt[:3])
                        constraint_values.append(0.0)
                        
                        # 内部点
                        inner_pt = pt[:3] - offset_distance * 0.5 * normal
                        constraint_points.append(inner_pt)
                        constraint_values.append(-offset_distance * 0.5)
                        
                        # 外部点
                        outer_pt = pt[:3] + offset_distance * 0.5 * normal
                        constraint_points.append(outer_pt)
                        constraint_values.append(offset_distance * 0.5)
        
        if len(constraint_points) < 100:
            print("  [WARN] Not enough constraint points for SDF")
            return {}
        
        constraint_points = np.array(constraint_points)
        constraint_values = np.array(constraint_values)
        
        # 限制最大点数
        max_points = 10000
        if len(constraint_points) > max_points:
            indices = np.random.choice(len(constraint_points), max_points, replace=False)
            constraint_points = constraint_points[indices]
            constraint_values = constraint_values[indices]
        
        print(f"  Constraint points: {len(constraint_points)}")
        print(f"  SDF values range: {constraint_values.min():.2f} ~ {constraint_values.max():.2f}")
        
        # 3. 计算边界
        bounds = {
            'x_min': constraint_points[:, 0].min() - 50,
            'x_max': constraint_points[:, 0].max() + 50,
            'y_min': constraint_points[:, 1].min() - 50,
            'y_max': constraint_points[:, 1].max() + 50,
            'z_min': constraint_points[:, 2].min() - 20,
            'z_max': constraint_points[:, 2].max() + 20
        }
        
        print(f"  Bounds: X({bounds['x_min']:.1f}~{bounds['x_max']:.1f}), "
              f"Y({bounds['y_min']:.1f}~{bounds['y_max']:.1f}), "
              f"Z({bounds['z_min']:.1f}~{bounds['z_max']:.1f})")
        
        # 4. 构建KDTree用于最近邻查询
        print("  Building KDTree...")
        kdtree = cKDTree(constraint_points)
        
        # 5. 生成体素网格（非均匀分辨率）
        # X和Y方向高分辨率，Z方向低分辨率
        nx = self.voxel_resolution
        ny = self.voxel_resolution
        nz = max(30, self.voxel_resolution // 3)
        
        print(f"  Generating voxel grid ({nx}x{ny}x{nz})...")
        x = np.linspace(bounds['x_min'], bounds['x_max'], nx)
        y = np.linspace(bounds['y_min'], bounds['y_max'], ny)
        z = np.linspace(bounds['z_min'], bounds['z_max'], nz)
        
        X, Y, Z = np.meshgrid(x, y, z, indexing='ij')
        grid_points = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
        
        # 6. 计算SDF值（带符号距离场）
        print("  Computing SDF values...")
        distances, indices = kdtree.query(grid_points, k=1)
        
        # 获取最近点的SDF值作为初始估计
        sdf_values = constraint_values[indices]
        
        # 根据距离调整SDF值
        # 如果点在表面附近，使用最近点的SDF值
        # 如果点远离表面，根据距离调整
        sdf_grid = sdf_values + np.sign(sdf_values) * distances * 0.1
        sdf_grid = sdf_grid.reshape(X.shape)
        
        print(f"  SDF range: {sdf_grid.min():.2f} ~ {sdf_grid.max():.2f}")
        
        return {
            'sdf_grid': sdf_grid,
            'bounds': bounds,
            'resolution': (nx, ny, nz),
            'x_coords': x,
            'y_coords': y,
            'z_coords': z
        }
    
    def classify_voxels_by_polygon(self, sdf_data: Dict, sections_3d: List[Dict]) -> Dict:
        """
        体素分类 - 使用点在多边形内判断（关键修复）
        
        不再用质心距离，而是用Shapely的Polygon.contains判断
        """
        print("\n=== Classifying Voxels by Polygon Containment ===")
        
        if not sdf_data:
            return {}
        
        sdf_grid = sdf_data['sdf_grid']
        bounds = sdf_data['bounds']
        x_coords = sdf_data['x_coords']
        y_coords = sdf_data['y_coords']
        z_coords = sdf_data['z_coords']
        
        nx, ny, nz = len(x_coords), len(y_coords), len(z_coords)
        
        # 初始化分类网格
        label_grid = np.zeros((nx, ny, nz), dtype=np.int32)
        
        if not HAS_SHAPELY:
            print("  [WARN] Shapely not available, using fallback centroid method")
            return self._classify_voxels_fallback(sdf_data, sections_3d)
        
        # 为每个截面处理
        print("  Processing sections for polygon containment...")
        section_idx = 0
        
        for section in sections_3d:
            station = section.get('station', 0)
            geological_regions = section.get('geological_regions', {})
            
            # 找到该截面对应的Y坐标范围
            y_idx_range = None
            for j, y in enumerate(y_coords):
                # 简单匹配：找到最近的Y坐标
                for cat, regions in geological_regions.items():
                    for region in regions:
                        centroid = region['centroid']
                        if abs(y - centroid[1]) < 50:  # 50米容差
                            y_idx_range = j
                            break
            
            if y_idx_range is None:
                continue
            
            # 对每个地层区域进行点在多边形内判断
            for category, regions in geological_regions.items():
                cat_id = self.category_ids.get(category, 0)
                if cat_id == 0:
                    continue
                
                for region in regions:
                    poly_2d = region.get('polygon_2d')
                    z_range = region.get('z_range', (-1000, 1000))
                    
                    if poly_2d is None or len(poly_2d) < 3:
                        continue
                    
                    try:
                        # 创建Shapely多边形
                        polygon = Polygon(poly_2d)
                        if not polygon.is_valid:
                            continue
                        
                        # 找到Z范围内的体素索引
                        k_min = max(0, np.searchsorted(z_coords, z_range[0]) - 1)
                        k_max = min(nz, np.searchsorted(z_coords, z_range[1]) + 1)
                        
                        # 对X方向进行点在多边形内判断
                        for i, x in enumerate(x_coords):
                            for j, y in enumerate(y_coords):
                                # 创建测试点
                                point = Point(x, y)
                                
                                # 点在多边形内判断
                                if polygon.contains(point):
                                    # 该体素属于该地层
                                    for k in range(k_min, k_max):
                                        if label_grid[i, j, k] == 0:  # 未分类
                                            label_grid[i, j, k] = cat_id
                    
                    except Exception as e:
                        continue
            
            section_idx += 1
            if section_idx % 50 == 0:
                print(f"    Processed {section_idx} sections...")
        
        # 统计分类结果
        unique, counts = np.unique(label_grid, return_counts=True)
        print("  Label distribution:")
        for u, c in zip(unique, counts):
            cat_name = [k for k, v in self.category_ids.items() if v == u]
            cat_name = cat_name[0] if cat_name else f'unknown_{u}'
            print(f"    {cat_name}: {c} voxels")
        
        # 应用高斯平滑
        print("  Applying Gaussian smooth...")
        for cat_id in range(1, 4):
            mask = (label_grid == cat_id).astype(np.float32)
            smoothed = gaussian_filter(mask, sigma=1.0)
            label_grid[smoothed > 0.5] = cat_id
        
        return {
            'label_grid': label_grid,
            'bounds': bounds,
            'resolution': (nx, ny, nz),
            'x_coords': x_coords,
            'y_coords': y_coords,
            'z_coords': z_coords
        }
    
    def _classify_voxels_fallback(self, sdf_data: Dict, sections_3d: List[Dict]) -> Dict:
        """Fallback分类方法（无Shapely时）"""
        print("  Using fallback centroid-based classification...")
        
        sdf_grid = sdf_data['sdf_grid']
        bounds = sdf_data['bounds']
        x_coords = sdf_data['x_coords']
        y_coords = sdf_data['y_coords']
        z_coords = sdf_data['z_coords']
        
        nx, ny, nz = len(x_coords), len(y_coords), len(z_coords)
        label_grid = np.zeros((nx, ny, nz), dtype=np.int32)
        
        # 简单的质心距离分类
        for section in sections_3d:
            for category, regions in section.get('geological_regions', {}).items():
                cat_id = self.category_ids.get(category, 0)
                if cat_id == 0:
                    continue
                
                for region in regions:
                    centroid = region['centroid']
                    z_range = region.get('z_range', (-1000, 1000))
                    
                    # 找到质心附近的体素
                    for i, x in enumerate(x_coords):
                        for j, y in enumerate(y_coords):
                            dist = np.sqrt((x - centroid[0])**2 + (y - centroid[1])**2)
                            if dist < 50:  # 50米半径
                                for k, z in enumerate(z_coords):
                                    if z_range[0] <= z <= z_range[1]:
                                        if label_grid[i, j, k] == 0:
                                            label_grid[i, j, k] = cat_id
        
        return {
            'label_grid': label_grid,
            'bounds': bounds,
            'resolution': (nx, ny, nz),
            'x_coords': x_coords,
            'y_coords': y_coords,
            'z_coords': z_coords
        }
    
    def extract_meshes(self, classification_data: Dict) -> Dict[str, Dict]:
        """提取网格"""
        print("\n=== Extracting Meshes ===")
        
        if not classification_data:
            return {}
        
        label_grid = classification_data['label_grid']
        x_coords = classification_data['x_coords']
        y_coords = classification_data['y_coords']
        z_coords = classification_data['z_coords']
        
        meshes = {}
        
        # 尝试使用scikit-image的Marching Cubes
        try:
            from skimage import measure
            has_marching_cubes = True
            print("  Using Marching Cubes from scikit-image...")
        except ImportError:
            has_marching_cubes = False
            print("  [WARN] scikit-image not available, using simple extraction")
        
        for cat_name, cat_id in self.category_ids.items():
            if cat_id == 0:  # 跳过背景
                continue
            
            # 创建该类别的二值场
            binary_grid = (label_grid == cat_id).astype(np.float32)
            
            if binary_grid.sum() < 10:
                print(f"  {cat_name}: too few voxels, skipping")
                continue
            
            if has_marching_cubes:
                # Marching Cubes提取
                try:
                    verts, faces, normals, values = measure.marching_cubes(
                        binary_grid, level=0.5, spacing=(
                            x_coords[1] - x_coords[0],
                            y_coords[1] - y_coords[0],
                            z_coords[1] - z_coords[0]
                        )
                    )
                    
                    # 转换到实际坐标
                    verts[:, 0] += x_coords[0]
                    verts[:, 1] += y_coords[0]
                    verts[:, 2] += z_coords[0]
                    
                    meshes[cat_name] = {
                        'vertices': verts,
                        'faces': faces,
                        'normals': normals
                    }
                    print(f"  {cat_name}: {len(verts)} vertices, {len(faces)} faces")
                except Exception as e:
                    print(f"  {cat_name}: Marching Cubes failed ({e}), using box")
                    meshes[cat_name] = self._extract_box_mesh(cat_name, binary_grid, x_coords, y_coords, z_coords)
            else:
                # 简单box提取
                meshes[cat_name] = self._extract_box_mesh(cat_name, binary_grid, x_coords, y_coords, z_coords)
        
        return meshes
    
    def _extract_box_mesh(self, cat_name: str, binary_grid: np.ndarray, 
                          x_coords: np.ndarray, y_coords: np.ndarray, z_coords: np.ndarray) -> Dict:
        """简单box网格提取"""
        # 找到该类别的边界
        indices = np.where(binary_grid > 0.5)
        if len(indices[0]) == 0:
            return {'vertices': np.array([]), 'faces': np.array([])}
        
        x_min, x_max = x_coords[indices[0].min()], x_coords[indices[0].max()]
        y_min, y_max = y_coords[indices[1].min()], y_coords[indices[1].max()]
        z_min, z_max = z_coords[indices[2].min()], z_coords[indices[2].max()]
        
        # 创建box顶点
        verts = np.array([
            [x_min, y_min, z_min],
            [x_max, y_min, z_min],
            [x_max, y_max, z_min],
            [x_min, y_max, z_min],
            [x_min, y_min, z_max],
            [x_max, y_min, z_max],
            [x_max, y_max, z_max],
            [x_min, y_max, z_max],
        ])
        
        # 创建box面
        faces = np.array([
            [0, 1, 2], [0, 2, 3],  # 底面
            [4, 5, 6], [4, 6, 7],  # 顶面
            [0, 1, 5], [0, 5, 4],  # 前面
            [2, 3, 7], [2, 7, 6],  # 后面
            [0, 3, 7], [0, 7, 4],  # 左面
            [1, 2, 6], [1, 6, 5],  # 右面
        ])
        
        print(f"  {cat_name}: simple box mesh")
        return {'vertices': verts, 'faces': faces}
    
    def export_to_html(self, output_path: str, meshes: Dict[str, Dict], 
                       sections_3d: List[Dict] = None) -> bool:
        """导出为Plotly HTML"""
        print("\n=== Exporting to HTML ===")
        
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError:
            print("  [ERROR] plotly not available")
            return False
        
        fig = make_subplots(rows=1, cols=1, specs=[[{'type': 'mesh3d'}]])
        
        # 添加DMX ribbon
        if sections_3d:
            dmx_vertices = []
            dmx_faces = []
            vertex_offset = 0
            
            for section in sections_3d:
                for line in section.get('dmx_3d', []):
                    if len(line) < 2:
                        continue
                    pts = np.array(line)
                    n = len(pts)
                    
                    for pt in pts:
                        dmx_vertices.append(pt)
                    
                    for i in range(n - 1):
                        dmx_faces.append([vertex_offset + i, vertex_offset + i + 1, vertex_offset + i])
                    
                    vertex_offset += n
            
            if dmx_vertices:
                dmx_vertices = np.array(dmx_vertices)
                fig.add_trace(go.Scatter3d(
                    x=dmx_vertices[:, 0],
                    y=dmx_vertices[:, 1],
                    z=dmx_vertices[:, 2],
                    mode='lines',
                    name='DMX',
                    line=dict(color='blue', width=2),
                    legendgroup='dmx'
                ), row=1, col=1)
        
        # 添加地质层mesh
        for cat_name, mesh_data in meshes.items():
            if 'vertices' not in mesh_data or len(mesh_data['vertices']) == 0:
                continue
            
            verts = mesh_data['vertices']
            faces = mesh_data.get('faces', [])
            
            cat_info = LAYER_CATEGORIES.get(cat_name, {'name_cn': cat_name, 'color': '#888888'})
            
            if len(faces) > 0:
                # Mesh3d
                i, j, k = faces[:, 0], faces[:, 1], faces[:, 2]
                fig.add_trace(go.Mesh3d(
                    x=verts[:, 0],
                    y=verts[:, 1],
                    z=verts[:, 2],
                    i=i, j=j, k=k,
                    name=cat_info['name_cn'],
                    color=cat_info['color'],
                    opacity=0.7,
                    legendgroup=cat_name
                ), row=1, col=1)
            else:
                # Scatter3d
                fig.add_trace(go.Scatter3d(
                    x=verts[:, 0],
                    y=verts[:, 1],
                    z=verts[:, 2],
                    mode='markers',
                    name=cat_info['name_cn'],
                    marker=dict(color=cat_info['color'], size=3),
                    legendgroup=cat_name
                ), row=1, col=1)
        
        # 设置布局
        fig.update_layout(
            title='V9 Geology Model (Fixed: SDF with Inside/Outside)',
            scene=dict(
                xaxis_title='X (m)',
                yaxis_title='Y (m)',
                zaxis_title='Z (m)',
                aspectmode='data'
            ),
            legend=dict(
                x=1.02,
                y=1,
                xanchor='left'
            ),
            width=1400,
            height=900
        )
        
        # 保存
        fig.write_html(output_path)
        file_size = os.path.getsize(output_path) / 1024
        print(f"  Output: {output_path}")
        print(f"  File size: {file_size:.1f} KB")
        
        return True
    
    def build_and_export(self, output_path: str) -> str:
        """完整构建流程"""
        if not self.load_data():
            return ""
        
        sections_3d = self.transform_all_sections()
        
        # 构建带内外信息的SDF
        sdf_data = self.build_sdf_with_inside_outside(sections_3d)
        
        # 使用点在多边形内判断进行分类
        classification_data = self.classify_voxels_by_polygon(sdf_data, sections_3d)
        
        # 提取网格
        meshes = self.extract_meshes(classification_data)
        
        # 导出
        self.export_to_html(output_path, meshes, sections_3d)
        
        return output_path


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='V9 Geology Model Builder (Fixed)')
    parser.add_argument('--section-json', required=True, help='Section metadata JSON')
    parser.add_argument('--spine-json', required=True, help='Spine match JSON')
    parser.add_argument('--output', required=True, help='Output HTML path')
    parser.add_argument('--resolution', type=int, default=100, help='Voxel resolution')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("V9 Geology Model Builder (Fixed)")
    print("  - SDF with Inside/Outside information")
    print("  - Polygon containment classification (Shapely)")
    print("  - Higher voxel resolution (100)")
    print("=" * 60)
    
    builder = GeologyModelBuilderV9Fixed(
        args.section_json,
        args.spine_json,
        args.resolution
    )
    
    builder.build_and_export(args.output)


if __name__ == '__main__':
    main()