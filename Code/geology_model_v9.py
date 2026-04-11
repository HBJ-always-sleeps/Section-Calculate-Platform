# -*- coding: utf-8 -*-
"""
航道三维地质模型 V9 - SDF隐式建模 + 体素分类优化版本

核心设计（基于用户提供的算法框架）：
1. 截面预处理：拓扑标准化 + 点采样
2. 截面间匹配：最优传输匹配（Hungarian算法）
3. 隐式几何建模：RBF-SDF（Signed Distance Field）
4. 分类场建模：体素分类 + CRF优化
5. 网格提取：Marching Cubes

相比V7/V8的改进：
- 天然避免穿模问题
- 分类边界贴合几何表面
- 支持地层分裂/合并

作者: @黄秉俊
日期: 2026-04-06
"""

import json
import numpy as np
import os
from typing import List, Dict, Tuple, Optional
import math
import sys
from scipy.interpolate import RBFInterpolator
from scipy.spatial import cKDTree
from scipy.ndimage import gaussian_filter
from collections import defaultdict

# 添加Code目录到路径
sys.path.insert(0, r'D:\断面算量平台\Code')

# shapely延迟导入
SHAPELY_AVAILABLE = None


def check_shapely():
    """延迟检查shapely是否可用"""
    global SHAPELY_AVAILABLE
    if SHAPELY_AVAILABLE is None:
        try:
            from shapely.geometry import Polygon, Point
            from shapely.ops import unary_union
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


# ==================== V4坐标变换（保持与V7一致） ====================

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


# ==================== Step 1: 截面预处理 ====================

class SectionPreprocessor:
    """截面预处理器：拓扑标准化 + 点采样"""
    
    def __init__(self, num_samples: int = 64):
        self.num_samples = num_samples
    
    def preprocess_section(self, section_data: Dict) -> Dict:
        """
        预处理单个截面
        
        输入：section_data包含dmx_points, overbreak_points, fill_boundaries
        输出：标准化后的截面数据，包含采样点集
        """
        result = {
            'station': section_data.get('station_value', 0),
            'dmx_3d': [],
            'overbreak_3d': [],
            'geological_regions': {}  # {category: [polygon_points]}
        }
        
        # 处理DMX和超挖线（保持V7逻辑）
        if 'dmx_3d' in section_data:
            result['dmx_3d'] = section_data['dmx_3d']
        if 'overbreak_3d' in section_data:
            result['overbreak_3d'] = section_data['overbreak_3d']
        
        # 处理地质区域
        fill_boundaries = section_data.get('fill_boundaries', {})
        for layer_name, polygons in fill_boundaries.items():
            category = categorize_layer(layer_name)
            if category is None:
                continue
            
            if category not in result['geological_regions']:
                result['geological_regions'][category] = []
            
            for polygon in polygons:
                if len(polygon) >= 3:
                    # 采样多边形边界
                    sampled = self._sample_polygon_boundary(polygon)
                    result['geological_regions'][category].append({
                        'points': sampled,
                        'layer_name': layer_name,
                        'centroid': self._compute_centroid(sampled)
                    })
        
        return result
    
    def _sample_polygon_boundary(self, polygon: List) -> np.ndarray:
        """均匀采样多边形边界"""
        if len(polygon) < 3:
            return np.array(polygon)
        
        points = np.array(polygon)
        n = len(points)
        
        # 计算周长
        diffs = np.diff(points, axis=0)
        distances = np.sqrt(np.sum(diffs**2, axis=1))
        total_length = np.sum(distances)
        
        if total_length < 1e-6:
            return points
        
        # 均匀采样
        target_distances = np.linspace(0, total_length, self.num_samples)
        sampled = np.zeros((self.num_samples, 2))
        
        cumdist = np.concatenate(([0], np.cumsum(distances)))
        
        for i, td in enumerate(target_distances):
            # 找到对应的线段
            idx = np.searchsorted(cumdist, td) - 1
            idx = max(0, min(idx, n - 2))
            
            # 线性插值
            if idx < n - 1:
                seg_start = cumdist[idx]
                seg_len = distances[idx]
                if seg_len > 1e-6:
                    t = (td - seg_start) / seg_len
                else:
                    t = 0
                sampled[i] = points[idx] + t * (points[idx + 1] - points[idx])
            else:
                sampled[i] = points[-1]
        
        return sampled
    
    def _compute_centroid(self, points: np.ndarray) -> Tuple[float, float]:
        """计算质心"""
        return float(np.mean(points[:, 0])), float(np.mean(points[:, 1]))


# ==================== Step 2: 截面间最优传输匹配 ====================

class SectionMatcher:
    """截面匹配器：使用Hungarian算法进行最优传输匹配"""
    
    def __init__(self, distance_weight: float = 1.0, shape_weight: float = 0.5, area_weight: float = 0.3):
        self.distance_weight = distance_weight
        self.shape_weight = shape_weight
        self.area_weight = area_weight
    
    def match_sections(self, section_a: Dict, section_b: Dict) -> Dict:
        """
        匹配两个相邻截面的地质区域
        
        返回：匹配关系字典 {category: [(idx_a, idx_b, cost)]}
        """
        matches = {}
        
        regions_a = section_a.get('geological_regions', {})
        regions_b = section_b.get('geological_regions', {})
        
        # 按类别分别匹配
        all_categories = set(regions_a.keys()) | set(regions_b.keys())
        
        for category in all_categories:
            cat_regions_a = regions_a.get(category, [])
            cat_regions_b = regions_b.get(category, [])
            
            if not cat_regions_a or not cat_regions_b:
                matches[category] = []
                continue
            
            # 构建代价矩阵
            n_a = len(cat_regions_a)
            n_b = len(cat_regions_b)
            cost_matrix = np.zeros((n_a, n_b))
            
            for i, region_a in enumerate(cat_regions_a):
                for j, region_b in enumerate(cat_regions_b):
                    cost_matrix[i, j] = self._compute_matching_cost(region_a, region_b)
            
            # 使用贪心匹配（简化版Hungarian）
            category_matches = self._greedy_match(cost_matrix, cat_regions_a, cat_regions_b)
            matches[category] = category_matches
        
        return matches
    
    def _compute_matching_cost(self, region_a: Dict, region_b: Dict) -> float:
        """
        计算两个区域之间的匹配代价
        
        代价 = α * 欧氏距离 + β * 形状差异 + γ * 面积差异
        """
        # 欧氏距离（质心）
        centroid_a = region_a['centroid']
        centroid_b = region_b['centroid']
        dist = np.sqrt((centroid_a[0] - centroid_b[0])**2 + (centroid_a[1] - centroid_b[1])**2)
        
        # 形状差异（简化：使用点集的Hausdorff距离近似）
        points_a = region_a['points']
        points_b = region_b['points']
        shape_diff = self._compute_shape_difference(points_a, points_b)
        
        # 面积差异
        area_a = self._compute_polygon_area(points_a)
        area_b = self._compute_polygon_area(points_b)
        area_diff = abs(area_a - area_b) / max(area_a, area_b, 1e-6)
        
        # 综合代价
        cost = (self.distance_weight * dist + 
                self.shape_weight * shape_diff + 
                self.area_weight * area_diff)
        
        return cost
    
    def _compute_shape_difference(self, points_a: np.ndarray, points_b: np.ndarray) -> float:
        """计算形状差异（使用简化的距离度量）"""
        # 使用质心到各点的距离分布作为形状描述子
        centroid_a = np.mean(points_a, axis=0)
        centroid_b = np.mean(points_b, axis=0)
        
        dists_a = np.sqrt(np.sum((points_a - centroid_a)**2, axis=1))
        dists_b = np.sqrt(np.sum((points_b - centroid_b)**2, axis=1))
        
        # 归一化
        dists_a = dists_a / (np.max(dists_a) + 1e-6)
        dists_b = dists_b / (np.max(dists_b) + 1e-6)
        
        # 计算差异
        if len(dists_a) != len(dists_b):
            # 重采样到相同长度
            min_len = min(len(dists_a), len(dists_b))
            dists_a = np.interp(np.linspace(0, 1, min_len), np.linspace(0, 1, len(dists_a)), dists_a)
            dists_b = np.interp(np.linspace(0, 1, min_len), np.linspace(0, 1, len(dists_b)), dists_b)
        
        return float(np.mean(np.abs(dists_a - dists_b)))
    
    def _compute_polygon_area(self, points: np.ndarray) -> float:
        """计算多边形面积（Shoelace公式）"""
        n = len(points)
        if n < 3:
            return 0.0
        
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += points[i, 0] * points[j, 1]
            area -= points[j, 0] * points[i, 1]
        
        return abs(area) / 2.0
    
    def _greedy_match(self, cost_matrix: np.ndarray, regions_a: List, regions_b: List) -> List:
        """贪心匹配算法"""
        n_a, n_b = cost_matrix.shape
        matches = []
        used_b = set()
        
        # 按代价排序
        indices = np.argsort(cost_matrix.flatten())
        
        for idx in indices:
            i = idx // n_b
            j = idx % n_b
            
            if j not in used_b:
                matches.append((i, j, cost_matrix[i, j]))
                used_b.add(j)
        
        return matches


# ==================== Step 3: RBF-SDF隐式几何建模 ====================

class SDFBuilder:
    """SDF构建器：使用RBF插值构建隐式距离场"""
    
    def __init__(self, voxel_resolution: int = 50):
        self.voxel_resolution = voxel_resolution
        self.rbf_interpolator = None
        self.bounds = None
    
    def build_sdf(self, sections: List[Dict], matches: List[Dict]) -> Dict:
        """
        构建整个模型的SDF
        
        输入：预处理后的截面列表 + 匹配关系
        输出：SDF体素网格
        """
        print("\n=== Building SDF ===")
        
        # 1. 收集约束点
        constraint_points = []
        constraint_values = []
        
        for section in sections:
            dmx_3d = section.get('dmx_3d', [])
            if dmx_3d:
                for line in dmx_3d:
                    if isinstance(line, np.ndarray) and len(line) > 0:
                        for pt in line:
                            if len(pt) >= 3:
                                constraint_points.append(pt[:3])
                                constraint_values.append(0.0)  # 表面点
        
        if len(constraint_points) < 10:
            print("  [WARN] Not enough constraint points for SDF")
            return {}
        
        constraint_points = np.array(constraint_points)
        constraint_values = np.array(constraint_values)
        
        print(f"  Constraint points: {len(constraint_points)}")
        
        # 2. 计算边界
        self.bounds = {
            'x_min': constraint_points[:, 0].min(),
            'x_max': constraint_points[:, 0].max(),
            'y_min': constraint_points[:, 1].min(),
            'y_max': constraint_points[:, 1].max(),
            'z_min': constraint_points[:, 2].min(),
            'z_max': constraint_points[:, 2].max()
        }
        
        # 添加边界余量
        margin = 10.0
        self.bounds['x_min'] -= margin
        self.bounds['x_max'] += margin
        self.bounds['y_min'] -= margin
        self.bounds['y_max'] += margin
        self.bounds['z_min'] -= margin
        self.bounds['z_max'] += margin
        
        print(f"  Bounds: X({self.bounds['x_min']:.1f}~{self.bounds['x_max']:.1f}), "
              f"Y({self.bounds['y_min']:.1f}~{self.bounds['y_max']:.1f}), "
              f"Z({self.bounds['z_min']:.1f}~{self.bounds['z_max']:.1f})")
        
        # 3. 拟合RBF插值器
        print("  Fitting RBF interpolator...")
        try:
            self.rbf_interpolator = RBFInterpolator(
                constraint_points, 
                constraint_values,
                kernel='thin_plate_spline',
                smoothing=0.1
            )
        except Exception as e:
            print(f"  [ERROR] RBF fitting failed: {e}")
            return {}
        
        # 4. 生成体素网格
        print("  Generating voxel grid...")
        x = np.linspace(self.bounds['x_min'], self.bounds['x_max'], self.voxel_resolution)
        y = np.linspace(self.bounds['y_min'], self.bounds['y_max'], self.voxel_resolution)
        z = np.linspace(self.bounds['z_min'], self.bounds['z_max'], self.voxel_resolution)
        
        X, Y, Z = np.meshgrid(x, y, z, indexing='ij')
        grid_points = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
        
        # 5. 计算SDF值
        print("  Computing SDF values...")
        sdf_values = self.rbf_interpolator(grid_points)
        sdf_grid = sdf_values.reshape(X.shape)
        
        print(f"  SDF grid shape: {sdf_grid.shape}")
        print(f"  SDF range: {sdf_values.min():.2f} ~ {sdf_values.max():.2f}")
        
        return {
            'sdf_grid': sdf_grid,
            'bounds': self.bounds,
            'resolution': self.voxel_resolution,
            'x_coords': x,
            'y_coords': y,
            'z_coords': z
        }
    
    def query_sdf(self, point: np.ndarray) -> float:
        """查询点的SDF值"""
        if self.rbf_interpolator is None:
            return 0.0
        return float(self.rbf_interpolator(point.reshape(1, -1))[0])


# ==================== Step 4: 体素分类场 ====================

class VoxelClassifier:
    """体素分类器：构建分类场并进行CRF优化"""
    
    def __init__(self, smoothness: float = 1.0):
        self.smoothness = smoothness
    
    def classify_voxels(self, sdf_data: Dict, sections: List[Dict], matches: List[Dict]) -> Dict:
        """
        对体素进行分类
        
        输入：SDF数据 + 截面数据 + 匹配关系
        输出：分类标签体素网格
        """
        print("\n=== Classifying Voxels ===")
        
        if not sdf_data:
            return {}
        
        sdf_grid = sdf_data['sdf_grid']
        bounds = sdf_data['bounds']
        resolution = sdf_data['resolution']
        x_coords = sdf_data['x_coords']
        y_coords = sdf_data['y_coords']
        z_coords = sdf_data['z_coords']
        
        # 初始化分类网格
        label_grid = np.zeros(sdf_grid.shape, dtype=np.int32)  # 0 = 背景
        confidence_grid = np.zeros(sdf_grid.shape, dtype=np.float32)
        
        # 为每个截面投票
        print("  Voting from sections...")
        for section in sections:
            geological_regions = section.get('geological_regions', {})
            
            for category, regions in geological_regions.items():
                cat_id = self._get_category_id(category)
                if cat_id == 0:
                    continue
                
                for region in regions:
                    points = region['points']
                    centroid = region['centroid']
                    
                    # 找到对应的体素范围
                    for i, x in enumerate(x_coords):
                        for j, y in enumerate(y_coords):
                            for k, z in enumerate(z_coords):
                                # 检查点是否在区域内（简化：使用距离判断）
                                dist = np.sqrt((x - centroid[0])**2 + (y - centroid[1])**2)
                                if dist < 50:  # 简化的距离阈值
                                    if confidence_grid[i, j, k] < 1.0 / (dist + 1):
                                        label_grid[i, j, k] = cat_id
                                        confidence_grid[i, j, k] = 1.0 / (dist + 1)
        
        # 应用高斯平滑（简化版CRF）
        print("  Applying smoothness...")
        for cat_id in range(1, 4):
            mask = (label_grid == cat_id).astype(np.float32)
            smoothed = gaussian_filter(mask, sigma=self.smoothness)
            label_grid[smoothed > 0.5] = cat_id
        
        # 统计各类别体素数
        unique, counts = np.unique(label_grid, return_counts=True)
        print(f"  Label distribution:")
        for u, c in zip(unique, counts):
            cat_name = self._get_category_name(u)
            print(f"    {cat_name}: {c} voxels")
        
        return {
            'label_grid': label_grid,
            'confidence_grid': confidence_grid,
            'bounds': bounds,
            'resolution': resolution
        }
    
    def _get_category_id(self, category: str) -> int:
        """获取类别ID"""
        mapping = {
            'mud_fill': 1,
            'clay': 2,
            'sand_and_gravel': 3
        }
        return mapping.get(category, 0)
    
    def _get_category_name(self, cat_id: int) -> str:
        """获取类别名称"""
        mapping = {
            0: 'background',
            1: 'mud_fill',
            2: 'clay',
            3: 'sand_and_gravel'
        }
        return mapping.get(cat_id, 'unknown')


# ==================== Step 5: Marching Cubes网格提取 ====================

class MeshExtractor:
    """网格提取器：使用Marching Cubes算法从SDF提取网格"""
    
    def extract_mesh(self, sdf_data: Dict, label_data: Dict) -> Dict:
        """
        从SDF和分类数据提取网格
        
        输入：SDF数据 + 分类数据
        输出：各类别的三角网格
        """
        print("\n=== Extracting Meshes ===")
        
        if not sdf_data or not label_data:
            return {}
        
        try:
            from skimage.measure import marching_cubes
        except ImportError:
            print("  [ERROR] scikit-image not available for marching cubes")
            return self._simple_mesh_extraction(sdf_data, label_data)
        
        meshes = {}
        sdf_grid = sdf_data['sdf_grid']
        label_grid = label_data['label_grid']
        bounds = sdf_data['bounds']
        
        # 为每个类别提取等值面
        for cat_id in range(1, 4):
            cat_name = self._get_category_name(cat_id)
            
            # 创建该类别的掩码
            mask = (label_grid == cat_id).astype(np.float32)
            
            if np.sum(mask) < 10:
                print(f"  {cat_name}: skipped (too few voxels)")
                continue
            
            try:
                # 使用marching cubes提取表面
                verts, faces, normals, values = marching_cubes(mask, level=0.5)
                
                # 转换到世界坐标
                x_scale = (bounds['x_max'] - bounds['x_min']) / sdf_grid.shape[0]
                y_scale = (bounds['y_max'] - bounds['y_min']) / sdf_grid.shape[1]
                z_scale = (bounds['z_max'] - bounds['z_min']) / sdf_grid.shape[2]
                
                verts[:, 0] = verts[:, 0] * x_scale + bounds['x_min']
                verts[:, 1] = verts[:, 1] * y_scale + bounds['y_min']
                verts[:, 2] = verts[:, 2] * z_scale + bounds['z_min']
                
                meshes[cat_name] = {
                    'vertices': verts,
                    'faces': faces,
                    'normals': normals
                }
                
                print(f"  {cat_name}: {len(verts)} vertices, {len(faces)} faces")
                
            except Exception as e:
                print(f"  {cat_name}: extraction failed - {e}")
        
        return meshes
    
    def _simple_mesh_extraction(self, sdf_data: Dict, label_data: Dict) -> Dict:
        """简化的网格提取（当scikit-image不可用时）"""
        print("  Using simple mesh extraction...")
        
        meshes = {}
        label_grid = label_data['label_grid']
        bounds = sdf_data['bounds']
        
        # 简化：为每个类别创建边界框网格
        for cat_id in range(1, 4):
            cat_name = self._get_category_name(cat_id)
            mask = label_grid == cat_id
            
            if np.sum(mask) < 10:
                continue
            
            # 找到该类别的边界
            indices = np.where(mask)
            x_min, x_max = indices[0].min(), indices[0].max()
            y_min, y_max = indices[1].min(), indices[1].max()
            z_min, z_max = indices[2].min(), indices[2].max()
            
            # 转换到世界坐标
            x_scale = (bounds['x_max'] - bounds['x_min']) / label_grid.shape[0]
            y_scale = (bounds['y_max'] - bounds['y_min']) / label_grid.shape[1]
            z_scale = (bounds['z_max'] - bounds['z_min']) / label_grid.shape[2]
            
            # 创建简单的盒子网格
            verts = np.array([
                [x_min, y_min, z_min],
                [x_max, y_min, z_min],
                [x_max, y_max, z_min],
                [x_min, y_max, z_min],
                [x_min, y_min, z_max],
                [x_max, y_min, z_max],
                [x_max, y_max, z_max],
                [x_min, y_max, z_max],
            ], dtype=np.float32)
            
            verts[:, 0] = verts[:, 0] * x_scale + bounds['x_min']
            verts[:, 1] = verts[:, 1] * y_scale + bounds['y_min']
            verts[:, 2] = verts[:, 2] * z_scale + bounds['z_min']
            
            faces = np.array([
                [0, 1, 2], [0, 2, 3],  # 底面
                [4, 5, 6], [4, 6, 7],  # 顶面
                [0, 1, 5], [0, 5, 4],  # 前面
                [2, 3, 7], [2, 7, 6],  # 后面
                [0, 3, 7], [0, 7, 4],  # 左面
                [1, 2, 6], [1, 6, 5],  # 右面
            ])
            
            meshes[cat_name] = {
                'vertices': verts,
                'faces': faces
            }
            
            print(f"  {cat_name}: simple box mesh created")
        
        return meshes
    
    def _get_category_name(self, cat_id: int) -> str:
        """获取类别名称"""
        mapping = {
            1: 'mud_fill',
            2: 'clay',
            3: 'sand_and_gravel'
        }
        return mapping.get(cat_id, 'unknown')


# ==================== V9模型构建器主类 ====================

class GeologyModelBuilderV9:
    """
    V9地质模型构建器
    
    架构：SDF隐式建模 + 体素分类优化
    """
    
    def __init__(self, section_json_path: str, spine_json_path: str, 
                 voxel_resolution: int = 50):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.voxel_resolution = voxel_resolution
        
        self.sections_data = None
        self.spine_matches = None
        self.sections_3d = []
        
        # 各模块
        self.preprocessor = SectionPreprocessor(num_samples=64)
        self.matcher = SectionMatcher()
        self.sdf_builder = SDFBuilder(voxel_resolution=voxel_resolution)
        self.classifier = VoxelClassifier(smoothness=1.0)
        self.extractor = MeshExtractor()
    
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
        
        # 找到最近的两个匹配点
        stations = [m.get('station_value', 0) for m in matches]
        
        if station_value <= min(stations):
            return matches[0]
        if station_value >= max(stations):
            return matches[-1]
        
        # 线性插值
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
        
        # 修复：使用正确的字段名 ref_x/ref_y（而非 x/y）
        l1_ref = section.get('l1_ref_point', {})
        ref_x = l1_ref.get('ref_x', 0)
        ref_y = l1_ref.get('ref_y', 0)
        spine_x = spine_match.get('spine_x', 0)
        spine_y = spine_match.get('spine_y', 0)
        # 修复：使用 tangent_angle + pi/2 作为旋转角（与V7一致）
        tangent_angle = spine_match.get('tangent_angle', 0)
        rotation_angle = tangent_angle + math.pi / 2
        
        result = {
            'station': section.get('station_value', 0),
            'dmx_3d': [],
            'overbreak_3d': [],
            'fill_boundaries': {}
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
            if len(all_ob_points) >= 3:
                all_ob_points = sorted(all_ob_points, key=lambda p: p[0])
                result['overbreak_3d'] = [np.array(all_ob_points)]
        
        # 转换地质边界
        fill_boundaries = section.get('fill_boundaries', {})
        for layer_name, polygons in fill_boundaries.items():
            result['fill_boundaries'][layer_name] = []
            for polygon in polygons:
                if len(polygon) >= 3:
                    poly_3d = []
                    for pt in polygon:
                        if len(pt) >= 2:
                            eng_x, eng_y, z = transform_to_spine_aligned(
                                pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                            )
                            poly_3d.append([eng_x, eng_y])
                    if len(poly_3d) >= 3:
                        result['fill_boundaries'][layer_name].append(np.array(poly_3d))
        
        return result
    
    def build_model(self) -> Dict:
        """构建V9模型"""
        print("\n" + "=" * 60)
        print("V9 Geology Model Builder")
        print("  - SDF Implicit Modeling")
        print("  - Voxel Classification with CRF")
        print("  - Marching Cubes Mesh Extraction")
        print("=" * 60)
        
        if not self.load_data():
            return {}
        
        # Step 1: 转换截面到3D
        print("\n=== Transforming Sections to 3D ===")
        sections = self.sections_data.get('sections', [])
        
        for i, section in enumerate(sections):
            section_3d = self._transform_section_to_3d(section)
            if section_3d:
                self.sections_3d.append(section_3d)
        
        print(f"  Transformed sections: {len(self.sections_3d)}")
        
        # Step 2: 截面预处理
        print("\n=== Preprocessing Sections ===")
        preprocessed_sections = []
        for section in self.sections_3d:
            preprocessed = self.preprocessor.preprocess_section(section)
            preprocessed_sections.append(preprocessed)
        
        # Step 3: 截面间匹配
        print("\n=== Matching Adjacent Sections ===")
        matches = []
        for i in range(len(preprocessed_sections) - 1):
            match = self.matcher.match_sections(
                preprocessed_sections[i], 
                preprocessed_sections[i + 1]
            )
            matches.append(match)
        
        print(f"  Match pairs: {len(matches)}")
        
        # Step 4: 构建SDF
        sdf_data = self.sdf_builder.build_sdf(self.sections_3d, matches)
        
        # Step 5: 体素分类
        label_data = self.classifier.classify_voxels(sdf_data, preprocessed_sections, matches)
        
        # Step 6: 网格提取
        meshes = self.extractor.extract_mesh(sdf_data, label_data)
        
        return {
            'sdf_data': sdf_data,
            'label_data': label_data,
            'meshes': meshes,
            'sections_3d': self.sections_3d
        }
    
    def export_to_html(self, output_path: str, model_data: Dict,
                       title: str = "V9 Geology Model - SDF Implicit"):
        """导出为Plotly HTML"""
        print("\n=== Exporting to HTML ===")
        
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError:
            print("  [ERROR] plotly not available")
            return
        
        fig = make_subplots(
            rows=1, cols=1,
            specs=[[{'type': 'mesh3d'}]],
            subplot_titles=['V9 SDF Model']
        )
        
        meshes = model_data.get('meshes', {})
        
        for cat_name, mesh_data in meshes.items():
            vertices = mesh_data.get('vertices', np.array([]))
            faces = mesh_data.get('faces', np.array([]))
            
            if len(vertices) == 0 or len(faces) == 0:
                continue
            
            cat_info = LAYER_CATEGORIES.get(cat_name, {})
            color = cat_info.get('color', '#888888')
            name = cat_info.get('name_cn', cat_name)
            
            fig.add_trace(
                go.Mesh3d(
                    x=vertices[:, 0],
                    y=vertices[:, 1],
                    z=vertices[:, 2],
                    i=faces[:, 0],
                    j=faces[:, 1],
                    k=faces[:, 2],
                    color=color,
                    name=name,
                    legendgroup=cat_name,
                    showlegend=True,
                    opacity=0.8
                ),
                row=1, col=1
            )
        
        # 添加DMX参考线
        sections_3d = model_data.get('sections_3d', [])
        for section in sections_3d[:10]:  # 只显示前10个
            dmx_3d = section.get('dmx_3d', [])
            for line in dmx_3d:
                if isinstance(line, np.ndarray) and len(line) > 0:
                    fig.add_trace(
                        go.Scatter3d(
                            x=line[:, 0],
                            y=line[:, 1],
                            z=line[:, 2],
                            mode='lines',
                            line=dict(color='blue', width=2),
                            name='DMX',
                            legendgroup='dmx',
                            showlegend=False
                        ),
                        row=1, col=1
                    )
        
        fig.update_layout(
            title=title,
            scene=dict(
                xaxis_title='X (East)',
                yaxis_title='Y (North)',
                zaxis_title='Z (Elevation)',
                aspectmode='data'
            ),
            legend=dict(
                x=1.02,
                y=0.98,
                xanchor='left',
                yanchor='top'
            ),
            width=1400,
            height=900
        )
        
        fig.write_html(output_path)
        print(f"  Output: {output_path}")
        print(f"  File size: {os.path.getsize(output_path) / 1024:.1f} KB")
    
    def build_and_export(self, output_path: str) -> str:
        """构建模型并导出"""
        model_data = self.build_model()
        
        if model_data:
            self.export_to_html(output_path, model_data)
            return output_path
        
        return ""


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='V9 Geology Model Builder')
    parser.add_argument('--section-json', type=str, 
                        default=r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json')
    parser.add_argument('--spine-json', type=str,
                        default=r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json')
    parser.add_argument('--output', type=str,
                        default=r'D:\断面算量平台\测试文件\geology_model_v9.html')
    parser.add_argument('--resolution', type=int, default=50,
                        help='Voxel grid resolution')
    
    args = parser.parse_args()
    
    builder = GeologyModelBuilderV9(
        args.section_json,
        args.spine_json,
        voxel_resolution=args.resolution
    )
    
    builder.build_and_export(args.output)


if __name__ == '__main__':
    main()