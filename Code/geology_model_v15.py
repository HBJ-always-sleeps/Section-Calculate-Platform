# -*- coding: utf-8 -*-
"""
航道三维地质模型构建器 V15 - 双重空间约束 + MTL半透明 + 桩号标记

核心改进：
1. Vertical Clamping: Z_final = max(min(Z_interpolated, Z_DMX), Z_OVERDREDGE)
   强制地质层被夹逼在DMX设计线和超挖线之间
2. Horizontal Masking: 使用DMX边界检测，防止地质层溢出航道宽度
3. MTL Refinement: DMX材质添加半透明效果 (d 0.5)
4. Station Markers: 添加真实桩号值作为图层标记

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

# OBJ材质定义 - DMX添加半透明
OBJ_MATERIALS = {
    'DMX_RIBBON': {
        'color_rgb': (0.0, 0.5, 1.0),  # 浅蓝色
        'ambient': 0.2,
        'diffuse': 0.8,
        'specular': 0.3,
        'illum': 2,
        'opacity': 0.5,  # 半透明
    },
    'OVERBREAK_RIBBON': {
        'color_rgb': (1.0, 0.0, 0.0),
        'ambient': 0.2,
        'diffuse': 0.8,
        'specular': 0.3,
        'illum': 2,
        'opacity': 1.0,
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
}


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


class OBJExporterV15:
    """V15 OBJ导出器 - 支持半透明材质和桩号标记"""
    
    def __init__(self, output_obj, output_mtl):
        self.output_obj = output_obj
        self.output_mtl = output_mtl
        self.vertices = []
        self.faces = []
        self.groups = {}
        self.station_markers = []  # 桩号标记
    
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
    
    def add_station_marker(self, station_value, x, y, z):
        """添加桩号标记点"""
        self.station_markers.append({
            'station': station_value,
            'x': x,
            'y': y,
            'z': z
        })
    
    def write_mtl(self):
        with open(self.output_mtl, 'w', encoding='utf-8') as f:
            f.write("# MTL Material Library for Channel Geology Model V15\n")
            f.write("# Features: DMX semi-transparent, geological layers opaque\n\n")
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
            f.write("# OBJ File for Channel Geology Model V15\n")
            f.write("# Features: Double Space Constraint + Station Markers\n")
            f.write(f"# Vertices: {len(self.vertices)}\n")
            f.write(f"# Faces: {len(self.faces)}\n")
            f.write(f"# Station Markers: {len(self.station_markers)}\n\n")
            f.write(f"mtllib {os.path.basename(self.output_mtl)}\n\n")
            
            # 写入桩号标记作为注释
            if self.station_markers:
                f.write("# Station Markers (reference points)\n")
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
        print(f"  Station markers: {len(self.station_markers)}")


class ChannelBIMGeneratorV15:
    """V15生成器 - 双重空间约束"""
    
    def __init__(self, metadata_path, match_path):
        self.metadata_path = metadata_path
        self.match_path = match_path
        self.uvz_points = {'DMX': [], 'OVERDREDGE': [], 'MUD': [], 'CLAY': [], 'SAND': []}
        self.spine_data = {}
        self.sections_3d = []
        self.obj_exporter = None
        # 新增：DMX边界数据（用于Horizontal Masking）
        self.dmx_bounds = {}  # {u_station: (v_min, v_max)}
    
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
            
            # 解析DMX点并计算V边界
            dmx_points = sec.get('dmx_points', [])
            v_values = []
            for pt in dmx_points:
                eng_x, eng_y, z = transform_to_spine_aligned(pt[0], pt[1], ref_x, ref_y, spine['spine_x'], spine['spine_y'], rotation_angle)
                v = pt[0] - ref_x
                v_values.append(v)
                self.uvz_points['DMX'].append([station, v, z])
                section_3d['dmx_3d'].append([eng_x, eng_y, z])
            
            # 记录该断面的DMX V边界（用于Horizontal Masking）
            if v_values:
                self.dmx_bounds[station] = (min(v_values), max(v_values))
            
            # 解析超挖线点
            overbreak_points = sec.get('overbreak_points', [])
            for ob_line in overbreak_points:
                for pt in ob_line:
                    eng_x, eng_y, z = transform_to_spine_aligned(pt[0], pt[1], ref_x, ref_y, spine['spine_x'], spine['spine_y'], rotation_angle)
                    v = pt[0] - ref_x
                    self.uvz_points['OVERDREDGE'].append([station, v, z])
                    section_3d['overbreak_3d'].append([eng_x, eng_y, z])
            
            # 解析地质层边界
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
        """
        Horizontal Masking: 检查点(u,v)是否在航道宽度范围内
        
        Args:
            u: 桩号位置（沿航道方向）
            v: 横向偏移（垂直航道方向）
        
        Returns:
            bool: True表示在航道范围内，False表示超出边界
        """
        # 找最近的断面
        closest_station = min(self.dmx_bounds.keys(), key=lambda k: abs(k - u))
        v_min, v_max = self.dmx_bounds.get(closest_station, (-9999, 9999))
        
        # 允许一定的容差（1米）
        tolerance = 1.0
        return (v_min - tolerance) <= v <= (v_max + tolerance)
    
    def build_grid_surfaces(self, u_step=25.0, v_step=5.0):
        """
        构建网格表面，应用双重空间约束：
        1. Vertical Clamping: Z被夹逼在DMX和OVERDREDGE之间
        2. Horizontal Masking: 超出航道宽度的点被屏蔽
        """
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
        
        # 地质层网格
        grid_u, grid_v = np.mgrid[u_min:u_max:u_step, v_min:v_max:v_step]
        
        # Ribbon网格（V范围扩展1米）
        ribbon_margin = 1.0
        v_min_ribbon = v_min - ribbon_margin
        v_max_ribbon = v_max + ribbon_margin
        print(f"  V range (ribbon): {v_min_ribbon} - {v_max_ribbon} (expanded by 1m)")
        grid_u_ribbon, grid_v_ribbon = np.mgrid[u_min:u_max:u_step, v_min_ribbon:v_max_ribbon:v_step]
        
        # 地质层表面插值
        surfaces = {}
        for key in ['DMX', 'OVERDREDGE', 'MUD', 'CLAY', 'SAND']:
            if len(self.uvz_points[key]) > 0:
                pts = np.array(self.uvz_points[key])
                surfaces[key] = griddata((pts[:, 0], pts[:, 1]), pts[:, 2], (grid_u, grid_v), method='linear')
            else:
                surfaces[key] = np.full_like(grid_u, np.nan)
        
        # Ribbon表面插值
        ribbon_surfaces = {}
        for key in ['DMX', 'OVERDREDGE']:
            if len(self.uvz_points[key]) > 0:
                pts = np.array(self.uvz_points[key])
                ribbon_surfaces[key] = griddata((pts[:, 0], pts[:, 1]), pts[:, 2], (grid_u_ribbon, grid_v_ribbon), method='linear')
            else:
                ribbon_surfaces[key] = np.full_like(grid_u_ribbon, np.nan)
        
        # 补全缺失层
        if np.isnan(surfaces['OVERDREDGE']).all():
            print("  [WARN] No overbreak data, using DMX - 15m as fallback")
            surfaces['OVERDREDGE'] = surfaces['DMX'] - 15.0
            ribbon_surfaces['OVERDREDGE'] = ribbon_surfaces['DMX'] - 15.0
        
        # ========== 双重空间约束核心逻辑 ==========
        print("\n=== Applying Double Space Constraint ===")
        
        # 1. Vertical Clamping: 强制地质层在DMX和OVERDREDGE之间
        Z_DMX = surfaces['DMX']
        Z_OVER = surfaces['OVERDREDGE']
        
        clamped_count = 0
        for key in ['MUD', 'CLAY', 'SAND']:
            Z_orig = surfaces[key]
            # 补全缺失值
            mask_nan = np.isnan(Z_orig)
            if np.any(mask_nan):
                Z_orig[mask_nan] = Z_OVER[mask_nan]
            
            # Vertical Clamping: max(min(Z, Z_DMX), Z_OVER)
            # 确保地质层不会穿透DMX（上限）也不会低于OVERDREDGE（下限）
            Z_clamped = np.maximum(np.minimum(Z_orig, Z_DMX), Z_OVER)
            
            # 统计被夹逼的点数
            clamped_mask = (Z_orig != Z_clamped) & ~np.isnan(Z_orig)
            clamped_count += np.sum(clamped_mask)
            
            surfaces[key] = Z_clamped
            print(f"    {key}: {np.sum(clamped_mask)} points clamped vertically")
        
        print(f"  Total vertical clamping: {clamped_count} points")
        
        # 2. Horizontal Masking: 超出航道宽度的点设为NaN
        rows, cols = grid_u.shape
        masked_count = 0
        for i in range(rows):
            for j in range(cols):
                u = grid_u[i, j]
                v = grid_v[i, j]
                if not self.is_in_channel(u, v):
                    # 超出航道边界，屏蔽该点
                    for key in ['MUD', 'CLAY', 'SAND']:
                        if not np.isnan(surfaces[key][i, j]):
                            surfaces[key][i, j] = np.nan
                            masked_count += 1
        
        print(f"  Horizontal masking: {masked_count} points outside channel")
        
        # 防穿模拓扑约束（保持层序）
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
    
    def create_ribbon_surface(self, msp, ribbon_grid, surface_key, layer_name, layer_color, obj_material=None):
        """创建Ribbon曲面"""
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
                face_pts = [(p[0], p[1], z) for p, z in zip(w_pts, z_vals)]
                
                msp.add_3dface(face_pts, dxfattribs={'color': layer_color})
                
                if self.obj_exporter and obj_material:
                    v_indices = []
                    for pt in face_pts:
                        idx = self.obj_exporter.add_vertex(pt[0], pt[1], pt[2])
                        v_indices.append(idx - 1)
                    self.obj_exporter.add_face(obj_material, v_indices, group=layer_name)
                face_count += 1
        
        print(f"    {layer_name} Ribbon: {face_count} 3DFACEs")
    
    def create_closed_solid_mesh(self, msp, geo_grid, z_top_key, z_bot_key, layer_color, layer_name, obj_material=None):
        """生成闭合六面体网格"""
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
    
    def add_station_markers_to_obj(self):
        """添加桩号标记到OBJ文件"""
        if not self.obj_exporter:
            return
        
        print("\n=== Adding Station Markers ===")
        marker_count = 0
        
        for section in self.sections_3d:
            station = section['station_value']
            dmx_3d = section.get('dmx_3d', [])
            
            if len(dmx_3d) > 0:
                # 使用DMX中心点作为桩号标记位置
                center_idx = len(dmx_3d) // 2
                center_pt = dmx_3d[center_idx]
                
                self.obj_exporter.add_station_marker(
                    station_value=station,
                    x=center_pt[0],
                    y=center_pt[1],
                    z=center_pt[2]
                )
                marker_count += 1
        
        print(f"  Station markers added: {marker_count}")
    
    def generate_bim(self, output_dxf, output_obj=None, output_mtl=None):
        print("\n=== Generating BIM Model V15 ===")
        print("  Features: Double Space Constraint + Semi-transparent DMX + Station Markers")
        print(f"  Output DXF: {output_dxf}")
        
        if output_obj and output_mtl:
            self.obj_exporter = OBJExporterV15(output_obj, output_mtl)
            print(f"  Output OBJ: {output_obj}")
            print(f"  Output MTL: {output_mtl}")
        
        if not self.load_and_parse_data():
            print("  [ERROR] Data loading failed")
            return False
        
        geo_grid, ribbon_grid, _ = self.build_grid_surfaces()
        if geo_grid is None:
            print("  [ERROR] Grid building failed")
            return False
        
        # 添加桩号标记
        self.add_station_markers_to_obj()
        
        print("\n=== Creating DXF Model ===")
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()
        
        # 创建图层
        doc.layers.new(name='DMX_RIBBON', dxfattribs={'color': 5})
        doc.layers.new(name='OVERBREAK_RIBBON', dxfattribs={'color': 1})
        for cat_key, cat_info in LAYER_CATEGORIES.items():
            doc.layers.new(name=f'GEO_{cat_key}', dxfattribs={'color': cat_info['color']})
        
        # DMX设计线Ribbon
        print("  Generating DMX Ribbon surface...")
        self.create_ribbon_surface(msp, ribbon_grid, 'DMX', 'DMX_RIBBON', 5, 'DMX_RIBBON')
        
        # 超挖线Ribbon
        print("  Generating Overbreak Ribbon surface...")
        self.create_ribbon_surface(msp, ribbon_grid, 'OVERDREDGE', 'OVERBREAK_RIBBON', 1, 'OVERBREAK_RIBBON')
        
        # 三类地质层实体
        print("  Generating geological volumes...")
        self.create_closed_solid_mesh(msp, geo_grid, 'DMX', 'MUD', 1, 'GEO_MUD', 'GEO_MUD')
        self.create_closed_solid_mesh(msp, geo_grid, 'MUD', 'CLAY', 2, 'GEO_CLAY', 'GEO_CLAY')
        self.create_closed_solid_mesh(msp, geo_grid, 'CLAY', 'SAND', 3, 'GEO_SAND', 'GEO_SAND')
        # 底层合并到砂石层
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
    output_dxf = r"D:\断面算量平台\测试文件\Channel_Geology_Model_V15.dxf"
    output_obj = r"D:\断面算量平台\测试文件\Channel_Geology_Model_V15.obj"
    output_mtl = r"D:\断面算量平台\测试文件\Channel_Geology_Model_V15.mtl"
    
    print("=" * 60)
    print("航道三维地质模型构建器 V15")
    print("核心改进: 双重空间约束 + MTL半透明 + 桩号标记")
    print("  1. Vertical Clamping: Z夹逼在DMX和OVERDREDGE之间")
    print("  2. Horizontal Masking: 屏蔽超出航道宽度的点")
    print("  3. MTL Refinement: DMX材质半透明(d=0.5)")
    print("  4. Station Markers: 添加真实桩号值标记")
    print("=" * 60)
    
    generator = ChannelBIMGeneratorV15(meta_file, match_file)
    success = generator.generate_bim(output_dxf, output_obj, output_mtl)
    
    if success:
        print("\n[SUCCESS] V15 Model generation completed!")
    else:
        print("\n[FAILED] V15 Model generation failed!")