# -*- coding: utf-8 -*-
"""
航道三维模型构建器 - 脊梁点对齐版本

坐标映射规则：
- X轴：脊梁点工程坐标X（spine_x）+ 断面局部X偏移（旋转后）
- Y轴：脊梁点工程坐标Y（spine_y）+ 断面局部Y偏移（旋转后）
- Z轴：CAD原始高程（相对于L1基准点，脊梁点统一在Z=0）

这样确保：
1. 断面在XY平面上按真实地理位置排布（曲线）
2. Z轴保留真实的相对高程关系
3. 脊梁点在Z轴上统一对齐

作者: @黄秉俊
日期: 2026-04-02
"""

import json
import numpy as np
import os
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import math
import sys

# 添加Code目录到路径
sys.path.insert(0, r'D:\断面算量平台\Code')
from bim_lofting_core import BIMLoftingEngine, GeologicalBody, SectionMetadata

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
    target_layers = LAYER_CATEGORIES[category]['layers']
    
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
        return coords
    elif merged_poly.geom_type == 'MultiPolygon':
        largest = max(merged_poly.geoms, key=lambda p: p.area)
        coords = list(largest.exterior.coords)
        return coords
    
    return None


def transform_to_spine_aligned(
    cad_x: float, cad_y: float,
    ref_x: float, ref_y: float,
    spine_x: float, spine_y: float,
    rotation_angle: float
) -> Tuple[float, float, float]:
    """
    将CAD局部坐标转换为脊梁点对齐的三维坐标
    
    坐标映射规则：
    - X/Y轴：使用脊梁点工程坐标 + 旋转后的水平偏移
    - Z轴：CAD点的Y值相对于L1基准点的高程差（脊梁点在Z=0）
    
    Args:
        cad_x, cad_y: CAD局部坐标（Y是高程方向）
        ref_x, ref_y: L1基准点在CAD坐标中的位置（ref_y是高程）
        spine_x, spine_y: 脊梁点工程坐标
        rotation_angle: 旋转角度（弧度）
    
    Returns:
        (eng_x, eng_y, z): 工程坐标X, Y + 相对高程Z
    """
    # 1. 计算相对高程（Z轴）
    # CAD中Y轴是高程方向，ref_y是L1基准点的高程
    # Z = CAD点的Y - L1基准点的Y，使脊梁点在Z=0
    z = cad_y - ref_y
    
    # 2. 计算水平偏移（只使用X方向）
    dx = cad_x - ref_x
    
    # 3. 旋转（使断面与切线垂直）
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    rotated_dx = dx * cos_a
    rotated_dy = dx * sin_a
    
    # 4. 计算工程坐标X/Y
    eng_x = spine_x + rotated_dx
    eng_y = spine_y + rotated_dy
    
    return eng_x, eng_y, z


class SpineAlignedModelBuilder:
    """脊梁点对齐三维模型构建器"""
    
    def __init__(self, section_json_path: str, spine_json_path: str, num_samples: int = 100):
        """
        Args:
            section_json_path: 断面JSON元数据文件路径
            spine_json_path: 脊梁点匹配结果JSON路径
            num_samples: 重采样点数
        """
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.num_samples = num_samples
        self.metadata = None
        self.spine_matches = None
        self.sections = []
        self.engine = BIMLoftingEngine(num_samples=num_samples)
    
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
    
    def build_category_volumes(self) -> Dict[str, Dict]:
        """构建三类地质实体的体积数据"""
        print(f"\n=== Building Category Volumes ===")
        
        # 创建脊梁点查找字典
        spine_dict = {}
        for match in self.spine_matches.get('matches', []):
            station_value = match['station_value']
            spine_dict[station_value] = match
        
        # 按桩号排序
        sorted_sections = sorted(
            self.sections,
            key=lambda s: s['station_value'],
            reverse=True
        )
        
        category_data = {
            'mud_fill': {'coords_3d_list': [], 'color': LAYER_CATEGORIES['mud_fill']['color']},
            'clay': {'coords_3d_list': [], 'color': LAYER_CATEGORIES['clay']['color']},
            'sand_gravel': {'coords_3d_list': [], 'color': LAYER_CATEGORIES['sand_gravel']['color']}
        }
        
        for section in sorted_sections:
            station_value = section['station_value']
            
            # 获取脊梁点匹配数据
            spine_match = spine_dict.get(station_value)
            if not spine_match:
                print(f"  WARNING: No spine match for station {section['station_name']}")
                continue
            
            # 获取转换参数
            l1_ref = section.get('l1_ref_point', {})
            ref_x = l1_ref.get('ref_x', 0)
            ref_y = l1_ref.get('ref_y', 0)
            
            spine_x = spine_match['spine_x']
            spine_y = spine_match['spine_y']
            tangent_angle = spine_match['tangent_angle']
            
            # 计算旋转角度（使断面与切线垂直，沿法线方向展开）
            # 法线角度 = 切线角度 + 90°
            rotation_angle = tangent_angle + math.pi / 2
            
            # 获取填充边界
            fill_boundaries = section.get('fill_boundaries', {})
            
            for category in category_data.keys():
                merged_bounds = merge_boundaries_by_category(fill_boundaries, category)
                
                if merged_bounds:
                    merged_poly = create_merged_polygon(merged_bounds)
                    if merged_poly and len(merged_poly) >= 3:
                        # 转换每个点到三维坐标
                        coords_3d = []
                        for pt in merged_poly:
                            eng_x, eng_y, z = transform_to_spine_aligned(
                                pt[0], pt[1],
                                ref_x, ref_y,
                                spine_x, spine_y,
                                rotation_angle
                            )
                            coords_3d.append([eng_x, eng_y, z])
                        category_data[category]['coords_3d_list'].append(np.array(coords_3d))
                    elif category_data[category]['coords_3d_list']:
                        # 尖灭处理
                        last_coords = category_data[category]['coords_3d_list'][-1]
                        centroid = np.mean(last_coords, axis=0)
                        taper_coords = np.array([centroid] * self.num_samples)
                        category_data[category]['coords_3d_list'].append(taper_coords)
        
        for category, data in category_data.items():
            print(f"  {LAYER_CATEGORIES[category]['name_cn']}: {len(data['coords_3d_list'])} sections")
        
        return category_data
    
    def build_dmx_ribbon(self) -> List[np.ndarray]:
        """构建DMX带状曲面"""
        print(f"\n=== Building DMX Ribbon Surface ===")
        
        # 创建脊梁点查找字典
        spine_dict = {}
        for match in self.spine_matches.get('matches', []):
            station_value = match['station_value']
            spine_dict[station_value] = match
        
        # 按桩号排序
        sorted_sections = sorted(
            self.sections,
            key=lambda s: s['station_value'],
            reverse=True
        )
        
        coords_3d_list = []
        
        for section in sorted_sections:
            station_value = section['station_value']
            spine_match = spine_dict.get(station_value)
            if not spine_match:
                continue
            
            l1_ref = section.get('l1_ref_point', {})
            ref_x = l1_ref.get('ref_x', 0)
            ref_y = l1_ref.get('ref_y', 0)
            
            spine_x = spine_match['spine_x']
            spine_y = spine_match['spine_y']
            tangent_angle = spine_match['tangent_angle']
            
            # 计算旋转角度（使断面与切线垂直，沿法线方向展开）
            rotation_angle = tangent_angle + math.pi / 2
            
            dmx_points = section.get('dmx_points', [])
            if dmx_points and len(dmx_points) >= 2:
                coords_3d = []
                for pt in dmx_points:
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        pt[0], pt[1],
                        ref_x, ref_y,
                        spine_x, spine_y,
                        rotation_angle
                    )
                    coords_3d.append([eng_x, eng_y, z])
                coords_3d_list.append(np.array(coords_3d))
        
        print(f"  DMX sections: {len(coords_3d_list)}")
        return coords_3d_list
    
    def build_overbreak_ribbons(self) -> List[List[np.ndarray]]:
        """构建超挖线带状曲面"""
        print(f"\n=== Building Overbreak Ribbon Surfaces ===")
        
        # 创建脊梁点查找字典
        spine_dict = {}
        for match in self.spine_matches.get('matches', []):
            station_value = match['station_value']
            spine_dict[station_value] = match
        
        # 按桩号排序
        sorted_sections = sorted(
            self.sections,
            key=lambda s: s['station_value'],
            reverse=True
        )
        
        # 收集所有超挖线
        all_overbreaks = []
        
        for section in sorted_sections:
            station_value = section['station_value']
            spine_match = spine_dict.get(station_value)
            if not spine_match:
                continue
            
            l1_ref = section.get('l1_ref_point', {})
            ref_x = l1_ref.get('ref_x', 0)
            ref_y = l1_ref.get('ref_y', 0)
            
            spine_x = spine_match['spine_x']
            spine_y = spine_match['spine_y']
            tangent_angle = spine_match['tangent_angle']
            
            # 计算旋转角度（使断面与切线垂直，沿法线方向展开）
            rotation_angle = tangent_angle + math.pi / 2
            
            overbreak_points = section.get('overbreak_points', [])
            
            for i, ob_line in enumerate(overbreak_points):
                if len(ob_line) >= 2:
                    while len(all_overbreaks) <= i:
                        all_overbreaks.append([])
                    
                    coords_3d = []
                    for pt in ob_line:
                        eng_x, eng_y, z = transform_to_spine_aligned(
                            pt[0], pt[1],
                            ref_x, ref_y,
                            spine_x, spine_y,
                            rotation_angle
                        )
                        coords_3d.append([eng_x, eng_y, z])
                    all_overbreaks[i].append(np.array(coords_3d))
        
        # 过滤有效的超挖线
        valid_overbreaks = [ob for ob in all_overbreaks if len(ob) >= 2]
        print(f"  Valid overbreak ribbons: {len(valid_overbreaks)}")
        
        return valid_overbreaks
    
    def _resample_3d_polygon(self, coords_3d: np.ndarray, num_samples: int) -> np.ndarray:
        """
        对3D多边形进行弧长重采样，确保点数一致
        
        Args:
            coords_3d: 3D坐标数组 [[x, y, z], ...]
            num_samples: 目标采样点数
        
        Returns:
            重采样后的3D坐标数组
        """
        coords_3d = np.array(coords_3d)
        
        # 闭合多边形
        if not np.allclose(coords_3d[0], coords_3d[-1]):
            coords_3d = np.vstack([coords_3d, coords_3d[0]])
        
        # 计算弧长参数
        diff = np.diff(coords_3d, axis=0)
        dist = np.sqrt((diff**2).sum(axis=1))
        u = np.concatenate(([0], np.cumsum(dist)))
        
        if u[-1] == 0:
            return np.tile(coords_3d[0], (num_samples, 1))
        
        # 线性插值重采样
        try:
            target_u = np.linspace(0, u[-1], num_samples)
            resampled = np.zeros((num_samples, 3))
            for k in range(len(u) - 1):
                mask = (target_u >= u[k]) & (target_u <= u[k+1])
                if np.any(mask):
                    t = (target_u[mask] - u[k]) / (u[k+1] - u[k] + 1e-10)
                    resampled[mask] = coords_3d[k] + t[:, None] * (coords_3d[k+1] - coords_3d[k])
            if target_u[-1] > u[-1]:
                resampled[-1] = coords_3d[-1]
        except Exception:
            resampled = coords_3d[:num_samples] if len(coords_3d) >= num_samples else np.vstack([coords_3d, coords_3d[-1]] * (num_samples - len(coords_3d)))
        
        return resampled

    def export_to_html(self, output_path: str, category_data: Dict, dmx_coords: List, overbreak_coords: List):
        """导出为Plotly HTML格式"""
        try:
            import plotly.graph_objects as go
        except ImportError:
            print("ERROR: Need plotly library: pip install plotly")
            return None
        
        print(f"\n=== Exporting HTML ===")
        print(f"  Output: {output_path}")
        
        fig = go.Figure()
        
        # 1. 地质体积实体
        for category, data in category_data.items():
            coords_list = data['coords_3d_list']
            if len(coords_list) < 2:
                continue
            
            color = data['color']
            
            # 构建3D顶点
            num_sects = len(coords_list)
            num_pts = len(coords_list[0])
            
            all_points = []
            for coords in coords_list:
                for pt in coords:
                    all_points.append([pt[0], pt[1], pt[2]])
            
            all_points = np.array(all_points)
            
            # 构建面索引
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
                x=all_points[:, 0],
                y=all_points[:, 1],
                z=all_points[:, 2],
                i=i_list,
                j=j_list,
                k=k_list,
                color=color,
                opacity=0.7,
                name=LAYER_CATEGORIES[category]['name_cn'],
                legendgroup=category,
                showlegend=True
            ))
            
            print(f"  {LAYER_CATEGORIES[category]['name_cn']}: {num_sects} sections, {len(faces)} faces")
        
        # 2. 超挖线带状曲面（红色）
        for idx, ob_coords_list in enumerate(overbreak_coords):
            if len(ob_coords_list) < 2:
                continue
            
            num_sects = len(ob_coords_list)
            num_pts = len(ob_coords_list[0])
            
            all_points = []
            for coords in ob_coords_list:
                for pt in coords:
                    all_points.append([pt[0], pt[1], pt[2]])
            
            all_points = np.array(all_points)
            
            # 构建带状面索引
            faces = []
            for i in range(num_sects - 1):
                for j in range(num_pts - 1):
                    p1 = i * num_pts + j
                    p2 = i * num_pts + j + 1
                    p3 = (i + 1) * num_pts + j + 1
                    p4 = (i + 1) * num_pts + j
                    faces.append([p1, p2, p3])
                    faces.append([p1, p3, p4])
            
            i_list = [f[0] for f in faces]
            j_list = [f[1] for f in faces]
            k_list = [f[2] for f in faces]
            
            fig.add_trace(go.Mesh3d(
                x=all_points[:, 0],
                y=all_points[:, 1],
                z=all_points[:, 2],
                i=i_list,
                j=j_list,
                k=k_list,
                color='red',
                opacity=0.5,
                name=f'Overbreak-{idx+1}',
                legendgroup='Overbreak',
                showlegend=(idx == 0)
            ))
        
        print(f"  Overbreak ribbons: {len(overbreak_coords)}")
        
        # 3. DMX带状曲面（蓝色）
        if len(dmx_coords) >= 2:
            num_sects = len(dmx_coords)
            num_pts = len(dmx_coords[0])
            
            all_points = []
            for coords in dmx_coords:
                for pt in coords:
                    all_points.append([pt[0], pt[1], pt[2]])
            
            all_points = np.array(all_points)
            
            faces = []
            for i in range(num_sects - 1):
                for j in range(num_pts - 1):
                    p1 = i * num_pts + j
                    p2 = i * num_pts + j + 1
                    p3 = (i + 1) * num_pts + j + 1
                    p4 = (i + 1) * num_pts + j
                    faces.append([p1, p2, p3])
                    faces.append([p1, p3, p4])
            
            i_list = [f[0] for f in faces]
            j_list = [f[1] for f in faces]
            k_list = [f[2] for f in faces]
            
            fig.add_trace(go.Mesh3d(
                x=all_points[:, 0],
                y=all_points[:, 1],
                z=all_points[:, 2],
                i=i_list,
                j=j_list,
                k=k_list,
                color='blue',
                opacity=0.5,
                name='DMX',
                legendgroup='DMX',
                showlegend=True
            ))
            
            print(f"  DMX ribbon: {num_sects} sections, {len(faces)} faces")
        
        # 设置布局
        fig.update_layout(
            title='Spine-Aligned 3D Geological Model',
            scene=dict(
                xaxis_title='Engineering X',
                yaxis_title='Engineering Y',
                zaxis_title='Elevation (Z)',
                aspectmode='data'
            ),
            legend=dict(
                x=0.02,
                y=0.98,
                bgcolor='rgba(255,255,255,0.8)'
            )
        )
        
        fig.write_html(output_path)
        print(f"  HTML saved: {output_path}")
        
        return output_path

    def build_and_export(self, output_path: str) -> str:
        """完整构建流程"""
        print("=" * 60)
        print("Spine-Aligned 3D Model Builder")
        print("=" * 60)
        
        if not self.load_data():
            return None
        
        category_data = self.build_category_volumes()
        dmx_coords = self.build_dmx_ribbon()
        overbreak_coords = self.build_overbreak_ribbons()
        
        self.export_to_html(output_path, category_data, dmx_coords, overbreak_coords)
        
        print("\n" + "=" * 60)
        print("SUCCESS: Model exported!")
        print("=" * 60)
        
        return output_path


def main():
    section_json = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    spine_json = r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    output_html = r'D:\断面算量平台\测试文件\spine_aligned_model.html'
    
    builder = SpineAlignedModelBuilder(section_json, spine_json)
    builder.build_and_export(output_html)


if __name__ == '__main__':
    main()