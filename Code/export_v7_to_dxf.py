# -*- coding: utf-8 -*-
"""
V7地质模型DXF导出器

功能：
1. 将V7的3D模型数据导出为DXF格式
2. 支持导出DMX Ribbon、超挖线Ribbon、地质体积实体
3. 使用3DFACE和POLYLINE实体表示3D网格
4. 分图层管理不同类型的实体
5. 确保坐标系统正确（X=东向, Y=北向里程, Z=高程）

作者: @黄秉俊
日期: 2026-04-03
"""

import json
import numpy as np
import os
from typing import List, Dict, Tuple, Optional
import math
import sys

# 添加Code目录到路径
sys.path.insert(0, r'D:\断面算量平台\Code')

# ezdxf延迟导入
EZXDF_AVAILABLE = None


def check_ezdxf():
    """延迟检查ezdxf是否可用"""
    global EZXDF_AVAILABLE
    if EZXDF_AVAILABLE is None:
        try:
            import ezdxf
            EZXDF_AVAILABLE = True
        except ImportError:
            EZXDF_AVAILABLE = False
            print("[ERROR] ezdxf not available. Install with: pip install ezdxf")
    return EZXDF_AVAILABLE


# ==================== 地层分类 ====================

LAYER_CATEGORIES = {
    'mud_fill': {
        'name_cn': '淤泥与填土',
        'color': 8,  # AutoCAD颜色索引（灰色）
        'layers': ['1级淤泥', '2级淤泥', '3级淤泥', '4级淤泥', '1级填土', '2级填土', '3级填土', '4级填土'],
    },
    'clay': {
        'name_cn': '黏土',
        'color': 30,  # 棕色
        'layers': ['3级黏土', '4级黏土', '5级黏土'],
    },
    'sand_and_gravel': {
        'name_cn': '砂与碎石类',
        'color': 50,  # 金色
        'layers': ['6级砂', '7级砂', '8级砂', '9级砂', '10级砂', '6级碎石', '9级碎石'],
    }
}

# DXF图层定义
DXF_LAYERS = {
    'DMX_RIBBON': {'color': 5, 'description': 'DMX断面线Ribbon曲面'},  # 蓝色
    'OVERBREAK_RIBBON': {'color': 1, 'description': '超挖线梯形槽Ribbon曲面'},  # 红色
    'GEO_MUD_FILL': {'color': 8, 'description': '淤泥与填土体积实体'},  # 灰色
    'GEO_CLAY': {'color': 30, 'description': '黏土体积实体'},  # 棕色
    'GEO_SAND': {'color': 50, 'description': '砂与碎石类体积实体'},  # 金色
    'GEO_MESH_EDGES': {'color': 256, 'description': '地质体网格边线'},  # ByLayer
}


def categorize_layer(layer_name: str) -> Optional[str]:
    """将原始层名映射到分类类别"""
    for cat_key, cat_info in LAYER_CATEGORIES.items():
        if layer_name in cat_info['layers']:
            return cat_key
    return None


# ==================== V7模型数据加载 ====================

class V7ModelDataLoader:
    """V7模型数据加载器"""
    
    def __init__(self, section_json_path: str, spine_json_path: str):
        self.section_json_path = section_json_path
        self.spine_json_path = spine_json_path
        self.metadata = None
        self.spine_matches = None
        self.sections = []
        self.spine_interpolation = None
    
    def load_data(self) -> bool:
        """加载断面数据和脊梁匹配数据"""
        print(f"\n=== Loading V7 Model Data ===")
        
        with open(self.section_json_path, 'r', encoding='utf-8') as f:
            self.metadata = json.load(f)
        
        with open(self.spine_json_path, 'r', encoding='utf-8') as f:
            self.spine_matches = json.load(f)
        
        if 'sections' not in self.metadata:
            return False
        
        self.sections = self.metadata['sections']
        
        # 处理spine_matches格式
        matches = self.spine_matches.get('matches', [])
        if not matches:
            matches = [v for k, v in self.spine_matches.items() if isinstance(v, dict) and 'station_value' in v]
        
        print(f"  Sections: {len(self.sections)}, Spine matches: {len(matches)}")
        
        # 预计算插值参数
        spine_matches_sorted = sorted(matches, key=lambda m: m['station_value'])
        if spine_matches_sorted:
            self.spine_interpolation = {
                'station_min': spine_matches_sorted[0]['station_value'],
                'station_max': spine_matches_sorted[-1]['station_value'],
                'spine_x_min': spine_matches_sorted[0]['spine_x'],
                'spine_x_max': spine_matches_sorted[-1]['spine_x'],
                'spine_y_min': spine_matches_sorted[0]['spine_y'],
                'spine_y_max': spine_matches_sorted[-1]['spine_y']
            }
        
        return True
    
    def _get_interpolated_spine_match(self, station_value: float) -> Dict:
        """线性插值计算spine坐标"""
        if not self.spine_interpolation:
            return {'spine_x': 0, 'spine_y': station_value, 'tangent_angle': 0}
        
        station_min = self.spine_interpolation['station_min']
        station_max = self.spine_interpolation['station_max']
        spine_x_min = self.spine_interpolation['spine_x_min']
        spine_x_max = self.spine_interpolation['spine_x_max']
        spine_y_min = self.spine_interpolation['spine_y_min']
        spine_y_max = self.spine_interpolation['spine_y_max']
        
        if station_max > station_min:
            ratio = (station_value - station_min) / (station_max - station_min)
            interpolated_spine_x = spine_x_min + ratio * (spine_x_max - spine_x_min)
            interpolated_spine_y = spine_y_min + ratio * (spine_y_max - spine_y_min)
        else:
            interpolated_spine_x = spine_x_min
            interpolated_spine_y = spine_y_min
        
        return {
            'spine_x': interpolated_spine_x,
            'spine_y': interpolated_spine_y,
            'tangent_angle': 0
        }
    
    def transform_to_spine_aligned(self, cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle):
        """
        坐标转换：CAD局部坐标 -> 工程坐标
        
        关键：Z是高程（cad_y - ref_y），只旋转dx（X偏移）
        """
        z = cad_y - ref_y  # Z是高程
        dx = cad_x - ref_x
        cos_a = math.cos(rotation_angle)
        sin_a = math.sin(rotation_angle)
        rotated_dx = dx * cos_a
        rotated_dy = dx * sin_a
        eng_x = spine_x + rotated_dx
        eng_y = spine_y + rotated_dy
        return eng_x, eng_y, z
    
    def get_section_3d_data(self, section: Dict, spine_match: Dict) -> Dict:
        """将断面数据转换为工程坐标3D数据"""
        l1_ref = section.get('l1_ref_point', {})
        ref_x = l1_ref.get('ref_x', 0)
        ref_y = l1_ref.get('ref_y', 0)
        
        station_value = section.get('station_value', 0)
        
        spine_x = spine_match['spine_x']
        spine_y = spine_match['spine_y']
        rotation_angle = spine_match['tangent_angle'] + math.pi / 2
        
        result = {
            'station_value': station_value,
            'spine_y': spine_y,
            'dmx_3d': None,
            'overbreak_3d': [],
            'geological_polys': []
        }
        
        # DMX转换
        dmx_points = section.get('dmx_points', [])
        if dmx_points and len(dmx_points) >= 2:
            dmx_3d = []
            for pt in dmx_points:
                eng_x, eng_y, z = self.transform_to_spine_aligned(
                    pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                )
                dmx_3d.append([eng_x, eng_y, z])
            result['dmx_3d'] = np.array(dmx_3d)
        
        # 超挖线转换
        overbreak_points = section.get('overbreak_points', [])
        all_ob_points = []
        for ob_line in overbreak_points:
            if len(ob_line) >= 2:
                for pt in ob_line:
                    eng_x, eng_y, z = self.transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    all_ob_points.append([eng_x, eng_y, z])
        
        if len(all_ob_points) >= 2:
            all_ob_points = sorted(all_ob_points, key=lambda p: p[0])
            result['overbreak_3d'].append(np.array(all_ob_points))
        
        # 地质填充转换
        fill_boundaries = section.get('fill_boundaries', {})
        for layer_name, boundaries in fill_boundaries.items():
            cat_key = categorize_layer(layer_name)
            if cat_key is None:
                continue
            
            for boundary in boundaries:
                if len(boundary) < 3:
                    continue
                
                poly_3d = []
                for pt in boundary:
                    eng_x, eng_y, z = self.transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    poly_3d.append([eng_x, eng_y, z])
                
                poly_3d = np.array(poly_3d)
                centroid = (np.mean(poly_3d[:, 0]), np.mean(poly_3d[:, 1]))
                
                result['geological_polys'].append({
                    'layer': cat_key,
                    'points': poly_3d,
                    'centroid': centroid,
                    'layer_name': layer_name
                })
        
        return result
    
    def build_all_section_data(self) -> List[Dict]:
        """构建所有断面的3D数据"""
        matches = self.spine_matches.get('matches', [])
        if not matches:
            matches = [v for k, v in self.spine_matches.items() if isinstance(v, dict) and 'station_value' in v]
        
        spine_dict = {m['station_value']: m for m in matches}
        sorted_sections = sorted(self.sections, key=lambda s: s['station_value'], reverse=True)
        
        section_data_list = []
        for section in sorted_sections:
            spine_match = spine_dict.get(section['station_value'])
            if not spine_match:
                spine_match = self._get_interpolated_spine_match(section.get('station_value', 0))
            
            data = self.get_section_3d_data(section, spine_match)
            section_data_list.append(data)
        
        return section_data_list


# ==================== DXF导出器 ====================

class V7ModelDXFExporter:
    """V7模型DXF导出器"""
    
    def __init__(self, model_data_loader: V7ModelDataLoader):
        self.loader = model_data_loader
        self.doc = None
        self.msp = None
    
    def create_dxf_document(self):
        """创建DXF文档"""
        if not check_ezdxf():
            return False
        
        import ezdxf
        
        # 创建新文档
        self.doc = ezdxf.new('R2010', setup=True)
        self.msp = self.doc.modelspace()
        
        # 创建图层（ezdxf不支持description属性）
        for layer_name, layer_info in DXF_LAYERS.items():
            self.doc.layers.new(name=layer_name, dxfattribs={
                'color': layer_info['color']
            })
        
        # 添加边界框图层
        self.doc.layers.new(name='BOUNDING_BOX', dxfattribs={'color': 3})  # 绿色
        self.doc.layers.new(name='VIEW_MARKERS', dxfattribs={'color': 6})  # 紫色
        
        print(f"\n=== DXF Document Created ===")
        print(f"  Layers: {list(DXF_LAYERS.keys()) + ['BOUNDING_BOX', 'VIEW_MARKERS']}")
        
        return True
    
    def export_dmx_ribbon(self, section_data_list: List[Dict], num_samples: int = 60):
        """
        导出DMX Ribbon曲面
        
        使用3DFACE实体构建曲面 + 3DPOLYLINE骨架线
        """
        print(f"\n=== Exporting DMX Ribbon ===")
        
        # 收集所有DMX线
        all_lines = []
        for data in section_data_list:
            if data['dmx_3d'] is not None and len(data['dmx_3d']) >= 2:
                all_lines.append(data['dmx_3d'])
        
        if len(all_lines) < 2:
            print("  [WARN] Not enough DMX lines")
            return
        
        # 重采样每条线
        resampled_lines = self._resample_all_lines(all_lines, num_samples)
        
        # 创建3DFACE网格
        face_count = 0
        n_sections = len(resampled_lines)
        
        for sec_idx in range(n_sections - 1):
            line_a = resampled_lines[sec_idx]
            line_b = resampled_lines[sec_idx + 1]
            
            for pt_idx in range(num_samples - 1):
                # 四边形顶点
                p1 = tuple(line_a[pt_idx])
                p2 = tuple(line_a[pt_idx + 1])
                p3 = tuple(line_b[pt_idx + 1])
                p4 = tuple(line_b[pt_idx])
                
                # 创建两个3DFACE（三角形）
                self.msp.add_3dface([p1, p2, p3], dxfattribs={'layer': 'DMX_RIBBON'})
                self.msp.add_3dface([p1, p3, p4], dxfattribs={'layer': 'DMX_RIBBON'})
                face_count += 2
        
        # 添加3DPOLYLINE骨架线（每10个断面添加一条）
        polyline_count = 0
        for sec_idx in range(0, n_sections, 10):
            line = resampled_lines[sec_idx]
            points = [tuple(pt) for pt in line]
            self.msp.add_polyline3d(points, dxfattribs={'layer': 'DMX_RIBBON'})
            polyline_count += 1
        
        print(f"  DMX Ribbon: {n_sections} sections, {face_count} 3DFACEs, {polyline_count} 3DPOLYLINEs")
    
    def export_overbreak_ribbon(self, section_data_list: List[Dict], n_slope: int = 15, n_bottom: int = 30):
        """
        导出超挖线梯形槽Ribbon曲面
        """
        print(f"\n=== Exporting Overbreak Ribbon ===")
        
        # 收集所有超挖线
        all_lines = []
        for data in section_data_list:
            if data['overbreak_3d'] and len(data['overbreak_3d']) > 0:
                for ob_line in data['overbreak_3d']:
                    if len(ob_line) >= 3:
                        # 检查坐标是否在合理范围内
                        y_values = ob_line[:, 1]
                        y_min = np.min(y_values)
                        # 过滤掉Y坐标为0或负数的异常数据
                        if y_min > 0:
                            all_lines.append(ob_line)
        
        print(f"  Valid overbreak lines: {len(all_lines)}/{len(section_data_list)} sections")
        
        if len(all_lines) < 2:
            print("  [WARN] Not enough overbreak lines")
            return
        
        # 分段重采样
        total_points = n_slope * 2 + n_bottom
        resampled_lines = self._resample_trench_all(all_lines, n_slope, n_bottom)
        
        # 创建3DFACE网格
        face_count = 0
        n_sections = len(resampled_lines)
        
        for sec_idx in range(n_sections - 1):
            line_a = resampled_lines[sec_idx]
            line_b = resampled_lines[sec_idx + 1]
            
            for pt_idx in range(total_points - 1):
                p1 = tuple(line_a[pt_idx])
                p2 = tuple(line_a[pt_idx + 1])
                p3 = tuple(line_b[pt_idx + 1])
                p4 = tuple(line_b[pt_idx])
                
                self.msp.add_3dface([p1, p2, p3], dxfattribs={'layer': 'OVERBREAK_RIBBON'})
                self.msp.add_3dface([p1, p3, p4], dxfattribs={'layer': 'OVERBREAK_RIBBON'})
                face_count += 2
        
        # 添加3DPOLYLINE骨架线
        polyline_count = 0
        for sec_idx in range(0, n_sections, 10):
            line = resampled_lines[sec_idx]
            points = [tuple(pt) for pt in line]
            self.msp.add_polyline3d(points, dxfattribs={'layer': 'OVERBREAK_RIBBON'})
            polyline_count += 1
        
        print(f"  Overbreak Ribbon: {n_sections} sections, {face_count} 3DFACEs, {polyline_count} 3DPOLYLINEs")
    
    def export_geological_volumes(self, section_data_list: List[Dict], num_samples: int = 64):
        """
        导出地质体积实体
        
        使用3DFACE构建体积网格侧面
        """
        print(f"\n=== Exporting Geological Volumes ===")
        
        # 匹配地质体
        connections = self._match_geological_polygons(section_data_list)
        
        # 按类别分组
        category_faces = {cat: 0 for cat in LAYER_CATEGORIES.keys()}
        
        for p_a, p_b in connections:
            cat_key = p_a['layer']
            
            # 重采样多边形
            pts_a = self._resample_polygon(p_a['points'], num_samples)
            pts_b = self._resample_polygon(p_b['points'], num_samples)
            
            # 确定图层
            if cat_key == 'mud_fill':
                layer_name = 'GEO_MUD_FILL'
            elif cat_key == 'clay':
                layer_name = 'GEO_CLAY'
            else:
                layer_name = 'GEO_SAND'
            
            # 创建侧面3DFACE
            for i in range(num_samples):
                next_i = (i + 1) % num_samples
                
                p1 = tuple(pts_a[i])
                p2 = tuple(pts_a[next_i])
                p3 = tuple(pts_b[next_i])
                p4 = tuple(pts_b[i])
                
                self.msp.add_3dface([p1, p2, p3], dxfattribs={'layer': layer_name})
                self.msp.add_3dface([p1, p3, p4], dxfattribs={'layer': layer_name})
                category_faces[cat_key] += 2
        
        print(f"  Geological volumes: {len(connections)} connections")
        for cat, count in category_faces.items():
            print(f"    {LAYER_CATEGORIES[cat]['name_cn']}: {count} 3DFACEs")
    
    def export_coordinate_markers(self, section_data_list: List[Dict]):
        """
        导出坐标标记点
        
        用于验证坐标正确性
        """
        print(f"\n=== Exporting Coordinate Markers ===")
        
        # 提取关键坐标点
        marker_count = 0
        
        # 每10个断面取一个标记点
        for i, data in enumerate(section_data_list[::10]):
            if data['dmx_3d'] is not None:
                # 取DMX中点
                mid_idx = len(data['dmx_3d']) // 2
                mid_pt = data['dmx_3d'][mid_idx]
                
                # 创建POINT实体
                self.msp.add_point(
                    (mid_pt[0], mid_pt[1], mid_pt[2]),
                    dxfattribs={'layer': 'DMX_RIBBON'}
                )
                marker_count += 1
        
        print(f"  Coordinate markers: {marker_count}")
    
    def export_bounding_box(self, section_data_list: List[Dict]):
        """
        导出边界框和视图标记
        
        用于在CAD中定位模型位置，解决"看不到"的问题
        """
        print(f"\n=== Exporting Bounding Box ===")
        
        # 收集所有坐标点
        all_points = []
        for data in section_data_list:
            if data['dmx_3d'] is not None:
                all_points.extend(data['dmx_3d'])
            if data['overbreak_3d']:
                for ob in data['overbreak_3d']:
                    all_points.extend(ob)
            if data['geological_polys']:
                for poly in data['geological_polys']:
                    all_points.extend(poly['points'])
        
        if not all_points:
            print("  [WARN] No points found for bounding box")
            return
        
        all_points = np.array(all_points)
        
        # 计算边界
        x_min, x_max = np.min(all_points[:, 0]), np.max(all_points[:, 0])
        y_min, y_max = np.min(all_points[:, 1]), np.max(all_points[:, 1])
        z_min, z_max = np.min(all_points[:, 2]), np.max(all_points[:, 2])
        
        print(f"  X range: {x_min:.1f} ~ {x_max:.1f} (span: {x_max - x_min:.1f} m)")
        print(f"  Y range: {y_min:.1f} ~ {y_max:.1f} (span: {y_max - y_min:.1f} m)")
        print(f"  Z range: {z_min:.1f} ~ {z_max:.1f} (span: {z_max - z_min:.1f} m)")
        
        # 创建边界框（使用3DPOLYLINE）
        # 底面
        bottom_corners = [
            (x_min, y_min, z_min),
            (x_max, y_min, z_min),
            (x_max, y_max, z_min),
            (x_min, y_max, z_min),
            (x_min, y_min, z_min)  # 闭合
        ]
        self.msp.add_polyline3d(bottom_corners, dxfattribs={'layer': 'BOUNDING_BOX'})

        # 顶面
        top_corners = [
            (x_min, y_min, z_max),
            (x_max, y_min, z_max),
            (x_max, y_max, z_max),
            (x_min, y_max, z_max),
            (x_min, y_min, z_max)  # 闭合
        ]
        self.msp.add_polyline3d(top_corners, dxfattribs={'layer': 'BOUNDING_BOX'})

        # 立柱
        for corner in [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)]:
            pillar = [
                (corner[0], corner[1], z_min),
                (corner[0], corner[1], z_max)
            ]
            self.msp.add_polyline3d(pillar, dxfattribs={'layer': 'BOUNDING_BOX'})
        
        # 创建中心点标记（POINT实体）
        center_x = (x_min + x_max) / 2
        center_y = (y_min + y_max) / 2
        center_z = (z_min + z_max) / 2
        
        self.msp.add_point((center_x, center_y, center_z), dxfattribs={'layer': 'VIEW_MARKERS'})
        
        # 创建对角线（帮助视图定位）
        diagonal1 = [(x_min, y_min, z_min), (x_max, y_max, z_max)]
        diagonal2 = [(x_max, y_min, z_min), (x_min, y_max, z_max)]
        self.msp.add_polyline3d(diagonal1, dxfattribs={'layer': 'BOUNDING_BOX'})
        self.msp.add_polyline3d(diagonal2, dxfattribs={'layer': 'BOUNDING_BOX'})
        
        print(f"  Bounding box created with 8 edges + 2 diagonals")
        print(f"  Center point: ({center_x:.1f}, {center_y:.1f}, {center_z:.1f})")
        
        # 存储边界信息供后续使用
        self.bounds = {
            'x_min': x_min, 'x_max': x_max,
            'y_min': y_min, 'y_max': y_max,
            'z_min': z_min, 'z_max': z_max,
            'center': (center_x, center_y, center_z)
        }
    
    def setup_viewport(self):
        """
        设置DXF视图范围
        
        确保CAD打开时能正确显示模型
        关键：设置EXTMIN/EXTMAX头变量，这是AutoCAD确定模型范围的核心参数
        """
        if not hasattr(self, 'bounds') or not self.bounds:
            print("  [WARN] No bounds available for viewport setup")
            return
        
        print(f"\n=== Setting Up Viewport ===")
        
        # 获取边界
        x_min, x_max = self.bounds['x_min'], self.bounds['x_max']
        y_min, y_max = self.bounds['y_min'], self.bounds['y_max']
        z_min, z_max = self.bounds['z_min'], self.bounds['z_max']
        
        # 计算视图中心
        center_x = (x_min + x_max) / 2
        center_y = (y_min + y_max) / 2
        
        # 计算视图范围（添加10%边距）
        width = x_max - x_min
        height = y_max - y_min
        margin = 0.1
        
        view_width = width * (1 + margin)
        view_height = height * (1 + margin)
        
        print(f"  Model bounds: X({x_min:.1f}~{x_max:.1f}), Y({y_min:.1f}~{y_max:.1f}), Z({z_min:.1f}~{z_max:.1f})")
        print(f"  View center: ({center_x:.1f}, {center_y:.1f})")
        print(f"  View size: {view_width:.1f} x {view_height:.1f}")
        
        # 关键：设置DXF头变量EXTMIN/EXTMAX
        # 这是AutoCAD确定模型范围的核心参数，用于ZOOM Extents
        # ezdxf需要使用特定的API设置这些变量
        try:
            from ezdxf.math import Vec3
            self.doc.header.set_extmin(Vec3(x_min, y_min, z_min))
            self.doc.header.set_extmax(Vec3(x_max, y_max, z_max))
            print(f"  Header $EXTMIN/$EXTMAX set correctly")
        except Exception as e:
            print(f"  [WARN] Header EXTMIN/EXTMAX setup failed: {e}")
            # 尝试备用方法
            try:
                self.doc.header['$EXTMIN'] = (x_min, y_min, z_min)
                self.doc.header['$EXTMAX'] = (x_max, y_max, z_max)
                print(f"  Header $EXTMIN/$EXTMAX set via dict method")
            except Exception as e2:
                print(f"  [WARN] Backup method also failed: {e2}")
        
        # 设置模型空间视图
        try:
            # 设置活动视口
            if self.doc.tables.has_table('VPORT'):
                vport_table = self.doc.tables.vport
                # 创建或更新*Active视口
                if '*Active' in vport_table:
                    vport = vport_table['*Active']
                else:
                    vport = vport_table.new('*Active')
                
                # 设置视口参数
                vport.dxf.center = (center_x, center_y)
                vport.dxf.height = view_height
                vport.dxf.width = view_width
                vport.dxf.view_direction = (0, 0, 1)  # 俯视图
                
                print(f"  Viewport '*Active' configured")
        except Exception as e:
            print(f"  [WARN] Viewport setup failed: {e}")
            # 不影响导出，继续执行
    
    def save_dxf(self, output_path: str):
        """保存DXF文件并修复EXTMIN/EXTMAX
        
        注意：ezdxf在保存时会重置EXTMIN/EXTMAX为默认极端值，
        需要在保存后直接修改DXF文件文本内容来修复这个问题。
        """
        if self.doc is None:
            print("[ERROR] No DXF document to save")
            return False
        
        # 先保存文件
        self.doc.saveas(output_path)
        print(f"\n=== DXF Saved ===")
        print(f"  Output: {output_path}")
        print(f"  File size: {os.path.getsize(output_path) / 1024:.1f} KB")
        
        # 关键修复：直接修改DXF文件的EXTMIN/EXTMAX
        # ezdxf保存时会重置这些值为1e+20，导致AutoCAD zoom extents显示问题
        if hasattr(self, 'bounds') and self.bounds:
            self._fix_extmin_extmax_direct(output_path)
        
        return True
    
    def _fix_extmin_extmax_direct(self, dxf_path: str):
        """直接修改DXF文件的EXTMIN/EXTMAX头变量
        
        绕过ezdxf的自动重置机制，直接修改DXF文本文件。
        """
        import re
        
        print(f"\n=== Fixing EXTMIN/EXTMAX ===")
        
        x_min = self.bounds['x_min']
        x_max = self.bounds['x_max']
        y_min = self.bounds['y_min']
        y_max = self.bounds['y_max']
        z_min = self.bounds['z_min']
        z_max = self.bounds['z_max']
        
        print(f"  Target range: X({x_min:.2f}~{x_max:.2f}), Y({y_min:.2f}~{y_max:.2f}), Z({z_min:.2f}~{z_max:.2f})")
        
        try:
            # 读取DXF文件文本内容
            with open(dxf_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 替换EXTMIN (DXF格式: $EXTMIN后跟10/20/30组码)
            extmin_pattern = r'(\$EXTMIN\s*\n\s*10\s*\n\s*)([^\n]+)(\s*\n\s*20\s*\n\s*)([^\n]+)(\s*\n\s*30\s*\n\s*)([^\n]+)'
            extmin_replacement = f'$EXTMIN\n  10\n{x_min:.6f}\n  20\n{y_min:.6f}\n  30\n{z_min:.6f}'
            content_new = re.sub(extmin_pattern, extmin_replacement, content)
            
            # 替换EXTMAX
            extmax_pattern = r'(\$EXTMAX\s*\n\s*10\s*\n\s*)([^\n]+)(\s*\n\s*20\s*\n\s*)([^\n]+)(\s*\n\s*30\s*\n\s*)([^\n]+)'
            extmax_replacement = f'$EXTMAX\n  10\n{x_max:.6f}\n  20\n{y_max:.6f}\n  30\n{z_max:.6f}'
            content_new = re.sub(extmax_pattern, extmax_replacement, content_new)
            
            # 尝试另一种格式（单空格）
            extmin_pattern2 = r'(\$EXTMIN\s*\n 10\s*\n\s*)([^\n]+)(\s*\n 20\s*\n\s*)([^\n]+)(\s*\n 30\s*\n\s*)([^\n]+)'
            extmin_replacement2 = f'$EXTMIN\n 10\n{x_min:.6f}\n 20\n{y_min:.6f}\n 30\n{z_min:.6f}'
            content_new = re.sub(extmin_pattern2, extmin_replacement2, content_new)
            
            extmax_pattern2 = r'(\$EXTMAX\s*\n 10\s*\n\s*)([^\n]+)(\s*\n 20\s*\n\s*)([^\n]+)(\s*\n 30\s*\n\s*)([^\n]+)'
            extmax_replacement2 = f'$EXTMAX\n 10\n{x_max:.6f}\n 20\n{y_max:.6f}\n 30\n{z_max:.6f}'
            content_new = re.sub(extmax_pattern2, extmax_replacement2, content_new)
            
            # 写入修复后的文件
            with open(dxf_path, 'w', encoding='utf-8', errors='ignore') as f:
                f.write(content_new)
            
            print(f"  [OK] EXTMIN/EXTMAX fixed successfully")
            
        except Exception as e:
            print(f"  [WARN] EXTMIN/EXTMAX fix failed: {e}")
            # 不影响导出，继续执行
    
    # ==================== 辅助方法 ====================
    
    def _resample_all_lines(self, lines: List[np.ndarray], num_samples: int) -> List[np.ndarray]:
        """重采样所有线条到相同点数"""
        resampled = []
        for line in lines:
            resampled.append(self._resample_line(line, num_samples))
        return resampled
    
    def _resample_line(self, points: np.ndarray, num_samples: int) -> np.ndarray:
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
    
    def _resample_trench_all(self, lines: List[np.ndarray], n_slope: int, n_bottom: int) -> List[np.ndarray]:
        """分段重采样所有超挖线"""
        total_points = n_slope * 2 + n_bottom
        resampled = []
        
        for line in lines:
            resampled.append(self._resample_trench(line, n_slope, n_bottom, total_points))
        
        return resampled
    
    def _resample_trench(self, points: np.ndarray, n_slope: int, n_bottom: int, total_points: int) -> np.ndarray:
        """分段重采样超挖线"""
        if len(points) < 4:
            return self._resample_line(points, total_points)
        
        # 简化处理：直接均匀重采样
        return self._resample_line(points, total_points)
    
    def _resample_polygon(self, points: np.ndarray, num_samples: int) -> np.ndarray:
        """重采样多边形"""
        if len(points) < 3:
            return points
        
        # 确保闭合
        closed = np.vstack([points, points[0]])
        
        # 计算累积距离
        diff = np.diff(closed, axis=0)
        dist = np.sqrt((diff**2).sum(axis=1))
        s = np.concatenate(([0], np.cumsum(dist)))
        
        if s[-1] == 0:
            return np.tile(points[0], (num_samples, 1))
        
        # 等距离采样
        target_s = np.linspace(0, s[-1], num_samples, endpoint=False)
        resampled = np.zeros((num_samples, points.shape[1]))
        for i in range(points.shape[1]):
            resampled[:, i] = np.interp(target_s, s, closed[:, i])
        
        return resampled
    
    def _match_geological_polygons(self, section_data_list: List[Dict], 
                                    threshold: float = 50.0,
                                    area_change_threshold: float = 0.8) -> List[Tuple[Dict, Dict]]:
        """匹配相邻断面的地质多边形"""
        connections = []
        
        for i in range(len(section_data_list) - 1):
            polys_a = section_data_list[i]['geological_polys']
            polys_b = section_data_list[i + 1]['geological_polys']
            
            for p_a in polys_a:
                layer_a = p_a['layer']
                centroid_a = p_a['centroid']
                
                candidates = [p_b for p_b in polys_b if p_b['layer'] == layer_a]
                
                if not candidates:
                    continue
                
                # 找最近的候选
                best_match = None
                min_dist = float('inf')
                
                for p_b in candidates:
                    centroid_b = p_b['centroid']
                    dist = math.sqrt((centroid_a[0] - centroid_b[0])**2 + 
                                    (centroid_a[1] - centroid_b[1])**2)
                    
                    if dist < min_dist:
                        min_dist = dist
                        best_match = p_b
                
                if min_dist <= threshold and best_match:
                    connections.append((p_a, best_match))
        
        return connections


# ==================== 主函数 ====================

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='V7 Model DXF Exporter')
    parser.add_argument('--input', type=str,
                        default=r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json',
                        help='Input JSON metadata file')
    parser.add_argument('--spine', type=str,
                        default=r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json',
                        help='Spine matches JSON file')
    parser.add_argument('--output', type=str,
                        default=r'D:\断面算量平台\测试文件\geology_model_v7.dxf',
                        help='Output DXF file')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("V7 Model DXF Exporter")
    print("  - Export DMX Ribbon as 3DFACE mesh")
    print("  - Export Overbreak Ribbon as 3DFACE mesh")
    print("  - Export Geological Volumes as 3DFACE mesh")
    print("  - Coordinate system: X=East, Y=North(Station), Z=Elevation")
    print("=" * 60)
    
    # 加载数据
    loader = V7ModelDataLoader(args.input, args.spine)
    if not loader.load_data():
        print("[ERROR] Failed to load data")
        return
    
    # 构建断面数据
    section_data_list = loader.build_all_section_data()
    print(f"  Total sections: {len(section_data_list)}")
    
    # 验证坐标范围
    if section_data_list:
        first = section_data_list[0]
        last = section_data_list[-1]
        
        if first['dmx_3d'] is not None and last['dmx_3d'] is not None:
            print(f"\n=== Coordinate Verification ===")
            print(f"  First section DMX:")
            print(f"    X range: {np.min(first['dmx_3d'][:, 0]):.2f} - {np.max(first['dmx_3d'][:, 0]):.2f}")
            print(f"    Y range: {np.min(first['dmx_3d'][:, 1]):.2f} - {np.max(first['dmx_3d'][:, 1]):.2f}")
            print(f"    Z range: {np.min(first['dmx_3d'][:, 2]):.2f} - {np.max(first['dmx_3d'][:, 2]):.2f}")
            print(f"  Last section DMX:")
            print(f"    X range: {np.min(last['dmx_3d'][:, 0]):.2f} - {np.max(last['dmx_3d'][:, 0]):.2f}")
            print(f"    Y range: {np.min(last['dmx_3d'][:, 1]):.2f} - {np.max(last['dmx_3d'][:, 1]):.2f}")
            print(f"    Z range: {np.min(last['dmx_3d'][:, 2]):.2f} - {np.max(last['dmx_3d'][:, 2]):.2f}")
    
    # 创建DXF导出器
    exporter = V7ModelDXFExporter(loader)
    if not exporter.create_dxf_document():
        return
    
    # 导出各类实体
    exporter.export_dmx_ribbon(section_data_list, num_samples=60)
    exporter.export_overbreak_ribbon(section_data_list, n_slope=15, n_bottom=30)
    exporter.export_geological_volumes(section_data_list, num_samples=64)
    exporter.export_coordinate_markers(section_data_list)
    
    # 导出边界框（解决CAD可见性问题）
    exporter.export_bounding_box(section_data_list)
    
    # 设置视图范围
    exporter.setup_viewport()
    
    # 保存DXF
    exporter.save_dxf(args.output)
    
    print("\n" + "=" * 60)
    print("SUCCESS: V7 Model exported to DXF!")
    print("=" * 60)


if __name__ == '__main__':
    main()