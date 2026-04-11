# -*- coding: utf-8 -*-
"""
航道三维地质模型构建器 V13 - HYPACK优化版本

核心改进（基于V12）：
1. 特征缩放：解决插值锯齿问题（U坐标缩放使纵横比接近1:1）
2. Z-Fighting过滤：零厚度单元格跳过，避免渲染冲突
3. 线性方位角内插：解决切线跳变导致的模型裂缝
4. 分层独立导出：每层地质单独DXF文件，便于HYPACK图层管理
5. V轴关键点对齐：强制加入设计关键偏距（底宽±15m，坡顶±30m）

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

# 添加Code目录到路径
sys.path.insert(0, r'D:\断面算量平台\Code')


# ==================== 地层分类映射 ====================

LAYER_CATEGORIES = {
    'MUD': {
        'name_cn': '淤泥与填土',
        'color': 1,  # DXF颜色索引：红色
        'keywords': ['1级淤泥', '2级淤泥', '3级淤泥', '4级淤泥', '1级填土', '2级填土', '3级填土', '4级填土']
    },
    'CLAY': {
        'name_cn': '黏土',
        'color': 2,  # DXF颜色索引：黄色
        'keywords': ['3级黏土', '4级黏土', '5级黏土']
    },
    'SAND': {
        'name_cn': '砂与碎石类',
        'color': 3,  # DXF颜色索引：绿色
        'keywords': ['6级砂', '7级砂', '8级砂', '9级砂', '10级砂', '6级碎石', '9级碎石']
    },
    'DMX': {
        'name_cn': '设计面',
        'color': 5,  # DXF颜色索引：蓝色（半透明盖子）
        'keywords': []
    }
}


def categorize_layer(layer_name: str) -> Optional[str]:
    """将原始层名映射到分类类别"""
    for cat_key, cat_info in LAYER_CATEGORIES.items():
        for kw in cat_info['keywords']:
            if kw in layer_name:
                return cat_key
    return None


# ==================== 坐标变换核心算法 ====================

def transform_to_spine_aligned(cad_x: float, cad_y: float,
                               ref_x: float, ref_y: float,
                               spine_x: float, spine_y: float,
                               rotation_angle: float) -> Tuple[float, float, float]:
    """
    坐标转换：CAD局部坐标 -> 工程坐标(CGCS2000)
    
    关键映射关系（来自V7验证）：
    - Z = cad_y - ref_y (CAD的Y坐标减去参考点Y就是高程)
    - X偏移 = cad_x - ref_x
    - 旋转角度 = tangent_angle + pi/2 (垂直于航道切线)
    """
    z = cad_y - ref_y
    dx = cad_x - ref_x
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    eng_x = spine_x + dx * cos_a
    eng_y = spine_y + dx * sin_a
    return eng_x, eng_y, z


# ==================== 主构建器类 V13 ====================

class ChannelBIMGeneratorV13:
    """
    航道三维地质模型构建器 V13 - HYPACK优化版本
    
    核心改进：
    1. 特征缩放解决插值锯齿
    2. Z-Fighting零厚度过滤
    3. 线性方位角内插
    4. 分层独立导出
    5. V轴关键点对齐
    """
    
    def __init__(self, metadata_path: str, match_path: str, output_dir: str):
        self.metadata_path = metadata_path
        self.match_path = match_path
        self.output_dir = output_dir
        
        # UVZ点集合
        self.uvz_points = {
            'DMX': [],
            'OVERDREDGE': [],
            'MUD': [],
            'CLAY': [],
            'SAND': []
        }
        
        # 脊梁点数据索引（用于线性插值）
        self.spine_data = {}
        self.spine_stations = []  # 排序后的桩号列表
        self.spine_xs = []        # 对应的spine_x列表
        self.spine_ys = []        # 对应的spine_y列表
        self.spine_angles = []    # 对应的tangent_angle列表
        
        # 原始断面数据
        self.sections_3d = []
        
    def load_and_parse_data(self) -> bool:
        """加载JSON数据并解析为UVZ格式"""
        print("\n=== Loading and Parsing Data ===")
        
        # 加载脊梁点匹配数据
        try:
            with open(self.match_path, 'r', encoding='utf-8') as f:
                match_data = json.load(f)
        except Exception as e:
            print(f"  [ERROR] Failed to load spine match: {e}")
            return False
        
        # 建立脊梁点索引
        matches = match_data.get('matches', [])
        if not matches:
            matches = [v for k, v in match_data.items() 
                      if isinstance(v, dict) and 'station_value' in v]
        
        for m in matches:
            self.spine_data[m['station_value']] = {
                'spine_x': m['spine_x'],
                'spine_y': m['spine_y'],
                'l1_x': m['l1_x'],
                'l1_y': m['l1_y'],
                'tangent_angle': m['tangent_angle']
            }
        
        # 【改进3】预计算线性插值参数
        self.spine_stations = sorted(self.spine_data.keys())
        self.spine_xs = [self.spine_data[s]['spine_x'] for s in self.spine_stations]
        self.spine_ys = [self.spine_data[s]['spine_y'] for s in self.spine_stations]
        self.spine_angles = [self.spine_data[s]['tangent_angle'] for s in self.spine_stations]
        
        print(f"  Spine matches loaded: {len(self.spine_data)}")
        print(f"  Station range: {self.spine_stations[0]} - {self.spine_stations[-1]}")
        
        # 加载断面元数据
        try:
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        except Exception as e:
            print(f"  [ERROR] Failed to load metadata: {e}")
            return False
        
        sections = metadata.get('sections', [])
        print(f"  Sections loaded: {len(sections)}")
        
        # 解析每个断面
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
            
            section_3d = {
                'station_value': station,
                'dmx_3d': [],
                'overbreak_3d': [],
                'geological_polys': {}
            }
            
            # 解析 DMX
            dmx_points = sec.get('dmx_points', [])
            for pt in dmx_points:
                eng_x, eng_y, z = transform_to_spine_aligned(
                    pt[0], pt[1], ref_x, ref_y,
                    spine['spine_x'], spine['spine_y'], rotation_angle
                )
                v = pt[0] - ref_x
                self.uvz_points['DMX'].append([station, v, z])
                section_3d['dmx_3d'].append([eng_x, eng_y, z])
            
            # 解析超挖线
            overbreak_points = sec.get('overbreak_points', [])
            for ob_line in overbreak_points:
                for pt in ob_line:
                    eng_x, eng_y, z = transform_to_spine_aligned(
                        pt[0], pt[1], ref_x, ref_y,
                        spine['spine_x'], spine['spine_y'], rotation_angle
                    )
                    v = pt[0] - ref_x
                    self.uvz_points['OVERDREDGE'].append([station, v, z])
                    section_3d['overbreak_3d'].append([eng_x, eng_y, z])
            
            # 解析地质分层
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
                        eng_x, eng_y, z = transform_to_spine_aligned(
                            pt[0], pt[1], ref_x, ref_y,
                            spine['spine_x'], spine['spine_y'], rotation_angle
                        )
                        v = pt[0] - ref_x
                        self.uvz_points[cat_key].append([station, v, z])
                        poly_3d.append([eng_x, eng_y, z])
                    
                    if cat_key not in section_3d['geological_polys']:
                        section_3d['geological_polys'][cat_key] = []
                    section_3d['geological_polys'][cat_key].append({
                        'layer_name': layer_name,
                        'points': np.array(poly_3d)
                    })
            
            self.sections_3d.append(section_3d)
            matched_count += 1
        
        print(f"  Sections matched: {matched_count}")
        
        for key, pts in self.uvz_points.items():
            print(f"  {key} UVZ points: {len(pts)}")
        
        return matched_count > 0
    
    def uv_to_world_smooth(self, u: float, v: float) -> Tuple[float, float]:
        """
        【改进3】线性方位角内插：解决切线跳变导致的模型裂缝
        
        Args:
            u: 桩号值
            v: 垂直于航道的偏距
        
        Returns:
            (world_x, world_y): CGCS2000坐标
        """
        # 线性内插基准中心点坐标
        target_x = np.interp(u, self.spine_stations, self.spine_xs)
        target_y = np.interp(u, self.spine_stations, self.spine_ys)
        
        # 线性内插切线角度（解决转弯处模型裂缝）
        target_angle = np.interp(u, self.spine_stations, self.spine_angles)
        
        # 垂直于切线的角度
        perp_angle = target_angle + math.pi / 2
        
        # 世界坐标
        world_x = target_x + v * math.cos(perp_angle)
        world_y = target_y + v * math.sin(perp_angle)
        
        return world_x, world_y
    
    def build_grid_surfaces(self, u_step: float = 25.0, v_step: float = 5.0,
                            design_offsets: List[float] = None) -> Tuple:
        """
        构建UV网格并插值
        
        【改进1】特征缩放：解决插值锯齿
        【改进5】V轴关键点对齐：强制加入设计偏距
        
        Args:
            u_step: 桩号方向步长
            v_step: 偏距方向步长
            design_offsets: 设计关键偏距列表（如[-30, -15, 0, 15, 30]）
        
        Returns:
            (grid_u, grid_v, z_surfaces): 网格坐标和各层高程面
        """
        print("\n=== Building Grid Surfaces ===")
        print(f"  U step: {u_step}m, V step: {v_step}m")
        
        if len(self.uvz_points['DMX']) == 0:
            print("  [ERROR] No DMX points available")
            return None, None, None
        
        all_points = np.array(self.uvz_points['DMX'])
        u_min, u_max = np.min(all_points[:, 0]), np.max(all_points[:, 0])
        v_min, v_max = np.min(all_points[:, 1]), np.max(all_points[:, 1])
        
        print(f"  U range: {u_min} - {u_max}")
        print(f"  V range: {v_min} - {v_max}")
        
        # 【改进5】V轴强制对齐：加入设计关键偏距
        if design_offsets is None:
            design_offsets = [-30, -15, 0, 15, 30]  # 默认设计关键点
        
        # 合并固定步长和关键点
        v_coords = np.sort(np.unique(np.concatenate([
            np.arange(v_min, v_max, v_step),
            np.array(design_offsets)
        ])))
        
        u_coords = np.arange(u_min, u_max, u_step)
        
        # 构建网格
        grid_u, grid_v = np.meshgrid(u_coords, v_coords, indexing='ij')
        
        print(f"  Grid size: {grid_u.shape}")
        print(f"  V coords include design offsets: {len(design_offsets)} points")
        
        # 【改进1】特征缩放：U坐标缩放使纵横比接近1:1
        u_scale = 0.1  # 缩放因子：断面间距25m缩小后变成2.5m
        
        # 插值各层表面
        surfaces = {}
        for key in ['DMX', 'OVERDREDGE', 'MUD', 'CLAY', 'SAND']:
            if len(self.uvz_points[key]) > 0:
                pts = np.array(self.uvz_points[key])
                
                # 特征缩放
                pts_scaled = pts.copy()
                pts_scaled[:, 0] *= u_scale
                
                grid_u_scaled = grid_u * u_scale
                
                # 执行插值
                surfaces[key] = griddata(
                    (pts_scaled[:, 0], pts_scaled[:, 1]), pts_scaled[:, 2],
                    (grid_u_scaled, grid_v), method='linear'
                )
            else:
                surfaces[key] = np.full_like(grid_u, np.nan)
        
        # 补全缺失层
        if np.isnan(surfaces['OVERDREDGE']).all():
            print("  [WARN] No overbreak data, using DMX - 15m as fallback")
            surfaces['OVERDREDGE'] = surfaces['DMX'] - 15.0
        
        # 防穿模拓扑约束
        Z_DMX = surfaces['DMX']
        
        for key in ['MUD', 'CLAY', 'SAND']:
            mask = np.isnan(surfaces[key])
            if np.any(mask):
                surfaces[key][mask] = surfaces['OVERDREDGE'][mask]
        
        Z_MUD = np.minimum(Z_DMX, surfaces['MUD'])
        Z_CLAY = np.minimum(Z_MUD, surfaces['CLAY'])
        Z_SAND = np.minimum(Z_CLAY, surfaces['SAND'])
        Z_OVER = np.minimum(Z_SAND, surfaces['OVERDREDGE'])
        
        valid_count = np.sum(~np.isnan(Z_DMX))
        print(f"  Valid grid points: {valid_count}")
        
        return grid_u, grid_v, {
            'DMX': Z_DMX,
            'MUD': Z_MUD,
            'CLAY': Z_CLAY,
            'SAND': Z_SAND,
            'OVERDREDGE': Z_OVER
        }
    
    def create_closed_solid_mesh(self, msp, u_grid, v_grid, 
                                 z_top: np.ndarray, z_bot: np.ndarray,
                                 layer_color: int, layer_name: str,
                                 min_thickness: float = 0.001) -> int:
        """
        【改进2】生成闭合六面体网格，零厚度过滤
        
        Args:
            min_thickness: 最小厚度阈值（米），小于此值跳过
        
        Returns:
            int: 生成的3DFACE数量
        """
        rows, cols = u_grid.shape
        
        face_count = 0
        skip_zero_thickness = 0
        skip_nan = 0
        
        for i in range(rows - 1):
            for j in range(cols - 1):
                uvs = [
                    (u_grid[i, j], v_grid[i, j]),
                    (u_grid[i+1, j], v_grid[i+1, j]),
                    (u_grid[i+1, j+1], v_grid[i+1, j+1]),
                    (u_grid[i, j+1], v_grid[i, j+1])
                ]
                
                z_t = [z_top[i, j], z_top[i+1, j], z_top[i+1, j+1], z_top[i, j+1]]
                z_b = [z_bot[i, j], z_bot[i+1, j], z_bot[i+1, j+1], z_bot[i, j+1]]
                
                # 检查数据有效性
                if np.isnan(z_t).any() or np.isnan(z_b).any():
                    skip_nan += 1
                    continue
                
                # 【改进2】Z-Fighting过滤：零厚度单元格跳过
                thickness = np.array(z_t) - np.array(z_b)
                if np.max(thickness) < min_thickness:
                    skip_zero_thickness += 1
                    continue
                
                # 【改进3】使用线性插值转换坐标
                w_pts = [self.uv_to_world_smooth(u, v) for u, v in uvs]
                
                top_face = [(p[0], p[1], z) for p, z in zip(w_pts, z_t)]
                bot_face = [(p[0], p[1], z) for p, z in zip(w_pts, z_b)]
                
                attr = {'color': layer_color}
                
                # 顶面（顺时针）
                msp.add_3dface(top_face, dxfattribs=attr)
                
                # 底面（逆时针，顶点顺序反转）
                msp.add_3dface([bot_face[0], bot_face[3], bot_face[2], bot_face[1]], 
                              dxfattribs=attr)
                
                # 四个侧面
                msp.add_3dface([top_face[0], top_face[1], bot_face[1], bot_face[0]], 
                              dxfattribs=attr)
                msp.add_3dface([top_face[1], top_face[2], bot_face[2], bot_face[1]], 
                              dxfattribs=attr)
                msp.add_3dface([top_face[2], top_face[3], bot_face[3], bot_face[2]], 
                              dxfattribs=attr)
                msp.add_3dface([top_face[3], top_face[0], bot_face[0], bot_face[3]], 
                              dxfattribs=attr)
                
                face_count += 6
        
        print(f"    {layer_name}: {face_count} 3DFACEs, skipped {skip_zero_thickness} zero-thickness, {skip_nan} NaN")
        
        return face_count
    
    def generate_bim(self) -> bool:
        """
        【改进4】主执行流程：分层独立导出
        
        每层地质单独DXF文件，便于HYPACK图层管理
        """
        print("\n=== Generating BIM Model V13 ===")
        print(f"  Output directory: {self.output_dir}")
        
        # 确保输出目录存在
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        
        # 加载和解析数据
        if not self.load_and_parse_data():
            print("  [ERROR] Data loading failed")
            return False
        
        # 构建UV网格
        u_grid, v_grid, z_surfs = self.build_grid_surfaces()
        
        if u_grid is None:
            print("  [ERROR] Grid building failed")
            return False
        
        print("\n=== Creating Layer DXF Files ===")
        
        # 【改进4】分层独立导出
        layers_to_export = [
            ('DMX', z_surfs['DMX'], z_surfs['MUD'], 1, '淤泥与填土'),
            ('CLAY', z_surfs['MUD'], z_surfs['CLAY'], 2, '黏土'),
            ('SAND', z_surfs['CLAY'], z_surfs['SAND'], 3, '砂与碎石类'),
            ('OVERDREDGE', z_surfs['SAND'], z_surfs['OVERDREDGE'], 4, '超挖底层')
        ]
        
        total_faces = 0
        
        for layer_key, z_top, z_bot, color, name_cn in layers_to_export:
            # 创建独立DXF文档
            doc = ezdxf.new('R2010')
            msp = doc.modelspace()
            
            # 创建图层
            doc.layers.new(name=f'GEO_{layer_key}', dxfattribs={'color': color})
            
            # 生成网格
            face_count = self.create_closed_solid_mesh(
                msp, u_grid, v_grid, z_top, z_bot, color, name_cn
            )
            
            total_faces += face_count
            
            # 保存独立文件
            output_file = os.path.join(self.output_dir, f"Geology_{layer_key}.dxf")
            doc.saveas(output_file)
            print(f"  Saved: {output_file}")
        
        # 【改进4】单独导出设计面盖子（DMX Ribbon）
        print("\n=== Creating Design Surface (DMX Cover) ===")
        doc_dmx = ezdxf.new('R2010')
        msp_dmx = doc_dmx.modelspace()
        doc_dmx.layers.new(name='DESIGN_SURFACE', dxfattribs={'color': 5})  # 蓝色
        
        # DMX作为单独的盖子面
        self.create_closed_solid_mesh(
            msp_dmx, u_grid, v_grid, 
            z_surfs['DMX'], z_surfs['DMX'] - 0.5,  # 薄层盖子（0.5m厚度）
            5, '设计面盖子'
        )
        
        dmx_file = os.path.join(self.output_dir, "Design_Surface.dxf")
        doc_dmx.saveas(dmx_file)
        print(f"  Saved: {dmx_file}")
        
        print(f"\n  Total 3DFACEs: {total_faces}")
        print("\n[SUCCESS] Model generation completed!")
        print("\n  HYPACK使用建议:")
        print("    1. Design_Surface.dxf 设为半透明蓝色（设计线盖子）")
        print("    2. Geology_MUD.dxf 设为不透明灰色（淤泥层）")
        print("    3. Geology_CLAY.dxf 设为不透明棕色（黏土层）")
        print("    4. Geology_SAND.dxf 设为不透明金色（砂层）")
        
        return True


# ==================== 主程序入口 ====================

if __name__ == "__main__":
    # 测试文件路径
    meta_file = r"D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json"
    match_file = r"D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json"
    output_dir = r"D:\断面算量平台\测试文件\Geology_V13"
    
    print("=" * 60)
    print("航道三维地质模型构建器 V13 - HYPACK优化版本")
    print("=" * 60)
    print("\n核心改进:")
    print("  1. 特征缩放 - 解决插值锯齿")
    print("  2. Z-Fighting过滤 - 零厚度单元格跳过")
    print("  3. 线性方位角内插 - 解决切线跳变")
    print("  4. 分层独立导出 - 便于HYPACK图层管理")
    print("  5. V轴关键点对齐 - 确保边坡和底口对齐")
    print("=" * 60)
    
    generator = ChannelBIMGeneratorV13(meta_file, match_file, output_dir)
    success = generator.generate_bim()
    
    if not success:
        print("\n[FAILED] Model generation failed!")