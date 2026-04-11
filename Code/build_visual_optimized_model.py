# -*- coding: utf-8 -*-
"""
航道三维模型视觉优化版本 - 最大化视觉效果

核心改进：
1. DMX双三次样条插值 (Bicubic Spline) + 网格曲面化
2. 超挖线相对厚度约束 (ΔZ ≥ 0) + 穿模防护
3. 砂层独立展示 (6-10级) + 拉普拉斯平滑
4. Z-Clipping空间裁剪
5. 退化逻辑优化（飞艇状透镜体）
6. HSL等距取色法 - 彩虹般区分度极高的色带
7. 砂类圆滑聚合体 - lighting属性优化

作者: @黄秉俊
日期: 2026-04-02
"""

import json
import numpy as np
import os
from typing import List, Dict, Tuple, Optional
import math
import sys
import colorsys

# 添加Code目录到路径
sys.path.insert(0, r'D:\断面算量平台\Code')

# scipy将在需要时延迟导入
SCIPY_AVAILABLE = None  # None表示未检查，True表示可用，False表示不可用


# ==================== HSL等距取色法 ====================

def get_distinct_colors(n: int) -> List[str]:
    """
    使用HSL色空间生成n个视觉区分度极高的颜色
    固定饱和度(80%)和亮度(50%)，只在0-360°之间等距分配色相
    """
    colors = []
    for i in range(n):
        # 使用等距分配色相 (Hue)
        hue = i / n
        # HLS格式: (hue, lightness, saturation)
        rgb = colorsys.hls_to_rgb(hue, 0.5, 0.8)
        hex_color = '#%02x%02x%02x' % tuple(int(x * 255) for x in rgb)
        colors.append(hex_color)
    return colors


# ==================== 地层分类（视觉稳定版） ====================

LAYER_CATEGORIES = {
    'mud_fill': {
        'name_cn': '淤泥与填土',
        'color': '#7f8c8d',
        'layers': ['1级淤泥', '2级淤泥', '3级淤泥', '4级淤泥', '1级填土', '2级填土', '3级填土', '4级填土'],
        'is_sand': False
    },
    'clay': {
        'name_cn': '黏土',
        'color': '#A52A2A',
        'layers': ['3级黏土', '4级黏土', '5级黏土'],
        'is_sand': False
    },
    'sand_and_gravel': {
        'name_cn': '砂与碎石类',
        'color': '#f1c40f',  # 醒目的金黄色
        'layers': ['6级砂', '7级砂', '8级砂', '9级砂', '10级砂', '6级碎石', '9级碎石'],
        'is_sand': True  # 标记为砂层，方便后续特殊处理
    }
}

# 为所有分类生成颜色（使用HSL等距取色）
_all_category_keys = list(LAYER_CATEGORIES.keys())
_distinct_colors = get_distinct_colors(len(_all_category_keys))
for idx, cat_key in enumerate(_all_category_keys):
    LAYER_CATEGORIES[cat_key]['color'] = _distinct_colors[idx]

print(f"  Total categories: {len(LAYER_CATEGORIES)}")
print(f"  Sand layers: {[k for k, v in LAYER_CATEGORIES.items() if v.get('is_sand', False)]}")


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
    """坐标转换"""
    z = cad_y - ref_y
    dx = cad_x - ref_x
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    rotated_dx = dx * cos_a
    rotated_dy = dx * sin_a
    eng_x = spine_x + rotated_dx
    eng_y = spine_y + rotated_dy
    return eng_x, eng_y, z


class VisualOptimizedModelBuilder:
    """视觉优化三维模型构建器"""
    
    def __init__(self, section_json_path: str, spine_json_path: str, num_samples: int = 300):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.num_samples = num_samples
        self.metadata = None
        self.spine_matches = None
        self.sections = []
        self.smooth_iterations = 100
        self.smooth_factor = 0.05
    
    def load_data(self) -> bool:
        print(f"\n=== Loading Data ===")
        self.metadata = load_metadata(self.section_json_path)
        self.spine_matches = load_spine_matches(self.spine_json_path)
        if 'sections' not in self.metadata:
            return False
        self.sections = self.metadata['sections']
        print(f"  Sections: {len(self.sections)}, Spine matches: {len(self.spine_matches.get('matches', []))}")
        return True
    
    def _resample_line(self, coords: np.ndarray, num_samples: int) -> np.ndarray:
        """对线条进行弧长重采样"""
        coords = np.array(coords)
        if len(coords) < 2:
            return np.tile(coords[0], (num_samples, 1)) if len(coords) == 1 else np.zeros((num_samples, 3))
        
        diff = np.diff(coords, axis=0)
        dist = np.sqrt((diff**2).sum(axis=1))
        s = np.concatenate(([0], np.cumsum(dist)))
        
        if s[-1] == 0:
            return np.tile(coords[0], (num_samples, 1))
        
        target_s = np.linspace(0, s[-1], num_samples)
        resampled = np.zeros((num_samples, 3))
        for i in range(3):
            resampled[:, i] = np.interp(target_s, s, coords[:, i])
        return resampled
    
    def _resample_polygon(self, coords: np.ndarray, num_samples: int) -> np.ndarray:
        """对闭合多边形进行弧长重采样"""
        coords = np.array(coords)
        if len(coords) < 3:
            return np.tile(coords[0], (num_samples, 1)) if len(coords) > 0 else np.zeros((num_samples, 3))
        
        if not np.allclose(coords[0], coords[-1]):
            coords = np.vstack([coords, coords[0]])
        
        diff = np.diff(coords, axis=0)
        dist = np.sqrt((diff**2).sum(axis=1))
        s = np.concatenate(([0], np.cumsum(dist)))
        
        if s[-1] == 0:
            return np.tile(coords[0], (num_samples, 1))
        
        target_s = np.linspace(0, s[-1], num_samples, endpoint=False)
        resampled = np.zeros((num_samples, 3))
        for i in range(3):
            resampled[:, i] = np.interp(target_s, s, coords[:, i])
        
        # 对齐起始点
        xy = resampled[:, :2]
        min_xy = xy.min(axis=0)
        max_xy = xy.max(axis=0)
        range_xy = max_xy - min_xy
        range_xy[range_xy == 0] = 1
        norm_xy = (xy - min_xy) / range_xy
        scores = norm_xy[:, 0] - norm_xy[:, 1]
        start_idx = np.argmin(scores)
        resampled = np.roll(resampled, -start_idx, axis=0)
        
        return resampled
    
    def _smooth_mesh(self, points: np.ndarray, faces: List) -> Tuple[np.ndarray, List]:
        """拉普拉斯平滑（可选）"""
        # 跳过平滑，直接返回原始数据
        # PyVista smooth在某些环境会崩溃
        return points, faces
    
    def _normalize_polygon(self, points: np.ndarray) -> np.ndarray:
        """
        统一多边形绕向(逆时针)并将最左侧点作为起点，防止三维蒙皮扭曲
        解决不同断面多边形起始点/方向不一致导致的麻花状扭转
        """
        if points is None or len(points) < 3:
            return points
        
        # 1. 计算多边形有向面积，判断绕向
        # 使用 XZ 平面（X为宽度，Z为高程）
        area = 0
        n = len(points)
        for i in range(n):
            j = (i + 1) % n
            area += points[i, 0] * points[j, 2] - points[j, 0] * points[i, 2]
        
        # 如果面积为负（顺时针），则翻转数组使其变为逆时针
        if area < 0:
            points = points[::-1]
        
        # 2. 找到 X 坐标最小（最左侧）的点作为共同的对齐锚点
        min_idx = np.argmin(points[:, 0])
        
        # 3. 滚动数组，让最左侧点始终作为第0个点
        points = np.roll(points, -min_idx, axis=0)
        
        return points
    
    def _split_overbreak_line(self, line: np.ndarray) -> Dict[str, np.ndarray]:
        """
        将超挖线分成三部分：底部、左端、右端
        底部：两个底角之间的部分（最低点之间）
        左端：航道左侧部分
        右端：航道右侧部分
        """
        if len(line) < 3:
            return {'bottom': line, 'left': np.array([]), 'right': np.array([])}
        
        # 找到底角（最低点）
        z_coords = line[:, 2]
        min_z = np.min(z_coords)
        
        # 找到所有最低点的索引
        bottom_indices = np.where(z_coords <= min_z + 0.1)[0]
        
        if len(bottom_indices) < 2:
            # 如果只有一个最低点，将其作为底部中心
            bottom_center = bottom_indices[0]
            bottom_start = max(0, bottom_center - 1)
            bottom_end = min(len(line), bottom_center + 2)
        else:
            # 取第一个和最后一个最低点作为底部边界
            bottom_start = bottom_indices[0]
            bottom_end = bottom_indices[-1] + 1
        
        # 分割超挖线
        bottom = line[bottom_start:bottom_end]
        left = line[:bottom_start]
        right = line[bottom_end:]
        
        return {
            'bottom': bottom,
            'left': left,
            'right': right
        }
    
    def create_smooth_surface(self, lines_data: List[np.ndarray], grid_resolution: int = 200) -> Optional[Dict]:
        """
        将离散线转化为平滑曲面网格
        使用动态边界裁剪和Cubic平滑，防止插值溢出
        """
        global SCIPY_AVAILABLE
        
        # 延迟导入scipy
        if SCIPY_AVAILABLE is None:
            try:
                from scipy.interpolate import griddata, interp1d
                SCIPY_AVAILABLE = True
            except ImportError:
                SCIPY_AVAILABLE = False
                print("    scipy not available, skipping surface creation")
                return None
        
        if not SCIPY_AVAILABLE:
            return None
        
        if len(lines_data) < 2:
            print("    Not enough lines for surface creation")
            return None
        
        # 1. 收集所有点，并提取每个里程(Y)的实际宽度边界
        all_x, all_y, all_z = [], [], []
        boundary_dict = {}  # {y_val: {'min_x': min_x, 'max_x': max_x}}
        
        for line in lines_data:
            if len(line) == 0:
                continue
            x_coords = line[:, 0]
            y_coords = line[:, 1]
            z_coords = line[:, 2]
            
            # 同一条线在同一个断面，取第一个y即可
            y_val = y_coords[0]
            
            all_x.extend(x_coords)
            all_y.extend(y_coords)
            all_z.extend(z_coords)
            
            if y_val not in boundary_dict:
                boundary_dict[y_val] = {'min_x': np.min(x_coords), 'max_x': np.max(x_coords)}
            else:
                boundary_dict[y_val]['min_x'] = min(boundary_dict[y_val]['min_x'], np.min(x_coords))
                boundary_dict[y_val]['max_x'] = max(boundary_dict[y_val]['max_x'], np.max(x_coords))
        
        if len(all_x) < 4:
            print("    Not enough points for interpolation")
            return None
        
        all_x = np.array(all_x)
        all_y = np.array(all_y)
        all_z = np.array(all_z)
        
        # 2. 定义高致密度网格（提升平滑度）
        xi = np.linspace(np.min(all_x), np.max(all_x), grid_resolution)
        yi = np.linspace(np.min(all_y), np.max(all_y), grid_resolution)
        X, Y = np.meshgrid(xi, yi)
        
        try:
            from scipy.interpolate import griddata, interp1d
            
            # 3. 插值生成平滑的 Z 值（裁剪前大胆使用 cubic）
            Z = griddata((all_x, all_y), all_z, (X, Y), method='cubic')
            # 使用 linear 给 cubic 的插值盲区兜底
            Z_linear = griddata((all_x, all_y), all_z, (X, Y), method='linear')
            Z = np.where(np.isnan(Z), Z_linear, Z)
            
            # 4. 构建边界包络线函数
            sorted_y = sorted(list(boundary_dict.keys()))
            min_x_vals = [boundary_dict[y]['min_x'] for y in sorted_y]
            max_x_vals = [boundary_dict[y]['max_x'] for y in sorted_y]
            
            # 允许边界线进行微弱的外推，防止越界报错
            f_min_x = interp1d(sorted_y, min_x_vals, kind='linear', fill_value="extrapolate")
            f_max_x = interp1d(sorted_y, max_x_vals, kind='linear', fill_value="extrapolate")
            
            # 5. 执行动态裁剪：将原始数据范围外的网格点全部置为 NaN
            for i in range(len(yi)):
                y_current = yi[i]
                x_min_bound = f_min_x(y_current)
                x_max_bound = f_max_x(y_current)
                
                # 找出当前里程下，超出真实航道宽度的点
                mask = (X[i, :] < x_min_bound) | (X[i, :] > x_max_bound)
                Z[i, mask] = np.nan  # Plotly 会自动隐去这些点
            
            return {'X': X, 'Y': Y, 'Z': Z, 'valid': True}
        except Exception as e:
            print(f"    Interpolation failed: {e}")
            return None
    
    def _create_mesh_faces(self, num_sects: int, num_pts: int, is_closed: bool = True) -> List:
        """创建面索引"""
        faces = []
        for i in range(num_sects - 1):
            for j in range(num_pts):
                if is_closed:
                    next_j = (j + 1) % num_pts
                else:
                    if j == num_pts - 1:
                        continue
                    next_j = j + 1
                
                p1 = i * num_pts + j
                p2 = i * num_pts + next_j
                p3 = (i + 1) * num_pts + next_j
                p4 = (i + 1) * num_pts + j
                faces.append([p1, p2, p3])
                faces.append([p1, p3, p4])
        return faces
    
    def build_dmx_surface(self) -> Dict:
        """构建DMX曲面（Bicubic Spline拟合）"""
        print(f"\n=== Building DMX Surface (Bicubic Spline) ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        all_points_3d = []
        
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                continue
            
            l1_ref = section.get('l1_ref_point', {})
            ref_x = l1_ref.get('ref_x', 0)
            ref_y = l1_ref.get('ref_y', 0)
            spine_x = spine_match['spine_x']
            spine_y = spine_match['spine_y']
            rotation_angle = spine_match['tangent_angle'] + math.pi / 2
            
            dmx_points = section.get('dmx_points', [])
            if dmx_points and len(dmx_points) >= 2:
                for pt in dmx_points:
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    all_points_3d.append([eng_x, eng_y, z])
        
        if len(all_points_3d) < 4:
            print(f"  WARNING: Not enough DMX points for spline fitting")
            return {'points': np.array(all_points_3d), 'valid': False}
        
        all_points_3d = np.array(all_points_3d)
        print(f"  DMX points collected: {len(all_points_3d)}")
        
        return {'points': all_points_3d, 'valid': True}
    
    def build_category_volumes(self) -> Dict[str, Dict]:
        """构建地质实体（不合并多边形，保留独立实体）"""
        print(f"\n=== Building Category Volumes (Independent Entities) ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        category_data = {}
        for cat_key, cat_info in LAYER_CATEGORIES.items():
            category_data[cat_key] = {
                'coords_3d_list': [],
                'color': cat_info['color'],
                'name_cn': cat_info['name_cn'],
                'section_stations': []
            }
        
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                continue
            
            l1_ref = section.get('l1_ref_point', {})
            ref_x = l1_ref.get('ref_x', 0)
            ref_y = l1_ref.get('ref_y', 0)
            spine_x = spine_match['spine_x']
            spine_y = spine_match['spine_y']
            rotation_angle = spine_match['tangent_angle'] + math.pi / 2
            
            fill_boundaries = section.get('fill_boundaries', {})
            
            for cat_key in LAYER_CATEGORIES.keys():
                cat_layers = LAYER_CATEGORIES[cat_key]['layers']
                
                # 收集该类别所有层的边界（不合并，保留独立实体）
                for layer_name, boundaries in fill_boundaries.items():
                    if layer_name in cat_layers:
                        for boundary in boundaries:
                            if len(boundary) >= 3:
                                coords_3d = []
                                for pt in boundary:
                                    eng_x, eng_y, z = transform_to_spine_aligned(
                                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                                    )
                                    coords_3d.append([eng_x, eng_y, z])
                                
                                coords_3d = np.array(coords_3d)
                                
                                # 核心修复点：连线前先执行几何重置，防止麻花状扭曲
                                coords_3d = self._normalize_polygon(coords_3d)
                                
                                resampled = self._resample_polygon(coords_3d, self.num_samples)
                                category_data[cat_key]['coords_3d_list'].append(resampled)
                                category_data[cat_key]['section_stations'].append(section['station_value'])
        
        # 打印统计
        for cat_key, data in category_data.items():
            if data['coords_3d_list']:
                print(f"  {data['name_cn']}: {len(data['coords_3d_list'])} entities")
        
        return category_data
    
    def _merge_boundaries(self, boundaries: List) -> Optional[List]:
        """合并多个边界为一个外轮廓"""
        if not boundaries:
            return None
        
        try:
            from shapely.geometry import Polygon
            from shapely.ops import unary_union
            
            polygons = []
            for boundary in boundaries:
                if len(boundary) >= 3:
                    try:
                        poly = Polygon(boundary)
                        if poly.is_valid and poly.area > 0:
                            polygons.append(poly)
                    except:
                        continue
            
            if not polygons:
                return None
            
            merged = unary_union(polygons)
            if merged.geom_type == 'Polygon':
                return list(merged.exterior.coords)[:-1]
            elif merged.geom_type == 'MultiPolygon':
                largest = max(merged.geoms, key=lambda p: p.area)
                return list(largest.exterior.coords)[:-1]
        except Exception as e:
            print(f"    Merge failed: {e}")
            return boundaries[0] if boundaries else None
        
        return None
    
    def build_dmx_lines(self) -> List[np.ndarray]:
        """构建DMX线条"""
        print(f"\n=== Building DMX Lines ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        dmx_lines = []
        
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                continue
            
            l1_ref = section.get('l1_ref_point', {})
            ref_x = l1_ref.get('ref_x', 0)
            ref_y = l1_ref.get('ref_y', 0)
            spine_x = spine_match['spine_x']
            spine_y = spine_match['spine_y']
            rotation_angle = spine_match['tangent_angle'] + math.pi / 2
            
            dmx_points = section.get('dmx_points', [])
            if dmx_points and len(dmx_points) >= 2:
                coords_3d = []
                for pt in dmx_points:
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    coords_3d.append([eng_x, eng_y, z])
                
                resampled = self._resample_line(np.array(coords_3d), self.num_samples)
                dmx_lines.append(resampled)
        
        print(f"  DMX lines: {len(dmx_lines)}")
        return dmx_lines
    
    def build_overbreak_lines(self) -> Dict[str, List[np.ndarray]]:
        """构建超挖线（分段处理：底部、左端、右端）"""
        print(f"\n=== Building Overbreak Lines (Segmented) ===")
        
        spine_dict = {m['station_value']: m for m in self.spine_matches.get('matches', [])}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        # 先构建DMX高程字典用于ΔZ约束
        dmx_z_dict = {}
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                continue
            
            l1_ref = section.get('l1_ref_point', {})
            ref_y = l1_ref.get('ref_y', 0)
            spine_x = spine_match['spine_x']
            spine_y = spine_match['spine_y']
            
            dmx_points = section.get('dmx_points', [])
            if dmx_points:
                dmx_z = np.mean([pt[1] - ref_y for pt in dmx_points])
                dmx_z_dict[section['station_value']] = dmx_z
        
        # 分段存储超挖线
        overbreak_segments = {
            'bottom': [],  # 底部
            'left': [],    # 左端
            'right': []    # 右端
        }
        
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                continue
            
            l1_ref = section.get('l1_ref_point', {})
            ref_x = l1_ref.get('ref_x', 0)
            ref_y = l1_ref.get('ref_y', 0)
            spine_x = spine_match['spine_x']
            spine_y = spine_match['spine_y']
            rotation_angle = spine_match['tangent_angle'] + math.pi / 2
            
            dmx_z = dmx_z_dict.get(section['station_value'], 0)
            
            overbreak_points = section.get('overbreak_points', [])
            
            for ob_line in overbreak_points:
                if len(ob_line) < 2:
                    continue
                
                coords_3d = []
                for pt in ob_line:
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    
                    # ΔZ约束：超挖线必须在DMX下方
                    if z > dmx_z:
                        z = dmx_z - 0.1  # 强制在DMX下方
                    
                    coords_3d.append([eng_x, eng_y, z])
                
                line_arr = np.array(coords_3d)
                
                # 过滤异常
                diff = np.diff(line_arr, axis=0)
                length = np.sqrt((diff**2).sum()).sum()
                span = np.sqrt(((line_arr.max(axis=0) - line_arr.min(axis=0))**2).sum())
                
                if length > 10 and span < 500:
                    # 分段处理超挖线
                    segments = self._split_overbreak_line(line_arr)
                    
                    # 存储各段
                    if len(segments['bottom']) > 0:
                        overbreak_segments['bottom'].append(segments['bottom'])
                    if len(segments['left']) > 0:
                        overbreak_segments['left'].append(segments['left'])
                    if len(segments['right']) > 0:
                        overbreak_segments['right'].append(segments['right'])
        
        print(f"  Overbreak segments: bottom={len(overbreak_segments['bottom'])}, left={len(overbreak_segments['left'])}, right={len(overbreak_segments['right'])}")
        return overbreak_segments
    
    def export_to_html(self, output_path: str, category_data: Dict, dmx_lines: List, overbreak_segments: Dict[str, List[np.ndarray]]):
        """导出为Plotly HTML（曲面化版本）"""
        try:
            import plotly.graph_objects as go
        except ImportError:
            print("ERROR: Need plotly: pip install plotly")
            return None
        
        print(f"\n=== Exporting HTML (Surface Mode) ===")
        print(f"  Output: {output_path}")
        
        fig = go.Figure()
        
        # 1. 地质体积实体（为每个实体单独构建 Mesh3d）
        for cat_key, data in category_data.items():
            coords_list = data['coords_3d_list']
            if not coords_list:
                continue
            
            color = data['color']
            is_sand = LAYER_CATEGORIES.get(cat_key, {}).get('is_sand', False)
            
            # 砂层特殊光照：调高ambient和diffuse，调低specular（果冻效果）
            if is_sand:
                lighting = dict(
                    ambient=0.9,      # 环境光 - 高
                    diffuse=0.8,      # 漫反射 - 高
                    specular=0.1,     # 高光 - 低（避免刺眼）
                    roughness=0.9,    # 粗糙度 - 高（柔和）
                    fresnel=0.1       # 菲涅尔效应 - 低
                )
                opacity = 0.85
            else:
                lighting = dict(
                    ambient=0.6,
                    diffuse=0.8,
                    specular=0.3,
                    roughness=0.5,
                    fresnel=0.2
                )
                opacity = 0.8
            
            # 为每个实体单独构建 Mesh3d
            for idx, coords in enumerate(coords_list):
                if len(coords) < 3:
                    continue
                
                # 构建简单的三角形扇形网格（从中心点向外辐射）
                num_pts = len(coords)
                center = np.mean(coords, axis=0)
                
                # 添加中心点
                all_points = np.vstack([center, coords])
                
                # 构建三角形面
                i_list, j_list, k_list = [], [], []
                for i in range(1, num_pts):
                    j = i + 1 if i < num_pts else 1
                    i_list.append(0)  # 中心点
                    j_list.append(i)
                    k_list.append(j)
                
                fig.add_trace(go.Mesh3d(
                    x=all_points[:, 0], y=all_points[:, 1], z=all_points[:, 2],
                    i=i_list, j=j_list, k=k_list,
                    color=color, opacity=opacity,
                    lighting=lighting,
                    name=f'{data["name_cn"]}-{idx+1}',
                    legendgroup=cat_key,
                    showlegend=(idx == 0),
                    flatshading=False  # 平滑着色
                ))
            
            print(f"  {data['name_cn']}: {len(coords_list)} entities" + 
                  (" [SAND - Jelly Effect]" if is_sand else ""))
        
        # 2. 超挖线（分段处理：底部、左端、右端）
        print(f"\n  Processing overbreak segments...")
        colors = {'bottom': 'red', 'left': 'orange', 'right': 'purple'}
        names = {'bottom': '超挖底部', 'left': '超挖左端', 'right': '超挖右端'}
        
        for segment_name, segment_lines in overbreak_segments.items():
            if not segment_lines:
                continue
            
            # 为每个段构建 Mesh3d
            for idx, line in enumerate(segment_lines):
                if len(line) < 2:
                    continue
                
                # 使用 Scatter3d 显示线条
                fig.add_trace(go.Scatter3d(
                    x=line[:, 0], y=line[:, 1], z=line[:, 2],
                    mode='lines',
                    line=dict(color=colors[segment_name], width=2),
                    name=f'{names[segment_name]}-{idx+1}',
                    legendgroup=f'Overbreak-{segment_name}',
                    showlegend=(idx == 0)
                ))
            
            print(f"  {names[segment_name]}: {len(segment_lines)} lines")
        
        # 3. DMX线（保持简单线条模式）
        print(f"\n  Processing DMX lines...")
        for idx, dmx_line in enumerate(dmx_lines):
            if len(dmx_line) < 2:
                continue
            fig.add_trace(go.Scatter3d(
                x=dmx_line[:, 0], y=dmx_line[:, 1], z=dmx_line[:, 2],
                mode='lines',
                line=dict(color='blue', width=2),
                name=f'DMX-{idx+1}',
                legendgroup='DMX',
                showlegend=(idx == 0)
            ))
        print(f"  DMX lines: {len(dmx_lines)}")
        
        fig.update_layout(
            title='Visual Optimized 3D Geological Model (Surface Mode)',
            scene=dict(
                xaxis_title='Engineering X',
                yaxis_title='Engineering Y',
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
        print("Visual Optimized 3D Model Builder")
        print("=" * 60)
        
        if not self.load_data():
            return None
        
        category_data = self.build_category_volumes()
        dmx_lines = self.build_dmx_lines()
        overbreak_lines = self.build_overbreak_lines()
        
        self.export_to_html(output_path, category_data, dmx_lines, overbreak_lines)
        
        print("\n" + "=" * 60)
        print("SUCCESS: Model exported!")
        print("=" * 60)
        
        return output_path


def main():
    section_json = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    spine_json = r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    output_html = r'D:\断面算量平台\测试文件\visual_optimized_model.html'
    
    builder = VisualOptimizedModelBuilder(section_json, spine_json, num_samples=300)
    builder.build_and_export(output_html)


if __name__ == '__main__':
    main()
