# -*- coding: utf-8 -*-
"""
航道地质三维体积模型构建器
基于BIM鲁棒性放样引擎（bim_lofting_core.py）

核心功能：
1. 从JSON元数据读取断面数据
2. 合并地质分层为三类实体：
   -淤泥与填土（合并）
   -黏土（独立）
   -砂与碎石（合并）
3. 使用create_volume_mesh()生成闭合体积网格
4. 导出为Plotly HTML格式（真实比例）

作者: @黄秉俊
日期: 2026-04-02
"""

import json
import numpy as np
import os
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import math

# 导入鲁棒性放样引擎
from bim_lofting_core import BIMLoftingEngine, GeologicalBody, SectionMetadata


# ==================== 地层分类映射 ====================

LAYER_CATEGORIES = {
    'mud_fill': {  #淤泥与填土类
        'name': 'Mud & Fill',
        'name_cn': '淤泥与填土',
        'color': '#7f8c8d',  # 灰色
        'layers': ['1级淤泥', '2级淤泥', '3级淤泥', '4级淤泥', '1级填土', '2级填土', '3级填土', '4级填土']
    },
    'clay': {  # 黏土类
        'name': 'Clay',
        'name_cn': '黏土',
        'color': '#A52A2A',  # 棕色
        'layers': ['3级黏土', '4级黏土', '5级黏土']
    },
    'sand_gravel': {  # 砂与碎石类
        'name': 'Sand & Gravel',
        'name_cn': '砂与碎石',
        'color': '#f1c40f',  # 金色
        'layers': ['6级砂', '7级砂', '8级砂', '6级碎石', '9级碎石']
    }
}


def categorize_layer(layer_name: str) -> Optional[str]:
    """将原始层名映射到分类类别"""
    # 处理编码问题（可能显示为乱码）
    layer_lower = layer_name.lower()
    
    # 淤泥类检测
    if '淤泥' in layer_name or '级淤泥' in layer_name or '淤' in layer_name:
        return 'mud_fill'
    
    # 填土类检测
    if '填土' in layer_name or '级填土' in layer_name or '填' in layer_name:
        return 'mud_fill'
    
    # 黏土类检测
    if '黏土' in layer_name or '粘土' in layer_name or '级黏土' in layer_name or '黏' in layer_name:
        return 'clay'
    
    # 砂类检测
    if '砂' in layer_name or '级砂' in layer_name:
        return 'sand_gravel'
    
    # 碎石类检测
    if '碎石' in layer_name or '级碎石' in layer_name or '砾' in layer_name:
        return 'sand_gravel'
    
    return None


def load_metadata(json_path: str) -> Dict:
    """加载JSON元数据文件"""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def transform_to_3d(pt: Tuple[float, float], ref: Dict, mileage: float, scale_z: float = 0.1) -> Tuple[float, float, float]:
    """
    坐标转换：从局部2D坐标转换为3D脊梁线坐标
    
    Args:
        pt: (x, z) 局部坐标
        ref: L1基准点 {ref_x, ref_y}
        mileage: 里程（Y轴）
        scale_z: Z轴缩放比例（真实比例用1.0）
    
    Returns:
        (x, y, z) 3D坐标
    """
    x = pt[0] - ref['ref_x']  # 相对L1的X偏移
    y = mileage                 # Y轴为里程
    z = pt[1] * scale_z         # Z轴为高程（可缩放）
    return (x, y, z)


def merge_boundaries_by_category(fill_boundaries: Dict, category: str) -> List[List[Tuple[float, float]]]:
    """
    合并同一类别的所有边界
    
    Args:
        fill_boundaries: {layer_name: [boundaries]}
        category: 类别名称（mud_fill, clay, sand_gravel）
    
    Returns:
        合并后的边界列表
    """
    merged = []
    target_layers = LAYER_CATEGORIES[category]['layers']
    
    for layer_name, boundaries in fill_boundaries.items():
        cat = categorize_layer(layer_name)
        if cat == category:
            merged.extend(boundaries)
    
    return merged


def create_merged_polygon(boundaries: List[List[Tuple[float, float]]]) -> Optional[List[Tuple[float, float]]]:
    """
    从多个边界创建合并的多边形（取外轮廓）
    
    Args:
        boundaries: 边界列表
    
    Returns:
        合并后的多边形顶点列表
    """
    if not boundaries:
        return None
    
    # 简化处理：取面积最大的边界作为代表
    # 或者合并所有点并重新排序
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
    
    # 合并所有多边形（取union）
    merged_poly = unary_union(polygons)
    
    # 提取外轮廓坐标
    if merged_poly.geom_type == 'Polygon':
        coords = list(merged_poly.exterior.coords)
        return coords
    elif merged_poly.geom_type == 'MultiPolygon':
        # 取最大的多边形
        largest = max(merged_poly.geoms, key=lambda p: p.area)
        coords = list(largest.exterior.coords)
        return coords
    
    return None


class VolumeModelBuilder:
    """三维体积模型构建器"""
    
    def __init__(self, json_path: str, scale_z: float = 0.1, num_samples: int = 100):
        """
        Args:
            json_path: JSON元数据文件路径
            scale_z: Z轴缩放比例（真实比例用1.0，之前HTML用0.1）
            num_samples: 重采样点数
        """
        self.json_path = json_path
        self.scale_z = scale_z
        self.num_samples = num_samples
        self.metadata = None
        self.sections = []
        self.engine = BIMLoftingEngine(num_samples=num_samples)
    
    def load_data(self) -> bool:
        """加载并解析JSON数据"""
        print(f"\n=== Loading Metadata ===")
        print(f"  Path: {self.json_path}")
        
        self.metadata = load_metadata(self.json_path)
        
        if 'sections' not in self.metadata:
            print("ERROR: No sections found in metadata!")
            return False
        
        self.sections = self.metadata['sections']
        print(f"  Sections loaded: {len(self.sections)}")
        
        # 检查L1基准点
        sections_with_l1 = [s for s in self.sections if s.get('l1_ref_point')]
        print(f"  Sections with L1 ref: {len(sections_with_l1)}")
        
        return len(sections_with_l1) > 0
    
    def build_category_volumes(self) -> Dict[str, Dict]:
        """
        构建三类地质实体的体积数据
        
        Returns:
            {category: {'mileages': [], 'coords_list': [], 'color': str}}
        """
        print(f"\n=== Building Category Volumes ===")
        
        # 按桩号排序（降序）
        sorted_sections = sorted(
            [s for s in self.sections if s.get('l1_ref_point')],
            key=lambda s: s['station_value'],
            reverse=True
        )
        
        category_data = {
            'mud_fill': {'mileages': [], 'coords_list': [], 'color': LAYER_CATEGORIES['mud_fill']['color']},
            'clay': {'mileages': [], 'coords_list': [], 'color': LAYER_CATEGORIES['clay']['color']},
            'sand_gravel': {'mileages': [], 'coords_list': [], 'color': LAYER_CATEGORIES['sand_gravel']['color']}
        }
        
        # 同时提取DMX和超挖线数据（膜图层）
        membrane_data = {
            'dmx': {'sections': [], 'points_3d': []},
            'overbreak': {'sections': [], 'points_3d': []}
        }
        
        for section in sorted_sections:
            mileage = section['station_value']
            ref = section['l1_ref_point']
            fill_boundaries = section.get('fill_boundaries', {})
            
            # 提取DMX断面线（膜图层）
            dmx_points = section.get('dmx_points', [])
            if dmx_points and len(dmx_points) >= 2:
                # 转换为3D坐标
                dmx_3d = []
                for pt in dmx_points:
                    x = pt[0] - ref['ref_x']
                    y = mileage
                    z = (pt[1] - ref['ref_y']) * self.scale_z
                    dmx_3d.append([x, y, z])
                membrane_data['dmx']['sections'].append(section['station_name'])
                membrane_data['dmx']['points_3d'].append(dmx_3d)
            
            # 提取超挖线（膜图层）- 字段名为overbreak_points
            overbreak_points = section.get('overbreak_points', [])
            if overbreak_points:
                for ob_line in overbreak_points:
                    if len(ob_line) >= 2:
                        ob_3d = []
                        for pt in ob_line:
                            x = pt[0] - ref['ref_x']
                            y = mileage
                            z = (pt[1] - ref['ref_y']) * self.scale_z
                            ob_3d.append([x, y, z])
                        membrane_data['overbreak']['sections'].append(section['station_name'])
                        membrane_data['overbreak']['points_3d'].append(ob_3d)
            
            # 为每个类别处理
            for category in category_data.keys():
                merged_bounds = merge_boundaries_by_category(fill_boundaries, category)
                
                if merged_bounds:
                    merged_poly = create_merged_polygon(merged_bounds)
                    if merged_poly and len(merged_poly) >= 3:
                        # 转换为2D坐标（相对L1归一化）
                        # X坐标：相对于L1的X偏移
                        # Z坐标：相对于L1的Y偏移（CAD中Y轴对应高程Z）
                        coords_2d = [(p[0] - ref['ref_x'], p[1] - ref['ref_y']) for p in merged_poly]
                        category_data[category]['mileages'].append(mileage)
                        category_data[category]['coords_list'].append(np.array(coords_2d))
                elif category_data[category]['mileages']:
                    # 该类别在此断面缺失，创建退化点
                    # 使用上一个断面的重心位置
                    last_coords = category_data[category]['coords_list'][-1]
                    centroid_x = np.mean(last_coords[:, 0])
                    centroid_z = np.mean(last_coords[:, 1])
                    taper_coords = np.array([[centroid_x, centroid_z]] * self.num_samples)
                    category_data[category]['mileages'].append(mileage)
                    category_data[category]['coords_list'].append(taper_coords)
        
        # 打印统计
        for category, data in category_data.items():
            print(f"  {LAYER_CATEGORIES[category]['name_cn']}: {len(data['mileages'])} sections")
        
        # 打印膜图层统计
        print(f"  DMX断面线: {len(membrane_data['dmx']['points_3d'])} lines")
        print(f"  超挖线: {len(membrane_data['overbreak']['points_3d'])} lines")
        
        return category_data, membrane_data
    
    def export_to_html(self, output_path: str, category_data: Dict, membrane_data: Dict = None):
        """
        导出为Plotly HTML格式
        
        Args:
            output_path: HTML输出路径
            category_data: 类别体积数据
            membrane_data: 膜图层数据（DMX和超挖线）
        """
        try:
            import plotly.graph_objects as go
        except ImportError:
            print("ERROR: Need plotly library: pip install plotly")
            return None
        
        print(f"\n=== Exporting HTML ===")
        print(f"  Output: {output_path}")
        
        fig = go.Figure()
        
        # Layer rendering order: Volume Mesh -> Overbreak -> DMX (DMX last, renders on top)
        
        # 为每个类别生成3D Mesh（体积实体）
        for category, data in category_data.items():
            if len(data['mileages']) < 2:
                print(f"  Skipping {category}: insufficient data")
                continue
            
            mileages = data['mileages']
            coords_list = data['coords_list']
            color = data['color']
            
            # 使用鲁棒性放样引擎对齐坐标
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
                    x = pt[0]  # 相对L1的X偏移
                    y = mileage  # 里程
                    z = pt[1] * self.scale_z  # 高程（缩放）
                    all_points.append([x, y, z])
            
            all_points = np.array(all_points)
            
            # 构建面索引（闭合多边形放样）
            faces = []
            for i in range(num_sects - 1):
                for j in range(num_pts):
                    next_j = (j + 1) % num_pts
                    
                    p1 = i * num_pts + j
                    p2 = i * num_pts + next_j
                    p3 = (i + 1) * num_pts + next_j
                    p4 = (i + 1) * num_pts + j
                    
                    # 两个三角形组成四边形面
                    faces.append([p1, p2, p3])
                    faces.append([p1, p3, p4])
            
            # 创建Mesh3d
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
                showlegend=True,
                hovertemplate=f'{LAYER_CATEGORIES[category]["name_cn"]}<br>X: %{{x:.1f}}<br>Y: %{{y:.1f}}<br>Z: %{{z:.1f}}'
            ))
            
            print(f"  {LAYER_CATEGORIES[category]['name_cn']}: {num_sects} sections, {num_pts} pts/section, {len(faces)} faces")
        
        # 膜图层渲染（Scatter3d线条，不是体积实体）
        if membrane_data:
            # 超挖线（红色虚线）- 第二层
            ob_lines_count = 0
            for i, (station_name, pts_3d) in enumerate(zip(membrane_data['overbreak']['sections'], membrane_data['overbreak']['points_3d'])):
                xs = [p[0] for p in pts_3d]
                ys = [p[1] for p in pts_3d]
                zs = [p[2] for p in pts_3d]
                
                fig.add_trace(go.Scatter3d(
                    x=xs, y=ys, z=zs,
                    mode='lines',
                    line=dict(color='red', width=1.5, dash='dash'),
                    name=f'Overbreak-{station_name}',
                    legendgroup='Overbreak',
                    showlegend=(ob_lines_count == 0),
                    opacity=0.5,
                    hovertemplate=f'Overbreak<br>{station_name}<br>X: %{{x:.1f}}<br>Y: %{{y:.1f}}<br>Z: %{{z:.1f}}'
                ))
                ob_lines_count += 1
            
            print(f"  Overbreak lines: {ob_lines_count} lines")
            
            # DMX断面线（蓝色实线）- 最后渲染（最上层）
            dmx_lines_count = 0
            for i, (station_name, pts_3d) in enumerate(zip(membrane_data['dmx']['sections'], membrane_data['dmx']['points_3d'])):
                xs = [p[0] for p in pts_3d]
                ys = [p[1] for p in pts_3d]
                zs = [p[2] for p in pts_3d]
                
                fig.add_trace(go.Scatter3d(
                    x=xs, y=ys, z=zs,
                    mode='lines',
                    line=dict(color='blue', width=1),
                    name=f'DMX-{station_name}',
                    legendgroup='DMX',
                    showlegend=(dmx_lines_count == 0),
                    hovertemplate=f'DMX<br>{station_name}<br>X: %{{x:.1f}}<br>Y: %{{y:.1f}}<br>Z: %{{z:.1f}}'
                ))
                dmx_lines_count += 1
            
            print(f"  DMX section lines: {dmx_lines_count} lines")
        
        # 设置布局
        fig.update_layout(
            title=dict(
                text=f'Geological Volume Model - {len(self.sections)} Sections',
                x=0.5,
                xanchor='center'
            ),
            scene=dict(
                xaxis_title='X (Width)',
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
        
        # 保存HTML
        fig.write_html(output_path)
        print(f"  HTML saved: {output_path}")
        print(f"  Open in browser for interactive view")
        
        return output_path
    
    def build_and_export(self, output_path: str) -> str:
        """完整构建流程"""
        if not self.load_data():
            return None
        
        category_data, membrane_data = self.build_category_volumes()
        
        return self.export_to_html(output_path, category_data, membrane_data)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Geological Volume Model Builder')
    parser.add_argument('--input', '-i', type=str,
                       default=r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json',
                       help='Input metadata JSON file path')
    parser.add_argument('--output', '-o', type=str, default=None,
                       help='Output HTML file path')
    parser.add_argument('--scale', '-s', type=float, default=0.1,
                       help='Z axis scale factor (use 1.0 for true scale)')
    parser.add_argument('--samples', '-n', type=int, default=100,
                       help='Number of resampling points per section')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Geological Volume Model Builder")
    print("=" * 60)
    
    # 默认输出路径
    if args.output is None:
        base_dir = os.path.dirname(args.input)
        args.output = os.path.join(base_dir, 'geological_volume_model.html')
    
    builder = VolumeModelBuilder(
        json_path=args.input,
        scale_z=args.scale,
        num_samples=args.samples
    )
    
    result = builder.build_and_export(args.output)
    
    if result:
        print(f"\n{'=' * 60}")
        print("SUCCESS: Volume model exported!")
        print("=" * 60)
    else:
        print(f"\n{'=' * 60}")
        print("FAILED: Check error messages above")
        print("=" * 60)


if __name__ == '__main__':
    main()