# -*- coding: utf-8 -*-
"""
V7地质模型OBJ导出器

功能：
1. 将V7的3D模型数据导出为OBJ格式
2. 支持导出DMX Ribbon、超挖线Ribbon、地质体积实体
3. 生成配套的MTL材质文件
4. 分组管理不同类型的实体
5. 支持Blender、3ds Max、Maya等3D软件导入

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


# ==================== 地层分类 ====================

LAYER_CATEGORIES = {
    'mud_fill': {
        'name_cn': '淤泥与填土',
        'color_rgb': (0.5, 0.5, 0.5),  # 灰色
        'layers': ['1级淤泥', '2级淤泥', '3级淤泥', '4级淤泥', '1级填土', '2级填土', '3级填土', '4级填土'],
    },
    'clay': {
        'name_cn': '黏土',
        'color_rgb': (0.6, 0.4, 0.2),  # 棕色
        'layers': ['3级黏土', '4级黏土', '5级黏土'],
    },
    'sand_and_gravel': {
        'name_cn': '砂与碎石类',
        'color_rgb': (0.9, 0.8, 0.3),  # 金色
        'layers': ['6级砂', '7级砂', '8级砂', '9级砂', '10级砂', '6级碎石', '9级碎石'],
    }
}

# OBJ材质定义
OBJ_MATERIALS = {
    'DMX_RIBBON': {
        'color_rgb': (0.0, 0.0, 1.0),  # 蓝色
        'ambient': 0.2,
        'diffuse': 0.8,
        'specular': 0.3,
        'transparency': 0.0,
    },
    'OVERBREAK_RIBBON': {
        'color_rgb': (1.0, 0.0, 0.0),  # 红色
        'ambient': 0.2,
        'diffuse': 0.8,
        'specular': 0.3,
        'transparency': 0.0,
    },
    'GEO_MUD_FILL': {
        'color_rgb': (0.5, 0.5, 0.5),  # 灰色
        'ambient': 0.2,
        'diffuse': 0.7,
        'specular': 0.2,
        'transparency': 0.0,
    },
    'GEO_CLAY': {
        'color_rgb': (0.6, 0.4, 0.2),  # 棕色
        'ambient': 0.2,
        'diffuse': 0.7,
        'specular': 0.2,
        'transparency': 0.0,
    },
    'GEO_SAND': {
        'color_rgb': (0.9, 0.8, 0.3),  # 金色
        'ambient': 0.2,
        'diffuse': 0.7,
        'specular': 0.2,
        'transparency': 0.0,
    },
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
        # JSON中的overbreak_points是线段列表，每个线段有2个点
        # 需要将所有线段的点收集起来，按X坐标排序形成完整的超挖线轮廓
        overbreak_points = section.get('overbreak_points', [])
        all_ob_points = []
        for ob_line in overbreak_points:
            if len(ob_line) >= 2:
                for pt in ob_line:
                    eng_x, eng_y, z = self.transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                    )
                    all_ob_points.append([eng_x, eng_y, z])
        
        # 按X坐标排序形成完整的超挖线轮廓
        if len(all_ob_points) >= 3:
            all_ob_points = sorted(all_ob_points, key=lambda p: p[0])
            result['overbreak_3d'].append(np.array(all_ob_points))
        
        # 地质多边形转换
        fill_boundaries = section.get('fill_boundaries', {})
        for layer_name, polygons in fill_boundaries.items():
            cat_key = categorize_layer(layer_name)
            if cat_key is None:
                continue
            
            for poly in polygons:
                if len(poly) >= 3:
                    poly_3d = []
                    for pt in poly:
                        eng_x, eng_y, z = self.transform_to_spine_aligned(
                            pt[0], pt[1], ref_x, ref_y, spine_x, spine_y, rotation_angle
                        )
                        poly_3d.append([eng_x, eng_y, z])
                    
                    poly_3d = np.array(poly_3d)
                    centroid = np.mean(poly_3d, axis=0)
                    
                    result['geological_polys'].append({
                        'layer': cat_key,
                        'layer_name': layer_name,
                        'points': poly_3d,
                        'centroid': centroid
                    })
        
        return result
    
    def build_all_section_data(self) -> List[Dict]:
        """构建所有断面的3D数据"""
        section_data_list = []
        
        for section in self.sections:
            station_value = section.get('station_value', 0)
            spine_match = self._get_interpolated_spine_match(station_value)
            
            section_data = self.get_section_3d_data(section, spine_match)
            section_data_list.append(section_data)
        
        return section_data_list


# ==================== OBJ导出器 ====================

class V7ModelOBJExporter:
    """V7模型OBJ格式导出器"""
    
    def __init__(self, data_loader: V7ModelDataLoader):
        self.loader = data_loader
        self.vertices = []  # 顶点列表
        self.faces = []     # 面列表 (group_name, vertex_indices)
        self.groups = {}    # 组信息
        self.bounds = None  # 边界信息
        self.vertex_offset = 0  # 顶点索引偏移
    
    def export_to_obj(self, section_data_list: List[Dict], output_path: str):
        """
        导出为OBJ格式
        
        Args:
            section_data_list: 断面数据列表
            output_path: 输出OBJ文件路径
        """
        print(f"\n=== Exporting to OBJ Format ===")
        
        # 重置数据
        self.vertices = []
        self.faces = []
        self.groups = {}
        self.vertex_offset = 0
        
        # 导出各类实体
        self._export_dmx_ribbon(section_data_list, num_samples=60)
        self._export_overbreak_ribbon(section_data_list, n_slope=15, n_bottom=30)
        self._export_geological_volumes(section_data_list, num_samples=64)
        
        # 计算边界
        self._calculate_bounds()
        
        # 写入OBJ文件
        self._write_obj_file(output_path)
        
        # 写入MTL材质文件
        mtl_path = output_path.replace('.obj', '.mtl')
        self._write_mtl_file(mtl_path)
        
        print(f"\n=== OBJ Export Complete ===")
        print(f"  Vertices: {len(self.vertices)}")
        print(f"  Faces: {len(self.faces)}")
        print(f"  Groups: {len(self.groups)}")
        print(f"  Output: {output_path}")
        print(f"  MTL: {mtl_path}")
    
    def _export_dmx_ribbon(self, section_data_list: List[Dict], num_samples: int = 60):
        """导出DMX Ribbon曲面"""
        print(f"\n  Exporting DMX Ribbon...")
        
        # 收集所有DMX线
        all_lines = []
        for data in section_data_list:
            if data['dmx_3d'] is not None and len(data['dmx_3d']) >= 2:
                all_lines.append(data['dmx_3d'])
        
        if len(all_lines) < 2:
            print("    [WARN] Not enough DMX lines")
            return
        
        # 重采样
        resampled_lines = self._resample_all_lines(all_lines, num_samples)
        
        # 添加顶点
        group_name = 'DMX_RIBBON'
        face_count = 0
        
        for sec_idx, line in enumerate(resampled_lines):
            for pt in line:
                self.vertices.append(pt)
        
        # 创建面
        n_sections = len(resampled_lines)
        for sec_idx in range(n_sections - 1):
            for pt_idx in range(num_samples - 1):
                # 计算顶点索引（OBJ索引从1开始）
                v1 = self.vertex_offset + sec_idx * num_samples + pt_idx + 1
                v2 = self.vertex_offset + sec_idx * num_samples + pt_idx + 2
                v3 = self.vertex_offset + (sec_idx + 1) * num_samples + pt_idx + 2
                v4 = self.vertex_offset + (sec_idx + 1) * num_samples + pt_idx + 1
                
                # 两个三角形面
                self.faces.append((group_name, [v1, v2, v3]))
                self.faces.append((group_name, [v1, v3, v4]))
                face_count += 2
        
        self.vertex_offset = len(self.vertices)
        self.groups[group_name] = face_count
        print(f"    DMX Ribbon: {n_sections} sections, {face_count} faces")
    
    def _export_overbreak_ribbon(self, section_data_list: List[Dict], n_slope: int = 15, n_bottom: int = 30):
        """导出超挖线梯形槽Ribbon曲面"""
        print(f"\n  Exporting Overbreak Ribbon...")
        
        # 收集所有超挖线
        all_lines = []
        sections_with_overbreak = 0
        for data in section_data_list:
            if data['overbreak_3d'] and len(data['overbreak_3d']) > 0:
                sections_with_overbreak += 1
                for ob_line in data['overbreak_3d']:
                    if len(ob_line) >= 3:
                        # 检查坐标是否在合理范围内
                        y_values = ob_line[:, 1]
                        y_min = np.min(y_values)
                        # 过滤掉Y坐标为0或负数的异常数据
                        if y_min > 0:
                            all_lines.append(ob_line)
        
        print(f"    Sections with overbreak data: {sections_with_overbreak}/{len(section_data_list)}")
        print(f"    Valid overbreak lines collected: {len(all_lines)}")
        
        if len(all_lines) < 2:
            print("    [WARN] Not enough overbreak lines, skipping overbreak ribbon export")
            return
        
        # 分段重采样
        total_points = n_slope * 2 + n_bottom
        resampled_lines = self._resample_trench_all(all_lines, n_slope, n_bottom)
        
        # 添加顶点
        group_name = 'OVERBREAK_RIBBON'
        face_count = 0
        
        for line in resampled_lines:
            for pt in line:
                self.vertices.append(pt)
        
        # 创建面
        n_sections = len(resampled_lines)
        for sec_idx in range(n_sections - 1):
            for pt_idx in range(total_points - 1):
                v1 = self.vertex_offset + sec_idx * total_points + pt_idx + 1
                v2 = self.vertex_offset + sec_idx * total_points + pt_idx + 2
                v3 = self.vertex_offset + (sec_idx + 1) * total_points + pt_idx + 2
                v4 = self.vertex_offset + (sec_idx + 1) * total_points + pt_idx + 1
                
                self.faces.append((group_name, [v1, v2, v3]))
                self.faces.append((group_name, [v1, v3, v4]))
                face_count += 2
        
        self.vertex_offset = len(self.vertices)
        self.groups[group_name] = face_count
        print(f"    Overbreak Ribbon: {n_sections} sections, {face_count} faces")
    
    def _export_geological_volumes(self, section_data_list: List[Dict], num_samples: int = 64):
        """导出地质体积实体"""
        print(f"\n  Exporting Geological Volumes...")
        
        # 匹配地质体
        connections = self._match_geological_polygons(section_data_list)
        
        # 按类别分组导出
        category_faces = {cat: 0 for cat in LAYER_CATEGORIES.keys()}
        
        for p_a, p_b in connections:
            cat_key = p_a['layer']
            
            # 重采样多边形
            pts_a = self._resample_polygon(p_a['points'], num_samples)
            pts_b = self._resample_polygon(p_b['points'], num_samples)
            
            # 确定组名
            if cat_key == 'mud_fill':
                group_name = 'GEO_MUD_FILL'
            elif cat_key == 'clay':
                group_name = 'GEO_CLAY'
            else:
                group_name = 'GEO_SAND'
            
            # 添加顶点
            start_idx = len(self.vertices) + 1  # OBJ索引从1开始
            for pt in pts_a:
                self.vertices.append(pt)
            for pt in pts_b:
                self.vertices.append(pt)
            
            # 创建侧面面片
            for i in range(num_samples):
                next_i = (i + 1) % num_samples
                
                v1 = start_idx + i
                v2 = start_idx + next_i
                v3 = start_idx + num_samples + next_i
                v4 = start_idx + num_samples + i
                
                self.faces.append((group_name, [v1, v2, v3]))
                self.faces.append((group_name, [v1, v3, v4]))
                category_faces[cat_key] += 2
        
        # 更新组信息
        for cat, count in category_faces.items():
            if cat == 'mud_fill':
                self.groups['GEO_MUD_FILL'] = self.groups.get('GEO_MUD_FILL', 0) + count
            elif cat == 'clay':
                self.groups['GEO_CLAY'] = self.groups.get('GEO_CLAY', 0) + count
            else:
                self.groups['GEO_SAND'] = self.groups.get('GEO_SAND', 0) + count
        
        self.vertex_offset = len(self.vertices)
        
        print(f"    Geological volumes: {len(connections)} connections")
        for cat, count in category_faces.items():
            print(f"      {LAYER_CATEGORIES[cat]['name_cn']}: {count} faces")
    
    def _calculate_bounds(self):
        """计算边界"""
        if not self.vertices:
            return
        
        vertices = np.array(self.vertices)
        self.bounds = {
            'x_min': np.min(vertices[:, 0]),
            'x_max': np.max(vertices[:, 0]),
            'y_min': np.min(vertices[:, 1]),
            'y_max': np.max(vertices[:, 1]),
            'z_min': np.min(vertices[:, 2]),
            'z_max': np.max(vertices[:, 2]),
        }
        
        print(f"\n  Bounds:")
        print(f"    X: {self.bounds['x_min']:.2f} ~ {self.bounds['x_max']:.2f}")
        print(f"    Y: {self.bounds['y_min']:.2f} ~ {self.bounds['y_max']:.2f}")
        print(f"    Z: {self.bounds['z_min']:.2f} ~ {self.bounds['z_max']:.2f}")
    
    def _write_obj_file(self, output_path: str):
        """写入OBJ文件"""
        with open(output_path, 'w', encoding='utf-8') as f:
            # 文件头
            f.write("# V7 Geology Model - OBJ Format\n")
            f.write(f"# Generated: 2026-04-03\n")
            f.write(f"# Vertices: {len(self.vertices)}\n")
            f.write(f"# Faces: {len(self.faces)}\n")
            f.write(f"# Groups: {len(self.groups)}\n")
            f.write("#\n")
            f.write(f"mtllib {os.path.basename(output_path).replace('.obj', '.mtl')}\n\n")
            
            # 写入顶点
            f.write("# Vertices\n")
            for v in self.vertices:
                f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            
            # 按组写入面
            f.write("\n# Faces\n")
            current_group = None
            
            for group_name, vertex_indices in self.faces:
                if group_name != current_group:
                    current_group = group_name
                    f.write(f"\ng {group_name}\n")
                    f.write(f"usemtl {group_name}\n")
                
                # 面索引
                face_str = " ".join(str(idx) for idx in vertex_indices)
                f.write(f"f {face_str}\n")
    
    def _write_mtl_file(self, mtl_path: str):
        """写入MTL材质文件"""
        with open(mtl_path, 'w', encoding='utf-8') as f:
            f.write("# V7 Geology Model - MTL Material File\n")
            f.write("# Generated: 2026-04-03\n\n")
            
            for mat_name, mat_info in OBJ_MATERIALS.items():
                rgb = mat_info['color_rgb']
                f.write(f"newmtl {mat_name}\n")
                f.write(f"Ka {mat_info['ambient']:.2f} {mat_info['ambient']:.2f} {mat_info['ambient']:.2f}\n")
                f.write(f"Kd {rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f}\n")
                f.write(f"Ks {mat_info['specular']:.2f} {mat_info['specular']:.2f} {mat_info['specular']:.2f}\n")
                f.write(f"d {1.0 - mat_info['transparency']:.2f}\n")
                f.write(f"illum 2\n\n")
    
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
            resampled.append(self._resample_line(line, total_points))
        
        return resampled
    
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
                                    threshold: float = 50.0) -> List[Tuple[Dict, Dict]]:
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
    
    parser = argparse.ArgumentParser(description='V7 Model OBJ Exporter')
    parser.add_argument('--input', type=str,
                        default=r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json',
                        help='Input JSON metadata file')
    parser.add_argument('--spine', type=str,
                        default=r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json',
                        help='Spine matches JSON file')
    parser.add_argument('--output', type=str,
                        default=r'D:\断面算量平台\测试文件\geology_model_v7.obj',
                        help='Output OBJ file')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("V7 Model OBJ Exporter")
    print("  - Export DMX Ribbon as triangle mesh")
    print("  - Export Overbreak Ribbon as triangle mesh")
    print("  - Export Geological Volumes as triangle mesh")
    print("  - Generate MTL material file")
    print("  - Compatible with Blender, 3ds Max, Maya")
    print("=" * 60)
    
    # 加载数据
    loader = V7ModelDataLoader(args.input, args.spine)
    if not loader.load_data():
        print("[ERROR] Failed to load data")
        return
    
    # 构建断面数据
    section_data_list = loader.build_all_section_data()
    print(f"  Total sections: {len(section_data_list)}")
    
    # 创建OBJ导出器
    exporter = V7ModelOBJExporter(loader)
    exporter.export_to_obj(section_data_list, args.output)
    
    print("\n" + "=" * 60)
    print("SUCCESS: V7 Model exported to OBJ!")
    print("=" * 60)


if __name__ == '__main__':
    main()