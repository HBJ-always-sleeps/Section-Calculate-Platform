# -*- coding: utf-8 -*-
"""
航道三维地质模型 V7 - 参数空间版本

核心设计：
1. 将"截面间匹配 + 拉网格"替换为"(s, u, v)参数空间曲面拟合"
2. (x,y,z) -> (s,u,v): s=里程, u=横向偏移, v=高程
3. 使用RBF曲面拟合每个地质层，消除截面匹配问题
4. 自动防止穿透：上层曲面v值始终大于下层

关键算法：
- build_parametric_points(): 构建参数空间点集
- fit_layer_surface(): RBF曲面拟合
- build_volumes(): 从曲面生成体积网格

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

# 添加Code目录到路径
sys.path.insert(0, r'D:\断面算量平台\Code')

# ==================== 地层分类 ====================

LAYER_CATEGORIES = {
    'mud_fill': {
        'name_cn': '淤泥与填土',
        'color': '#7f8c8d',
        'layers': ['1级淤泥', '2级淤泥', '3级淤泥', '4级淤泥', '1级填土', '2级填土', '3级填土', '4级填土'],
        'order': 1,  # 最上层
    },
    'clay': {
        'name_cn': '黏土',
        'color': '#A52A2A',
        'layers': ['3级黏土', '4级黏土', '5级黏土'],
        'order': 2,  # 中层
    },
    'sand_and_gravel': {
        'name_cn': '砂与碎石类',
        'color': '#f1c40f',
        'layers': ['6级砂', '7级砂', '8级砂', '9级砂', '10级砂', '6级碎石', '9级碎石'],
        'order': 3,  # 最下层
    }
}

# 层顺序（从上到下）
LAYER_ORDER = ['mud_fill', 'clay', 'sand_and_gravel']


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


# ==================== 参数空间核心算法 ====================

def build_parametric_points(sections_3d: List[Dict]) -> np.ndarray:
    """
    构建参数空间点集 (s, u, v, label)
    
    输入：sections_3d - 所有截面的3D数据
    输出：param_points - (N, 4)数组，每行是 (s, u, v, category_id)
    
    原理：
    - s = station_value（里程）
    - u = lateral_offset（横向偏移，相对于中心线）
    - v = z（高程）
    - label = category_id（地层类别ID）
    """
    param_points = []
    
    for section in sections_3d:
        s = section.get('station_value', 0)
        dmx_pts = section.get('dmx_3d', np.array([]))
        
        if len(dmx_pts) == 0:
            continue
        
        # 计算中心线X坐标（DMX中心点）
        center_x = np.mean(dmx_pts[:, 0])
        
        # 处理地质层
        fill_boundaries = section.get('fill_boundaries_3d', {})
        
        for layer_name, polygons in fill_boundaries.items():
            category = categorize_layer(layer_name)
            if category is None:
                continue
            
            category_id = LAYER_ORDER.index(category) + 1  # 1,2,3
            
            for poly_pts in polygons:
                if len(poly_pts) < 3:
                    continue
                
                # 将每个点转换为参数空间
                for pt in poly_pts:
                    x, y, z = pt[0], pt[1], pt[2]
                    u = x - center_x  # 横向偏移
                    v = z  # 高程
                    
                    # 过滤异常点
                    if abs(u) > 200:  # 横向偏移超过200m视为异常
                        continue
                    if v > 10 or v < -100:  # 高程异常
                        continue
                    
                    param_points.append([s, u, v, category_id])
    
    return np.array(param_points)


def split_by_layer(param_points: np.ndarray) -> Dict[str, np.ndarray]:
    """
    按地层类别分割参数点
    
    输入：param_points - (N, 4)数组
    输出：{category: points_3d}字典，每层只保留(s, u, v)
    """
    layer_points = {}
    
    for category in LAYER_ORDER:
        category_id = LAYER_ORDER.index(category) + 1
        mask = param_points[:, 3] == category_id
        points = param_points[mask, :3]  # 只取(s, u, v)
        
        if len(points) > 10:  # 至少10个点才拟合
            layer_points[category] = points
    
    return layer_points


def fit_layer_surface(layer_points: np.ndarray,
                      smoothing: float = 0.1) -> Optional[RBFInterpolator]:
    """
    RBF曲面拟合：v = f(s, u)
    
    输入：layer_points - (N, 3)数组，每行是(s, u, v)
    输出：RBFInterpolator对象，可调用rbf(s, u)得到v
    
    原理：
    - 使用Thin Plate Spline RBF（平滑曲面）
    - 输入是(s, u)，输出是v
    - smoothing参数控制平滑度
    - 保留所有原始点，不进行稀疏采样（保持几何精度）
    """
    if len(layer_points) < 10:
        return None
    
    # 提取输入(s, u)和输出v
    X = layer_points[:, :2]  # (s, u)
    y = layer_points[:, 2]   # v
    
    # 不再稀疏采样，保留所有原始点以保持几何精度
    # 如果点数过多，使用neighbors参数限制
    n_neighbors = min(100, len(X) - 1) if len(X) > 100 else None
    
    try:
        # Thin Plate Spline RBF
        if n_neighbors:
            rbf = RBFInterpolator(X, y, kernel='thin_plate_spline',
                                  smoothing=smoothing, neighbors=n_neighbors)
        else:
            rbf = RBFInterpolator(X, y, kernel='thin_plate_spline', smoothing=smoothing)
        return rbf
    except Exception as e:
        print(f"  [WARN] RBF拟合失败: {e}")
        return None


def densify_parametric_grid(s_bounds: Tuple[float, float],
                            u_bounds: Tuple[float, float],
                            n_s: int = 100,
                            n_u: int = 80) -> Tuple[np.ndarray, np.ndarray]:
    """
    构建高密度参数网格（加密采样）
    
    输入：s_bounds, u_bounds - 参数范围
    输出：S, U - 高密度网格
    
    核心思想：
    - 不缩小断面，而是加密采样密度
    - 默认100x80网格，比原来50x40更密集
    """
    S = np.linspace(s_bounds[0], s_bounds[1], n_s)
    U = np.linspace(u_bounds[0], u_bounds[1], n_u)
    return S, U


def evaluate_surfaces(rbfs: Dict[str, RBFInterpolator], 
                      S: np.ndarray, 
                      U: np.ndarray) -> Dict[str, np.ndarray]:
    """
    在参数网格上评估所有曲面
    
    输入：rbfs - 各层的RBF拟合器
    输出：V_surfaces - 各层的v值网格
    """
    V_surfaces = {}
    
    # 创建网格点
    SS, UU = np.meshgrid(S, U)
    grid_points = np.column_stack([SS.ravel(), UU.ravel()])
    
    for category in LAYER_ORDER:
        rbf = rbfs.get(category)
        if rbf is None:
            continue
        
        try:
            V_flat = rbf(grid_points)
            V = V_flat.reshape(SS.shape)
            V_surfaces[category] = V
        except Exception as e:
            print(f"  [WARN] 曲面评估失败 {category}: {e}")
    
    return V_surfaces


def enforce_no_penetration(V_surfaces: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """
    防止穿透：确保上层v值始终大于下层
    
    原理：
    - mud_fill在最上面，v应该最大
    - clay在中间
    - sand_and_gravel在最下面，v应该最小
    - 如果检测到穿透（上层v < 下层v），强制修正
    """
    V_corrected = {}
    
    # 获取各层曲面
    V_mud = V_surfaces.get('mud_fill')
    V_clay = V_surfaces.get('clay')
    V_sand = V_surfaces.get('sand_and_gravel')
    
    # 修正规则：从下往上修正
    # 1. sand_and_gravel保持不变（最底层）
    if V_sand is not None:
        V_corrected['sand_and_gravel'] = V_sand
    
    # 2. clay必须高于sand
    if V_clay is not None and V_sand is not None:
        V_clay_corrected = np.maximum(V_clay, V_sand + 0.5)  # 至少0.5m间隙
        V_corrected['clay'] = V_clay_corrected
    elif V_clay is not None:
        V_corrected['clay'] = V_clay
    
    # 3. mud_fill必须高于clay
    if V_mud is not None:
        if 'clay' in V_corrected:
            V_mud_corrected = np.maximum(V_mud, V_corrected['clay'] + 0.5)
        elif 'sand_and_gravel' in V_corrected:
            V_mud_corrected = np.maximum(V_mud, V_corrected['sand_and_gravel'] + 0.5)
        else:
            V_mud_corrected = V_mud
        V_corrected['mud_fill'] = V_mud_corrected
    
    return V_corrected


def param_to_world(S: np.ndarray, U: np.ndarray, V: np.ndarray,
                   spine_func) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    参数空间 -> 世界坐标
    
    输入：S - 1D数组（里程）
          U - 1D数组（横向偏移）
          V - 2D数组（高程网格，shape=(n_u, n_s)）
    输出：(X, Y, Z)世界坐标网格
    
    原理：
    - X = spine_x(s) + u * cos(angle)
    - Y = spine_y(s) + u * sin(angle)
    - Z = v
    """
    n_u = len(U)
    n_s = len(S)
    
    # 创建meshgrid
    SS, UU = np.meshgrid(S, U)
    
    X = np.zeros((n_u, n_s))
    Y = np.zeros((n_u, n_s))
    Z = V
    
    # 对每个s值，获取spine坐标和角度
    for i, s_val in enumerate(S):
        spine_match = spine_func(s_val)
        spine_x = spine_match.get('spine_x', 0)
        spine_y = spine_match.get('spine_y', 0)
        angle = spine_match.get('tangent_angle', 0) + math.pi / 2
        
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        
        # 横向偏移转换为世界坐标偏移
        for j, u_val in enumerate(U):
            X[j, i] = spine_x + u_val * cos_a
            Y[j, i] = spine_y + u_val * sin_a
    
    return X, Y, Z


def build_mesh_from_surfaces(X: np.ndarray, Y: np.ndarray, 
                             V_top: np.ndarray, V_bottom: np.ndarray,
                             category: str) -> Dict:
    """
    从上下曲面生成体积网格
    
    输入：X, Y - 世界坐标网格
          V_top, V_bottom - 上下曲面的v值
          category - 地层类别
    输出：mesh_data - {vertices, faces}字典
    """
    n_u, n_s = X.shape
    
    vertices = []
    faces = []
    
    color = LAYER_CATEGORIES[category]['color']
    name_cn = LAYER_CATEGORIES[category]['name_cn']
    
    # 构建顶点：上曲面 + 下曲面
    for j in range(n_u):
        for i in range(n_s):
            # 上曲面顶点
            vertices.append([X[j, i], Y[j, i], V_top[j, i]])
            # 下曲面顶点
            vertices.append([X[j, i], Y[j, i], V_bottom[j, i]])
    
    vertices = np.array(vertices)
    
    # 构建面：每个网格单元有2个三角形（上）+ 2个三角形（下）+ 侧面
    for j in range(n_u - 1):
        for i in range(n_s - 1):
            # 顶点索引
            # 上曲面：v0, v1, v2, v3
            v0_top = 2 * (j * n_s + i)
            v1_top = 2 * (j * n_s + i + 1)
            v2_top = 2 * ((j + 1) * n_s + i + 1)
            v3_top = 2 * ((j + 1) * n_s + i)
            
            # 下曲面：v0, v1, v2, v3（索引+1）
            v0_bot = v0_top + 1
            v1_bot = v1_top + 1
            v2_bot = v2_top + 1
            v3_bot = v3_top + 1
            
            # 上曲面三角形
            faces.append([v0_top, v1_top, v2_top])
            faces.append([v0_top, v2_top, v3_top])
            
            # 下曲面三角形（反向）
            faces.append([v0_bot, v2_bot, v1_bot])
            faces.append([v0_bot, v3_bot, v2_bot])
            
            # 侧面三角形（连接上下）
            # 前侧面
            faces.append([v0_top, v1_top, v1_bot])
            faces.append([v0_top, v1_bot, v0_bot])
            
            # 后侧面
            faces.append([v2_top, v3_top, v3_bot])
            faces.append([v2_top, v3_bot, v2_bot])
            
            # 左侧面
            faces.append([v0_top, v3_top, v3_bot])
            faces.append([v0_top, v3_bot, v0_bot])
            
            # 右侧面
            faces.append([v1_top, v2_top, v2_bot])
            faces.append([v1_top, v2_bot, v1_bot])
    
    faces = np.array(faces)
    
    return {
        'vertices': vertices,
        'faces': faces,
        'category': category,
        'color': color,
        'name_cn': name_cn
    }


# ==================== DMX/超挖线处理（保留V4逻辑） ====================

def find_bottom_corners(points: np.ndarray, z_tolerance: float = 0.3) -> Tuple[int, int]:
    """识别梯形槽的底角点"""
    if len(points) < 4:
        return (0, len(points) - 1)
    
    z_min = np.min(points[:, 2])
    bottom_threshold = z_min + z_tolerance
    
    bottom_indices = np.where(points[:, 2] <= bottom_threshold)[0]
    
    if len(bottom_indices) >= 2:
        left_corner = bottom_indices[0]
        right_corner = bottom_indices[-1]
        return (left_corner, right_corner)
    
    return (0, len(points) - 1)


def resample_line_uniform(points: np.ndarray, num_samples: int) -> np.ndarray:
    """均匀重采样线条"""
    if len(points) < 2:
        return points
    
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
    分段重采样梯形槽：左坡 + 底板 + 右坡
    确保底角点纵向对齐
    """
    if len(points) < 4:
        return resample_line_uniform(points, n_slope * 2 + n_bottom)
    
    left_corner, right_corner = find_bottom_corners(points)
    
    # 分段
    left_slope = points[:left_corner + 1]
    bottom = points[left_corner:right_corner + 1]
    right_slope = points[right_corner:]
    
    # 重采样各段
    left_resampled = resample_line_uniform(left_slope, n_slope) if len(left_slope) > 1 else left_slope
    bottom_resampled = resample_line_uniform(bottom, n_bottom) if len(bottom) > 1 else bottom
    right_resampled = resample_line_uniform(right_slope, n_slope) if len(right_slope) > 1 else right_slope
    
    # 合并（去重叠点）
    if len(left_resampled) > 0 and len(bottom_resampled) > 0:
        if np.allclose(left_resampled[-1], bottom_resampled[0]):
            bottom_resampled = bottom_resampled[1:]
    
    if len(bottom_resampled) > 0 and len(right_resampled) > 0:
        if np.allclose(bottom_resampled[-1], right_resampled[0]):
            right_resampled = right_resampled[1:]
    
    return np.vstack([left_resampled, bottom_resampled, right_resampled])


def generate_dmx_ribbon(section_data_list: List[Dict], 
                        num_samples: int = 60) -> Dict:
    """生成DMX ribbon曲面"""
    all_lines = []
    
    for section in section_data_list:
        dmx_3d = section.get('dmx_3d', np.array([]))
        if len(dmx_3d) < 2:
            continue
        resampled = resample_line_uniform(dmx_3d, num_samples)
        all_lines.append(resampled)
    
    if len(all_lines) < 2:
        return {'vertices': np.array([]), 'faces': np.array([])}
    
    # 构建ribbon网格
    vertices = []
    faces = []
    
    n_pts = len(all_lines[0])
    
    for line in all_lines:
        vertices.extend(line.tolist())
    
    vertices = np.array(vertices)
    
    n_sections = len(all_lines)
    
    for i in range(n_sections - 1):
        for j in range(n_pts - 1):
            v0 = i * n_pts + j
            v1 = i * n_pts + j + 1
            v2 = (i + 1) * n_pts + j + 1
            v3 = (i + 1) * n_pts + j
            
            faces.append([v0, v1, v2])
            faces.append([v0, v2, v3])
    
    faces = np.array(faces)
    
    return {
        'vertices': vertices,
        'faces': faces,
        'color': '#3498db',
        'name': 'DMX断面线',
        'opacity': 0.5
    }


def smooth_longitudinal(vertices: np.ndarray, window_size: int = 3) -> np.ndarray:
    """
    纵向平滑：沿里程方向平滑顶点
    
    输入：vertices - (n_sections, n_pts, 3)数组
    输出：平滑后的顶点数组
    """
    if len(vertices) < window_size:
        return vertices
    
    smoothed = vertices.copy()
    half_window = window_size // 2
    
    for i in range(half_window, len(vertices) - half_window):
        for j in range(vertices.shape[1]):
            for k in range(3):
                window = vertices[i - half_window:i + half_window + 1, j, k]
                smoothed[i, j, k] = np.mean(window)
    
    return smoothed


def generate_trench_ribbon(section_data_list: List[Dict],
                            n_slope: int = 15,
                            n_bottom: int = 30,
                            apply_smooth: bool = True) -> Dict:
    """
    生成超挖线梯形槽ribbon曲面
    
    与V7原版一致的处理逻辑：
    1. Y坐标异常检查（y_min < 1000时跳过）
    2. 分段重采样（左坡15点 + 底板30点 + 右坡15点）
    3. 形状一致性检查和padding
    4. 纵向平滑
    """
    all_lines = []
    valid_count = 0
    total_points = n_slope * 2 + n_bottom
    
    for section in section_data_list:
        overbreak_3d = section.get('overbreak_3d', [])
        if len(overbreak_3d) == 0:
            continue
        
        # 选择最长的超挖线段
        if isinstance(overbreak_3d, list) and len(overbreak_3d) > 0:
            if isinstance(overbreak_3d[0], list):
                longest = max(overbreak_3d, key=lambda x: len(x))
                overbreak_pts = np.array(longest)
            else:
                overbreak_pts = np.array(overbreak_3d)
        else:
            overbreak_pts = np.array(overbreak_3d)
        
        if len(overbreak_pts) < 2:
            continue
        
        # Y坐标异常检查（与V7原版一致）
        y_min = np.min(overbreak_pts[:, 1])
        if y_min < 1000:
            print(f"  [WARN] Skipping overbreak with abnormal Y range: {y_min:.2f}")
            continue
        
        resampled = resample_trench_segmented(overbreak_pts, n_slope, n_bottom)
        
        # 形状一致性检查和padding（与V7原版一致）
        if resampled.shape[0] != total_points:
            if resampled.shape[0] < total_points:
                padding = np.tile(resampled[-1], (total_points - resampled.shape[0], 1))
                resampled = np.vstack([resampled, padding])
            elif resampled.shape[0] > total_points:
                resampled = resampled[:total_points]
        
        all_lines.append(resampled)
        valid_count += 1
    
    print(f"  [INFO] Valid overbreak lines: {valid_count}")
    
    if len(all_lines) < 2:
        return {'vertices': np.array([]), 'faces': np.array([])}
    
    # 构建3D顶点数组 (n_sections, n_pts, 3)
    vertices_3d = np.array(all_lines)
    
    # 纵向平滑（与V7原版一致）
    if apply_smooth and vertices_3d.shape[0] >= 3:
        vertices_3d = smooth_longitudinal(vertices_3d, window_size=3)
    
    # 展平为顶点列表
    all_vertices = []
    for line in vertices_3d:
        for pt in line:
            all_vertices.append(pt)
    
    vertices = np.array(all_vertices)
    
    # 构建面片
    faces = []
    n_sections = vertices_3d.shape[0]
    n_pts = vertices_3d.shape[1]
    
    for i in range(n_sections - 1):
        for j in range(n_pts - 1):
            v0 = i * n_pts + j
            v1 = i * n_pts + j + 1
            v2 = (i + 1) * n_pts + j + 1
            v3 = (i + 1) * n_pts + j
            
            faces.append([v0, v1, v2])
            faces.append([v0, v2, v3])
    
    faces = np.array(faces)
    
    return {
        'vertices': vertices,
        'faces': faces,
        'color': '#e74c3c',
        'name': '超挖线梯形槽',
        'opacity': 0.3
    }


# ==================== 主构建器类 ====================

class GeologyModelBuilderV7Parametric:
    """
    V7参数空间版本地质模型构建器
    
    核心创新：
    - 不做截面间匹配
    - 直接在(s,u,v)参数空间拟合曲面
    - 自动防止穿透
    """
    
    def __init__(self, section_json_path: str, spine_json_path: str, 
                 output_dir: str = r'D:\断面算量平台\测试文件'):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.output_dir = output_dir
        
        self.metadata = None
        self.spine_matches = None
        self.sections_3d = []
        
        # 参数网格分辨率（高密度加密采样）
        self.n_s = 100  # 里程方向（加密）
        self.n_u = 80   # 横向方向（加密）
        
    def load_data(self) -> bool:
        """加载截面和脊梁数据"""
        try:
            self.metadata = load_metadata(self.section_json_path)
            self.spine_matches = load_spine_matches(self.spine_json_path)
            
            print(f"  [INFO] 加载截面数据: {len(self.metadata.get('sections', []))} 个截面")
            print(f"  [INFO] 加载脊梁数据: {len(self.spine_matches.get('matches', []))} 个匹配点")
            
            return True
        except Exception as e:
            print(f"  [ERROR] 数据加载失败: {e}")
            return False
    
    def _get_interpolated_spine_match(self, station_value: float) -> Dict:
        """插值获取脊梁匹配点"""
        matches = self.spine_matches.get('matches', [])
        
        if len(matches) == 0:
            return {}
        
        # 找到最近的两个匹配点
        stations = [m.get('station_value', 0) for m in matches]
        
        if station_value <= stations[0]:
            return matches[0]
        if station_value >= stations[-1]:
            return matches[-1]
        
        # 线性插值
        for i in range(len(stations) - 1):
            if stations[i] <= station_value <= stations[i + 1]:
                t = (station_value - stations[i]) / (stations[i + 1] - stations[i])
                m1 = matches[i]
                m2 = matches[i + 1]
                
                return {
                    'station_value': station_value,
                    'spine_x': m1['spine_x'] + t * (m2['spine_x'] - m1['spine_x']),
                    'spine_y': m1['spine_y'] + t * (m2['spine_y'] - m1['spine_y']),
                    'tangent_angle': m1['tangent_angle'] + t * (m2['tangent_angle'] - m1['tangent_angle']),
                }
        
        return matches[-1]
    
    def _get_section_3d_data(self, section: Dict, spine_match: Dict) -> Dict:
        """将截面数据转换为3D坐标"""
        section_3d = {
            'station_value': section.get('station_value', 0),
            'dmx_3d': np.array([]),
            'overbreak_3d': [],
            'fill_boundaries_3d': {}
        }
        
        ref_x = section.get('l1_ref_point', {}).get('ref_x', 0)
        ref_y = section.get('l1_ref_point', {}).get('ref_y', 0)
        spine_x = spine_match.get('spine_x', 0)
        spine_y = spine_match.get('spine_y', 0)
        rotation_angle = spine_match.get('tangent_angle', 0) + math.pi / 2
        
        # DMX转换
        dmx_pts = section.get('dmx_points', [])
        if len(dmx_pts) > 0:
            dmx_3d = []
            for pt in dmx_pts:
                cad_x, cad_y = pt[0], pt[1]
                eng_x, eng_y, z = transform_to_spine_aligned(
                    cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                )
                dmx_3d.append([eng_x, eng_y, z])
            section_3d['dmx_3d'] = np.array(dmx_3d)
        
        # 超挖线转换
        overbreak_pts = section.get('overbreak_points', [])
        if len(overbreak_pts) > 0:
            overbreak_3d = []
            for seg in overbreak_pts:
                if isinstance(seg, list):
                    seg_3d = []
                    for pt in seg:
                        cad_x, cad_y = pt[0], pt[1]
                        eng_x, eng_y, z = transform_to_spine_aligned(
                            cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                        )
                        seg_3d.append([eng_x, eng_y, z])
                    overbreak_3d.append(seg_3d)
            section_3d['overbreak_3d'] = overbreak_3d
        
        # 地质层转换
        fill_boundaries = section.get('fill_boundaries', {})
        fill_boundaries_3d = {}
        
        for layer_name, polygons in fill_boundaries.items():
            polygons_3d = []
            for poly in polygons:
                poly_3d = []
                for pt in poly:
                    cad_x, cad_y = pt[0], pt[1]
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    poly_3d.append([eng_x, eng_y, z])
                polygons_3d.append(poly_3d)
            fill_boundaries_3d[layer_name] = polygons_3d
        
        section_3d['fill_boundaries_3d'] = fill_boundaries_3d
        
        return section_3d
    
    def build_all_section_data(self) -> List[Dict]:
        """构建所有截面的3D数据"""
        sections = self.metadata.get('sections', [])
        
        for section in sections:
            station_value = section.get('station_value', 0)
            spine_match = self._get_interpolated_spine_match(station_value)
            section_3d = self._get_section_3d_data(section, spine_match)
            self.sections_3d.append(section_3d)
        
        print(f"  [INFO] 构建3D截面数据: {len(self.sections_3d)} 个")
        return self.sections_3d
    
    def build_parametric_model(self) -> Dict[str, Dict]:
        """
        构建参数空间地质模型
        
        核心流程：
        1. build_parametric_points() - 构建参数点集
        2. split_by_layer() - 按地层分割
        3. fit_layer_surface() - RBF曲面拟合
        4. enforce_no_penetration() - 防止穿透
        5. build_mesh_from_surfaces() - 生成网格
        """
        print("\n[STEP 1] 构建参数空间点集...")
        param_points = build_parametric_points(self.sections_3d)
        
        if len(param_points) == 0:
            print("  [ERROR] 参数点集为空")
            return {}
        
        print(f"  [INFO] 参数点总数: {len(param_points)}")
        
        # 统计各层点数
        for category in LAYER_ORDER:
            category_id = LAYER_ORDER.index(category) + 1
            count = np.sum(param_points[:, 3] == category_id)
            print(f"    - {LAYER_CATEGORIES[category]['name_cn']}: {count} 点")
        
        print("\n[STEP 2] 按地层分割...")
        layer_points = split_by_layer(param_points)
        
        print("\n[STEP 3] RBF曲面拟合...")
        rbfs = {}
        for category, points in layer_points.items():
            print(f"  [INFO] 拟合 {LAYER_CATEGORIES[category]['name_cn']}...")
            rbf = fit_layer_surface(points)
            if rbf is not None:
                rbfs[category] = rbf
                print(f"    - 成功")
            else:
                print(f"    - 失败（点数不足）")
        
        if len(rbfs) == 0:
            print("  [ERROR] 所有曲面拟合失败")
            return {}
        
        print("\n[STEP 4] 构建参数网格...")
        # 计算参数范围
        s_min = np.min(param_points[:, 0])
        s_max = np.max(param_points[:, 0])
        u_min = np.min(param_points[:, 1])
        u_max = np.max(param_points[:, 1])
        
        print(f"  [INFO] s范围: [{s_min:.1f}, {s_max:.1f}]")
        print(f"  [INFO] u范围: [{u_min:.1f}, {u_max:.1f}]")
        
        # 使用高密度网格（加密采样，不缩小断面）
        S, U = densify_parametric_grid((s_min, s_max), (u_min, u_max), self.n_s, self.n_u)
        
        print("\n[STEP 5] 评估曲面...")
        V_surfaces = evaluate_surfaces(rbfs, S, U)
        
        print("\n[STEP 6] 防止穿透修正...")
        V_corrected = enforce_no_penetration(V_surfaces)
        
        print("\n[STEP 7] 转换为世界坐标...")
        # 定义spine插值函数
        def spine_func(s_val):
            return self._get_interpolated_spine_match(s_val)
        
        # 构建各层体积网格
        volume_meshes = {}
        
        # 获取参考曲面（最底层）
        V_ref = V_corrected.get('sand_and_gravel')
        if V_ref is None:
            V_ref = V_corrected.get('clay')
        if V_ref is None:
            V_ref = V_corrected.get('mud_fill')
        
        # 构建各层
        for i, category in enumerate(LAYER_ORDER):
            if category not in V_corrected:
                continue
            
            V_top = V_corrected[category]
            
            # 确定下边界
            if i < len(LAYER_ORDER) - 1:
                next_cat = LAYER_ORDER[i + 1]
                V_bottom = V_corrected.get(next_cat, V_ref)
            else:
                # 最底层：使用参考曲面或固定深度
                V_bottom = V_ref if V_ref is not None else V_top - 5.0
            
            # 转换为世界坐标
            X, Y, Z_top = param_to_world(S, U, V_top, spine_func)
            _, _, Z_bottom = param_to_world(S, U, V_bottom, spine_func)
            
            # 构建网格
            mesh = build_mesh_from_surfaces(X, Y, Z_top, Z_bottom, category)
            volume_meshes[category] = mesh
            
            print(f"  [INFO] {LAYER_CATEGORIES[category]['name_cn']}: "
                  f"{len(mesh['vertices'])} vertices, {len(mesh['faces'])} faces")
        
        return volume_meshes
    
    def build_dmx_ribbon(self) -> Dict:
        """生成DMX ribbon"""
        return generate_dmx_ribbon(self.sections_3d, num_samples=60)
    
    def build_overbreak_ribbon(self) -> Dict:
        """生成超挖线ribbon"""
        return generate_trench_ribbon(self.sections_3d, n_slope=15, n_bottom=30)
    
    def export_to_html(self, output_path: str,
                       volume_meshes: Dict[str, Dict],
                       dmx_ribbon: Dict,
                       overbreak_ribbon: Dict):
        """导出为Plotly HTML"""
        try:
            import plotly.graph_objects as go
            from plotly.offline import plot
        except ImportError:
            print("  [ERROR] plotly未安装")
            return
        
        fig = go.Figure()
        
        # 添加DMX ribbon
        if len(dmx_ribbon.get('vertices', [])) > 0:
            vertices = dmx_ribbon['vertices']
            faces = dmx_ribbon['faces']
            
            x = vertices[:, 0]
            y = vertices[:, 1]
            z = vertices[:, 2]
            i = faces[:, 0]
            j = faces[:, 1]
            k = faces[:, 2]
            
            fig.add_trace(go.Mesh3d(
                x=x, y=y, z=z, i=i, j=j, k=k,
                color=dmx_ribbon['color'],
                opacity=dmx_ribbon['opacity'],
                name=dmx_ribbon['name'],
                legendgroup='dmx',
                showlegend=True
            ))
        
        # 添加超挖线ribbon
        if len(overbreak_ribbon.get('vertices', [])) > 0:
            vertices = overbreak_ribbon['vertices']
            faces = overbreak_ribbon['faces']
            
            x = vertices[:, 0]
            y = vertices[:, 1]
            z = vertices[:, 2]
            i = faces[:, 0]
            j = faces[:, 1]
            k = faces[:, 2]
            
            fig.add_trace(go.Mesh3d(
                x=x, y=y, z=z, i=i, j=j, k=k,
                color=overbreak_ribbon['color'],
                opacity=overbreak_ribbon['opacity'],
                name=overbreak_ribbon['name'],
                legendgroup='overbreak',
                showlegend=True
            ))
        
        # 添加地质体积
        for category, mesh in volume_meshes.items():
            vertices = mesh['vertices']
            faces = mesh['faces']
            
            x = vertices[:, 0]
            y = vertices[:, 1]
            z = vertices[:, 2]
            i = faces[:, 0]
            j = faces[:, 1]
            k = faces[:, 2]
            
            fig.add_trace(go.Mesh3d(
                x=x, y=y, z=z, i=i, j=j, k=k,
                color=mesh['color'],
                opacity=0.7,
                name=mesh['name_cn'],
                legendgroup=category,
                showlegend=True
            ))
        
        # 设置布局
        fig.update_layout(
            title='航道三维地质模型 V7 - 参数空间版本',
            scene=dict(
                xaxis_title='X (东向)',
                yaxis_title='Y (北向)',
                zaxis_title='Z (高程)',
                aspectmode='data'
            ),
            legend=dict(
                x=0.02,
                y=0.98,
                bgcolor='rgba(255,255,255,0.8)'
            ),
            width=1200,
            height=800
        )
        
        # 保存HTML
        plot(fig, filename=output_path, auto_open=False)
        print(f"  [INFO] HTML已保存: {output_path}")
    
    def build_and_export(self, output_path: str) -> str:
        """完整构建流程"""
        print("\n" + "="*60)
        print("航道三维地质模型 V7 - 参数空间版本")
        print("="*60)
        
        # 1. 加载数据
        if not self.load_data():
            return ""
        
        # 2. 构建3D截面数据
        self.build_all_section_data()
        
        # 3. 构建DMX和超挖线ribbon
        print("\n[BUILD] DMX ribbon...")
        dmx_ribbon = self.build_dmx_ribbon()
        print(f"  [INFO] DMX: {len(dmx_ribbon.get('vertices', []))} vertices")
        
        print("\n[BUILD] 超挖线 ribbon...")
        overbreak_ribbon = self.build_overbreak_ribbon()
        print(f"  [INFO] 超挖线: {len(overbreak_ribbon.get('vertices', []))} vertices")
        
        # 4. 构建参数空间地质模型
        print("\n[BUILD] 参数空间地质模型...")
        volume_meshes = self.build_parametric_model()
        
        # 5. 导出HTML
        print("\n[EXPORT] HTML...")
        self.export_to_html(output_path, volume_meshes, dmx_ribbon, overbreak_ribbon)
        
        # 统计
        total_vertices = len(dmx_ribbon.get('vertices', [])) + \
                        len(overbreak_ribbon.get('vertices', []))
        total_faces = len(dmx_ribbon.get('faces', [])) + \
                      len(overbreak_ribbon.get('faces', []))
        
        for mesh in volume_meshes.values():
            total_vertices += len(mesh['vertices'])
            total_faces += len(mesh['faces'])
        
        print("\n" + "="*60)
        print(f"[SUMMARY] 总计: {total_vertices} vertices, {total_faces} faces")
        print("="*60)
        
        return output_path


# ==================== 主函数 ====================

def main():
    """测试运行"""
    section_json = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    spine_json = r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    output_html = r'D:\断面算量平台\测试文件\geology_model_v7_parametric.html'
    
    builder = GeologyModelBuilderV7Parametric(section_json, spine_json)
    builder.build_and_export(output_html)


if __name__ == '__main__':
    main()