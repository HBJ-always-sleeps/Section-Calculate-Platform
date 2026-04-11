# -*- coding: utf-8 -*-
"""
航道三维模型完整构建流程 - 从DXF到3D模型

功能：
1. 从DXF提取断面数据（地质分层、DMX、超挖线）
2. 脊梁点匹配与坐标转换
3. 构建精细三维模型

作者: @黄秉俊
日期: 2026-04-02
"""

import json
import numpy as np
import os
from typing import List, Dict, Tuple, Optional
import math
import sys

# 添加Code目录到路径
sys.path.insert(0, r'D:\断面算量平台\Code')
from bim_lofting_core import BIMLoftingEngine


# ==================== 地层分类映射 ====================

LAYER_CATEGORIES = {
    'mud_fill': {
        'name': 'Mud & Fill',
        'name_cn': '淤泥与填土',
        'color': '#7f8c8d',
        'layers': ['1级淤泥', '2级淤泥', '3级淤泥', '4级淤泥', '1级填土', '2级填土', '3级填土', '4级填土']
    },
    'clay': {
        'name': 'Clay',
        'name_cn': '黏土',
        'color': '#A52A2A',
        'layers': ['3级黏土', '4级黏土', '5级黏土']
    },
    'sand_gravel': {
        'name': 'Sand & Gravel',
        'name_cn': '砂与碎石',
        'color': '#f1c40f',
        'layers': ['6级砂', '7级砂', '8级砂', '6级碎石', '9级碎石']
    }
}


def categorize_layer(layer_name: str) -> Optional[str]:
    """将原始层名映射到分类类别"""
    if '淤泥' in layer_name or '级淤泥' in layer_name or '淤' in layer_name:
        return 'mud_fill'
    if '填土' in layer_name or '级填土' in layer_name or '填' in layer_name:
        return 'mud_fill'
    if '黏土' in layer_name or '粘土' in layer_name or '级黏土' in layer_name or '黏' in layer_name:
        return 'clay'
    if '砂' in layer_name or '级砂' in layer_name:
        return 'sand_gravel'
    if '碎石' in layer_name or '级碎石' in layer_name or '砾' in layer_name:
        return 'sand_gravel'
    return None


def load_metadata(json_path: str) -> Dict:
    """加载JSON元数据文件"""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_spine_matches(json_path: str) -> Dict:
    """加载脊梁点匹配结果"""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def merge_boundaries_by_category(fill_boundaries: Dict, category: str) -> List[List[Tuple[float, float]]]:
    """合并同一类别的所有边界"""
    merged = []
    for layer_name, boundaries in fill_boundaries.items():
        cat = categorize_layer(layer_name)
        if cat == category:
            merged.extend(boundaries)
    return merged


def create_merged_polygon(boundaries: List[List[Tuple[float, float]]]) -> Optional[List[Tuple[float, float]]]:
    """从多个边界创建合并的多边形"""
    if not boundaries:
        return None
    
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    
    polygons = []
    for boundary in boundaries:
        if len(boundary) >= 3:
            try:
                poly = Polygon(boundary)
                if poly.is_valid and poly.area > 0:
                    polygons.append(poly)
            except Exception:
                continue
    
    if not polygons:
        return None
    
    merged_poly = unary_union(polygons)
    
    if merged_poly.geom_type == 'Polygon':
        coords = list(merged_poly.exterior.coords)
        return coords[:-1]
    elif merged_poly.geom_type == 'MultiPolygon':
        largest = max(merged_poly.geoms, key=lambda p: p.area)
        coords = list(largest.exterior.coords)
        return coords[:-1]
    
    return None


def transform_to_spine_aligned(
    cad_x: float, cad_y: float,
    ref_x: float, ref_y: float,
    spine_x: float, spine_y: float,
    rotation_angle: float
) -> Tuple[float, float, float]:
    """
    将CAD局部坐标转换为脊梁点对齐的三维坐标
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


class Complete3DModelBuilder:
    """完整三维模型构建器"""
    
    def __init__(self, section_json_path: str, spine_json_path: str, num_samples: int = 200):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.num_samples = num_samples
        self.metadata = None
        self.spine_matches = None
        self.sections = []
    
    def load_data(self) -> bool:
        """加载并解析数据"""
        print(f"\n=== Loading Data ===")
        print(f"  Section JSON: {self.section_json_path}")
        print(f"  Spine JSON: {self.spine_json_path}")
        
        self.metadata = load_metadata(self.section_json_path)
        self.spine_matches = load_spine_matches(self.spine_json_path)
        
        if 'sections' not in self.metadata:
            print("ERROR: No sections found in metadata!")
            return False
        
        self.sections = self.metadata['sections']
        print(f"  Sections loaded: {len(self.sections)}")
        print(f"  Spine matches: {len(self.spine_matches.get('matches', []))}")
        
        return len(self.spine_matches.get('matches', [])) > 0
    
    def _resample_polygon(self, coords: np.ndarray, num_samples: int, is_closed: bool = True) -> np.ndarray:
        """对多边形/线条进行弧长重采样"""
        coords = np.array(coords)
        if len(coords) < 2:
            if len(coords) == 1:
                return np.tile(coords[0], (num_samples, 1))
            return np.zeros((num_samples, 3))
        
        if is_closed and not np.allclose(coords[0], coords[-1]):
            coords = np.vstack([coords, coords[0]])
        
        diff = np.diff(coords, axis=0)
        dist = np.sqrt((diff**2).sum(axis=1))
        s = np.concatenate(([0], np.cumsum(dist)))
        
        if s[-1] == 0:
            return np.tile(coords[0], (num_samples, 1))
        
        target_s = np.linspace(0, s[-1], num_samples, endpoint=not is_closed)
        resampled = np.zeros((num_samples, 3))
        for i in range(3):
            resampled[:, i] = np.interp(target_s, s, coords[:, i])
        
        if is_closed and num_samples > 10:
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
    
    def build_category_volumes(self) -> Dict[str, Dict]:
        """构建三类地质实体的体积数据"""
        print(f"\n=== Building Category Volumes ===")
        
        spine_dict = {}
        for match in self.spine_matches.get('matches', []):
            spine_dict[match['station_value']] = match
        
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        category_data = {
            'mud_fill': {'coords_3d_list': [], 'color': LAYER_CATEGORIES['mud_fill']['color']},
            'clay': {'coords_3d_list': [], 'color': LAYER_CATEGORIES['clay']['color']},
            'sand_gravel': {'coords_3d_list': [], 'color': LAYER_CATEGORIES['sand_gravel']['color']}
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
            
            for category in category_data.keys():
                merged_bounds = merge_boundaries_by_category(fill_boundaries, category)
                
                if merged_bounds:
                    merged_poly = create_merged_polygon(merged_bounds)
                    if merged_poly and len(merged_poly) >= 3:
                        coords_3d = []
                        for pt in merged_poly:
                            eng_x, eng_y, z = transform_to_spine_aligned(
                                pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                            )
                            coords_3d.append([eng_x, eng_y, z])
                        
                        resampled = self._resample_polygon(np.array(coords_3d), self.num_samples, is_closed=True)
                        category_data[category]['coords_3d_list'].append(resampled)
                    elif category_data[category]['coords_3d_list']:
                        last_coords = category_data[category]['coords_3d_list'][-1]
                        centroid = np.mean(last_coords, axis=0)
                        category_data[category]['coords_3d_list'].append(np.tile(centroid, (self.num_samples, 1)))
        
        for category, data in category_data.items():
            print(f"  {LAYER_CATEGORIES[category]['name_cn']}: {len(data['coords_3d_list'])} sections")
        
        return category_data
    
    def build_dmx_lines(self) -> List[np.ndarray]:
        """构建DMX线条（使用Scatter3d而非Mesh3d）"""
        print(f"\n=== Building DMX Lines ===")
        
        spine_dict = {}
        for match in self.spine_matches.get('matches', []):
            spine_dict[match['station_value']] = match
        
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
                dmx_lines.append(np.array(coords_3d))
        
        print(f"  DMX lines: {len(dmx_lines)}")
        return dmx_lines
    
    def build_overbreak_lines(self) -> List[np.ndarray]:
        """构建超挖线（过滤异常数据）"""
        print(f"\n=== Building Overbreak Lines ===")
        
        spine_dict = {}
        for match in self.spine_matches.get('matches', []):
            spine_dict[match['station_value']] = match
        
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        all_overbreaks = []
        
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
            
            overbreak_points = section.get('overbreak_points', [])
            
            for ob_line in overbreak_points:
                if len(ob_line) >= 2:
                    coords_3d = []
                    for pt in ob_line:
                        eng_x, eng_y, z = transform_to_spine_aligned(
                            pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                        )
                        coords_3d.append([eng_x, eng_y, z])
                    
                    line_arr = np.array(coords_3d)
                    
                    diff = np.diff(line_arr, axis=0)
                    length = np.sqrt((diff**2).sum()).sum()
                    span = np.sqrt(((line_arr.max(axis=0) - line_arr.min(axis=0))**2).sum())
                    
                    if length > 10 and span < 500:
                        all_overbreaks.append(line_arr)
        
        print(f"  Valid overbreak lines: {len(all_overbreaks)}")
        return all_overbreaks
    
    def export_to_html(self, output_path: str, category_data: Dict, dmx_lines: List, overbreak_lines: List):
        """导出为Plotly HTML格式"""
        try:
            import plotly.graph_objects as go
        except ImportError:
            print("ERROR: Need plotly library: pip install plotly")
            return None
        
        print(f"\n=== Exporting HTML ===")
        print(f"  Output: {output_path}")
        
        fig = go.Figure()
        
        # 地质体积实体
        for category, data in category_data.items():
            coords_list = data['coords_3d_list']
            if len(coords_list) < 2:
                continue
            
            color = data['color']
            num_sects = len(coords_list)
            num_pts = len(coords_list[0])
            
            all_points = []
            for coords in coords_list:
                for pt in coords:
                    all_points.append([pt[0], pt[1], pt[2]])
            all_points = np.array(all_points)
            
            faces = []
            for i in range(num_sects - 1):
                for j in range(num_pts):
                    next_j = (j + 1) % num_pts
                    p1 = i * num_pts + j
                    p2 = i * num_pts + next_j
                    p3 = (i + 1) * num_pts + next_j
                    p4 = (i + 1) * num_pts + j
                    faces.append([p1, p2, p3])
                    faces.append([p1, p3, p4])
            
            i_list = [f[0] for f in faces]
            j_list = [f[1] for f in faces]
            k_list = [f[2] for f in faces]
            
            fig.add_trace(go.Mesh3d(
                x=all_points[:, 0], y=all_points[:, 1], z=all_points[:, 2],
                i=i_list, j=j_list, k=k_list,
                color=color, opacity=0.7,
                name=LAYER_CATEGORIES[category]['name_cn'],
                legendgroup=category, showlegend=True
            ))
            
            print(f"  {LAYER_CATEGORIES[category]['name_cn']}: {num_sects} sections, {len(faces)} faces")
        
        # 超挖线（Scatter3d线条）
        for idx, ob_line in enumerate(overbreak_lines):
            if len(ob_line) < 2:
                continue
            
            fig.add_trace(go.Scatter3d(
                x=ob_line[:, 0], y=ob_line[:, 1], z=ob_line[:, 2],
                mode='lines',
                line=dict(color='red', width=2),
                name=f'Overbreak-{idx+1}',
                legendgroup='Overbreak',
                showlegend=(idx == 0)
            ))
        
        print(f"  Overbreak lines: {len(overbreak_lines)}")
        
        # DMX线（Scatter3d线条）
        for idx, dmx_line in enumerate(dmx_lines):
            if len(dmx_line) < 2:
                continue
            
            fig.add_trace(go.Scatter3d(
                x=dmx_line[:, 0], y=dmx_line[:, 1], z=dmx_line[:, 2],
                mode='lines',
                line=dict(color='blue', width=1),
                name=f'DMX-{idx+1}',
                legendgroup='DMX',
                showlegend=(idx == 0)
            ))
        
        print(f"  DMX lines: {len(dmx_lines)}")
        
        fig.update_layout(
            title='Spine-Aligned 3D Geological Model (Complete)',
            scene=dict(
                xaxis_title='Engineering X',
                yaxis_title='Engineering Y',
                zaxis_title='Elevation (Z)',
                aspectmode='data'
            ),
            legend=dict(x=0.02, y=0.98, bgcolor='rgba(255,255,255,0.8)')
        )
        
        fig.write_html(output_path)
        print(f"  HTML saved: {output_path}")
        
        return output_path
    
    def build_and_export(self, output_path: str) -> str:
        """完整构建流程"""
        print("=" * 60)
        print("Complete 3D Model Builder")
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
    output_html = r'D:\断面算量平台\测试文件\complete_3d_model.html'
    
    builder = Complete3DModelBuilder(section_json, spine_json, num_samples=200)
    builder.build_and_export(output_html)


if __name__ == '__main__':
    main()