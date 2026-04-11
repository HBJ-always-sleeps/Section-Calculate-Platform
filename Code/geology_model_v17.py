# -*- coding: utf-8 -*-
"""
航道三维地质模型构建器 V17 - 桩号线标记 + DMX向上厚度 + 超挖向下厚度 + 厚度2米

核心改进（基于V16用户反馈）：
1. DMX厚度方向：向上加厚度（Z + thickness）
2. 超挖槽厚度方向：向下加厚度（Z - thickness）- 保持不变
3. 厚度值：改为2米（原5米）
4. 桩号标记：改为平行断面方向的直线（原立方体）
5. 桩号线位置：放在超挖槽下方
6. 桩号数字：实体化文本，格式简化为"00000"（原"00+000"）
7. 桩号数字位置：平行桩号线标注

作者: @黄秉俊
日期: 2026-04-07
"""

import json
import numpy as np
from scipy.interpolate import griddata
import ezdxf
import math
import sys
import os
from typing import Dict, List, Tuple, Optional

sys.path.insert(0, r'D:\断面算量平台\Code')


# ==================== 地层分类映射 ====================

LAYER_CATEGORIES = {
    'MUD': {
        'name_cn': '淤泥与填土',
        'color': 1,
        'keywords': ['1级淤泥', '2级淤泥', '3级淤泥', '4级淤泥', '1级填土', '2级填土', '3级填土', '4级填土'],
        'obj_color': (0.5, 0.5, 0.5)
    },
    'CLAY': {
        'name_cn': '黏土',
        'color': 2,
        'keywords': ['3级黏土', '4级黏土', '5级黏土'],
        'obj_color': (0.6, 0.4, 0.2)
    },
    'SAND': {
        'name_cn': '砂与碎石类',
        'color': 3,
        'keywords': ['6级砂', '7级砂', '8级砂', '9级砂', '10级砂', '6级碎石', '9级碎石'],
        'obj_color': (0.9, 0.8, 0.3)
    }
}

# OBJ材质定义 - DMX和超挖都半透明
OBJ_MATERIALS = {
    'DMX_SOLID': {
        'color_rgb': (0.0, 0.5, 1.0),  # 浅蓝色
        'ambient': 0.2,
        'diffuse': 0.8,
        'specular': 0.3,
        'illum': 2,
        'opacity': 0.5,  # 半透明
    },
    'OVERBREAK_SOLID': {
        'color_rgb': (1.0, 0.3, 0.0),  # 红色
        'ambient': 0.2,
        'diffuse': 0.8,
        'specular': 0.3,
        'illum': 2,
        'opacity': 0.5,  # 半透明
    },
    'GEO_MUD': {
        'color_rgb': (0.5, 0.5, 0.5),
        'ambient': 0.2,
        'diffuse': 0.7,
        'specular': 0.2,
        'illum': 2,
        'opacity': 1.0,
    },
    'GEO_CLAY': {
        'color_rgb': (0.6, 0.4, 0.2),
        'ambient': 0.2,
        'diffuse': 0.7,
        'specular': 0.2,
        'illum': 2,
        'opacity': 1.0,
    },
    'GEO_SAND': {
        'color_rgb': (0.9, 0.8, 0.3),
        'ambient': 0.2,
        'diffuse': 0.7,
        'specular': 0.2,
        'illum': 2,
        'opacity': 1.0,
    },
    'STATION_LINE': {
        'color_rgb': (1.0, 0.0, 0.0),  # 红色桩号线和数字
        'ambient': 0.1,
        'diffuse': 0.9,
        'specular': 0.1,
        'illum': 2,
        'opacity': 1.0,  # 不透明
    },
}

# DMX/超挖厚度参数 - 改为2米
RIBBON_THICKNESS = 2.0  # 米

# 桩号线参数 - 改为实体长方体
STATION_LINE_CROSS_SECTION = 0.2  # 米（桩号线横截面尺寸：0.2m x 0.2m - 增粗一倍）
STATION_LINE_EXTRA_LENGTH = 33.75  # 米（桩号线比DMX宽度额外增加的长度 - 原来22.5米的1.5倍）
STATION_LINE_OFFSET_Z = 5.0  # 米（桩号线相对于DMX顶部的向上偏移）
STATION_LINE_INTERVAL = 200  # 米（桩号线间隔：每200米一条）
STATION_TEXT_HEIGHT = 16.0  # 米（桩号文字高度 - 增大4倍）
STATION_TEXT_WIDTH = 6.4  # 米（桩号文字宽度 - 增大4倍）
STATION_TEXT_DEPTH = 0.2  # 米（桩号文字厚度 - 增粗）
STATION_TEXT_OFFSET = 5.0  # 米（桩号文字相对于桩号线的偏移）


def categorize_layer(layer_name: str) -> Optional[str]:
    for cat_key, cat_info in LAYER_CATEGORIES.items():
        for kw in cat_info['keywords']:
            if kw in layer_name:
                return cat_key
    return None


def transform_to_spine_aligned(cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle):
    """
    坐标转换：将CAD坐标转换为三维大地坐标系
    
    参考 extract_xyz_from_dxf.py 的转换逻辑：
    - dx = cad_x - ref_x (相对于L1交点的X偏移，断面方向距离)
    - z = cad_y - ref_y (高程，相对于L1点)
    - eng_x = spine_x + dx * cos(rotation_angle)
    - eng_y = spine_y + dx * sin(rotation_angle)
    
    这样保留了真实的弯道形状
    """
    z = cad_y - ref_y
    dx = cad_x - ref_x
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    eng_x = spine_x + dx * cos_a
    eng_y = spine_y + dx * sin_a
    return eng_x, eng_y, z


def uv_to_world(u, v, spine_data):
    """
    UV坐标转世界坐标
    
    Args:
        u: 桩号值
        v: 横向偏移
        spine_data: 脊梁点数据
    """
    closest_station = min(spine_data.keys(), key=lambda k: abs(k - u))
    spine = spine_data[closest_station]
    angle_rad = spine['tangent_angle'] + math.pi / 2
    world_x = spine['spine_x'] + v * math.cos(angle_rad)
    world_y = spine['spine_y'] + v * math.sin(angle_rad)
    return world_x, world_y


def format_station_number(station_value: float) -> str:
    """
    将桩号值格式化为简化格式 "00000"
    例如: 500 -> "00500", 1200 -> "01200"
    """
    # 桩号值通常是米数，转换为整数
    station_int = int(round(station_value))
    # 格式化为5位数字字符串
    return f"{station_int:05d}"


class OBJExporterV17:
    """V17 OBJ导出器 - 支持半透明材质、桩号线实体化、厚度化Ribbon"""
    
    def __init__(self, output_obj, output_mtl):
        self.output_obj = output_obj
        self.output_mtl = output_mtl
        self.vertices = []
        self.faces = []
        self.lines = []  # 线段数据
        self.groups = {}
        self.station_markers = []  # 桩号标记数据（线段）
        self.station_texts = []  # 桩号文本数据
    
    def add_vertex(self, x, y, z):
        self.vertices.append((x, y, z))
        return len(self.vertices)
    
    def add_face(self, material, v_indices, group=None):
        face_indices = [i + 1 for i in v_indices]
        self.faces.append((material, face_indices))
        if group:
            if group not in self.groups:
                self.groups[group] = []
            self.groups[group].append(len(self.faces) - 1)
    
    def add_line(self, material, v_indices, group=None):
        """添加线段（用于桩号线）"""
        line_indices = [i + 1 for i in v_indices]
        self.lines.append((material, line_indices))
        if group:
            if group not in self.groups:
                self.groups[group] = []
            self.groups[group].append(len(self.lines) - 1)
    
    def add_station_line(self, station_value, start_x, start_y, start_z, end_x, end_y, end_z):
        """添加桩号线段"""
        self.station_markers.append({
            'station': station_value,
            'start': (start_x, start_y, start_z),
            'end': (end_x, end_y, end_z)
        })
        # 添加两个顶点
        v0 = self.add_vertex(start_x, start_y, start_z) - 1
        v1 = self.add_vertex(end_x, end_y, end_z) - 1
        # 添加线段
        self.add_line('STATION_LINE', [v0, v1], 'STATION_LINES')
    
    def add_station_text_marker(self, station_value, x, y, z, text_content):
        """添加桩号文本标记位置（用于OBJ注释）"""
        self.station_texts.append({
            'station': station_value,
            'x': x,
            'y': y,
            'z': z,
            'text': text_content
        })
    
    def write_mtl(self):
        with open(self.output_mtl, 'w', encoding='utf-8') as f:
            f.write("# MTL Material Library for Channel Geology Model V17\n")
            f.write("# Features: DMX/OVERBREAK semi-transparent + Station Lines\n\n")
            for mat_name, mat_info in OBJ_MATERIALS.items():
                r, g, b = mat_info['color_rgb']
                opacity = mat_info.get('opacity', 1.0)
                f.write(f"newmtl {mat_name}\n")
                f.write(f"Ka {mat_info['ambient']:.3f} {mat_info['ambient']:.3f} {mat_info['ambient']:.3f}\n")
                f.write(f"Kd {r:.3f} {g:.3f} {b:.3f}\n")
                f.write(f"Ks {mat_info['specular']:.3f} {mat_info['specular']:.3f} {mat_info['specular']:.3f}\n")
                f.write(f"illum {mat_info['illum']}\n")
                # 添加透明度参数
                if opacity < 1.0:
                    f.write(f"d {opacity:.3f}\n")  # dissolve = opacity
                f.write("\n")
    
    def write_obj(self):
        with open(self.output_obj, 'w', encoding='utf-8') as f:
            f.write("# OBJ File for Channel Geology Model V17\n")
            f.write("# Features: Thick Ribbon(2m) + Station Lines + Semi-transparent\n")
            f.write(f"# Vertices: {len(self.vertices)}\n")
            f.write(f"# Faces: {len(self.faces)}\n")
            f.write(f"# Station Lines: {len(self.station_markers)}\n\n")
            f.write(f"mtllib {os.path.basename(self.output_mtl)}\n\n")
            
            # 写入桩号线信息作为注释
            if self.station_markers:
                f.write("# Station Line Locations\n")
                for marker in self.station_markers:
                    f.write(f"# Station {marker['station']:.1f}m: ({marker['start'][0]:.2f}, {marker['start'][1]:.2f}, {marker['start'][2]:.2f}) -> ({marker['end'][0]:.2f}, {marker['end'][1]:.2f}, {marker['end'][2]:.2f})\n")
                f.write("\n")
            
            # 写入桩号文本信息作为注释
            if self.station_texts:
                f.write("# Station Text Labels (for DXF TEXT entities)\n")
                for text in self.station_texts:
                    f.write(f"# Station {text['station']:.1f}m: Text '{text['text']}' at ({text['x']:.2f}, {text['y']:.2f}, {text['z']:.2f})\n")
                f.write("\n")
            
            # 写入顶点
            f.write("# Vertices\n")
            for x, y, z in self.vertices:
                f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
            f.write("\n")
            
            # 写入面
            current_material = None
            for group_name, face_indices in self.groups.items():
                f.write(f"g {group_name}\n")
                for fi in face_indices:
                    # 检查是面还是线
                    if fi < len(self.faces):
                        mat, v_list = self.faces[fi]
                        if mat != current_material:
                            f.write(f"usemtl {mat}\n")
                            current_material = mat
                        if len(v_list) == 4:
                            f.write(f"f {v_list[0]} {v_list[1]} {v_list[2]} {v_list[3]}\n")
                        elif len(v_list) == 3:
                            f.write(f"f {v_list[0]} {v_list[1]} {v_list[2]}\n")
                    elif fi < len(self.faces) + len(self.lines):
                        # 线段
                        line_idx = fi - len(self.faces)
                        mat, v_list = self.lines[line_idx]
                        if mat != current_material:
                            f.write(f"usemtl {mat}\n")
                            current_material = mat
                        if len(v_list) == 2:
                            f.write(f"l {v_list[0]} {v_list[1]}\n")
    
    def export(self):
        self.write_mtl()
        self.write_obj()
        print(f"  OBJ exported: {self.output_obj}")
        print(f"  MTL exported: {self.output_mtl}")
        print(f"  Total vertices: {len(self.vertices)}")
        print(f"  Total faces: {len(self.faces)}")
        print(f"  Station lines: {len(self.station_markers)}")
        print(f"  Station texts: {len(self.station_texts)}")


class ChannelBIMGeneratorV17:
    """V17生成器 - 桩号线实体化 + DMX向上厚度 + 超挖向下厚度 + 厚度2米"""
    
    def __init__(self, metadata_path, match_path):
        self.metadata_path = metadata_path
        self.match_path = match_path
        self.uvz_points = {'DMX': [], 'OVERDREDGE': [], 'MUD': [], 'CLAY': [], 'SAND': []}
        self.spine_data = {}
        self.sections_3d = []
        self.obj_exporter = None
        self.dmx_bounds = {}
    
    def load_and_parse_data(self):
        print("\n=== Loading and Parsing Data ===")
        try:
            with open(self.match_path, 'r', encoding='utf-8') as f:
                match_data = json.load(f)
        except Exception as e:
            print(f"  [ERROR] Failed to load spine match: {e}")
            return False
        
        matches = match_data.get('matches', [])
        if not matches:
            matches = [v for k, v in match_data.items() if isinstance(v, dict) and 'station_value' in v]
        
        for m in matches:
            self.spine_data[m['station_value']] = {
                'spine_x': m['spine_x'], 'spine_y': m['spine_y'],
                'l1_x': m['l1_x'], 'l1_y': m['l1_y'],
                'tangent_angle': m['tangent_angle']
            }
        print(f"  Spine matches loaded: {len(self.spine_data)}")
        
        try:
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        except Exception as e:
            print(f"  [ERROR] Failed to load metadata: {e}")
            return False
        
        sections = metadata.get('sections', [])
        print(f"  Sections loaded: {len(sections)}")
        
        matched_count = 0
        for sec in sections:
            station = sec.get('station_value', 0)
            if station not in self.spine_data:
                continue
            
            spine = self.spine_data[station]
            l1_ref = sec.get('l1_ref_point', {})
            ref_x = l1_ref.get('ref_x', spine['l1_x'])
            ref_y = l1_ref.get('ref_y', spine['l1_y'])
            rotation_angle = spine['tangent_angle'] + math.pi / 2
            
            section_3d = {'station_value': station, 'dmx_3d': [], 'overbreak_3d': [], 'geological_polys': {}}
            
            dmx_points = sec.get('dmx_points', [])
            for pt in dmx_points:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    cad_x, cad_y = pt[0], pt[1]
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        cad_x, cad_y, ref_x, ref_y, spine['spine_x'], spine['spine_y'], rotation_angle)
                    section_3d['dmx_3d'].append((eng_x, eng_y, z))
                    self.uvz_points['DMX'].append((station, cad_x - ref_x, z))
            
            overbreak_points = sec.get('overbreak_points', [])
            for pt_group in overbreak_points:
                if isinstance(pt_group, (list, tuple)):
                    for pt in pt_group:
                        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                            cad_x, cad_y = pt[0], pt[1]
                            eng_x, eng_y, z = transform_to_spine_aligned(
                                cad_x, cad_y, ref_x, ref_y, spine['spine_x'], spine['spine_y'], rotation_angle)
                            section_3d['overbreak_3d'].append((eng_x, eng_y, z))
                            self.uvz_points['OVERDREDGE'].append((station, cad_x - ref_x, z))
            
            fill_boundaries = sec.get('fill_boundaries', {})
            for layer_name, poly_groups in fill_boundaries.items():
                cat_key = categorize_layer(layer_name)
                if cat_key is None:
                    continue
                if cat_key not in section_3d['geological_polys']:
                    section_3d['geological_polys'][cat_key] = []
                
                for poly_group in poly_groups:
                    if isinstance(poly_group, (list, tuple)):
                        poly_3d = []
                        for pt in poly_group:
                            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                                cad_x, cad_y = pt[0], pt[1]
                                eng_x, eng_y, z = transform_to_spine_aligned(
                                    cad_x, cad_y, ref_x, ref_y, spine['spine_x'], spine['spine_y'], rotation_angle)
                                poly_3d.append((eng_x, eng_y, z))
                                self.uvz_points[cat_key].append((station, cad_x - ref_x, z))
                        if poly_3d:
                            section_3d['geological_polys'][cat_key].append(poly_3d)
            
            self.sections_3d.append(section_3d)
            matched_count += 1
        
        print(f"  Sections matched: {matched_count}")
        return True
    
    def is_in_channel(self, u, v):
        """检查点是否在航道范围内（基于DMX边界）"""
        if not self.dmx_bounds:
            return True
        
        u_min = self.dmx_bounds.get('u_min', -float('inf'))
        u_max = self.dmx_bounds.get('u_max', float('inf'))
        v_min = self.dmx_bounds.get('v_min', -float('inf'))
        v_max = self.dmx_bounds.get('v_max', float('inf'))
        
        return u_min <= u <= u_max and v_min <= v <= v_max
    
    def build_grid_surfaces(self, u_step=200.0, v_step=5.0):
        print("\n=== Building Grid Surfaces ===")
        
        if not self.uvz_points['DMX']:
            print("  [ERROR] No DMX points found")
            return None, None, None
        
        # 计算DMX边界
        dmx_u_vals = [p[0] for p in self.uvz_points['DMX']]
        dmx_v_vals = [p[1] for p in self.uvz_points['DMX']]
        self.dmx_bounds = {
            'u_min': min(dmx_u_vals) - 10, 'u_max': max(dmx_u_vals) + 10,
            'v_min': min(dmx_v_vals) - 10, 'v_max': max(dmx_v_vals) + 10
        }
        
        u_min = min(dmx_u_vals)
        u_max = max(dmx_u_vals)
        v_min = min(dmx_v_vals)
        v_max = max(dmx_v_vals)
        
        print(f"  U range: {u_min:.1f} ~ {u_max:.1f} (station)")
        print(f"  V range: {v_min:.1f} ~ {v_max:.1f} (offset)")
        
        u_grid = np.arange(u_min, u_max + u_step, u_step)
        v_grid = np.arange(v_min, v_max + v_step, v_step)
        
        U, V = np.meshgrid(u_grid, v_grid)
        
        geo_grid = {'u': U, 'v': V}
        ribbon_grid = {'u': U, 'v': V}
        
        # 插值各层Z值
        for layer_key in ['DMX', 'OVERDREDGE', 'MUD', 'CLAY', 'SAND']:
            points = self.uvz_points[layer_key]
            if not points:
                geo_grid[layer_key] = np.full(U.shape, np.nan)
                ribbon_grid[layer_key] = np.full(U.shape, np.nan)
                continue
            
            pts = np.array([(p[0], p[1]) for p in points])
            z_vals = np.array([p[2] for p in points])
            
            Z = griddata(pts, z_vals, (U, V), method='linear')
            geo_grid[layer_key] = Z
            ribbon_grid[layer_key] = Z
        
        # 双重空间约束
        print("  Applying Double Space Constraint...")
        Z_DMX = geo_grid['DMX']
        Z_OVERDREDGE = geo_grid['OVERDREDGE']
        
        for layer_key in ['MUD', 'CLAY', 'SAND']:
            Z_layer = geo_grid[layer_key]
            if np.isnan(Z_layer).all():
                continue
            
            # Vertical Clamping: Z_final = max(min(Z_layer, Z_DMX), Z_OVERDREDGE)
            Z_clamped = np.copy(Z_layer)
            for i in range(Z_clamped.shape[0]):
                for j in range(Z_clamped.shape[1]):
                    if np.isnan(Z_clamped[i, j]):
                        continue
                    z_dmx = Z_DMX[i, j]
                    z_over = Z_OVERDREDGE[i, j]
                    if not np.isnan(z_dmx):
                        Z_clamped[i, j] = min(Z_clamped[i, j], z_dmx)
                    if not np.isnan(z_over):
                        Z_clamped[i, j] = max(Z_clamped[i, j], z_over)
            
            # Horizontal Masking
            for i in range(U.shape[0]):
                for j in range(U.shape[1]):
                    u, v = U[i, j], V[i, j]
                    if not self.is_in_channel(u, v):
                        Z_clamped[i, j] = np.nan
            
            geo_grid[layer_key] = Z_clamped
        
        return geo_grid, ribbon_grid, self.dmx_bounds
    
    def create_thick_ribbon_solid(self, msp, ribbon_grid, surface_key, layer_name, layer_color, 
                                   obj_material=None, thickness=RIBBON_THICKNESS, thickness_direction='down'):
        """
        创建有厚度的Ribbon实体
        
        Args:
            thickness: 厚度（米），默认2米
            thickness_direction: 'up' 向上加厚度，'down' 向下加厚度
        """
        u_grid = ribbon_grid['u']
        v_grid = ribbon_grid['v']
        z_surf = ribbon_grid[surface_key]
        
        rows, cols = u_grid.shape
        face_count = 0
        
        for i in range(rows - 1):
            for j in range(cols - 1):
                uvs = [(u_grid[i, j], v_grid[i, j]), (u_grid[i+1, j], v_grid[i+1, j]),
                       (u_grid[i+1, j+1], v_grid[i+1, j+1]), (u_grid[i, j+1], v_grid[i, j+1])]
                z_vals = [z_surf[i, j], z_surf[i+1, j], z_surf[i+1, j+1], z_surf[i, j+1]]
                
                if np.isnan(z_vals).any():
                    continue
                
                w_pts = [uv_to_world(u, v, self.spine_data) for u, v in uvs]
                
                # 根据厚度方向决定上下表面
                if thickness_direction == 'up':
                    # DMX: 向上加厚度
                    # 下表面（原始Z）
                    bot_face = [(p[0], p[1], z) for p, z in zip(w_pts, z_vals)]
                    # 上表面（Z + thickness）
                    top_face = [(p[0], p[1], z + thickness) for p, z in zip(w_pts, z_vals)]
                else:
                    # OVERBREAK: 向下加厚度
                    # 上表面（原始Z）
                    top_face = [(p[0], p[1], z) for p, z in zip(w_pts, z_vals)]
                    # 下表面（Z - thickness）
                    bot_face = [(p[0], p[1], z - thickness) for p, z in zip(w_pts, z_vals)]
                
                # 生成6个面构成闭合实体
                attr = {'color': layer_color}
                # 上表面
                msp.add_3dface(top_face, dxfattribs=attr)
                # 下表面（反向绕序）
                msp.add_3dface([bot_face[0], bot_face[3], bot_face[2], bot_face[1]], dxfattribs=attr)
                # 四个侧面
                msp.add_3dface([top_face[0], top_face[1], bot_face[1], bot_face[0]], dxfattribs=attr)
                msp.add_3dface([top_face[1], top_face[2], bot_face[2], bot_face[1]], dxfattribs=attr)
                msp.add_3dface([top_face[2], top_face[3], bot_face[3], bot_face[2]], dxfattribs=attr)
                msp.add_3dface([top_face[3], top_face[0], bot_face[0], bot_face[3]], dxfattribs=attr)
                
                if self.obj_exporter and obj_material:
                    all_verts = top_face + bot_face
                    v_idx = [self.obj_exporter.add_vertex(v[0], v[1], v[2]) - 1 for v in all_verts]
                    # 上表面
                    self.obj_exporter.add_face(obj_material, v_idx[:4], group=layer_name)
                    # 下表面
                    self.obj_exporter.add_face(obj_material, [v_idx[4], v_idx[7], v_idx[6], v_idx[5]], group=layer_name)
                    # 四个侧面
                    self.obj_exporter.add_face(obj_material, [v_idx[0], v_idx[1], v_idx[5], v_idx[4]], group=layer_name)
                    self.obj_exporter.add_face(obj_material, [v_idx[1], v_idx[2], v_idx[6], v_idx[5]], group=layer_name)
                    self.obj_exporter.add_face(obj_material, [v_idx[2], v_idx[3], v_idx[7], v_idx[6]], group=layer_name)
                    self.obj_exporter.add_face(obj_material, [v_idx[3], v_idx[0], v_idx[4], v_idx[7]], group=layer_name)
                
                face_count += 6
        
        direction_str = "向上" if thickness_direction == 'up' else "向下"
        print(f"    {layer_name} Thick Solid: {face_count} 3DFACEs (thickness={thickness}m, {direction_str})")
    
    def create_closed_solid_mesh(self, msp, geo_grid, z_top_key, z_bot_key, layer_color, layer_name, obj_material=None):
        u_grid = geo_grid['u']
        v_grid = geo_grid['v']
        z_top = geo_grid[z_top_key]
        z_bot = geo_grid[z_bot_key]
        
        rows, cols = u_grid.shape
        face_count = 0
        skip_count = 0
        
        for i in range(rows - 1):
            for j in range(cols - 1):
                uvs = [(u_grid[i, j], v_grid[i, j]), (u_grid[i+1, j], v_grid[i+1, j]),
                       (u_grid[i+1, j+1], v_grid[i+1, j+1]), (u_grid[i, j+1], v_grid[i, j+1])]
                z_t = [z_top[i, j], z_top[i+1, j], z_top[i+1, j+1], z_top[i, j+1]]
                z_b = [z_bot[i, j], z_bot[i+1, j], z_bot[i+1, j+1], z_bot[i, j+1]]
                
                if np.isnan(z_t).any() or np.isnan(z_b).any():
                    skip_count += 1
                    continue
                if np.allclose(z_t, z_b, atol=0.01):
                    skip_count += 1
                    continue
                
                w_pts = [uv_to_world(u, v, self.spine_data) for u, v in uvs]
                top_face = [(p[0], p[1], z) for p, z in zip(w_pts, z_t)]
                bot_face = [(p[0], p[1], z) for p, z in zip(w_pts, z_b)]
                
                attr = {'color': layer_color}
                msp.add_3dface(top_face, dxfattribs=attr)
                msp.add_3dface([bot_face[0], bot_face[3], bot_face[2], bot_face[1]], dxfattribs=attr)
                msp.add_3dface([top_face[0], top_face[1], bot_face[1], bot_face[0]], dxfattribs=attr)
                msp.add_3dface([top_face[1], top_face[2], bot_face[2], bot_face[1]], dxfattribs=attr)
                msp.add_3dface([top_face[2], top_face[3], bot_face[3], bot_face[2]], dxfattribs=attr)
                msp.add_3dface([top_face[3], top_face[0], bot_face[0], bot_face[3]], dxfattribs=attr)
                
                if self.obj_exporter and obj_material:
                    all_verts = top_face + bot_face
                    v_idx = [self.obj_exporter.add_vertex(v[0], v[1], v[2]) - 1 for v in all_verts]
                    self.obj_exporter.add_face(obj_material, v_idx[:4], group=layer_name)
                    self.obj_exporter.add_face(obj_material, [v_idx[4], v_idx[7], v_idx[6], v_idx[5]], group=layer_name)
                    self.obj_exporter.add_face(obj_material, [v_idx[0], v_idx[1], v_idx[5], v_idx[4]], group=layer_name)
                    self.obj_exporter.add_face(obj_material, [v_idx[1], v_idx[2], v_idx[6], v_idx[5]], group=layer_name)
                    self.obj_exporter.add_face(obj_material, [v_idx[2], v_idx[3], v_idx[7], v_idx[6]], group=layer_name)
                    self.obj_exporter.add_face(obj_material, [v_idx[3], v_idx[0], v_idx[4], v_idx[7]], group=layer_name)
                face_count += 6
        
        print(f"    {layer_name} Solid: {face_count} 3DFACEs, {skip_count} skipped")
    
    def add_station_markers_as_lines(self, msp):
        """
        添加桩号标记实体长方体（平行断面方向）+ 桩号数字实体
        
        V17修订版改进：
        - 桩号线：0.1m x 0.1m横截面的实体长方体，长度根据DMX宽度计算
        - 位置：DMX顶部以上
        - 桩号数字：直立在桩号线上，方向平行于桩号线
        - 使用真实世界坐标，保留弯道形状
        """
        if not self.obj_exporter:
            return
        
        print("\n=== Adding Station Marker Solid Boxes ===")
        marker_count = 0
        text_count = 0
        
        # 获取最小桩号值作为基准
        all_stations = sorted([s['station_value'] for s in self.sections_3d])
        if not all_stations:
            print("  [WARNING] No stations found")
            return
        base_station = all_stations[0]
        
        for section in self.sections_3d:
            station = section['station_value']
            dmx_3d = section.get('dmx_3d', [])
            
            if station not in self.spine_data:
                continue
            
            # 桩号线间隔过滤：只处理每200米的桩号
            station_offset = station - base_station
            if station_offset % STATION_LINE_INTERVAL != 0:
                continue
            
            spine = self.spine_data[station]
            
            # 计算断面方向（垂直于脊梁线切向）
            tangent_angle = spine['tangent_angle']
            cross_angle = tangent_angle + math.pi / 2  # 断面方向
            
            # 桩号线中心点位置（脊梁线中心，真实世界坐标）
            center_x = spine['spine_x']
            center_y = spine['spine_y']
            
            # Z值：使用DMX最高点 + 向上偏移
            if len(dmx_3d) > 0:
                dmx_z_values = [pt[2] for pt in dmx_3d]
                base_z = max(dmx_z_values)  # DMX最高点
            else:
                continue
            
            # 桩号线Z位置：DMX顶部上方
            line_z = base_z + STATION_LINE_OFFSET_Z
            
            # 计算DMX宽度（左右距离）
            if len(dmx_3d) > 0:
                # 计算DMX点相对于脊梁线的垂直距离
                dmx_distances = []
                for pt in dmx_3d:
                    # pt[0], pt[1] 是真实世界坐标
                    dx = pt[0] - center_x
                    dy = pt[1] - center_y
                    # 计算沿断面方向的距离
                    dist = dx * math.cos(cross_angle) + dy * math.sin(cross_angle)
                    dmx_distances.append(dist)
                dmx_width = max(dmx_distances) - min(dmx_distances)
            else:
                dmx_width = 50.0  # 默认宽度
            
            # 桩号线长度：DMX宽度 + 额外长度
            line_length = dmx_width + STATION_LINE_EXTRA_LENGTH
            
            # 创建桩号线实体长方体
            self._create_station_line_box(msp, center_x, center_y, line_z,
                                          line_length, cross_angle, station)
            marker_count += 1
            
            # 添加桩号数字实体（直立在桩号线上）
            station_text = format_station_number(station)
            
            # 数字实体位置：桩号线正方向一端上方，直立
            text_x = center_x + (line_length / 2.0 + STATION_TEXT_OFFSET) * math.cos(cross_angle)
            text_y = center_y + (line_length / 2.0 + STATION_TEXT_OFFSET) * math.sin(cross_angle)
            text_z = line_z + STATION_TEXT_HEIGHT / 2.0
            
            # 为每个数字创建直立实体 - 正方向端
            self._add_station_number_blocks_upright(msp, station_text, text_x, text_y, text_z, cross_angle)
            text_count += 1
            
            # 数字实体位置：桩号线负方向一端上方，直立（翻转180度）
            text_x2 = center_x - (line_length / 2.0 + STATION_TEXT_OFFSET) * math.cos(cross_angle)
            text_y2 = center_y - (line_length / 2.0 + STATION_TEXT_OFFSET) * math.sin(cross_angle)
            text_z2 = line_z + STATION_TEXT_HEIGHT / 2.0
            
            # 翻转180度，使数字从另一端也能正确读取
            flipped_angle = cross_angle + math.pi
            self._add_station_number_blocks_upright(msp, station_text, text_x2, text_y2, text_z2, flipped_angle)
            text_count += 1
        
        print(f"  Station line boxes added: {marker_count}")
        print(f"  Station number blocks added: {text_count}")
    
    def _create_station_line_box(self, msp, cx, cy, cz, length, cross_angle, station_value):
        """
        创建桩号线实体长方体（0.1m x 0.1m横截面）
        
        Args:
            cx, cy, cz: 长方体中心位置（真实世界坐标）
            length: 长度（沿断面方向）
            cross_angle: 断面方向角度（弧度）
            station_value: 桩号值
        """
        # 横截面尺寸
        cross_size = STATION_LINE_CROSS_SECTION  # 0.1m x 0.1m
        half_length = length / 2.0
        half_cross = cross_size / 2.0
        
        cos_a = math.cos(cross_angle)
        sin_a = math.sin(cross_angle)
        
        # 8个顶点（局部坐标）
        # 长方体沿断面方向延伸，横截面垂直于断面方向
        local_verts = [
            # 底面（Z = cz - half_cross）
            (-half_length, -half_cross, -half_cross),
            (half_length, -half_cross, -half_cross),
            (half_length, half_cross, -half_cross),
            (-half_length, half_cross, -half_cross),
            # 顶面（Z = cz + half_cross）
            (-half_length, -half_cross, half_cross),
            (half_length, -half_cross, half_cross),
            (half_length, half_cross, half_cross),
            (-half_length, half_cross, half_cross),
        ]
        
        # 旋转并平移到世界坐标
        # 旋转：长方体的长度方向沿断面方向（cross_angle）
        world_verts = []
        for lx, ly, lz in local_verts:
            # lx沿断面方向，ly垂直于断面方向（水平），lz垂直（Z轴）
            wx = lx * cos_a - ly * sin_a + cx
            wy = lx * sin_a + ly * cos_a + cy
            wz = lz + cz
            world_verts.append((wx, wy, wz))
        
        # 添加到OBJ
        if self.obj_exporter:
            v_idx = [self.obj_exporter.add_vertex(v[0], v[1], v[2]) - 1 for v in world_verts]
            
            # 6个面
            # 底面
            self.obj_exporter.add_face('STATION_LINE', [v_idx[0], v_idx[1], v_idx[2], v_idx[3]], 'STATION_LINES')
            # 顶面
            self.obj_exporter.add_face('STATION_LINE', [v_idx[4], v_idx[5], v_idx[6], v_idx[7]], 'STATION_LINES')
            # 四个侧面
            self.obj_exporter.add_face('STATION_LINE', [v_idx[0], v_idx[1], v_idx[5], v_idx[4]], 'STATION_LINES')
            self.obj_exporter.add_face('STATION_LINE', [v_idx[1], v_idx[2], v_idx[6], v_idx[5]], 'STATION_LINES')
            self.obj_exporter.add_face('STATION_LINE', [v_idx[2], v_idx[3], v_idx[7], v_idx[6]], 'STATION_LINES')
            self.obj_exporter.add_face('STATION_LINE', [v_idx[3], v_idx[0], v_idx[4], v_idx[7]], 'STATION_LINES')
        
        # 添加到DXF（红色实体）
        attr = {'color': 1}  # 红色
        
        # 底面
        msp.add_3dface([world_verts[0], world_verts[1], world_verts[2], world_verts[3]], dxfattribs=attr)
        # 顶面
        msp.add_3dface([world_verts[4], world_verts[5], world_verts[6], world_verts[7]], dxfattribs=attr)
        # 四个侧面
        msp.add_3dface([world_verts[0], world_verts[1], world_verts[5], world_verts[4]], dxfattribs=attr)
        msp.add_3dface([world_verts[1], world_verts[2], world_verts[6], world_verts[5]], dxfattribs=attr)
        msp.add_3dface([world_verts[2], world_verts[3], world_verts[7], world_verts[6]], dxfattribs=attr)
        msp.add_3dface([world_verts[3], world_verts[0], world_verts[4], world_verts[7]], dxfattribs=attr)
    
    # 七段数码管笔画定义（数字0-9）
    # 段索引: 0=上横, 1=右上竖, 2=右下竖, 3=下横, 4=左下竖, 5=左上竖, 6=中横
    DIGIT_STROKES = {
        '0': [0, 1, 2, 3, 4, 5],      # 6段，缺中横
        '1': [1, 2],                   # 2段，右竖
        '2': [0, 1, 6, 4, 3],          # 5段
        '3': [0, 1, 6, 2, 3],          # 5段
        '4': [5, 6, 1, 2],             # 4段
        '5': [0, 5, 6, 2, 3],          # 5段
        '6': [0, 5, 4, 3, 2, 6],       # 6段
        '7': [0, 1, 2],                # 3段
        '8': [0, 1, 2, 3, 4, 5, 6],    # 7段全亮
        '9': [0, 1, 2, 3, 5, 6],       # 6段
    }
    
    def _get_stroke_coords(self, segment_idx, char_width, char_height):
        """
        获取七段数码管中某一段的局部坐标（起点和终点）
        
        返回: (p1, p2) 两个端点的局部坐标 (lx, lz)
        """
        w = char_width
        h = char_height
        sw = char_width * 0.15  # 笔画宽度
        
        # 段位置定义（局部坐标，lx为水平，lz为垂直）
        # 中心在(0, 0)，高度范围[-h/2, h/2]，宽度范围[-w/2, w/2]
        hw = w / 2.0
        hh = h / 2.0
        
        if segment_idx == 0:  # 上横
            return ((-hw + sw/2, hh - sw/2), (hw - sw/2, hh - sw/2))
        elif segment_idx == 1:  # 右上竖
            return ((hw - sw/2, hh - sw/2), (hw - sw/2, 0))
        elif segment_idx == 2:  # 右下竖
            return ((hw - sw/2, 0), (hw - sw/2, -hh + sw/2))
        elif segment_idx == 3:  # 下横
            return ((-hw + sw/2, -hh + sw/2), (hw - sw/2, -hh + sw/2))
        elif segment_idx == 4:  # 左下竖
            return ((-hw + sw/2, 0), (-hw + sw/2, -hh + sw/2))
        elif segment_idx == 5:  # 左上竖
            return ((-hw + sw/2, hh - sw/2), (-hw + sw/2, 0))
        elif segment_idx == 6:  # 中横
            return ((-hw + sw/2, 0), (hw - sw/2, 0))
        return None
    
    def _add_station_number_blocks_upright(self, msp, text, x, y, z, rotation_angle):
        """
        为桩号数字创建七段数码管风格的笔画面片（扁平，无厚度）
        
        Args:
            text: 桩号数字字符串（如"00500"）
            x, y, z: 文字底部中心位置
            rotation_angle: 旋转角度（弧度，平行于桩号线方向）
        """
        # 数字参数
        char_width = STATION_TEXT_WIDTH   # 宽度
        char_height = STATION_TEXT_HEIGHT  # 高度
        stroke_width = char_width * 0.05   # 笔画宽度（细）
        char_spacing = char_width * 1.2    # 字符间距
        
        # 计算总宽度
        total_width = len(text) * char_spacing
        start_offset = -total_width / 2.0
        
        cos_a = math.cos(rotation_angle)
        sin_a = math.sin(rotation_angle)
        
        for i, char in enumerate(text):
            if char not in self.DIGIT_STROKES:
                continue
            
            # 计算每个数字的位置（沿旋转方向排列）
            offset = start_offset + i * char_spacing + char_width / 2.0
            
            # 沿旋转方向偏移
            char_x = x + offset * cos_a
            char_y = y + offset * sin_a
            char_z = z  # 直立在桩号线上
            
            # 获取该数字的笔画索引
            strokes = self.DIGIT_STROKES[char]
            
            # 绘制每个笔画面片
            for seg_idx in strokes:
                coords = self._get_stroke_coords(seg_idx, char_width, char_height)
                if coords:
                    self._draw_flat_stroke_face(msp, coords, char_x, char_y, char_z,
                                                stroke_width, rotation_angle)
    
    def _draw_flat_stroke_face(self, msp, stroke_coords, cx, cy, cz, stroke_width, rotation_angle):
        """
        绘制单个笔画的扁平面片（垂直于地面，平行于桩号线方向）
        
        Args:
            stroke_coords: 笔画起点和终点 ((lx1, lz1), (lx2, lz2))
            cx, cy, cz: 字符中心位置
            stroke_width: 笔画宽度
            rotation_angle: 旋转角度
        """
        (lx1, lz1), (lx2, lz2) = stroke_coords
        sw = stroke_width / 2.0
        
        cos_a = math.cos(rotation_angle)
        sin_a = math.sin(rotation_angle)
        
        # 计算笔画方向向量
        dx = lx2 - lx1
        dz = lz2 - lz1
        length = math.sqrt(dx*dx + dz*dz)
        if length < 0.001:
            return
        
        # 笔画垂直方向（在XZ平面内）
        perp_x = -dz / length
        perp_z = dx / length
        
        # 构建4个顶点（扁平面片，垂直于地面）
        # 面片平行于桩号线方向（Y方向延伸极小厚度）
        thickness = 0.01  # 极小厚度，避免渲染问题
        
        # 4个顶点：沿笔画方向两端，向两侧偏移笔画宽度
        local_verts = [
            (lx1 + perp_x * sw, -thickness, lz1 + perp_z * sw),
            (lx1 - perp_x * sw, -thickness, lz1 - perp_z * sw),
            (lx2 - perp_x * sw, -thickness, lz2 - perp_z * sw),
            (lx2 + perp_x * sw, -thickness, lz2 + perp_z * sw),
            # 正面（极小厚度偏移）
            (lx1 + perp_x * sw, thickness, lz1 + perp_z * sw),
            (lx1 - perp_x * sw, thickness, lz1 - perp_z * sw),
            (lx2 - perp_x * sw, thickness, lz2 - perp_z * sw),
            (lx2 + perp_x * sw, thickness, lz2 + perp_z * sw),
        ]
        
        # 旋转并平移到世界坐标
        world_verts = []
        for lx, ly, lz in local_verts:
            # lx沿断面方向旋转，ly垂直于断面方向（极小厚度），lz沿Z轴
            wx = lx * cos_a - ly * sin_a + cx
            wy = lx * sin_a + ly * cos_a + cy
            wz = lz + cz
            world_verts.append((wx, wy, wz))
        
        # 添加到OBJ（只添加正面和背面两个面）
        if self.obj_exporter:
            v_idx = [self.obj_exporter.add_vertex(v[0], v[1], v[2]) - 1 for v in world_verts]
            
            # 正面
            self.obj_exporter.add_face('STATION_LINE', [v_idx[4], v_idx[5], v_idx[6], v_idx[7]], 'STATION_NUMBERS')
            # 背面
            self.obj_exporter.add_face('STATION_LINE', [v_idx[0], v_idx[1], v_idx[2], v_idx[3]], 'STATION_NUMBERS')
        
        # 添加到DXF（红色面片）
        attr = {'color': 1}  # 红色
        
        # 正面
        msp.add_3dface([world_verts[4], world_verts[5], world_verts[6], world_verts[7]], dxfattribs=attr)
        # 背面
        msp.add_3dface([world_verts[0], world_verts[1], world_verts[2], world_verts[3]], dxfattribs=attr)
    
    def generate_bim(self, output_dxf, output_obj=None, output_mtl=None):
        print("\n=== Generating BIM Model V17 ===")
        print("  Features: Thick Ribbon(2m) + Station Lines + Semi-transparent")
        print("  DMX: thickness UPWARD, OVERBREAK: thickness DOWNWARD")
        print(f"  Output DXF: {output_dxf}")
        
        if output_obj and output_mtl:
            self.obj_exporter = OBJExporterV17(output_obj, output_mtl)
            print(f"  Output OBJ: {output_obj}")
            print(f"  Output MTL: {output_mtl}")
        
        if not self.load_and_parse_data():
            print("  [ERROR] Data loading failed")
            return False
        
        geo_grid, ribbon_grid, _ = self.build_grid_surfaces()
        if geo_grid is None:
            print("  [ERROR] Grid building failed")
            return False
        
        print("\n=== Creating DXF Model ===")
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()
        
        # 创建图层
        doc.layers.new(name='DMX_SOLID', dxfattribs={'color': 5})
        doc.layers.new(name='OVERBREAK_SOLID', dxfattribs={'color': 1})
        doc.layers.new(name='STATION_LINES', dxfattribs={'color': 1})  # 红色
        doc.layers.new(name='STATION_NUMBERS', dxfattribs={'color': 1})  # 红色
        for cat_key, cat_info in LAYER_CATEGORIES.items():
            doc.layers.new(name=f'GEO_{cat_key}', dxfattribs={'color': cat_info['color']})
        
        # DMX设计线厚度实体（厚度2米，向上加厚度）
        print("  Generating DMX Thick Solid (thickness UPWARD)...")
        self.create_thick_ribbon_solid(msp, ribbon_grid, 'DMX', 'DMX_SOLID', 5, 'DMX_SOLID', 
                                        RIBBON_THICKNESS, thickness_direction='up')
        
        # 超挖线厚度实体（厚度2米，向下加厚度）
        print("  Generating Overbreak Thick Solid (thickness DOWNWARD)...")
        self.create_thick_ribbon_solid(msp, ribbon_grid, 'OVERDREDGE', 'OVERBREAK_SOLID', 1, 'OVERBREAK_SOLID', 
                                        RIBBON_THICKNESS, thickness_direction='down')
        
        # 三类地质层实体
        print("  Generating geological volumes...")
        self.create_closed_solid_mesh(msp, geo_grid, 'DMX', 'MUD', 1, 'GEO_MUD', 'GEO_MUD')
        self.create_closed_solid_mesh(msp, geo_grid, 'MUD', 'CLAY', 2, 'GEO_CLAY', 'GEO_CLAY')
        self.create_closed_solid_mesh(msp, geo_grid, 'CLAY', 'SAND', 3, 'GEO_SAND', 'GEO_SAND')
        self.create_closed_solid_mesh(msp, geo_grid, 'SAND', 'OVERDREDGE', 3, 'GEO_SAND', 'GEO_SAND')
        
        # 添加桩号线和文本
        self.add_station_markers_as_lines(msp)
        
        doc.saveas(output_dxf)
        print(f"\n  DXF model saved: {output_dxf}")
        
        if self.obj_exporter:
            print("\n=== Exporting OBJ/MTL ===")
            self.obj_exporter.export()
        
        return True


if __name__ == "__main__":
    meta_file = r"D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json"
    match_file = r"D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json"
    output_dxf = r"D:\断面算量平台\测试文件\Channel_Geology_Model_V17.dxf"
    output_obj = r"D:\断面算量平台\测试文件\Channel_Geology_Model_V17.obj"
    output_mtl = r"D:\断面算量平台\测试文件\Channel_Geology_Model_V17.mtl"
    
    print("=" * 60)
    print("航道三维地质模型构建器 V17 (修订版)")
    print("核心改进: 桩号线实体化 + DMX向上厚度 + 超挖向下厚度 + 厚度2米")
    print("  1. DMX: 向上加厚度 (Z + 2m)")
    print("  2. OVERBREAK: 向下加厚度 (Z - 2m)")
    print("  3. Station Lines: 1m x 1m横截面实体长方体，放在DMX以上")
    print("  4. Station Texts: 直立在桩号线上，笔画变细，方向平行")
    print("=" * 60)
    
    generator = ChannelBIMGeneratorV17(meta_file, match_file)
    success = generator.generate_bim(output_dxf, output_obj, output_mtl)
    
    if success:
        print("\n[SUCCESS] V17 Model generation completed!")
    else:
        print("\n[FAILED] V17 Model generation failed!")