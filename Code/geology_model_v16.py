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
    'STATION_MARKER': {
        'color_rgb': (1.0, 1.0, 0.0),  # 黄色桩号标记
        'ambient': 0.3,
        'diffuse': 0.9,
        'specular': 0.5,
        'illum': 2,
        'opacity': 1.0,
    },
}

# DMX/超挖厚度参数
RIBBON_THICKNESS = 5.0  # 米

# 桩号标记尺寸
MARKER_SIZE = 10.0  # 米（立方体边长）


def categorize_layer(layer_name: str) -> Optional[str]:
    for cat_key, cat_info in LAYER_CATEGORIES.items():
        for kw in cat_info['keywords']:
            if kw in layer_name:
                return cat_key
    return None


def transform_to_spine_aligned(cad_x, cad_y, ref_x, ref_y, spine_x, spine_y, rotation_angle):
    z = cad_y - ref_y
    dx = cad_x - ref_x
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    eng_x = spine_x + dx * cos_a
    eng_y = spine_y + dx * sin_a
    return eng_x, eng_y, z


def uv_to_world(u, v, spine_data):
    closest_station = min(spine_data.keys(), key=lambda k: abs(k - u))
    spine = spine_data[closest_station]
    angle_rad = spine['tangent_angle'] + math.pi / 2
    world_x = spine['spine_x'] + v * math.cos(angle_rad)
    world_y = spine['spine_y'] + v * math.sin(angle_rad)
    return world_x, world_y


class OBJExporterV16:
    """V16 OBJ导出器 - 支持半透明材质、桩号实体化、厚度化Ribbon"""
    
    def __init__(self, output_obj, output_mtl):
        self.output_obj = output_obj
        self.output_mtl = output_mtl
        self.vertices = []
        self.faces = []
        self.groups = {}
        self.station_markers = []  # 桩号标记数据
    
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
    
    def add_cube(self, center_x, center_y, center_z, size, material, group=None):
        """
        添加一个立方体（用于桩号标记实体化）
        
        Args:
            center_x, center_y, center_z: 立方体中心坐标
            size: 立方体边长
            material: OBJ材质名称
            group: OBJ组名称
        """
        half = size / 2.0
        
        # 8个顶点
        v0 = self.add_vertex(center_x - half, center_y - half, center_z - half) - 1
        v1 = self.add_vertex(center_x + half, center_y - half, center_z - half) - 1
        v2 = self.add_vertex(center_x + half, center_y + half, center_z - half) - 1
        v3 = self.add_vertex(center_x - half, center_y + half, center_z - half) - 1
        v4 = self.add_vertex(center_x - half, center_y - half, center_z + half) - 1
        v5 = self.add_vertex(center_x + half, center_y - half, center_z + half) - 1
        v6 = self.add_vertex(center_x + half, center_y + half, center_z + half) - 1
        v7 = self.add_vertex(center_x - half, center_y + half, center_z + half) - 1
        
        # 6个面（每个面4个顶点）
        # 底面 (z - half)
        self.add_face(material, [v0, v1, v2, v3], group)
        # 顶面 (z + half)
        self.add_face(material, [v4, v5, v6, v7], group)
        # 前面 (y - half)
        self.add_face(material, [v0, v1, v5, v4], group)
        # 后面 (y + half)
        self.add_face(material, [v2, v3, v7, v6], group)
        # 左面 (x - half)
        self.add_face(material, [v0, v3, v7, v4], group)
        # 右面 (x + half)
        self.add_face(material, [v1, v2, v6, v5], group)
    
    def add_station_marker_cube(self, station_value, x, y, z, size=MARKER_SIZE):
        """添加桩号标记立方体"""
        self.station_markers.append({
            'station': station_value,
            'x': x,
            'y': y,
            'z': z,
            'size': size
        })
        self.add_cube(x, y, z, size, 'STATION_MARKER', 'STATION_MARKERS')
    
    def write_mtl(self):
        with open(self.output_mtl, 'w', encoding='utf-8') as f:
            f.write("# MTL Material Library for Channel Geology Model V16\n")
            f.write("# Features: DMX/OVERBREAK semi-transparent + Station Markers\n\n")
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
            f.write("# OBJ File for Channel Geology Model V16\n")
            f.write("# Features: Thick Ribbon(5m) + Station Marker Cubes + Semi-transparent\n")
            f.write(f"# Vertices: {len(self.vertices)}\n")
            f.write(f"# Faces: {len(self.faces)}\n")
            f.write(f"# Station Markers: {len(self.station_markers)} cubes\n\n")
            f.write(f"mtllib {os.path.basename(self.output_mtl)}\n\n")
            
            # 写入桩号标记信息作为注释
            if self.station_markers:
                f.write("# Station Marker Locations (cube centers)\n")
                for marker in self.station_markers:
                    f.write(f"# Station {marker['station']:.1f}m: ({marker['x']:.2f}, {marker['y']:.2f}, {marker['z']:.2f})\n")
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
                    mat, v_list = self.faces[fi]
                    if mat != current_material:
                        f.write(f"usemtl {mat}\n")
                        current_material = mat
                    if len(v_list) == 4:
                        f.write(f"f {v_list[0]} {v_list[1]} {v_list[2]} {v_list[3]}\n")
                    elif len(v_list) == 3:
                        f.write(f"f {v_list[0]} {v_list[1]} {v_list[2]}\n")
    
    def export(self):
        self.write_mtl()
        self.write_obj()
        print(f"  OBJ exported: {self.output_obj}")
        print(f"  MTL exported: {self.output_mtl}")
        print(f"  Total vertices: {len(self.vertices)}")
        print(f"  Total faces: {len(self.faces)}")
        print(f"  Station marker cubes: {len(self.station_markers)}")


class ChannelBIMGeneratorV16:
    """V16生成器 - 桩号实体化 + 超挖半透明 + DMX/超挖厚度5米"""
    
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
            v_values = []
            for pt in dmx_points:
                eng_x, eng_y, z = transform_to_spine_aligned(pt[0], pt[1], ref_x, ref_y, spine['spine_x'], spine['spine_y'], rotation_angle)
                v = pt[0] - ref_x
                v_values.append(v)
                self.uvz_points['DMX'].append([station, v, z])
                section_3d['dmx_3d'].append([eng_x, eng_y, z])
            
            if v_values:
                self.dmx_bounds[station] = (min(v_values), max(v_values))
            
            overbreak_points = sec.get('overbreak_points', [])
            for ob_line in overbreak_points:
                for pt in ob_line:
                    eng_x, eng_y, z = transform_to_spine_aligned(pt[0], pt[1], ref_x, ref_y, spine['spine_x'], spine['spine_y'], rotation_angle)
                    v = pt[0] - ref_x
                    self.uvz_points['OVERDREDGE'].append([station, v, z])
                    section_3d['overbreak_3d'].append([eng_x, eng_y, z])
            
            fill_boundaries = sec.get('fill_boundaries', {})
            for layer_name, boundaries in fill_boundaries.items():
                cat_key = categorize_layer(layer_name)
                if cat_key is None:
                    continue
                for boundary in boundaries:
                    if len(boundary) < 3:
                        continue
                    poly_3d = []
                    for pt in boundary:
                        eng_x, eng_y, z = transform_to_spine_aligned(pt[0], pt[1], ref_x, ref_y, spine['spine_x'], spine['spine_y'], rotation_angle)
                        v = pt[0] - ref_x
                        self.uvz_points[cat_key].append([station, v, z])
                        poly_3d.append([eng_x, eng_y, z])
                    if cat_key not in section_3d['geological_polys']:
                        section_3d['geological_polys'][cat_key] = []
                    section_3d['geological_polys'][cat_key].append({'layer_name': layer_name, 'points': np.array(poly_3d)})
            
            self.sections_3d.append(section_3d)
            matched_count += 1
        
        print(f"  Sections matched: {matched_count}")
        for key, pts in self.uvz_points.items():
            print(f"  {key} UVZ points: {len(pts)}")
        print(f"  DMX bounds recorded: {len(self.dmx_bounds)} stations")
        return matched_count > 0
    
    def is_in_channel(self, u, v):
        closest_station = min(self.dmx_bounds.keys(), key=lambda k: abs(k - u))
        v_min, v_max = self.dmx_bounds.get(closest_station, (-9999, 9999))
        tolerance = 1.0
        return (v_min - tolerance) <= v <= (v_max + tolerance)
    
    def build_grid_surfaces(self, u_step=25.0, v_step=5.0):
        print("\n=== Building Grid Surfaces with Double Space Constraint ===")
        print(f"  U step: {u_step}m, V step: {v_step}m")
        
        if len(self.uvz_points['DMX']) == 0:
            print("  [ERROR] No DMX points available")
            return None, None, None
        
        all_points = np.array(self.uvz_points['DMX'])
        u_min, u_max = np.min(all_points[:, 0]), np.max(all_points[:, 0])
        v_min, v_max = np.min(all_points[:, 1]), np.max(all_points[:, 1])
        
        print(f"  U range: {u_min} - {u_max}")
        print(f"  V range (geo): {v_min} - {v_max}")
        
        grid_u, grid_v = np.mgrid[u_min:u_max:u_step, v_min:v_max:v_step]
        
        ribbon_margin = 1.0
        v_min_ribbon = v_min - ribbon_margin
        v_max_ribbon = v_max + ribbon_margin
        print(f"  V range (ribbon): {v_min_ribbon} - {v_max_ribbon} (expanded by 1m)")
        grid_u_ribbon, grid_v_ribbon = np.mgrid[u_min:u_max:u_step, v_min_ribbon:v_max_ribbon:v_step]
        
        surfaces = {}
        for key in ['DMX', 'OVERDREDGE', 'MUD', 'CLAY', 'SAND']:
            if len(self.uvz_points[key]) > 0:
                pts = np.array(self.uvz_points[key])
                surfaces[key] = griddata((pts[:, 0], pts[:, 1]), pts[:, 2], (grid_u, grid_v), method='linear')
            else:
                surfaces[key] = np.full_like(grid_u, np.nan)
        
        ribbon_surfaces = {}
        for key in ['DMX', 'OVERDREDGE']:
            if len(self.uvz_points[key]) > 0:
                pts = np.array(self.uvz_points[key])
                ribbon_surfaces[key] = griddata((pts[:, 0], pts[:, 1]), pts[:, 2], (grid_u_ribbon, grid_v_ribbon), method='linear')
            else:
                ribbon_surfaces[key] = np.full_like(grid_u_ribbon, np.nan)
        
        if np.isnan(surfaces['OVERDREDGE']).all():
            print("  [WARN] No overbreak data, using DMX - 15m as fallback")
            surfaces['OVERDREDGE'] = surfaces['DMX'] - 15.0
            ribbon_surfaces['OVERDREDGE'] = ribbon_surfaces['DMX'] - 15.0
        
        # 双重空间约束
        print("\n=== Applying Double Space Constraint ===")
        Z_DMX = surfaces['DMX']
        Z_OVER = surfaces['OVERDREDGE']
        
        clamped_count = 0
        for key in ['MUD', 'CLAY', 'SAND']:
            Z_orig = surfaces[key]
            mask_nan = np.isnan(Z_orig)
            if np.any(mask_nan):
                Z_orig[mask_nan] = Z_OVER[mask_nan]
            Z_clamped = np.maximum(np.minimum(Z_orig, Z_DMX), Z_OVER)
            clamped_mask = (Z_orig != Z_clamped) & ~np.isnan(Z_orig)
            clamped_count += np.sum(clamped_mask)
            surfaces[key] = Z_clamped
            print(f"    {key}: {np.sum(clamped_mask)} points clamped vertically")
        
        print(f"  Total vertical clamping: {clamped_count} points")
        
        rows, cols = grid_u.shape
        masked_count = 0
        for i in range(rows):
            for j in range(cols):
                u = grid_u[i, j]
                v = grid_v[i, j]
                if not self.is_in_channel(u, v):
                    for key in ['MUD', 'CLAY', 'SAND']:
                        if not np.isnan(surfaces[key][i, j]):
                            surfaces[key][i, j] = np.nan
                            masked_count += 1
        
        print(f"  Horizontal masking: {masked_count} points outside channel")
        
        Z_MUD = surfaces['MUD']
        Z_CLAY = np.minimum(Z_MUD, surfaces['CLAY'])
        Z_SAND = np.minimum(Z_CLAY, surfaces['SAND'])
        Z_OVER_FINAL = np.minimum(Z_SAND, Z_OVER)
        
        valid_count = np.sum(~np.isnan(Z_DMX))
        print(f"  Valid grid points after constraints: {valid_count}")
        
        geo_grid = {
            'u': grid_u, 'v': grid_v,
            'DMX': Z_DMX, 'MUD': Z_MUD, 'CLAY': Z_CLAY, 'SAND': Z_SAND, 'OVERDREDGE': Z_OVER_FINAL
        }
        ribbon_grid = {
            'u': grid_u_ribbon, 'v': grid_v_ribbon,
            'DMX': ribbon_surfaces['DMX'], 'OVERDREDGE': ribbon_surfaces['OVERDREDGE']
        }
        
        return geo_grid, ribbon_grid, None
    
    def create_thick_ribbon_solid(self, msp, ribbon_grid, surface_key, layer_name, layer_color, obj_material=None, thickness=RIBBON_THICKNESS):
        """
        创建有厚度的Ribbon实体（从单层曲面变成双层有厚度的实体）
        
        Args:
            thickness: 厚度（米），默认5米
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
        
        print(f"    {layer_name} Thick Solid: {face_count} 3DFACEs (thickness={thickness}m)")
    
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
    
    def add_station_markers_as_cubes(self):
        """
        添加桩号标记立方体（实体化）
        
        位置规则：
        - X, Y: 使用脊梁线中心点（航道中心线位置）
        - Z: 使用DMX最低点（航道底部）
        """
        if not self.obj_exporter:
            return
        
        print("\n=== Adding Station Marker Cubes ===")
        marker_count = 0
        
        for section in self.sections_3d:
            station = section['station_value']
            dmx_3d = section.get('dmx_3d', [])
            
            if station not in self.spine_data:
                continue
            
            # 使用脊梁线中心点作为桩号标记位置（航道中心线）
            spine = self.spine_data[station]
            marker_x = spine['spine_x']
            marker_y = spine['spine_y']
            
            # Z值：使用DMX的最低点（航道底部）
            if len(dmx_3d) > 0:
                dmx_z_values = [pt[2] for pt in dmx_3d]
                marker_z = min(dmx_z_values)  # 使用DMX最低点（航道底部）
            else:
                continue
            
            # 添加桩号标记立方体
            self.obj_exporter.add_station_marker_cube(
                station_value=station,
                x=marker_x,
                y=marker_y,
                z=marker_z,
                size=MARKER_SIZE
            )
            marker_count += 1
        
        print(f"  Station marker cubes added: {marker_count}")
        print(f"  Marker size: {MARKER_SIZE}m x {MARKER_SIZE}m x {MARKER_SIZE}m")
        print(f"  Marker position: Spine center (航道中心线), Z at DMX bottom (航道底部)")
    
    def generate_bim(self, output_dxf, output_obj=None, output_mtl=None):
        print("\n=== Generating BIM Model V16 ===")
        print("  Features: Thick Ribbon(5m) + Station Marker Cubes + Semi-transparent")
        print(f"  Output DXF: {output_dxf}")
        
        if output_obj and output_mtl:
            self.obj_exporter = OBJExporterV16(output_obj, output_mtl)
            print(f"  Output OBJ: {output_obj}")
            print(f"  Output MTL: {output_mtl}")
        
        if not self.load_and_parse_data():
            print("  [ERROR] Data loading failed")
            return False
        
        geo_grid, ribbon_grid, _ = self.build_grid_surfaces()
        if geo_grid is None:
            print("  [ERROR] Grid building failed")
            return False
        
        # 添加桩号标记立方体
        self.add_station_markers_as_cubes()
        
        print("\n=== Creating DXF Model ===")
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()
        
        # 创建图层
        doc.layers.new(name='DMX_SOLID', dxfattribs={'color': 5})
        doc.layers.new(name='OVERBREAK_SOLID', dxfattribs={'color': 1})
        doc.layers.new(name='STATION_MARKERS', dxfattribs={'color': 2})  # 黄色
        for cat_key, cat_info in LAYER_CATEGORIES.items():
            doc.layers.new(name=f'GEO_{cat_key}', dxfattribs={'color': cat_info['color']})
        
        # DMX设计线厚度实体（厚度5米）
        print("  Generating DMX Thick Solid...")
        self.create_thick_ribbon_solid(msp, ribbon_grid, 'DMX', 'DMX_SOLID', 5, 'DMX_SOLID', RIBBON_THICKNESS)
        
        # 超挖线厚度实体（厚度5米）
        print("  Generating Overbreak Thick Solid...")
        self.create_thick_ribbon_solid(msp, ribbon_grid, 'OVERDREDGE', 'OVERBREAK_SOLID', 1, 'OVERBREAK_SOLID', RIBBON_THICKNESS)
        
        # 三类地质层实体
        print("  Generating geological volumes...")
        self.create_closed_solid_mesh(msp, geo_grid, 'DMX', 'MUD', 1, 'GEO_MUD', 'GEO_MUD')
        self.create_closed_solid_mesh(msp, geo_grid, 'MUD', 'CLAY', 2, 'GEO_CLAY', 'GEO_CLAY')
        self.create_closed_solid_mesh(msp, geo_grid, 'CLAY', 'SAND', 3, 'GEO_SAND', 'GEO_SAND')
        self.create_closed_solid_mesh(msp, geo_grid, 'SAND', 'OVERDREDGE', 3, 'GEO_SAND', 'GEO_SAND')
        
        doc.saveas(output_dxf)
        print(f"\n  DXF model saved: {output_dxf}")
        
        if self.obj_exporter:
            print("\n=== Exporting OBJ/MTL ===")
            self.obj_exporter.export()
        
        return True


if __name__ == "__main__":
    meta_file = r"D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json"
    match_file = r"D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json"
    output_dxf = r"D:\断面算量平台\测试文件\Channel_Geology_Model_V16.dxf"
    output_obj = r"D:\断面算量平台\测试文件\Channel_Geology_Model_V16.obj"
    output_mtl = r"D:\断面算量平台\测试文件\Channel_Geology_Model_V16.mtl"
    
    print("=" * 60)
    print("航道三维地质模型构建器 V16")
    print("核心改进: 桩号实体化 + 超挖半透明 + DMX/超挖厚度5米")
    print("  1. Station Markers: 生成立方体实体（可在OBJ中可视化）")
    print("  2. OVERBREAK: 半透明材质 (opacity=0.5)")
    print("  3. DMX/OVERBREAK: 有厚度的实体（厚度5米）")
    print("=" * 60)
    
    generator = ChannelBIMGeneratorV16(meta_file, match_file)
    success = generator.generate_bim(output_dxf, output_obj, output_mtl)
    
    if success:
        print("\n[SUCCESS] V16 Model generation completed!")
    else:
        print("\n[FAILED] V16 Model generation failed!")