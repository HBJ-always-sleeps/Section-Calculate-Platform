# -*- coding: utf-8 -*-
"""
航道三维地质模型构建器 V12 - 基于V7坐标映射体系的全新实现

核心设计：
1. 使用V7的坐标变换体系：CAD局部坐标 -> 工程坐标(CGCS2000)
2. 关键映射：Z = cad_y - ref_y (CAD的Y坐标减去参考点Y就是高程)
3. 超挖线使用真实数据：overbreak_points字段（而非占位）
4. 地质层分类：淤泥/填土、黏土、砂/碎石三类
5. UV网格插值 + 防穿模拓扑约束

作者: @黄秉俊
日期: 2026-04-06
"""

import json
import numpy as np
from scipy.interpolate import griddata
import ezdxf
import math
import sys
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
    
    Args:
        cad_x: CAD局部坐标系中的X坐标
        cad_y: CAD局部坐标系中的Y坐标（实际代表高程信息）
        ref_x: L1参考点在CAD坐标系中的X
        ref_y: L1参考点在CAD坐标系中的Y
        spine_x: 脊梁点在CGCS2000中的X坐标
        spine_y: 脊梁点在CGCS2000中的Y坐标
        rotation_angle: 旋转角度（tangent_angle + pi/2）
    
    Returns:
        (eng_x, eng_y, z): 工程坐标和高程
    """
    # 关键：Z是高程，由CAD的Y坐标减去参考点Y得到
    z = cad_y - ref_y
    
    # X偏移量
    dx = cad_x - ref_x
    
    # 旋转计算
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    
    # 工程坐标（必须加上spine_x/spine_y）
    eng_x = spine_x + dx * cos_a
    eng_y = spine_y + dx * sin_a
    
    return eng_x, eng_y, z


def uv_to_world(u: float, v: float, spine_data: Dict) -> Tuple[float, float]:
    """
    将UV坐标（桩号U, 偏距V）转换为世界坐标系(CGCS2000)
    
    Args:
        u: 桩号值（station_value）
        v: 垂直于航道的偏距
        spine_data: 脊梁点匹配数据
    
    Returns:
        (world_x, world_y): CGCS2000坐标
    """
    # 找到最近的脊梁点（简化处理，实际应线性插值）
    closest_station = min(spine_data.keys(), key=lambda k: abs(k - u))
    spine = spine_data[closest_station]
    
    # 垂直于切线的角度
    angle_rad = spine['tangent_angle'] + math.pi / 2
    perp_angle = angle_rad  # 已经是垂直方向
    
    # 世界坐标偏移
    world_x = spine['spine_x'] + v * math.cos(perp_angle)
    world_y = spine['spine_y'] + v * math.sin(perp_angle)
    
    return world_x, world_y


# ==================== 主构建器类 ====================

class ChannelBIMGeneratorV12:
    """
    航道三维地质模型构建器 V12
    
    使用V7验证的坐标映射体系，构建完整的3D BIM模型
    """
    
    def __init__(self, metadata_path: str, match_path: str):
        self.metadata_path = metadata_path
        self.match_path = match_path
        
        # UVZ点集合（桩号U, 偏距V, 高程Z）
        self.uvz_points = {
            'DMX': [],
            'OVERDREDGE': [],
            'MUD': [],
            'CLAY': [],
            'SAND': []
        }
        
        # 脊梁点数据索引
        self.spine_data = {}
        
        # 原始断面数据（保留用于后续处理）
        self.sections_3d = []
        
    def load_and_parse_data(self) -> bool:
        """
        加载JSON数据并解析为UVZ格式
        
        Returns:
            bool: 是否成功加载
        """
        print("\n=== Loading and Parsing Data ===")
        
        # 加载脊梁点匹配数据
        try:
            with open(self.match_path, 'r', encoding='utf-8') as f:
                match_data = json.load(f)
        except Exception as e:
            print(f"  [ERROR] Failed to load spine match: {e}")
            return False
        
        # 建立脊梁点索引 (Station -> Data)
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
        
        print(f"  Spine matches loaded: {len(self.spine_data)}")
        
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
            
            # 参考点坐标
            ref_x = l1_ref.get('ref_x', spine['l1_x'])
            ref_y = l1_ref.get('ref_y', spine['l1_y'])
            
            # 旋转角度（垂直于切线）
            rotation_angle = spine['tangent_angle'] + math.pi / 2
            
            # 存储断面3D数据
            section_3d = {
                'station_value': station,
                'dmx_3d': [],
                'overbreak_3d': [],
                'geological_polys': {}
            }
            
            # 解析 DMX (地面线)
            dmx_points = sec.get('dmx_points', [])
            for pt in dmx_points:
                eng_x, eng_y, z = transform_to_spine_aligned(
                    pt[0], pt[1], ref_x, ref_y,
                    spine['spine_x'], spine['spine_y'], rotation_angle
                )
                # 计算UV坐标
                v = pt[0] - ref_x  # 偏距
                self.uvz_points['DMX'].append([station, v, z])
                section_3d['dmx_3d'].append([eng_x, eng_y, z])
            
            # 解析超挖线（真实数据）
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
            
            # 解析地质分层边界
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
                    
                    # 存储地质多边形
                    if cat_key not in section_3d['geological_polys']:
                        section_3d['geological_polys'][cat_key] = []
                    section_3d['geological_polys'][cat_key].append({
                        'layer_name': layer_name,
                        'points': np.array(poly_3d)
                    })
            
            self.sections_3d.append(section_3d)
            matched_count += 1
        
        print(f"  Sections matched: {matched_count}")
        
        # 统计UVZ点数
        for key, pts in self.uvz_points.items():
            print(f"  {key} UVZ points: {len(pts)}")
        
        return matched_count > 0
    
    def build_grid_surfaces(self, u_step: float = 25.0, v_step: float = 5.0) -> Tuple:
        """
        在UV空间构建规则网格并插值，强制执行防穿模拓扑关系
        
        Args:
            u_step: 桩号方向步长（米）
            v_step: 偏距方向步长（米）
        
        Returns:
            (grid_u, grid_v, z_surfaces): 网格坐标和各层高程面
        """
        print("\n=== Building Grid Surfaces ===")
        print(f"  U step: {u_step}m, V step: {v_step}m")
        
        # 确定网格范围
        if len(self.uvz_points['DMX']) == 0:
            print("  [ERROR] No DMX points available")
            return None, None, None
        
        all_points = np.array(self.uvz_points['DMX'])
        u_min, u_max = np.min(all_points[:, 0]), np.max(all_points[:, 0])
        v_min, v_max = np.min(all_points[:, 1]), np.max(all_points[:, 1])
        
        print(f"  U range: {u_min} - {u_max}")
        print(f"  V range: {v_min} - {v_max}")
        
        # 构建网格
        grid_u, grid_v = np.mgrid[u_min:u_max:u_step, v_min:v_max:v_step]
        
        # 插值各层表面
        surfaces = {}
        for key in ['DMX', 'OVERDREDGE', 'MUD', 'CLAY', 'SAND']:
            if len(self.uvz_points[key]) > 0:
                pts = np.array(self.uvz_points[key])
                # 使用linear插值避免振荡
                surfaces[key] = griddata(
                    (pts[:, 0], pts[:, 1]), pts[:, 2],
                    (grid_u, grid_v), method='linear'
                )
            else:
                surfaces[key] = np.full_like(grid_u, np.nan)
        
        # 补全缺失层
        if np.isnan(surfaces['OVERDREDGE']).all():
            # 如果没有超挖线数据，使用DMX减去设计深度
            print("  [WARN] No overbreak data, using DMX - 15m as fallback")
            surfaces['OVERDREDGE'] = surfaces['DMX'] - 15.0
        
        # 防穿模拓扑约束（自上而下挤压）
        # 逻辑：下一层的Z绝对不能高于上一层的Z
        Z_DMX = surfaces['DMX']
        
        # 初始化缺失地质层
        for key in ['MUD', 'CLAY', 'SAND']:
            mask = np.isnan(surfaces[key])
            if np.any(mask):
                surfaces[key][mask] = surfaces['OVERDREDGE'][mask]
        
        # 强制拓扑约束
        Z_MUD = np.minimum(Z_DMX, surfaces['MUD'])
        Z_CLAY = np.minimum(Z_MUD, surfaces['CLAY'])
        Z_SAND = np.minimum(Z_CLAY, surfaces['SAND'])
        Z_OVER = np.minimum(Z_SAND, surfaces['OVERDREDGE'])
        
        # 统计有效网格点
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
                                 layer_color: int, layer_name: str):
        """
        生成完全闭合的六面体网格（模拟实体）
        
        Args:
            msp: DXF modelspace
            u_grid: 桩号网格
            v_grid: 偏距网格
            z_top: 顶面高程
            z_bot: 底面高程
            layer_color: DXF颜色索引
            layer_name: 图层名称
        """
        rows, cols = u_grid.shape
        
        face_count = 0
        skip_count = 0
        
        for i in range(rows - 1):
            for j in range(cols - 1):
                # 获取单元格的4个顶点UV坐标
                uvs = [
                    (u_grid[i, j], v_grid[i, j]),
                    (u_grid[i+1, j], v_grid[i+1, j]),
                    (u_grid[i+1, j+1], v_grid[i+1, j+1]),
                    (u_grid[i, j+1], v_grid[i, j+1])
                ]
                
                # 顶面和底面高程
                z_t = [z_top[i, j], z_top[i+1, j], z_top[i+1, j+1], z_top[i, j+1]]
                z_b = [z_bot[i, j], z_bot[i+1, j], z_bot[i+1, j+1], z_bot[i, j+1]]
                
                # 检查数据有效性
                if np.isnan(z_t).any() or np.isnan(z_b).any():
                    skip_count += 1
                    continue
                
                # 检查厚度是否为零
                if np.allclose(z_t, z_b, atol=0.01):
                    skip_count += 1
                    continue
                
                # 转换为世界坐标
                w_pts = [uv_to_world(u, v, self.spine_data) for u, v in uvs]
                
                # 构建顶面和底面顶点
                top_face = [(p[0], p[1], z) for p, z in zip(w_pts, z_t)]
                bot_face = [(p[0], p[1], z) for p, z in zip(w_pts, z_b)]
                
                # DXF属性
                attr = {'color': layer_color}
                
                # 写入3DFACE（顶面）
                msp.add_3dface(top_face, dxfattribs=attr)
                
                # 写入3DFACE（底面，顶点顺序反转）
                msp.add_3dface([bot_face[0], bot_face[3], bot_face[2], bot_face[1]], 
                              dxfattribs=attr)
                
                # 写入四个侧面（闭合）
                msp.add_3dface([top_face[0], top_face[1], bot_face[1], bot_face[0]], 
                              dxfattribs=attr)
                msp.add_3dface([top_face[1], top_face[2], bot_face[2], bot_face[1]], 
                              dxfattribs=attr)
                msp.add_3dface([top_face[2], top_face[3], bot_face[3], bot_face[2]], 
                              dxfattribs=attr)
                msp.add_3dface([top_face[3], top_face[0], bot_face[0], bot_face[3]], 
                              dxfattribs=attr)
                
                face_count += 6
        
        print(f"    {layer_name}: {face_count} 3DFACEs created, {skip_count} skipped")
    
    def generate_bim(self, output_dxf: str) -> bool:
        """
        主执行流程：生成完整的3D BIM模型
        
        Args:
            output_dxf: 输出DXF文件路径
        
        Returns:
            bool: 是否成功生成
        """
        print("\n=== Generating BIM Model ===")
        print(f"  Output: {output_dxf}")
        
        # 1. 加载和解析数据
        if not self.load_and_parse_data():
            print("  [ERROR] Data loading failed")
            return False
        
        # 2. 构建UV网格和插值表面
        u_grid, v_grid, z_surfs = self.build_grid_surfaces()
        
        if u_grid is None:
            print("  [ERROR] Grid building failed")
            return False
        
        # 3. 创建DXF文档
        print("\n=== Creating DXF Model ===")
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()
        
        # 创建图层
        for cat_key, cat_info in LAYER_CATEGORIES.items():
            doc.layers.new(name=f'GEO_{cat_key}', dxfattribs={'color': cat_info['color']})
        doc.layers.new(name='GEO_OVERDREDGE', dxfattribs={'color': 4})  # 青色
        
        # 4. 生成各层闭合实体
        print("  Generating geological volumes...")
        
        # 淤泥与填土层 (Top: DMX, Bot: MUD)
        self.create_closed_solid_mesh(
            msp, u_grid, v_grid, 
            z_surfs['DMX'], z_surfs['MUD'],
            layer_color=1, layer_name='MUD_FILL'
        )
        
        # 黏土层 (Top: MUD, Bot: CLAY)
        self.create_closed_solid_mesh(
            msp, u_grid, v_grid,
            z_surfs['MUD'], z_surfs['CLAY'],
            layer_color=2, layer_name='CLAY'
        )
        
        # 砂石层 (Top: CLAY, Bot: SAND)
        self.create_closed_solid_mesh(
            msp, u_grid, v_grid,
            z_surfs['CLAY'], z_surfs['SAND'],
            layer_color=3, layer_name='SAND'
        )
        
        # 底层/超挖区间 (Top: SAND, Bot: OVERDREDGE)
        self.create_closed_solid_mesh(
            msp, u_grid, v_grid,
            z_surfs['SAND'], z_surfs['OVERDREDGE'],
            layer_color=4, layer_name='OVERDREDGE'
        )
        
        # 5. 保存DXF
        doc.saveas(output_dxf)
        print(f"\n  BIM model saved: {output_dxf}")
        
        return True


# ==================== 主程序入口 ====================

if __name__ == "__main__":
    # 测试文件路径
    meta_file = r"D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json"
    match_file = r"D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json"
    output_file = r"D:\断面算量平台\测试文件\Channel_Geology_Solid_Model_V12.dxf"
    
    print("=" * 60)
    print("航道三维地质模型构建器 V12")
    print("=" * 60)
    
    generator = ChannelBIMGeneratorV12(meta_file, match_file)
    success = generator.generate_bim(output_file)
    
    if success:
        print("\n[SUCCESS] Model generation completed!")
    else:
        print("\n[FAILED] Model generation failed!")