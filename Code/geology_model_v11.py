# -*- coding: utf-8 -*-
"""
航道三维地质模型 V11 - 点云版本

核心设计：
1. 使用Scatter3d代替Mesh3d - 没有拓扑约束，没有穿透问题
2. 纵向插值：每2米生成一个虚拟截面（y_step=2.0）
3. 横向采样：每1米采样一个点（x_step=1.0）
4. 垂直填充：每0.5米填充一个点（z_fill_step=0.5）
5. DMX约束裁剪：point.z = min(point.z, dmx.z) - 简单裁剪防止穿透

关键算法：
- build_point_cloud(): 构建点云数据
- interpolate_section(): 截面间纵向插值
- sample_lateral_points(): 横向采样
- fill_vertical_points(): 垂直填充
- clip_to_dmx(): DMX约束裁剪

作者: @黄秉俊
日期: 2026-04-06
"""

import json
import numpy as np
import os
from typing import List, Dict, Tuple, Optional
import math
import sys
from scipy.interpolate import interp1d

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


# ==================== 点云核心算法 ====================

class PointCloudModelBuilder:
    """
    点云模型构建器
    
    核心思路：
    1. 不构建Mesh，直接生成点云
    2. 点云密度控制：纵向2m，横向1m，垂直0.5m
    3. DMX约束裁剪：防止穿透
    """
    
    def __init__(self, metadata: Dict, spine_data: Dict):
        self.metadata = metadata
        self.spine_data = spine_data
        
        # 点云密度参数
        self.y_step = 2.0  # 纵向每2米生成一个点集
        self.x_step = 1.0  # 横向每1米生成一个点
        self.z_fill_step = 0.5  # 垂直方向填充步长
        
        # 数据存储
        self.sections_3d = []
        self.point_clouds = {}  # {category: np.array(N, 3)}
        
    def transform_all_sections(self) -> List[Dict]:
        """将所有截面转换为3D坐标"""
        sections_3d = []
        
        sections = self.metadata.get('sections', [])
        matches = self.spine_data.get('matches', [])
        
        # 构建station到spine_match的映射
        spine_map = {}
        for match in matches:
            station = match.get('station_value')
            if station is not None:
                spine_map[station] = match
        
        for section in sections:
            station_value = section.get('station_value')
            if station_value is None:
                continue
            
            spine_match = spine_map.get(station_value)
            if spine_match is None:
                continue
            
            section_3d = self._transform_section_to_3d(section, spine_match)
            if section_3d:
                sections_3d.append(section_3d)
        
        # 按station排序
        sections_3d.sort(key=lambda s: s.get('station_value', 0))
        self.sections_3d = sections_3d
        
        print(f"[INFO] 转换完成: {len(sections_3d)}个截面")
        return sections_3d
    
    def _transform_section_to_3d(self, section: Dict, spine_match: Dict) -> Dict:
        """将单个截面转换为3D坐标"""
        try:
            # 获取spine参数
            spine_x = spine_match.get('spine_x', 0)
            spine_y = spine_match.get('spine_y', 0)
            tangent_angle = spine_match.get('tangent_angle', 0)
            rotation_angle = tangent_angle + math.pi / 2
            
            # 获取L1参考点
            l1_ref = section.get('l1_ref_point', {})
            ref_x = l1_ref.get('ref_x', 0)
            ref_y = l1_ref.get('ref_y', 0)
            
            if ref_x == 0 and ref_y == 0:
                return None
            
            # 转换DMX点
            dmx_pts = section.get('dmx_points', [])
            dmx_3d = []
            for pt in dmx_pts:
                cad_x, cad_y = pt[0], pt[1]
                eng_x, eng_y, z = transform_to_spine_aligned(
                    cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                )
                dmx_3d.append([eng_x, eng_y, z])
            
            # 转换超挖线（注意：overbreak_points是嵌套列表）
            overbreak_pts = section.get('overbreak_points', [])
            overbreak_3d = []
            for ob_line in overbreak_pts:
                if len(ob_line) >= 2:
                    for pt in ob_line:
                        if len(pt) >= 2:
                            cad_x, cad_y = pt[0], pt[1]
                            eng_x, eng_y, z = transform_to_spine_aligned(
                                cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                            )
                            overbreak_3d.append([eng_x, eng_y, z])
            
            # 转换地质层（注意：fill_boundaries是{layer_name: [boundaries]}）
            fill_boundaries = section.get('fill_boundaries', {})
            fill_boundaries_3d = {}
            
            for layer_name, boundaries in fill_boundaries.items():
                category = categorize_layer(layer_name)
                if category is None:
                    continue
                
                if category not in fill_boundaries_3d:
                    fill_boundaries_3d[category] = []
                
                for boundary in boundaries:
                    if len(boundary) < 3:
                        continue
                    
                    poly_3d = []
                    for pt in boundary:
                        if len(pt) >= 2:
                            cad_x, cad_y = pt[0], pt[1]
                            eng_x, eng_y, z = transform_to_spine_aligned(
                                cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle
                            )
                            poly_3d.append([eng_x, eng_y, z])
                    
                    if len(poly_3d) >= 3:
                        fill_boundaries_3d[category].append(np.array(poly_3d))
            
            return {
                'station_value': section.get('station_value'),
                'spine_y': spine_y,
                'dmx_3d': np.array(dmx_3d) if dmx_3d else np.array([]),
                'overbreak_3d': np.array(overbreak_3d) if overbreak_3d else np.array([]),
                'fill_boundaries_3d': fill_boundaries_3d
            }
            
        except Exception as e:
            print(f"[WARN] 截面转换失败: {e}")
            return None
    
    def build_point_cloud(self) -> Dict[str, np.ndarray]:
        """
        构建点云数据
        
        核心算法：
        1. 纵向插值：在相邻截面间生成虚拟截面（每2m）
        2. 横向采样：在每个截面/虚拟截面上横向采样（每1m）
        3. 垂直填充：在地质层内部垂直填充点（每0.5m）
        4. DMX约束：裁剪超出DMX的点
        """
        if not self.sections_3d:
            self.transform_all_sections()
        
        point_clouds = {cat: [] for cat in LAYER_ORDER}
        dmx_points = []  # DMX点云
        
        # 获取里程范围
        stations = [s.get('station_value', 0) for s in self.sections_3d]
        if len(stations) < 2:
            print("[WARN] 截面数量不足，无法构建点云")
            return {}
        
        station_min = min(stations)
        station_max = max(stations)
        
        print(f"[INFO] 里程范围: {station_min} ~ {station_max}")
        print(f"[INFO] 纵向步长: {self.y_step}m")
        
        # 构建截面索引映射
        section_map = {s.get('station_value'): s for s in self.sections_3d}
        sorted_stations = sorted(stations)
        
        # 纵向遍历：每y_step生成一个虚拟截面
        current_y = station_min
        section_idx = 0
        
        while current_y <= station_max:
            # 找到当前y所在的截面区间
            while section_idx < len(sorted_stations) - 1 and sorted_stations[section_idx + 1] < current_y:
                section_idx += 1
            
            # 获取或插值当前截面的数据
            if current_y in section_map:
                section_data = section_map[current_y]
            else:
                # 插值生成虚拟截面
                section_data = self._interpolate_section(current_y, section_idx, sorted_stations, section_map)
            
            if section_data:
                # 处理DMX点云
                dmx_3d = section_data.get('dmx_3d', np.array([]))
                if len(dmx_3d) > 0:
                    # 横向采样DMX
                    sampled_dmx = self._sample_line_points(dmx_3d, self.x_step)
                    for pt in sampled_dmx:
                        dmx_points.append(pt)
                
                # 处理地质层点云
                fill_boundaries_3d = section_data.get('fill_boundaries_3d', {})
                
                for category in LAYER_ORDER:
                    polygons = fill_boundaries_3d.get(category, [])
                    
                    for poly in polygons:
                        if len(poly) < 3:
                            continue
                        
                        # 获取该截面的DMX约束
                        dmx_z_limit = self._get_dmx_z_limit(dmx_3d, poly)
                        
                        # 横向采样地质层边界
                        sampled_boundary = self._sample_polygon_boundary(poly, self.x_step)
                        
                        # 垂直填充地质层内部
                        filled_points = self._fill_polygon_vertical(sampled_boundary, self.z_fill_step, dmx_z_limit)
                        
                        for pt in filled_points:
                            point_clouds[category].append(pt)
            
            current_y += self.y_step
        
        # 转换为numpy数组
        result = {}
        for cat, pts in point_clouds.items():
            if pts:
                result[cat] = np.array(pts)
                print(f"[INFO] {LAYER_CATEGORIES[cat]['name_cn']}: {len(pts)}个点")
        
        if dmx_points:
            result['dmx'] = np.array(dmx_points)
            print(f"[INFO] DMX: {len(dmx_points)}个点")
        
        self.point_clouds = result
        return result
    
    def _interpolate_section(self, current_y: float, section_idx: int, 
                             sorted_stations: List[float], section_map: Dict) -> Optional[Dict]:
        """
        在两个截面间插值生成虚拟截面
        
        参数：
        - current_y: 当前里程
        - section_idx: 当前截面索引
        - sorted_stations: 排序后的里程列表
        - section_map: 里程到截面的映射
        """
        if section_idx >= len(sorted_stations) - 1:
            return None
        
        station_a = sorted_stations[section_idx]
        station_b = sorted_stations[section_idx + 1]
        
        section_a = section_map.get(station_a)
        section_b = section_map.get(station_b)
        
        if not section_a or not section_b:
            return None
        
        # 计算插值比例
        ratio = (current_y - station_a) / (station_b - station_a) if station_b != station_a else 0
        
        # 插值DMX
        dmx_a = section_a.get('dmx_3d', np.array([]))
        dmx_b = section_b.get('dmx_3d', np.array([]))
        
        dmx_interp = self._interpolate_line(dmx_a, dmx_b, ratio)
        
        # 插值地质层
        fill_boundaries_interp = {}
        
        for category in LAYER_ORDER:
            polys_a = section_a.get('fill_boundaries_3d', {}).get(category, [])
            polys_b = section_b.get('fill_boundaries_3d', {}).get(category, [])
            
            # 匹配并插值
            matched_polys = self._match_and_interpolate_polys(polys_a, polys_b, ratio)
            
            if matched_polys:
                fill_boundaries_interp[category] = matched_polys
        
        return {
            'station_value': current_y,
            'spine_y': section_a.get('spine_y', 0) + ratio * (section_b.get('spine_y', 0) - section_a.get('spine_y', 0)),
            'dmx_3d': dmx_interp,
            'overbreak_3d': np.array([]),
            'fill_boundaries_3d': fill_boundaries_interp
        }
    
    def _interpolate_line(self, line_a: np.ndarray, line_b: np.ndarray, ratio: float) -> np.ndarray:
        """插值两条线"""
        if len(line_a) == 0 or len(line_b) == 0:
            return np.array([])
        
        # 重采样到相同点数
        n_points = min(len(line_a), len(line_b))
        if n_points < 2:
            return np.array([])
        
        # 简单线性插值
        resampled_a = self._resample_line(line_a, n_points)
        resampled_b = self._resample_line(line_b, n_points)
        
        interp_line = resampled_a + ratio * (resampled_b - resampled_a)
        return interp_line
    
    def _resample_line(self, line: np.ndarray, n_points: int) -> np.ndarray:
        """重采样线到指定点数"""
        if len(line) == n_points:
            return line
        
        # 计算累积距离
        distances = [0]
        for i in range(1, len(line)):
            d = np.linalg.norm(line[i] - line[i-1])
            distances.append(distances[-1] + d)
        
        total_dist = distances[-1] if distances[-1] > 0 else 1
        
        # 创建插值函数
        target_distances = np.linspace(0, total_dist, n_points)
        
        resampled = np.zeros((n_points, 3))
        for dim in range(3):
            interp_func = interp1d(distances, line[:, dim], kind='linear', fill_value='extrapolate')
            resampled[:, dim] = interp_func(target_distances)
        
        return resampled
    
    def _match_and_interpolate_polys(self, polys_a: List[np.ndarray], 
                                      polys_b: List[np.ndarray], ratio: float) -> List[np.ndarray]:
        """匹配并插值两组多边形"""
        result = []
        
        # 简单匹配：按质心距离
        for poly_a in polys_a:
            if len(poly_a) < 3:
                continue
            
            centroid_a = np.mean(poly_a, axis=0)
            
            # 找最近的poly_b
            best_poly_b = None
            best_dist = float('inf')
            
            for poly_b in polys_b:
                if len(poly_b) < 3:
                    continue
                
                centroid_b = np.mean(poly_b, axis=0)
                dist = np.linalg.norm(centroid_a[:2] - centroid_b[:2])  # 只比较XY
                
                if dist < best_dist:
                    best_dist = dist
                    best_poly_b = poly_b
            
            if best_poly_b is not None and best_dist < 50:  # 50m阈值
                # 插值
                interp_poly = self._interpolate_line(poly_a, best_poly_b, ratio)
                result.append(interp_poly)
        
        return result
    
    def _sample_line_points(self, line: np.ndarray, step: float) -> List[np.ndarray]:
        """沿线采样点"""
        if len(line) < 2:
            return list(line)
        
        points = []
        
        # 计算累积距离
        distances = [0]
        for i in range(1, len(line)):
            d = np.linalg.norm(line[i] - line[i-1])
            distances.append(distances[-1] + d)
        
        total_dist = distances[-1]
        
        # 按步长采样
        current_dist = 0
        while current_dist <= total_dist:
            # 找到当前距离对应的点
            for i in range(len(distances) - 1):
                if distances[i] <= current_dist <= distances[i+1]:
                    # 线性插值
                    seg_ratio = (current_dist - distances[i]) / (distances[i+1] - distances[i]) if distances[i+1] != distances[i] else 0
                    pt = line[i] + seg_ratio * (line[i+1] - line[i])
                    points.append(pt)
                    break
            current_dist += step
        
        return points
    
    def _sample_polygon_boundary(self, poly: np.ndarray, step: float) -> List[np.ndarray]:
        """沿多边形边界采样点"""
        if len(poly) < 3:
            return list(poly)
        
        # 确保闭合
        closed_poly = np.vstack([poly, poly[0]])
        
        return self._sample_line_points(closed_poly, step)
    
    def _fill_polygon_vertical(self, boundary_points: List[np.ndarray], 
                                z_step: float, dmx_z_limit: Optional[float] = None) -> List[np.ndarray]:
        """
        在多边形内部垂直填充点
        
        参数：
        - boundary_points: 边界点列表
        - z_step: 垂直步长
        - dmx_z_limit: DMX高程约束（可选）
        """
        if len(boundary_points) < 3:
            return boundary_points
        
        filled_points = []
        
        # 找到高程范围
        z_values = [pt[2] for pt in boundary_points]
        z_min = min(z_values)
        z_max = max(z_values)
        
        # 如果有DMX约束，使用约束值
        if dmx_z_limit is not None:
            z_max = min(z_max, dmx_z_limit)
        
        # 计算XY范围
        x_values = [pt[0] for pt in boundary_points]
        y_values = [pt[1] for pt in boundary_points]
        x_min, x_max = min(x_values), max(x_values)
        y_min, y_max = min(y_values), max(y_values)
        
        # 简化填充：在边界点位置垂直填充
        for pt in boundary_points:
            x, y, z_top = pt[0], pt[1], pt[2]
            
            # 应用DMX约束
            if dmx_z_limit is not None:
                z_top = min(z_top, dmx_z_limit)
            
            # 从顶部向下填充
            current_z = z_top
            while current_z >= z_min:
                filled_points.append(np.array([x, y, current_z]))
                current_z -= z_step
        
        return filled_points
    
    def _get_dmx_z_limit(self, dmx_3d: np.ndarray, poly: np.ndarray) -> Optional[float]:
        """
        获取DMX对给定多边形的高程约束
        
        原理：找到DMX在多边形XY范围内的最小Z值
        """
        if len(dmx_3d) < 2 or len(poly) < 3:
            return None
        
        # 计算多边形XY范围
        poly_x_min, poly_x_max = np.min(poly[:, 0]), np.max(poly[:, 0])
        poly_y_min, poly_y_max = np.min(poly[:, 1]), np.max(poly[:, 1])
        
        # 找到DMX在该范围内的点
        mask = (dmx_3d[:, 0] >= poly_x_min - 5) & (dmx_3d[:, 0] <= poly_x_max + 5) & \
               (dmx_3d[:, 1] >= poly_y_min - 5) & (dmx_3d[:, 1] <= poly_y_max + 5)
        
        dmx_in_range = dmx_3d[mask]
        
        if len(dmx_in_range) == 0:
            return None
        
        # 返回最小Z值（最深的DMX点）
        return np.min(dmx_in_range[:, 2])
    
    def export_to_html(self, output_path: str, point_clouds: Dict[str, np.ndarray]) -> str:
        """
        导出为Plotly HTML
        
        使用Scatter3d代替Mesh3d
        """
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError:
            print("[ERROR] 请安装plotly: pip install plotly")
            return ""
        
        fig = go.Figure()
        
        # 添加DMX点云
        if 'dmx' in point_clouds:
            dmx_pts = point_clouds['dmx']
            fig.add_trace(go.Scatter3d(
                x=dmx_pts[:, 0],
                y=dmx_pts[:, 1],
                z=dmx_pts[:, 2],
                mode='markers',
                marker=dict(
                    size=2,
                    color='#3498db',
                    opacity=0.8
                ),
                name='DMX断面线',
                legendgroup='dmx'
            ))
        
        # 添加地质层点云
        for category in LAYER_ORDER:
            if category not in point_clouds:
                continue
            
            pts = point_clouds[category]
            cat_info = LAYER_CATEGORIES[category]
            
            fig.add_trace(go.Scatter3d(
                x=pts[:, 0],
                y=pts[:, 1],
                z=pts[:, 2],
                mode='markers',
                marker=dict(
                    size=2,
                    color=cat_info['color'],
                    opacity=0.7
                ),
                name=cat_info['name_cn'],
                legendgroup=category
            ))
        
        # 设置布局
        fig.update_layout(
            title='航道三维地质模型 V11 - 点云版本',
            scene=dict(
                xaxis_title='X (东向)',
                yaxis_title='Y (北向里程)',
                zaxis_title='Z (高程)',
                aspectmode='data',
                camera=dict(
                    eye=dict(x=1.5, y=1.5, z=0.8)
                )
            ),
            legend=dict(
                yanchor="top",
                y=0.99,
                xanchor="left",
                x=0.01
            ),
            width=1200,
            height=800
        )
        
        # 保存
        fig.write_html(output_path)
        print(f"[INFO] HTML已保存: {output_path}")
        
        return output_path
    
    def build_and_export(self, output_path: str) -> str:
        """构建并导出"""
        point_clouds = self.build_point_cloud()
        
        if not point_clouds:
            print("[ERROR] 点云构建失败")
            return ""
        
        return self.export_to_html(output_path, point_clouds)


# ==================== 主程序 ====================

def main():
    """主程序入口"""
    # 数据路径
    metadata_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    spine_path = r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    output_path = r'D:\断面算量平台\测试文件\geology_model_v11.html'
    
    print("=" * 60)
    print("航道三维地质模型 V11 - 点云版本")
    print("=" * 60)
    
    # 加载数据
    print("\n[STEP 1] 加载元数据...")
    metadata = load_metadata(metadata_path)
    spine_data = load_spine_matches(spine_path)
    
    print(f"  - 截面数量: {len(metadata.get('sections', []))}")
    print(f"  - 脊梁匹配数量: {len(spine_data.get('matches', []))}")
    
    # 构建点云模型
    print("\n[STEP 2] 构建点云模型...")
    builder = PointCloudModelBuilder(metadata, spine_data)
    
    # 设置点云密度参数
    builder.y_step = 2.0  # 纵向每2米
    builder.x_step = 1.0  # 横向每1米
    builder.z_fill_step = 0.5  # 垂直每0.5米
    
    print(f"  - 纵向步长: {builder.y_step}m")
    print(f"  - 横向步长: {builder.x_step}m")
    print(f"  - 垂直步长: {builder.z_fill_step}m")
    
    # 构建并导出
    print("\n[STEP 3] 导出HTML...")
    result_path = builder.build_and_export(output_path)
    
    if result_path:
        print("\n" + "=" * 60)
        print("构建完成!")
        print("=" * 60)
        
        # 统计信息
        total_points = sum(len(pts) for pts in builder.point_clouds.values())
        print(f"\n总点数: {total_points}")
        
        for cat, pts in builder.point_clouds.items():
            if cat == 'dmx':
                print(f"  - DMX: {len(pts)}个点")
            else:
                print(f"  - {LAYER_CATEGORIES[cat]['name_cn']}: {len(pts)}个点")
        
        print(f"\n输出文件: {result_path}")
    else:
        print("\n[ERROR] 构建失败")


if __name__ == '__main__':
    main()