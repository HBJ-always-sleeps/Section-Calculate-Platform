# -*- coding: utf-8 -*-
"""
航道三维模型构建器 - 工程坐标版本

功能：
1. 使用工程坐标断面数据
2. 地质实体：create_volume_mesh() 生成闭合体积
3. DMX/超挖线：create_ribbon_mesh() 生成带状曲面（不再是离散线条）

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


class EngineeringCoordModelBuilder:
    """工程坐标三维模型构建器"""
    
    def __init__(self, json_path: str, num_samples: int = 100):
        """
        Args:
            json_path: 工程坐标JSON元数据文件路径
            num_samples: 重采样点数
        """
        self.json_path = json_path
        self.num_samples = num_samples
        self.metadata = None
        self.sections = []
        self.engine = BIMLoftingEngine(num_samples=num_samples)
    
    def load_data(self) -> bool:
        """加载并解析JSON数据"""
        print(f"\n=== Loading Engineering Coordinate Data ===")
        print(f"  Path: {self.json_path}")
        
        self.metadata = load_metadata(self.json_path)
        
        if 'sections' not in self.metadata:
            print("ERROR: No sections found in metadata!")
            return False
        
        self.sections = self.metadata['sections']
        print(f"  Sections loaded: {len(self.sections)}")
        
        # 检查工程坐标
        sections_with_eng = [s for s in self.sections if s.get('engineering_coords')]
        print(f"  Sections with engineering coords: {len(sections_with_eng)}")
        
        return len(sections_with_eng) > 0
    
    def build_dmx_ribbon(self) -> Dict:
        """
        构建DMX带状曲面
        
        Returns:
            {'mileages': [], 'coords_list': []}
        """
        print(f"\n=== Building DMX Ribbon Surface ===")
        
        # 按桩号排序
        sorted_sections = sorted(
            [s for s in self.sections if s.get('engineering_coords')],
            key=lambda s: s['station_value'],
            reverse=True
        )
        
        mileages = []
        coords_list = []
        
        for section in sorted_sections:
            mileage = section['station_value']
            dmx_eng = section.get('dmx_points_eng', [])
            
            if dmx_eng and len(dmx_eng) >= 2:
                # 使用工程坐标
                coords_2d = [(p[0], p[1]) for p in dmx_eng]
                mileages.append(mileage)
                coords_list.append(np.array(coords_2d))
        
        print(f"  DMX sections: {len(mileages)}")
        
        return {'mileages': mileages, 'coords_list': coords_list}
    
    def build_overbreak_ribbon(self) -> List[Dict]:
        """
        构建超挖线带状曲面（可能有多条）
        
        Returns:
            [{'mileages': [], 'coords_list': []}, ...]
        """
        print(f"\n=== Building Overbreak Ribbon Surfaces ===")
        
        # 按桩号排序
        sorted_sections = sorted(
            [s for s in self.sections if s.get('engineering_coords')],
            key=lambda s: s['station_value'],
            reverse=True
        )
        
        # 收集所有超挖线
        all_overbreaks = []
        
        for section in sorted_sections:
            mileage = section['station_value']
            ob_eng = section.get('overbreak_points_eng', [])
            
            for i, ob_line in enumerate(ob_eng):
                if len(ob_line) >= 2:
                    while len(all_overbreaks) <= i:
                        all_overbreaks.append({'mileages': [], 'coords_list': []})
                    coords_2d = [(p[0], p[1]) for p in ob_line]
                    all_overbreaks[i]['mileages'].append(mileage)
                    all_overbreaks[i]['coords_list'].append(np.array(coords_2d))
        
        # 过滤有效的超挖线
        valid_overbreaks = [ob for ob in all_overbreaks if len(ob['mileages']) >= 2]
        print(f"  Valid overbreak ribbons: {len(valid_overbreaks)}")
        
        return valid_overbreaks
    
    def build_category_volumes(self) -> Dict[str, Dict]:
        """构建三类地质实体的体积数据"""
        print(f"\n=== Building Category Volumes ===")
        
        sorted_sections = sorted(
            [s for s in self.sections if s.get('engineering_coords')],
            key=lambda s: s['station_value'],
            reverse=True
        )
        
        category_data = {
            'mud_fill': {'mileages': [], 'coords_list': [], 'color': LAYER_CATEGORIES['mud_fill']['color']},
            'clay': {'mileages': [], 'coords_list': [], 'color': LAYER_CATEGORIES['clay']['color']},
            'sand_gravel': {'mileages': [], 'coords_list': [], 'color': LAYER_CATEGORIES['sand_gravel']['color']}
        }
        
        for section in sorted_sections:
            mileage = section['station_value']
            fill_boundaries = section.get('fill_boundaries_eng', {})
            
            for category in category_data.keys():
                merged_bounds = merge_boundaries_by_category(fill_boundaries, category)
                
                if merged_bounds:
                    merged_poly = create_merged_polygon(merged_bounds)
                    if merged_poly and len(merged_poly) >= 3:
                        coords_2d = [(p[0], p[1]) for p in merged_poly]
                        category_data[category]['mileages'].append(mileage)
                        category_data[category]['coords_list'].append(np.array(coords_2d))
                elif category_data[category]['mileages']:
                    last_coords = category_data[category]['coords_list'][-1]
                    centroid_x = np.mean(last_coords[:, 0])
                    centroid_z = np.mean(last_coords[:, 1])
                    taper_coords = np.array([[centroid_x, centroid_z]] * self.num_samples)
                    category_data[category]['mileages'].append(mileage)
                    category_data[category]['coords_list'].append(taper_coords)
        
        for category, data in category_data.items():
            print(f"  {LAYER_CATEGORIES[category]['name_cn']}: {len(data['mileages'])} sections")
        
        return category_data
    
    def export_to_html(self, output_path: str, category_data: Dict, dmx_data: Dict, overbreak_data: List[Dict]):
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
            if len(data['mileages']) < 2:
                continue
            
            mileages = data['mileages']
            coords_list = data['coords_list']
            color = data['color']
            
            # 锚点同步
            aligned_coords_list = []
            for coords in coords_list:
                aligned = self.engine.sync_anchor_points(coords, is_closed=True)
                aligned_coords_list.append(aligned)
            
            # 构建3D顶点
            num_sects = len(mileages)
            num_pts = len(aligned_coords_list[0])
            
            all_points = []
            for i, (mileage, coords) in enumerate(zip(mileages, aligned_coords_list)):
                for j, pt in enumerate(coords):
                    # pt[0]: 工程坐标X偏移, pt[1]: 相对高程（Z轴）
                    # X/Y使用工程坐标，Z使用相对高程
                    x = pt[0]  # 工程坐标X
                    y = mileage  # 暂用里程作为Y（后续需要改为spine_y）
                    z = pt[1]  # 相对高程
                    all_points.append([x, y, z])
            
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
        for idx, ob_data in enumerate(overbreak_data):
            if len(ob_data['mileages']) < 2:
                continue
            
            mileages = ob_data['mileages']
            coords_list = ob_data['coords_list']
            
            # 锚点同步（开放线条）
            aligned_coords_list = []
            for coords in coords_list:
                aligned = self.engine.sync_anchor_points(coords, is_closed=False)
                aligned_coords_list.append(aligned)
            
            num_sects = len(mileages)
            num_pts = len(aligned_coords_list[0])
            
            all_points = []
            for i, (mileage, coords) in enumerate(zip(mileages, aligned_coords_list)):
                for j, pt in enumerate(coords):
                    x = pt[0]
                    y = mileage
                    z = pt[1]
                    all_points.append([x, y, z])
            
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
        
        print(f"  Overbreak ribbons: {len(overbreak_data)}")
        
        # 3. DMX带状曲面（蓝色）
        if len(dmx_data['mileages']) >= 2:
            mileages = dmx_data['mileages']
            coords_list = dmx_data['coords_list']
            
            aligned_coords_list = []
            for coords in coords_list:
                aligned = self.engine.sync_anchor_points(coords, is_closed=False)
                aligned_coords_list.append(aligned)
            
            num_sects = len(mileages)
            num_pts = len(aligned_coords_list[0])
            
            all_points = []
            for i, (mileage, coords) in enumerate(zip(mileages, aligned_coords_list)):
                for j, pt in enumerate(coords):
                    x = pt[0]
                    y = mileage
                    z = pt[1]
                    all_points.append([x, y, z])
            
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
                opacity=0.8,
                name='DMX',
                legendgroup='DMX',
                showlegend=True
            ))
            
            print(f"  DMX ribbon: {num_sects} sections, {len(faces)} faces")
        
        # 设置布局
        fig.update_layout(
            title=dict(
                text=f'Engineering Coordinate Model - {len(self.sections)} Sections',
                x=0.5,
                xanchor='center'
            ),
            scene=dict(
                xaxis_title='X (Engineering)',
                yaxis_title='Y (Mileage)',
                zaxis_title='Z (Elevation)',
                aspectmode='data',
                camera=dict(
                    eye=dict(x=1.5, y=1.5, z=0.8),
                    up=dict(x=0, y=0, z=1)
                )
            ),
            showlegend=True,
            legend=dict(
                x=0.02,
                y=0.98,
                bgcolor='rgba(255,255,255,0.8)',
                bordercolor='gray',
                borderwidth=1
            ),
            width=1200,
            height=800,
            margin=dict(l=0, r=0, t=50, b=0)
        )
        
        fig.write_html(output_path)
        print(f"  HTML saved: {output_path}")
        
        return output_path
    
    def build_and_export(self, output_path: str) -> str:
        """完整构建流程"""
        if not self.load_data():
            return None
        
        category_data = self.build_category_volumes()
        dmx_data = self.build_dmx_ribbon()
        overbreak_data = self.build_overbreak_ribbon()
        
        return self.export_to_html(output_path, category_data, dmx_data, overbreak_data)


def main():
    json_path = r'D:\断面算量平台\测试文件\断面元数据_工程坐标.json'
    output_path = r'D:\断面算量平台\测试文件\engineering_coord_model.html'
    
    print("=" * 60)
    print("Engineering Coordinate Model Builder")
    print("=" * 60)
    
    builder = EngineeringCoordModelBuilder(json_path=json_path, num_samples=100)
    result = builder.build_and_export(output_path)
    
    if result:
        print(f"\n{'=' * 60}")
        print("SUCCESS: Model exported!")
        print("=" * 60)
    else:
        print(f"\n{'=' * 60}")
        print("FAILED: Check error messages above")
        print("=" * 60)


if __name__ == '__main__':
    main()